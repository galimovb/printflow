"""Usage log of every OpenAI request: tokens, cache hits and the cost at list prices, one JSON line each.

The file is <PRINTFLOW_LOG_DIR>/wb_usage.jsonl (PRINTFLOW_WB_USAGE_LOG overrides it). The card being generated
is taken from a context variable, so every line says which card and which step paid for it.
"""

import contextlib
import contextvars
import json
import logging
import os
import time
from pathlib import Path

logger = logging.getLogger(__name__)

# $ per 1M tokens, OpenAI list prices (standard tier, short context).
IMAGE_PRICES = {"text_in": 5.0, "text_cached": 1.25, "image_in": 8.0, "image_cached": 2.0, "out": 30.0}
CHAT_PRICES = {
    "gpt-6-astra": {"in": 10.0, "cached": 1.0, "out": 50.0},
    "gpt-6.1-sol": {"in": 2.0, "cached": 0.10, "out": 10.0},
    "gpt-6.1-terra": {"in": 1.0, "cached": 0.05, "out": 5.0},
    "gpt-6-luna": {"in": 0.10, "cached": 0.01, "out": 0.50},
    "gpt-4.1-mini": {"in": 0.40, "cached": 0.10, "out": 1.60},
}

card = contextvars.ContextVar("wb_usage_card", default=None)


def _path() -> Path:
    explicit = os.environ.get("PRINTFLOW_WB_USAGE_LOG")
    return Path(explicit) if explicit else Path(os.environ.get("PRINTFLOW_LOG_DIR", "logs")) / "wb_usage.jsonl"


def _dump(usage) -> dict:
    if usage is None:
        return {}
    return usage.model_dump() if hasattr(usage, "model_dump") else dict(usage)


def image_cost(usage: dict) -> float:
    details = usage.get("input_tokens_details") or {}
    text = details.get("text_tokens") or 0
    image = details.get("image_tokens") or 0
    cached = details.get("cached_tokens") or 0
    # The cache discount is applied to image tokens first: they are the reused template.
    cached_image = min(cached, image)
    cached_text = min(cached - cached_image, text)
    price = IMAGE_PRICES
    return (
        (text - cached_text) * price["text_in"]
        + cached_text * price["text_cached"]
        + (image - cached_image) * price["image_in"]
        + cached_image * price["image_cached"]
        + (usage.get("output_tokens") or 0) * price["out"]
    ) / 1e6


def chat_cost(model: str, usage: dict) -> float | None:
    price = next((p for name, p in CHAT_PRICES.items() if model.startswith(name)), None)
    if price is None:
        return None
    prompt = usage.get("prompt_tokens") or 0
    cached = (usage.get("prompt_tokens_details") or {}).get("cached_tokens") or 0
    return (
        (prompt - cached) * price["in"]
        + cached * price["cached"]
        + (usage.get("completion_tokens") or 0) * price["out"]
    ) / 1e6


def lines_for(job_id: str) -> list[dict]:
    """Every logged request of one card, oldest first (the log is read line by line, cheap filter first)."""
    path = _path()
    if not path.exists():
        return []
    found = []
    with path.open(encoding="utf-8") as file:
        for line in file:
            if job_id in line:
                with contextlib.suppress(ValueError):
                    item = json.loads(line)
                    if item.get("job") == job_id:
                        found.append(item)
    return found


def record(kind: str, purpose: str, model: str, usage, **extra) -> None:
    """Never breaks generation: a failed write only goes to the application log."""
    if usage is None:  # fakes in tests and responses without accounting
        return
    try:
        data = _dump(usage)
        cost = image_cost(data) if kind == "image" else chat_cost(model, data)
        line = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), **(card.get() or {}), "kind": kind, "purpose": purpose,
                "model": model, **extra, "cost_usd": round(cost, 6) if cost is not None else None, "usage": data}  # fmt: skip
        path = _path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(line, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001 - usage accounting must never fail a card
        logger.exception("WB usage log write failed")

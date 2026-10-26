"""Generation settings: config.json defaults plus per-algorithm overrides.

A job stores its full config at creation, so later edits never change running jobs.
"""

import json

from printflow.wb_studio.domain.models import COLORS
from printflow.wb_studio.paths import CONFIG_DIR

CONFIG_PATH = CONFIG_DIR / "config.json"

SOURCE_REDRAW = {
    "gallery_revision": "source-redraw-v13",
    "vision_model": "gpt-4.1",
    # The mini model merged separate chest and hem prints into one; the full model counts them.
    "analysis_model": "gpt-4.1",
    # Prints wider than this share of the shirt front are rejected by the gallery filter.
    "max_print_width": 0.7,
}


def load_config() -> dict:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def build_config(colors, algorithm: str, group_size: int) -> dict:
    config = load_config()
    config["colors"] = [color for color in COLORS if color in set(colors)]
    if not config["colors"]:
        raise ValueError("Нужен хотя бы один цвет футболки")
    config["algorithm"] = algorithm
    if algorithm == "source_redraw":
        config.update(SOURCE_REDRAW)
    config["merge_designs"] = group_size
    return config


def default_colors(env) -> list[str]:
    values = list(
        dict.fromkeys(x.strip().lower() for x in env.get("PRINTFLOW_WB_COLORS", "white,black").split(",") if x.strip())
    )
    if not values or any(x not in ("white", "black") for x in values):
        raise ValueError("PRINTFLOW_WB_COLORS: нужны white,black")
    # Generate white first, so later scenes can preserve identity across colours.
    return [x for x in ("white", "black") if x in values]


def merge_designs(env) -> int:
    value = int(env.get("PRINTFLOW_WB_MERGE_DESIGNS", "10"))
    if not 1 <= value <= 15:
        raise ValueError("PRINTFLOW_WB_MERGE_DESIGNS: 1..15 принтов (до 30 вариантов WB с двумя цветами)")
    return value

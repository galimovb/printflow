#!/usr/bin/env python3
"""Прогресс очереди по товарам: карточки и привязка сертификатов (только чтение базы).

    docker compose exec -T app python -m printflow.scripts.progress                     # все товары
    docker compose exec -T app python -m printflow.scripts.progress --product mousepad  # один
    python -m printflow.scripts.progress                                                 # локально
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter

from printflow.config import load_app_settings
from printflow.products import get_product
from printflow.scripts._cli import add_product_arg, utf8_console
from printflow.services.ozon.retry import WAIT_REASON


def main() -> int:
    utf8_console()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_product_arg(parser, required=False)
    args = parser.parse_args()
    settings = load_app_settings()
    db = sqlite3.connect(f"file:{settings.jobs_db}?mode=ro", uri=True)
    for name in [args.product] if args.product else settings.products:
        rows = db.execute("SELECT payload, status, stage, result, error FROM jobs WHERE product = ?",
                          (name,)).fetchall()
        print(f"═══ {get_product(name).title} ({name}) ═══")
        report(rows)
    db.close()
    return 0


def report(rows: list[tuple]) -> None:
    cards, certs = [], []
    for payload, status, stage, result, error in rows:
        kind = json.loads(payload).get("kind")
        item = (status, stage, json.loads(result or "{}"), error or "")
        (cards if kind == "card" else certs if kind == "certificate" else []).append(item)

    print("КАРТОЧКИ")
    print(f"  всего: {len(cards)}")
    done = [c for c in cards if c[0] == "done"]
    published = [c for c in done if (c[2].get("ozon") or {}).get("product_ids")]
    offers = sum(len(c[2]["ozon"]["product_ids"]) for c in published)
    trial = len(done) - len(published)
    print(f"  готово: {len(done)} (выложено на Ozon: {len(published)}, товаров: {offers}"
          + (f"; пробных без выкладки: {trial}" if trial else "") + ")")
    ozon_wait = [c for c in cards if c[0] == "pending" and c[3].startswith(WAIT_REASON)]
    print(f"  ждут сброса лимитов Ozon (03:00): {len(ozon_wait)}")
    working = Counter(c[1] for c in cards if c[0] in ("pending", "running") and c not in ozon_wait)
    print(f"  в работе: {sum(working.values())}  " + ", ".join(f"{k}: {v}" for k, v in working.most_common()))
    failed = [c for c in cards if c[0] == "failed"]
    reasons = Counter(failure_reason(c[3]) for c in failed)
    print(f"  упало: {len(failed)}  " + ", ".join(f"{k}: {v}" for k, v in reasons.most_common()))

    print("СЕРТИФИКАТЫ")
    print(f"  задач: {len(certs)}")
    bound = [c for c in certs if c[0] == "done"]
    print(f"  привязано: {len(bound)} (товаров: {sum(int(c[2].get('products') or 0) for c in bound)})")
    cert_ozon_wait = [c for c in certs if c[0] == "pending" and c[3].startswith(WAIT_REASON)]
    print(f"  ждут сброса лимитов Ozon (03:00): {len(cert_ozon_wait)}")
    waiting = [c for c in certs if c[0] == "pending" and c[1] in ("waiting", "waiting_sku") and c not in cert_ozon_wait]
    print(f"  ждут SKU (модерация): {len(waiting)}")
    other = Counter(c[1] for c in certs if c[0] in ("pending", "running") and c not in waiting
                    and c not in cert_ozon_wait)
    print(f"  в работе: {sum(other.values())}  " + ", ".join(f"{k}: {v}" for k, v in other.most_common()))
    cert_failed = [c for c in certs if c[0] == "failed"]
    print(f"  упало: {len(cert_failed)}  " + ", ".join(f"{k}: {v}" for k, v in Counter(failure_reason(c[3]) for c in cert_failed).most_common()))


def failure_reason(error: str) -> str:
    """Короткая причина падения для сводки."""
    text = error.lower()
    if "moderation_blocked" in text or "safety system" in text:
        return "фильтр OpenAI"
    if "insufficient_quota" in text or "credits" in text:
        return "нет баланса OpenAI"
    if "skipped" in text:
        return "Ozon skipped"
    if "ozon" in text:
        return "ошибка Ozon"
    if "sku" in text:
        return "нет SKU"
    return error.split(":", 1)[0][:40] or "?"


if __name__ == "__main__":
    sys.exit(main())

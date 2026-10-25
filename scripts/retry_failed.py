#!/usr/bin/env python3
"""Вернуть упавшие задачи в очередь пачкой — кроме тех, где повтор не поможет (по умолчанию фильтр OpenAI).

Причины те же, что в сводке progress: «нет баланса OpenAI», «фильтр OpenAI», «ошибка Ozon», PermissionDeniedError…
Задача продолжит с места падения (готовые шаги не повторяются), попытки считаются заново.

    docker compose exec -T app python -m printflow.scripts.retry_failed --dry-run           # все товары
    docker compose exec -T app python -m printflow.scripts.retry_failed --product shopper
    docker compose exec -T app python -m printflow.scripts.retry_failed --only "нет баланса OpenAI"
    docker compose exec -T app python -m printflow.scripts.retry_failed --product mousepad --ozon-waits  # и не ждать 03:00
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from collections import Counter

from printflow.config import load_app_settings
from printflow.repositories.jobs import JobRepository
from printflow.scripts._cli import add_product_arg, utf8_console
from printflow.scripts.progress import failure_reason
from printflow.services.ozon.retry import WAIT_REASON

NEVER_RETRY = ("фильтр OpenAI",)


def main() -> int:
    utf8_console()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_product_arg(parser, required=False)
    parser.add_argument("--dry-run", action="store_true", help="только показать, что будет перезапущено")
    parser.add_argument("--ozon-waits", action="store_true",
                        help="ещё и снять ожидание 03:00 у задач, отложенных из-за ошибки Ozon (запустить сейчас)")
    parser.add_argument("--only", action="append", metavar="ПРИЧИНА", help="перезапустить только эти причины")
    parser.add_argument("--skip", action="append", metavar="ПРИЧИНА", default=list(NEVER_RETRY),
                        help=f"не перезапускать эти причины (по умолчанию: {', '.join(NEVER_RETRY)})")
    args = parser.parse_args()

    settings = load_app_settings()
    with sqlite3.connect(f"file:{settings.jobs_db}?mode=ro", uri=True) as db:
        sql, params = "SELECT id, error FROM jobs WHERE status = 'failed'", ()
        if args.product:
            sql, params = sql + " AND product = ?", (args.product,)
        failed = db.execute(sql, params).fetchall()
    chosen, skipped = [], Counter()
    for job_id, error in failed:
        reason = failure_reason(error or "")
        if reason in args.skip or (args.only and reason not in args.only):
            skipped[reason] += 1
        else:
            chosen.append((job_id, reason))

    print(f"Упало: {len(failed)}. Перезапуск: {len(chosen)}  " +
          ", ".join(f"{k}: {v}" for k, v in Counter(r for _, r in chosen).most_common()))
    if skipped:
        print("Остаются упавшими: " + ", ".join(f"{k}: {v}" for k, v in skipped.most_common()))
    if args.dry_run:
        return 0
    repo = JobRepository(settings.jobs_db, timeout_sec=settings.db_timeout_sec)
    for job_id, _ in chosen:
        repo.reset_failed(job_id)
    if chosen:
        print(f"Возвращено в очередь: {len(chosen)}")
    if args.ozon_waits:
        for name in [args.product] if args.product else settings.products:
            print(f"{name}: снято ожидание 03:00 у {repo.release_ozon_waits(name, WAIT_REASON)} задач")
    return 0


if __name__ == "__main__":
    sys.exit(main())

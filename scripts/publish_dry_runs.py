#!/usr/bin/env python3
"""Выложить на Ozon карточки, поставленные пробно (--dry-run): принт и галерея уже готовы, в Ozon уходит
только карточка (дальше — как обычно: ожидание лимитов, сертификат).

    docker compose exec -T app python -m printflow.scripts.publish_dry_runs --product mousepad --dry-run  # сколько
    docker compose exec -T app python -m printflow.scripts.publish_dry_runs --product mousepad

Нужны ключи кабинета товара (<ТОВАР>_OZON_CLIENT_ID / _API_KEY) в printflow/.env.
"""
from __future__ import annotations

import argparse
import sqlite3
import sys

from printflow.repositories.jobs import JobRepository
from printflow.scripts._cli import add_product_arg, target, utf8_console


def main() -> int:
    utf8_console()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_product_arg(parser)
    parser.add_argument("--dry-run", action="store_true", help="только посчитать, ничего не менять")
    args = parser.parse_args()

    t = target(args.product)
    if not t.settings.ozon.configured and not args.dry_run:
        sys.exit(f"Сначала задайте {t.product.env_prefix}_OZON_CLIENT_ID и _API_KEY в printflow/.env "
                 "и перезапустите app — иначе выкладка упадёт")
    if args.dry_run:
        with sqlite3.connect(f"file:{t.app.jobs_db}?mode=ro", uri=True) as db:
            count = db.execute(
                "SELECT count(*) FROM jobs WHERE product = ? AND status = 'done'"
                " AND json_extract(payload, '$.kind') = 'card' AND json_extract(payload, '$.dry_run') = 1",
                (t.product.name,)).fetchone()[0]
        print(f"Пробных карточек «{t.product.title}», готовых к выкладке: {count}")
        return 0
    repo = JobRepository(t.app.jobs_db, timeout_sec=t.app.db_timeout_sec)
    print(f"Поставлено на выкладку: {repo.publish_dry_runs(t.product.name)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

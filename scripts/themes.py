#!/usr/bin/env python3
"""Принты по тематикам: по N задач на тематику, идею каждого принта GPT придумывает сам.

Тематики — products/<товар>/config/themes.json. Направления принтов идут по кругу по списку «что уже продаётся»,
а в промпт передаются описания уже нарисованного в тематике (из базы), чтобы не повторяться.

    python -m printflow.scripts.themes --product mousepad --all --count 100
    python -m printflow.scripts.themes --product mousepad --theme cats space --count 10 --dry-run
    python -m printflow.scripts.themes --product shopper --theme cats space --count 10 --dry-run

Каждый запуск ставит новые --count задач на тематику. Нужен запущенный сервис (docker compose up -d),
задачи уходят в POST /api/v1/<товар>/jobs/batch.
"""
from __future__ import annotations

import argparse
import sys
import uuid

import httpx

from printflow.scripts._cli import add_product_arg, target, utf8_console


def main() -> int:
    utf8_console()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_product_arg(parser)
    which = parser.add_mutually_exclusive_group(required=True)
    which.add_argument("--theme", nargs="+", default=[], help="key тематики из themes.json")
    which.add_argument("--all", action="store_true", help="все тематики")
    parser.add_argument("--count", type=int, required=True, help="сколько принтов на тематику")
    parser.add_argument("--dry-run", action="store_true", help="сгенерировать, но не выкладывать на Ozon")
    parser.add_argument("--api", default=None, help="адрес API (по умолчанию SM_HOST:SM_PORT)")
    parser.add_argument("--batch-size", type=int, default=50, help="задач в одном запросе (одна транзакция), до 500")
    args = parser.parse_args()
    if args.count < 1:
        parser.error("--count должен быть больше нуля")
    if not 1 <= args.batch_size <= 500:
        parser.error("--batch-size должен быть от 1 до 500")

    t = target(args.product)
    token = t.settings.api.token
    if not token:
        sys.exit(f"Нет {t.product.env_prefix}_API_TOKEN в printflow/.env")
    themes = t.product.themes
    if not themes:
        sys.exit(f"Нет тематик в products/{t.product.name}/themes.json")
    keys = list(themes) if args.all else args.theme
    if missing := [k for k in keys if k not in themes]:
        sys.exit(f"Нет таких тематик: {', '.join(missing)}. Есть: {', '.join(themes)}")

    run = uuid.uuid4().hex[:8]  # повтор той же пачки (сбой сети) не создаёт дублей
    # тематики вперемешку: первые принты каждой тематики готовы раньше, а не одна тематика целиком
    # theme_step — номер принта в тематике: подряд идущие принты тематики берут разные направления
    jobs = [{"theme_key": key, "theme_step": i, "dry_run": args.dry_run, "external_id": f"theme:{key}:{run}:{i}"}
            for i in range(args.count) for key in keys]
    counts = {"+": 0, "=": 0, "!": 0}
    # trust_env=False: API локальный, системный прокси (HTTP_PROXY у VPN) ответил бы на него 503
    with httpx.Client(base_url=args.api or t.app.api_url, headers={"Authorization": f"Bearer {token}"},
                      timeout=t.settings.http.timeout_sec, trust_env=False) as client:
        for start in range(0, len(jobs), args.batch_size):
            batch = jobs[start:start + args.batch_size]
            try:
                response = client.post(f"{t.api_prefix}/jobs/batch", json={"jobs": batch})
                response.raise_for_status()
            except httpx.HTTPError as exc:
                counts["!"] += len(batch)
                detail = (f"HTTP {exc.response.status_code} {exc.response.text[:300]}"
                          if isinstance(exc, httpx.HTTPStatusError) else str(exc))
                print(f"  ! задачи {start + 1}–{start + len(batch)} не поставлены: {type(exc).__name__} {detail}")
                continue
            for job in response.json()["jobs"]:
                counts["+" if job["created"] else "="] += 1
            print(f"[{start + len(batch)}/{len(jobs)}] новых: {counts['+']}, ошибок: {counts['!']}")
    print(f"Поставлено задач: {counts['+']} ({len(keys)} тематик × {args.count}), ошибок: {counts['!']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

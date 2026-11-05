"""Progress of the WB studio queue: cards by status, publications, what is on WB, per theme.

Reads the queue database read-only, so it is safe while the queue runs.

    python -m printflow.scripts.wb_progress
    python -m printflow.scripts.wb_progress --watch 30          # refresh every 30 seconds
    python -m printflow.scripts.wb_progress --themes active     # only themes with work left
"""

import argparse
import collections
import json
import os
import sqlite3
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

DEFAULT_DB = Path(__file__).resolve().parents[1] / "data-wb-queue" / "jobs.db"
STATUS = {"done": "готово", "failed": "отклонено", "retry": "сбой, повторить", "running": "в работе", "pending": "в очереди"}


def load(db_path: Path) -> list[tuple]:
    db = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    return [
        (job_id, status, error or "", json.loads(payload), json.loads(result or "{}"), finished or "")
        for job_id, status, error, payload, result, finished in db.execute(
            "SELECT id, status, error, payload, result, finished_at FROM jobs WHERE product = 'tee_wb' ORDER BY number"
        )
    ]


def card_status(status: str, error: str) -> str:
    # A permanent failure is a rejection; any other failure is a transient error worth a retry.
    return "retry" if status == "failed" and not error.startswith("PermanentError") else status


def report(rows: list[tuple], themes_filter: str) -> str:
    today = (datetime.now(UTC) + timedelta(hours=3)).strftime("%Y-%m-%d")  # Moscow day
    since = (datetime.fromisoformat(today) - timedelta(hours=3)).isoformat()
    cards, theme_of, order = {}, {}, []
    publications = []
    for job_id, status, error, payload, result, finished in rows:
        kind = payload.get("kind")
        if kind == "wb_card":
            cards[job_id] = (card_status(status, error), finished, payload["theme"])
            theme_of[job_id] = payload["theme"]
            if payload["theme"] not in order:
                order.append(payload["theme"])
        elif kind == "wb_publish":
            publications.append((status, error, payload, result, finished))

    on_wb, on_wb_today, sent, published_cards = set(), set(), set(), set()
    publish_status, publish_errors = collections.Counter(), collections.Counter()
    per_theme_wb = collections.Counter()  # prints on WB per theme
    for status, error, payload, result, finished in publications:
        sent.update(payload["card_ids"])
        publish_status[status] += 1
        if status == "done":
            vendors = set((result.get("cards") or {}).keys())
            (on_wb_today if finished >= since else on_wb).update(vendors)
            for card_id in set(payload["card_ids"]) - published_cards:
                per_theme_wb[theme_of.get(card_id)] += 1
            published_cards.update(payload["card_ids"])
        elif error:
            publish_errors[error[:70]] += 1
    new_today = on_wb_today - on_wb
    all_wb = on_wb | on_wb_today

    totals = collections.Counter(status for status, _, _ in cards.values())
    done = {c for c, (s, _, _) in cards.items() if s == "done"}
    made_today = {c for c, (s, f, _) in cards.items() if s == "done" and f >= since}
    lines = [
        f"WB студия, {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "ТОВАРЫ (генерация карточек)",
        f"  {'всего':<17}{len(cards)}",
    ]
    lines += [f"  {STATUS[s]:<17}{totals[s]}" for s in STATUS if totals[s]]
    lines += [
        "",
        "WB",
        f"  на WB              принтов {len({v[4:13] for v in all_wb})}, карточек {len(all_wb)}",
        f"  выложено сегодня   принтов {len({v[4:13] for v in new_today})}, карточек {len(new_today)}",
        f"  готово, не отправлено на WB   {len(done - sent)}",
        f"  отправлено, ещё публикуется   {len((done & sent) - published_cards)}",
        "",
        f"СЕГОДНЯ сгенерировано принтов {len(made_today)}, из них на WB {len(made_today & published_cards)}",
        "",
        "ПУБЛИКАЦИИ (группы)  " + ", ".join(f"{s} {n}" for s, n in sorted(publish_status.items())),
    ]
    lines += [f"  ошибка {n}x: {e}" for e, n in publish_errors.most_common(3)]

    per = collections.defaultdict(collections.Counter)
    for status, _, theme in cards.values():
        per[theme][status] += 1
    lines += ["", f"{'ТЕМА':<36}{'готово':>7}{'отклон':>7}{'сбой':>6}{'работа':>7}{'очередь':>8}{'на WB':>7}"]
    for theme in order:
        c = per[theme]
        active = c["pending"] or c["running"] or c["retry"]
        if themes_filter == "active" and not active:
            continue
        lines.append(
            f"{theme[:35]:<36}{c['done']:>7}{c['failed']:>7}{c['retry']:>6}{c['running']:>7}{c['pending']:>8}"
            f"{per_theme_wb[theme]:>7}"
        )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB, help="queue database (default: data-wb-queue/jobs.db)")
    parser.add_argument("--watch", type=int, metavar="SEC", help="refresh every SEC seconds")
    parser.add_argument("--themes", choices=("all", "active"), default="all", help="themes to list")
    args = parser.parse_args()
    while True:
        text = report(load(args.db), args.themes)
        if args.watch:
            os.system("cls" if os.name == "nt" else "clear")
        print(text, flush=True)
        if not args.watch:
            break
        time.sleep(args.watch)


if __name__ == "__main__":
    main()

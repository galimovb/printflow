"""Parse WB on this computer, generate in the PrintFlow queue (Docker).

Search and galleries run in the local Google Chrome profile, which WB trusts. Each theme
is sent to /api/v1/wb-studio/sources with complete galleries, so the queue workers only
generate and publish and never open a browser. The queue generates --count products and
keeps the rest of --search as a reserve that replaces rejected prints portion by portion.

    python -m printflow.scripts.wb_parse_queue --themes themes.txt --count 20 --search 50
"""

import argparse
import asyncio
from pathlib import Path

import httpx

from printflow.config import load_app_settings, read_env
from printflow.wb_studio.config import default_colors
from printflow.wb_studio.infrastructure.wb import search

RESOLVE_CHUNK = 20  # resolve_product_urls accepts at most 20 links per call


async def parse(theme: str, count: int) -> list[dict]:
    found = await search.discover(theme, count)
    galleries = []
    urls = [card["url"] for card in found]
    for start in range(0, len(urls), RESOLVE_CHUNK):
        galleries += await search.resolve_product_urls(urls[start : start + RESOLVE_CHUNK], skip_errors=True)
    return [
        {"url": g["url"], "image": g["image"], "title": g.get("title", ""), "images": g["images"], "gallery_complete": True}
        for g in galleries
        if g.get("images")
    ]


async def send(client: httpx.Client, body: dict, token: str) -> httpx.Response:
    """The queue may be restarting: keep the parsed theme and retry for up to ten minutes."""
    for attempt in range(40):
        try:
            response = client.post("/api/v1/wb-studio/sources", json=body, headers={"Authorization": "Bearer " + token})
            if response.status_code < 500:
                response.raise_for_status()
                return response
        except httpx.TransportError:
            pass
        print(f"Очередь недоступна, повтор через 15 с ({attempt + 1}/40)", flush=True)
        await asyncio.sleep(15)
    raise SystemExit("Очередь недоступна 10 минут")


@search.parsing_batch
async def run(args, themes: list[str]) -> None:
    env = read_env()
    token = env.get("PRINTFLOW_WB_API_TOKEN", "")
    if not token:
        raise SystemExit("Не задан PRINTFLOW_WB_API_TOKEN")
    colors = args.colors or default_colors(env)
    with httpx.Client(base_url=args.api or load_app_settings().api_url, trust_env=False, timeout=60) as client:
        for number, theme in enumerate(themes, 1):
            sources = await parse(theme, args.search)
            if not sources:
                print(f"[{number}/{len(themes)}] {theme}: товаров с галереями не найдено", flush=True)
                continue
            work = min(args.count, len(sources))
            body = {"theme": theme, "sources": sources, "algorithm": "source_redraw", "colors": colors,
                    "design_limit": work}  # fmt: skip
            response = await send(client, body, token)
            print(f"[{number}/{len(themes)}] {theme}: в работу {work}, в запасе {len(sources) - work},"
                  f" задача {response.json()['id']}", flush=True)  # fmt: skip


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--theme")
    inputs.add_argument("--themes", type=Path, help="UTF-8 file, one search query per line")
    parser.add_argument("--count", type=int, choices=range(1, 21), default=20, help="products per theme")
    parser.add_argument("--search", type=int, choices=range(1, 61), default=50, help="products found, reserve included")
    parser.add_argument("--colors", nargs="+", choices=["white", "black"])
    parser.add_argument("--api", help="PrintFlow API, default from settings (http://127.0.0.1:8090)")
    args = parser.parse_args()
    args.search = max(args.search, args.count)
    themes = [args.theme] if args.theme else args.themes.read_text(encoding="utf-8-sig").splitlines()
    themes = list(dict.fromkeys(t.strip() for t in themes if t.strip()))
    asyncio.run(run(args, themes))


if __name__ == "__main__":
    main()

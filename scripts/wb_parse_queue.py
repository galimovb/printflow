"""Parse WB on this computer, generate in the PrintFlow queue (Docker).

Search and galleries run in the local Google Chrome profile, which WB trusts. Each theme
is sent to /api/v1/wb-studio/sources with complete galleries, so the queue workers only
generate and publish and never open a browser. The queue generates --count products and
keeps the rest of --search as a reserve that replaces rejected prints portion by portion.

    python -m printflow.scripts.wb_parse_queue --themes themes.txt --count 20 --search 50
    python -m printflow.scripts.wb_parse_queue --watch   # themes from /studio/wb/themes, until closed
"""

import argparse
import asyncio
import contextlib
from pathlib import Path

import httpx

from printflow.config import load_app_settings, read_env
from printflow.wb_studio.config import default_colors
from printflow.wb_studio.infrastructure.wb import browser, search

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


@browser.parsing_batch
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
            body = {"theme": theme, "sources": sources, "algorithm": args.algorithm, "colors": colors,
                    "design_limit": work}  # fmt: skip
            response = await send(client, body, token)
            print(f"[{number}/{len(themes)}] {theme}: в работу {work}, в запасе {len(sources) - work},"
                  f" задача {response.json()['id']}", flush=True)  # fmt: skip


STUDIO = "/api/v1/wb-studio"


async def handle(client: httpx.Client, token: str, request: dict) -> tuple[str, str | None, str]:
    """One theme from the interface: parse it here and hand its products to the queue."""
    sources = await parse(request["theme"], request["search"])
    if not sources:
        return "empty", None, "товаров с галереями не найдено"
    work = min(request["count"], len(sources))
    body = {"theme": request["theme"], "sources": sources, "algorithm": request["algorithm"],
            "colors": request["colors"], "design_limit": work}  # fmt: skip
    response = await send(client, body, token)
    return "queued", response.json()["id"], f"в работу {work}, в запасе {len(sources) - work}"


@browser.parsing_batch
async def watch(args) -> None:
    """Wait for themes added in the interface; a heartbeat shows the interface that the parser is running."""
    env = read_env()
    token = env.get("PRINTFLOW_WB_API_TOKEN", "")
    if not token:
        raise SystemExit("Не задан PRINTFLOW_WB_API_TOKEN")
    base = args.api or load_app_settings().api_url
    headers = {"Authorization": "Bearer " + token}
    current: dict = {"theme": None}

    async def beat() -> None:
        with httpx.Client(base_url=base, trust_env=False, timeout=20) as pulse:
            while True:
                with contextlib.suppress(httpx.HTTPError):
                    await asyncio.to_thread(pulse.post, STUDIO + "/parser/heartbeat", json={"current": current["theme"]},
                                            headers=headers)  # fmt: skip
                await asyncio.sleep(30)

    beater = asyncio.create_task(beat())
    print(f"Жду темы из интерфейса {base}/studio/wb/themes. Окно не закрывайте.", flush=True)
    try:
        with httpx.Client(base_url=base, trust_env=False, timeout=60) as client:
            while True:
                try:
                    response = await asyncio.to_thread(client.post, STUDIO + "/parser/claim", json={}, headers=headers)
                    response.raise_for_status()
                    request = response.json()["request"]
                except httpx.HTTPError as error:
                    print(f"Очередь недоступна ({type(error).__name__}), повтор через 30 с", flush=True)
                    await asyncio.sleep(30)
                    continue
                if not request:
                    await asyncio.sleep(args.poll)
                    continue
                current["theme"] = request["theme"]
                print(f"Тема «{request['theme']}»: ищу {request['search']} товаров", flush=True)
                try:
                    status, campaign, message = await handle(client, token, request)
                except (Exception, SystemExit) as error:  # noqa: BLE001 - one theme must not stop the watcher
                    status, campaign, message = "failed", None, f"{type(error).__name__}: {error}"
                print(f"Тема «{request['theme']}»: {status} {message}", flush=True)
                with contextlib.suppress(httpx.HTTPError):
                    client.post(STUDIO + f"/theme-requests/{request['id']}/finish", headers=headers,
                                json={"status": status, "campaign_id": campaign, "message": message})  # fmt: skip
                current["theme"] = None
    finally:
        beater.cancel()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--theme")
    inputs.add_argument("--themes", type=Path, help="UTF-8 file, one search query per line")
    inputs.add_argument("--watch", action="store_true", help="take themes added in /studio/wb/themes until closed")
    parser.add_argument("--poll", type=float, default=20, help="--watch: seconds between checks for new themes")
    parser.add_argument("--count", type=int, choices=range(1, 21), default=20, help="products per theme")
    parser.add_argument("--search", type=int, choices=range(1, 61), default=50, help="products found, reserve included")
    parser.add_argument("--colors", nargs="+", choices=["white", "black"])
    parser.add_argument(
        "--algorithm", choices=["source_redraw", "model_reference", "template_mockup"], default="source_redraw",
        help="model_reference: people in the frames are ready models from wb_studio/assets/models; "
        "template_mockup: the print goes onto ready mockup series from the tee-mockup-template-* buckets",
    )
    parser.add_argument("--api", help="PrintFlow API, default from settings (http://127.0.0.1:8090)")
    args = parser.parse_args()
    args.search = max(args.search, args.count)
    if args.watch:
        asyncio.run(watch(args))
        return
    themes = [args.theme] if args.theme else args.themes.read_text(encoding="utf-8-sig").splitlines()
    themes = list(dict.fromkeys(t.strip() for t in themes if t.strip()))
    asyncio.run(run(args, themes))


if __name__ == "__main__":
    main()

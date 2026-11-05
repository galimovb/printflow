"""Read the visible WB search order; never manufacture ranks or bypass challenges."""

import asyncio
import random
import re
from urllib.parse import quote

from printflow.domain.errors import PermanentError

from .browser import browser_options, browser_page, wait_for_access

NO_PHOTOS = "WB не вернул фото карточки"


def normalize_cards(cards, limit):
    result = []
    seen = set()
    for card in cards:
        match = re.search(r"/catalog/(\d+)/detail", str(card.get("url", "")))
        if not match or match[1] in seen or not str(card.get("image", "")).startswith("https://"):
            continue
        seen.add(match[1])
        result.append(
            {
                "sku": match[1],
                "rank": len(result) + 1,
                "url": card["url"],
                "title": str(card.get("title", "")).strip(),
                "image": card["image"],
            }
        )
        images = card.get("images", [])
        if images:
            result[-1]["images"] = list(dict.fromkeys(str(x) for x in images if str(x).startswith("https://")))[:20]
        if card.get("gallery_complete"):
            result[-1]["gallery_complete"] = True
        if len(result) == limit:
            break
    return result


def shirt_query(theme: str) -> str:
    """A bare theme (xanax, ира, jesus) finds pills and mugs on WB; the search is always for T-shirts."""
    return theme if "футболк" in theme.lower() else f"футболка {theme}"


async def discover(query, limit=20):
    from urllib.parse import parse_qs, urlparse

    from printflow.config import read_env

    from .catalog import catalog_cards

    query = shirt_query(query)
    env = read_env()
    async with browser_page(env) as (context, page):
        pending = set()
        cards = []
        try:
            headless = browser_options(env)["headless"]

            async def capture(response):
                parsed = urlparse(response.url)
                path = parsed.path.lower()
                if not (parsed.hostname or "").endswith((".wildberries.ru", ".wb.ru")):
                    return
                if not any(x in path for x in ("/search", "/catalog")):
                    return
                params = parse_qs(parsed.query)
                requested = (params.get("query") or params.get("search") or [""])[0]
                if requested and requested.casefold() != query.casefold():
                    return
                if response.status != 200:
                    return
                try:
                    items = catalog_cards(await response.json())
                except Exception:
                    return
                cards.extend(items)

            def on_response(response):
                task = asyncio.create_task(capture(response))
                pending.add(task)
                task.add_done_callback(pending.discard)

            page.on("response", on_response)
            dom = []
            for attempt in range(3):
                response = await page.goto(
                    "https://www.wildberries.ru/catalog/0/search.aspx?sort=popular&search=" + quote(query),
                    wait_until="domcontentloaded",
                )
                await wait_for_access(page, headless, status=response.status if response else None)
                for _ in range(15):
                    if pending:
                        await asyncio.gather(*tuple(pending), return_exceptions=True)
                    # Prefer the same JSON products as the seller parser, not thumbnail DOM order.
                    found = normalize_cards(cards, limit)
                    if len(found) >= limit:
                        return found
                    raw = await page.locator("article.product-card").evaluate_all("""nodes => nodes.map(n => {
                        const a=n.querySelector('a[href*=\"/catalog/\"][href*=\"/detail\"]');
                        const img=n.querySelector('img');
                        return {url:a?.href||'',title:img?.alt||n.innerText||'',image:img?.currentSrc||img?.src||''};
                    })""")
                    dom = normalize_cards(raw, limit)
                    if not cards and len(dom) >= limit:
                        return dom
                    await wait_for_access(page, headless)
                    await page.mouse.wheel(0, 900)
                    await asyncio.sleep(1)
                if normalize_cards(cards, limit) or dom:
                    break
                if attempt < 2:
                    import logging

                    logging.getLogger(__name__).warning("WB: каталог не получен, повторное открытие %s/3", attempt + 2)
                    await asyncio.sleep(random.uniform(1.0, 2.5))
            found = normalize_cards(cards, limit) or dom
            if not found:
                await wait_for_access(page, headless, status=response.status if response else None)
                raise PermanentError(
                    "Страница WB открылась, но данные товаров не получены. Диагностика сохранена; это не ошибка OpenAI."
                )
            return found
        except Exception:
            import json
            from pathlib import Path

            folder = Path(browser_options(env)["user_data_dir"]).parent / "printflow-diagnostics"
            folder.mkdir(parents=True, exist_ok=True)
            if "page" in locals():
                try:
                    await page.screenshot(path=str(folder / "search-error.png"))
                    body = (await page.locator("body").inner_text(timeout=3000))[:5000]
                    (folder / "search-error.json").write_text(
                        json.dumps(
                            {
                                "query": query,
                                "page_url": page.url,
                                "title": await page.title(),
                                "body": body,
                                "catalog_products": len(cards),
                            },
                            ensure_ascii=False,
                            indent=2,
                        ),
                        encoding="utf-8",
                    )
                    import logging

                    logging.getLogger(__name__).error("Диагностика WB: %s", folder)
                except Exception:
                    pass
            raise
        finally:
            if pending:
                await asyncio.gather(*tuple(pending), return_exceptions=True)


def validate_product_urls(urls):
    from urllib.parse import urlparse

    result = []
    for url in urls:
        parsed = urlparse(str(url).strip())
        match = re.fullmatch(r"/catalog/(\d+)/detail\.aspx/?", parsed.path)
        if parsed.scheme != "https" or parsed.hostname not in ("wildberries.ru", "www.wildberries.ru") or not match:
            raise ValueError("Нужна ссылка https://www.wildberries.ru/catalog/АРТИКУЛ/detail.aspx")
        canonical = f"https://www.wildberries.ru/catalog/{match[1]}/detail.aspx"
        if canonical not in result:
            result.append(canonical)
    if not 1 <= len(result) <= 20:
        raise ValueError("Нужно от 1 до 20 ссылок WB")
    return result


async def resolve_product_urls(urls, skip_errors=False):
    """skip_errors: a batch keeps the other galleries when one product page fails."""
    from printflow.config import read_env

    urls = validate_product_urls(urls)
    env = read_env()
    cards = []
    async with browser_page(env) as (context, page):
        headless = browser_options(env)["headless"]
        for url in urls:
            try:
                response = await page.goto(url, wait_until="domcontentloaded")
                await wait_for_access(page, headless, status=response.status if response else None)
                images = []
                sku = re.search(r"/catalog/(\d+)/", url)[1]
                collected = {}
                stable = 0
                for attempt in range(20):
                    observed = await page.evaluate(
                        r"""sku => {
                    const found=new Map();
                    for(const img of document.querySelectorAll('img')) {
                        const src=img.currentSrc||img.src||img.getAttribute('data-src')||'';
                        if(!src.startsWith('https://') || !src.includes('/'+sku+'/images/'))continue;
                        const match=src.match(/\/(\d+)\.(?:webp|jpg|png)(?:\?|$)/i);
                        if(!match)continue;
                        const number=Number(match[1]);
                        const score=src.includes('/big/')?3:src.includes('/c516x688/')?2:1;
                        if(!found.has(number)||found.get(number).score<score)found.set(number,{src,score});
                    }
                    return [...found.entries()].sort((a,b)=>a[0]-b[0]).slice(0,20).map(x=>x[1].src);
                }""",
                        sku,
                    )
                    previous = len(collected)
                    for image_url in observed:
                        number = int(re.search(r"/(\d+)\.(?:webp|jpg|png)(?:\?|$)", image_url, re.I)[1])

                        def quality(value):
                            return 3 if "/big/" in value else 2 if "/c516x688/" in value else 1

                        if number not in collected or quality(image_url) > quality(collected[number]):
                            collected[number] = image_url
                    stable = stable + 1 if len(collected) == previous else 0
                    if len(collected) >= 20 or (collected and stable >= 4 and attempt >= 5):
                        break
                    # Reveal lazy thumbnails in their own scrollable strip as well as on the page.
                    await page.evaluate(
                        r"""sku => {
                    const moved=new Set();
                    for(const img of document.querySelectorAll('img')) {
                        if(!(img.currentSrc||img.src||'').includes('/'+sku+'/images/'))continue;
                        let node=img.parentElement;
                        while(node && node!==document.body) {
                            if(!moved.has(node) && node.scrollHeight>node.clientHeight+20 && node.clientHeight>0) {
                                node.scrollTop+=Math.max(200,node.clientHeight*.8);moved.add(node);
                            }
                            if(!moved.has(node) && node.scrollWidth>node.clientWidth+20 && node.clientWidth>0) {
                                node.scrollLeft+=Math.max(200,node.clientWidth*.8);moved.add(node);
                            }
                            node=node.parentElement;
                        }
                    }
                }""",
                        sku,
                    )
                    await page.mouse.wheel(0, 450)
                    await asyncio.sleep(1)
                images = [collected[n] for n in sorted(collected)][:20]
                if not images:
                    raise PermanentError(NO_PHOTOS + ": " + url)
                cards.append(
                    {
                        "url": url,
                        "image": images[0],
                        "images": images,
                        "gallery_complete": True,
                        "title": await page.title(),
                    }
                )
            except Exception as exc:
                if not skip_errors:
                    raise
                print("PARSE FAILED", url, str(exc), flush=True)
            await asyncio.sleep(random.uniform(1.0, 2.5))
    return normalize_cards(cards, len(cards))

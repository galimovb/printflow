"""Read the visible WB search order; never manufacture ranks or bypass challenges."""

import asyncio
import contextlib
import random
import re
from contextlib import AsyncExitStack, asynccontextmanager
from contextvars import ContextVar
from functools import wraps
from urllib.parse import quote

from printflow.domain.errors import PermanentError

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


# Chrome profiles cannot be opened by several jobs at once.
_profile_lock = asyncio.Lock()
_batch = ContextVar("wb_parsing_batch", default=None)


@asynccontextmanager
async def parsing_session():
    """One lazily opened browser/page per batch; no browser for cached galleries."""
    if _batch.get() is not None:
        yield
        return
    async with AsyncExitStack() as stack:
        token = _batch.set({"stack": stack, "page": None, "lock": asyncio.Lock()})
        try:
            yield
        finally:
            _batch.reset(token)


def parsing_batch(function):
    @wraps(function)
    async def wrapped(*args, **kwargs):
        async with parsing_session():
            return await function(*args, **kwargs)

    return wrapped


@asynccontextmanager
async def browser_page(env):
    if _batch.get() is None:
        async with parsing_session(), browser_page(env) as value:
            yield value
        return
    state = _batch.get()
    # Sibling jobs may inherit the batch context; serialize access to its one tab.
    async with state["lock"]:
        if state["page"] is None:
            from playwright.async_api import async_playwright

            await state["stack"].enter_async_context(_profile_lock)
            playwright = await state["stack"].enter_async_context(async_playwright())
            context = await open_session(playwright, env)
            state["stack"].push_async_callback(context.close)
            page = await context.new_page()
            await warm_up(page, browser_options(env)["headless"])
            state.update(context=context, page=page)
        yield state["context"], state["page"]


def browser_options(env):
    import os
    import sys
    from pathlib import Path

    from printflow.config import load_app_settings

    profile = env.get("PRINTFLOW_WB_BROWSER_PROFILE")
    if not profile:
        profile = load_app_settings().data_dir / "wb_studio/chrome-profile-wb"
    profile = Path(profile).resolve()
    default_headless = "0" if sys.platform == "win32" or os.environ.get("DISPLAY") else "1"
    return {
        "user_data_dir": str(profile),
        "headless": env.get("PRINTFLOW_WB_HEADLESS", default_headless).lower() in ("1", "true", "yes"),
        "viewport": {"width": 1920, "height": 1080},
        "screen": {"width": 1920, "height": 1080},
        "locale": "ru-RU",
        "timezone_id": "Europe/Moscow",
        "color_scheme": "light",
        "args": [
            "--disable-blink-features=AutomationControlled",
            "--disable-dev-shm-usage",
            "--window-size=1920,1080",
            "--lang=ru-RU",
        ],
        "ignore_default_args": ["--enable-automation"],
        "extra_http_headers": {"Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7"},
    }


async def open_session(playwright, env):
    from pathlib import Path

    options = browser_options(env)
    Path(options["user_data_dir"]).mkdir(parents=True, exist_ok=True)
    import os

    configured = env.get("PRINTFLOW_WB_BROWSER_EXECUTABLE")
    candidates = (
        [Path(configured)]
        if configured
        else [
            Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "Google/Chrome/Application/chrome.exe",
            Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"))
            / "Google/Chrome/Application/chrome.exe",
            Path(os.environ.get("LOCALAPPDATA", "")) / "Google/Chrome/Application/chrome.exe",
        ]
    )
    executable = next((p for p in candidates if p.is_file()), None)
    if executable is None:
        raise PermanentError(
            "Google Chrome не найден. Установите его или задайте PRINTFLOW_WB_BROWSER_EXECUTABLE — полный путь к chrome.exe."
        )
    try:
        context = await playwright.chromium.launch_persistent_context(executable_path=str(executable), **options)
    except Exception as exc:
        raise PermanentError(
            "Не удалось открыть Google Chrome с профилем WB. Закройте процессы с этим профилем и повторите. "
            + str(exc)[:250]
        ) from exc
    context.set_default_timeout(90000)
    context.set_default_navigation_timeout(90000)
    await context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined});")
    return context


def access_is_pending(text, title="", status=None, url=""):
    text = text.lower()
    markers = (
        "подозрительная активность",
        "подтвердите, что вы не робот",
        "доступ ограничен",
        "captcha",
        "проверка браузера",
    )
    combined = (text + " " + title).lower()
    challenge_url = any(x in url.lower() for x in ("/captcha", "/challenge", "/antibot"))
    return (
        challenge_url
        or any(x in combined for x in markers)
        or (status in (403, 498) and (len(text.strip()) < 100 or title.strip() in ("", "...")))
    )


async def wait_for_access(page, headless, seconds=180, status=None):
    import logging

    # WB may render its challenge only after DOMContentLoaded. HTTP 498 must
    # never be treated as a successful empty page while that script loads.
    async def pending():
        try:
            text = await page.locator("body").inner_text(timeout=5000)
            title = await page.title()
            return access_is_pending(text[:4000], title, status, getattr(page, "url", ""))
        except Exception:
            return True  # navigation/reload in progress, not successful access

    await asyncio.sleep(1)
    if not await pending():
        return
    if headless:
        raise PermanentError(
            "WB ограничил доступ (проверка/HTTP 498). Запустите python -m printflow.scripts.wb_session с видимым Google Chrome."
        )
    logging.getLogger(__name__).warning(
        "WB проверяет доступ. Оставьте Google Chrome открытым; при необходимости пройдите проверку вручную. Ожидание до %s секунд.",
        seconds,
    )
    clear_checks = 0
    for _ in range(max(1, seconds // 2)):
        await asyncio.sleep(2)
        clear_checks = 0 if await pending() else clear_checks + 1
        if clear_checks >= 2:
            return
    raise PermanentError(
        f"WB не снял ограничение доступа за {seconds} секунд. Это проверка браузера/ограничение доступа, а не отсутствие товаров. Повторите ту же команду позже; прогресс сохранён."
    )


async def warm_up(page, headless):
    from playwright.async_api import Error

    try:
        response = await page.goto("https://www.wildberries.ru/", wait_until="domcontentloaded")
    except Error as exc:
        if page.is_closed():
            raise
        import logging

        logging.getLogger(__name__).warning("Главная WB не загрузилась; проверим доступ на целевой странице: %s", exc)
        return False
    await wait_for_access(page, headless, status=response.status if response else None)
    for text in ("Хорошо", "Понятно", "Принять", "Согласен"):
        button = page.get_by_role("button", name=text, exact=True)
        if await button.count() and await button.first.is_visible():
            await button.first.click()
            break
    with contextlib.suppress(Exception):
        await page.wait_for_load_state("networkidle", timeout=12000)
    await asyncio.sleep(random.uniform(1.5, 3.0))


async def discover(query, limit=20):
    from urllib.parse import parse_qs, urlparse

    from printflow.config import read_env

    from .catalog import catalog_cards

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

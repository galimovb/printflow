"""One Chrome session per parsing batch; WB access checks are waited out by a person, never bypassed."""

import asyncio
import contextlib
import random
from contextlib import AsyncExitStack, asynccontextmanager
from contextvars import ContextVar
from functools import wraps

from printflow.domain.errors import PermanentError

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
            Path("/usr/bin/google-chrome"),
            Path("/usr/bin/google-chrome-stable"),
        ]
    )
    executable = next((p for p in candidates if p.is_file()), None)
    if executable is None and configured:
        raise PermanentError(f"PRINTFLOW_WB_BROWSER_EXECUTABLE не найден: {configured}")
    # Without Google Chrome (e.g. the Linux image) the Chromium bundled with Playwright is used.
    launch = {"executable_path": str(executable)} if executable else {}
    try:
        context = await playwright.chromium.launch_persistent_context(**launch, **options)
    except Exception as exc:
        raise PermanentError(
            "Не удалось открыть браузер с профилем WB. Закройте процессы с этим профилем и повторите. " + str(exc)[:250]
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

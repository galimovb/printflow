import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock,patch
from printflow.wb_studio.infrastructure.wb.search import browser_page,parsing_session,access_is_pending,browser_options,open_session


class BrowserBatchTest(unittest.TestCase):
    def test_default_profile_and_executable_are_google_chrome(self):
        from pathlib import Path
        async def run():
            context=SimpleNamespace(set_default_timeout=lambda _:None,
                set_default_navigation_timeout=lambda _:None,add_init_script=AsyncMock())
            launch=AsyncMock(return_value=context)
            playwright=SimpleNamespace(chromium=SimpleNamespace(launch_persistent_context=launch))
            with patch.object(Path,'is_file',return_value=True),patch.object(Path,'mkdir'):
                await open_session(playwright,{})
            options=launch.await_args.kwargs
            self.assertTrue(options['executable_path'].replace('\\','/').endswith('Google/Chrome/Application/chrome.exe'))
            self.assertTrue(options['user_data_dir'].replace('\\','/').endswith('wb_studio/chrome-profile-wb'))
        asyncio.run(run())

    def test_batch_reuses_page_and_warms_up_once_and_closes_on_error(self):
        async def run():
            page=object()
            context=SimpleNamespace(new_page=AsyncMock(return_value=page),close=AsyncMock())
            manager=SimpleNamespace(__aenter__=AsyncMock(),__aexit__=AsyncMock())
            class Playwright:
                async def __aenter__(self):return object()
                async def __aexit__(self,*args):pass
            with patch('playwright.async_api.async_playwright',return_value=Playwright()), \
                 patch('printflow.wb_studio.infrastructure.wb.search.open_session',AsyncMock(return_value=context)) as opened, \
                 patch('printflow.wb_studio.infrastructure.wb.search.warm_up',AsyncMock()) as warm, \
                 patch('printflow.wb_studio.infrastructure.wb.search.browser_options',return_value={'headless':False}):
                with self.assertRaisesRegex(RuntimeError,'test'):
                    async with parsing_session():
                        async with browser_page({}) as first:self.assertIs(first[1],page)
                        async with parsing_session():
                            async with browser_page({}) as second:self.assertIs(second[1],page)
                        context.close.assert_not_awaited()
                        raise RuntimeError('test')
                opened.assert_awaited_once();warm.assert_awaited_once()
                context.new_page.assert_awaited_once();context.close.assert_awaited_once()
        asyncio.run(run())

    def test_cached_batch_does_not_launch_browser(self):
        async def run():
            with patch('printflow.wb_studio.infrastructure.wb.search.open_session',AsyncMock()) as opened:
                async with parsing_session():pass
                opened.assert_not_awaited()
        asyncio.run(run())

    def test_challenge_in_title_or_url_is_not_treated_as_a_product(self):
        self.assertTrue(access_is_pending('','Подозрительная активность',200))
        self.assertTrue(access_is_pending('Please wait','',200,'https://www.wildberries.ru/challenge'))
        self.assertFalse(access_is_pending('Футболка с котом','Карточка товара',200,'https://www.wildberries.ru/catalog/123/detail.aspx'))

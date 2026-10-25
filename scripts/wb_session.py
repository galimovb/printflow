"""Open the persistent Google Chrome profile for manual WB session setup."""
import asyncio
from printflow.config import read_env
from printflow.wb_studio.infrastructure.wb.search import open_session,browser_options


async def run():
    from playwright.async_api import async_playwright
    env=read_env();env['PRINTFLOW_WB_HEADLESS']='0'
    print('Профиль:',browser_options(env)['user_data_dir'])
    print('Закройте существующий парсер, если он использует этот профиль.')
    async with async_playwright() as p:
        context=await open_session(p,env)
        try:
            page=await context.new_page()
            await page.goto('https://www.wildberries.ru/',wait_until='domcontentloaded')
            await asyncio.to_thread(input,'Завершите проверку/настройку в Google Chrome. Нажмите Enter здесь для сохранения сессии: ')
        finally:
            await context.close()
    print('Сессия сохранена. Можно запускать задачи WB Studio.')


if __name__=='__main__':asyncio.run(run())

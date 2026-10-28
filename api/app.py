"""Приложение FastAPI для всех товаров: контроллеры каждого товара под /api/v1/<товар> + фоновые процессы
(у каждого товара свой воркер очереди и свой обработчик заказов кабинета).

POST /api/v1/<товар>/jobs                   → 202, карточка в очереди (повтор external_id → 200, та же задача)
POST /api/v1/<товар>/jobs/batch             → пачка карточек одной транзакцией
GET  /api/v1/<товар>/jobs/{id}              → статус, этап, результат
GET  /api/v1/<товар>/jobs?status=…          → список
POST /api/v1/<товар>/jobs/{id}/retry        → перезапуск упавшей задачи с места падения
POST /api/v1/<товар>/prints/{article}/hires → 202, перерисовка принта для печати
GET  /api/v1/<товар>/health, /api/v1/health → без авторизации, размер очереди
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from printflow.api.controllers import health, jobs, prints
from printflow.container import AppContainer

logger = logging.getLogger("printflow.app")


class UTF8JSONResponse(JSONResponse):
    """Явный charset: Windows PowerShell 5.1 без него читает кириллицу как Latin-1."""

    media_type = "application/json; charset=utf-8"


def _background(coro, name: str) -> asyncio.Task:
    """Фоновый процесс, который не умирает молча: если он завершится с ошибкой, она будет в логе."""
    task = asyncio.create_task(coro, name=name)

    def report(done: asyncio.Task) -> None:
        if not done.cancelled() and done.exception() is not None:
            logger.error("%s остановлен с ошибкой", name, exc_info=done.exception())

    task.add_done_callback(report)
    return task


def create_app(container: AppContainer | None = None, *, background: bool = True) -> FastAPI:
    """background=False — без воркеров и обработчиков заказов (тесты, отдельный API-инстанс)."""
    container = container or AppContainer()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        stop = asyncio.Event()
        tasks: list[asyncio.Task] = []
        if background:
            from printflow.config import read_env
            env = read_env()
            def enabled(name, default='0'):
                return env.get(name, default).lower() in ('1', 'true', 'yes')
            if enabled('PRINTFLOW_WB_ENABLED'):
                tasks.append(_background(container.wb_worker.run(stop),'tee_wb: studio queue'))
                tasks.append(_background(container.wb_studio.supervise(stop, enabled('PRINTFLOW_WB_AUTO_PUBLISH')),
                                         'tee_wb: reserve and auto-publication'))
            # PRINTFLOW_PRODUCTS_ENABLED=0 runs the WB studio alone, without Ozon products and order handlers.
            for pc in (container.products.values() if enabled('PRINTFLOW_PRODUCTS_ENABLED', '1') else ()):
                tasks.append(_background(pc.queue_worker.run(stop), f"{pc.name}: очередь"))
                if pc.order_watcher is not None:
                    tasks.append(_background(pc.order_watcher.run(stop), f"{pc.name}: заказы"))
                else:
                    logger.warning("%s: нет ключей Ozon — обработчик заказов не запущен", pc.name)
        yield
        stop.set()
        await asyncio.gather(*tasks, return_exceptions=True)

    app = FastAPI(title="PrintFlow API", version="4.0.0", lifespan=lifespan,
                  default_response_class=UTF8JSONResponse)
    app.state.container = container
    from printflow.wb_studio.api import router as studio_router
    app.include_router(studio_router(container))
    app.include_router(health.app_router(container))
    for pc in container.products.values():
        for controller in (health, jobs, prints):
            app.include_router(controller.router(pc), prefix=f"/api/v1/{pc.name}")
    return app

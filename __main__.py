"""Запуск: python -m printflow — API всех товаров + их воркеры очереди и обработчики заказов."""
from __future__ import annotations

import logging
import os
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

import uvicorn

from printflow.api.app import create_app
from printflow.container import AppContainer


FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"


def log_handlers() -> list[logging.Handler]:
    """Console, plus daily files in PRINTFLOW_LOG_DIR (a mounted volume) that survive container rebuilds."""
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if folder := os.environ.get("PRINTFLOW_LOG_DIR"):
        Path(folder).mkdir(parents=True, exist_ok=True)
        handlers.append(TimedRotatingFileHandler(Path(folder) / "app.log", when="midnight", backupCount=30,
                                                 encoding="utf-8"))
    return handlers


def main() -> None:
    logging.basicConfig(level=logging.INFO, format=FORMAT, handlers=log_handlers())
    container = AppContainer()
    uvicorn.run(create_app(container), host=container.settings.host, port=container.settings.port)


if __name__ == "__main__":
    main()

"""Запуск: python -m printflow — API всех товаров + их воркеры очереди и обработчики заказов."""
from __future__ import annotations

import logging

import uvicorn

from printflow.api.app import create_app
from printflow.container import AppContainer


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    container = AppContainer()
    uvicorn.run(create_app(container), host=container.settings.host, port=container.settings.port)


if __name__ == "__main__":
    main()

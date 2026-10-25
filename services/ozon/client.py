"""HTTP-клиент Ozon Seller API кабинета товара."""
from __future__ import annotations

from typing import Any

import httpx

from printflow.config import OzonSettings
from printflow.domain.errors import PermanentError, ShopperError


class OzonError(ShopperError):
    """Ошибка ответа Ozon (лимиты, отказ импорта): задача ждёт сброса лимитов, см. OzonRetryPolicy."""


class OzonNotConfigured(PermanentError):
    """Нет ключей кабинета: ждать бессмысленно — задача сразу failed с понятным текстом."""


class OzonClient:
    def __init__(self, settings: OzonSettings) -> None:
        if not settings.configured:
            p = settings.env_prefix or "<ТОВАР>"
            raise OzonNotConfigured(f"Не заданы {p}_OZON_CLIENT_ID / {p}_OZON_API_KEY в printflow/.env "
                                    "(после правки — docker compose up -d)")
        self.base_url = settings.api_url
        self.headers = {"Client-Id": settings.client_id, "Api-Key": settings.api_key}
        self.timeout = settings.timeout_sec

    async def post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        async with httpx.AsyncClient(base_url=self.base_url, headers=self.headers, timeout=self.timeout) as client:
            response = await client.post(path, json=body)
        if response.status_code >= 400:
            raise OzonError(f"Ozon {path}: HTTP {response.status_code} {response.text[:500]}")
        return response.json()

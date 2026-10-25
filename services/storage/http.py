"""HTTP-доступ к картинкам: скачать фото товара и проверить, что ссылка открывается публично."""
from __future__ import annotations

import httpx

from printflow.config import HttpSettings
from printflow.domain.errors import ShopperError


class ImageFetcher:
    def __init__(self, settings: HttpSettings) -> None:
        self.timeout = settings.timeout_sec

    async def download(self, url: str) -> bytes:
        """Картинка по ссылке (например, фото товара из XLSX парсера Ozon)."""
        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
            response = await client.get(url)
        if response.status_code != 200 or not response.headers.get("content-type", "").startswith("image/"):
            raise ShopperError(f"Не удалось скачать картинку (HTTP {response.status_code}): {url}")
        return response.content

    async def ensure_public(self, url: str) -> None:
        """Ozon скачивает фото сам — ссылка должна открываться без авторизации."""
        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
            response = await client.head(url)
        if response.status_code != 200:
            raise ShopperError(
                f"Фото недоступно публично (HTTP {response.status_code}): {url} — нужен public-read на бакет"
            )

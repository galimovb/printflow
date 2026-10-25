"""Общие заготовки тестов: настройки без секретов, временная база, заглушки внешних систем."""
from __future__ import annotations

import io
import tempfile
from dataclasses import replace
from pathlib import Path
from typing import Any

from PIL import Image

from printflow.config import (
    AppSettings,
    ProductSettings,
    QueueSettings,
    load_app_settings,
    load_product_settings,
)
from printflow.container import AppContainer
from printflow.migrations.runner import migrate
from printflow.products.mousepad.product import Mousepad
from printflow.products.shopper.product import Shopper
from printflow.repositories.jobs import JobRepository

TOKEN = "test-token"
SHOPPER = Shopper()
MOUSEPAD = Mousepad()


def product_settings(prefix: str, **ozon: Any) -> ProductSettings:
    settings = load_product_settings(prefix)
    return replace(settings, api=replace(settings.api, token=TOKEN),
                   ozon=replace(settings.ozon, client_id="", api_key="", certificate_id=None, **ozon))


def test_settings(data_dir: Path) -> AppSettings:
    return replace(load_app_settings(), data_dir=data_dir, products=("shopper", "mousepad"))


def test_container(data_dir: Path) -> AppContainer:
    """Приложение с обоими товарами: тестовые токены, без ключей Ozon, чистая общая база."""
    settings = test_settings(data_dir)
    migrate(settings.jobs_db)
    return AppContainer(settings=settings, product_settings={
        "shopper": product_settings("SHOPPER", merge_designs=1),
        "mousepad": product_settings("MOUSEPAD", merge_designs=14),
    })


def new_repository(data_dir: Path) -> JobRepository:
    """Чистая база с применёнными миграциями — как после сервиса migrate."""
    path = data_dir / "jobs.db"
    migrate(path)
    return JobRepository(path, timeout_sec=30)


def queue_settings(**overrides: Any) -> QueueSettings:
    base = QueueSettings(workers=3, max_attempts=3, retry_delays_sec=(0,), poll_sec=0.02, error_pause_sec=0.05,
                         first_article_number=1)
    return replace(base, **overrides)


class TempDir:
    def __enter__(self) -> Path:
        self._tmp = tempfile.TemporaryDirectory()
        return Path(self._tmp.name)

    def __exit__(self, *exc: Any) -> None:
        self._tmp.cleanup()


def png(color=(200, 40, 40, 255), size=(60, 80)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGBA", size, color).save(buf, format="PNG")
    return buf.getvalue()


class FakeStorage:
    def __init__(self, existing: set[str] | None = None) -> None:
        self.objects: dict[str, bytes] = {key: b"x" for key in existing or set()}
        self.puts: list[str] = []

    def url(self, bucket: str, key: str) -> str:
        return f"https://s3/{bucket}/{key}"

    async def put(self, bucket: str, key: str, data: bytes, content_type: str) -> str:
        self.objects[f"{bucket}/{key}"] = data
        self.puts.append(f"{bucket}/{key}")
        return self.url(bucket, key)

    async def get(self, bucket: str, key: str) -> bytes:
        return self.objects[f"{bucket}/{key}"]

    async def exists(self, bucket: str, key: str) -> bool:
        return f"{bucket}/{key}" in self.objects


class FakeGenerator:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def preview_print(self, theme: str) -> bytes:
        self.calls.append("preview")
        return png()

    async def copy_from_photo(self, photo: bytes, note: str = "") -> bytes:
        self.calls.append("copy")
        return png()

    async def hires_print(self, preview: bytes) -> bytes:
        self.calls.append("hires")
        return png(size=(300, 400))


class FakeGallery:
    def render(self, print_png: bytes, color: str) -> list[tuple[str, bytes]]:
        return [("00_hero", b"jpg"), ("01_main", b"jpg")]


class FakeFetcher:
    async def download(self, url: str) -> bytes:
        return b"photo"

    async def ensure_public(self, url: str) -> None:
        return None


class FakePublisher:
    def __init__(self) -> None:
        self.items: list[dict[str, Any]] = []

    async def publish(self, items: list[dict[str, Any]]) -> dict[str, Any]:
        self.items = items
        offers = [item["offer_id"] for item in items]
        return {"task_id": 1, "offers": offers, "product_ids": list(range(101, 101 + len(offers))), "errors": []}


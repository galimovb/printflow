"""Заготовки тестов ковриков: синтетические каркасы с зелёной поверхностью и заглушки."""
from __future__ import annotations

import io
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw

# Перспективный коврик: TL, TR, BR, BL
QUAD = [(180.0, 520.0), (1020.0, 470.0), (1100.0, 1180.0), (110.0, 1250.0)]


def green_template(path: Path, quad=QUAD, *, mouse: bool = True, size=(1200, 1600)) -> None:
    """Сцена: серый стол, зелёная поверхность со скруглёнными углами, тень, белая «мышь» поверх."""
    img = Image.new("RGB", size, (226, 224, 232))
    big = Image.new("L", (size[0] * 4, size[1] * 4), 0)
    ImageDraw.Draw(big).polygon([(x * 4, y * 4) for x, y in quad], fill=255)
    mask = big.resize(size, Image.Resampling.LANCZOS)
    # скругление углов: срезаем маленькие треугольники у углов
    corner = ImageDraw.Draw(mask)
    for x, y in quad:
        corner.ellipse([x - 9, y - 9, x + 9, y + 9], fill=0)
    yy = np.linspace(0.85, 1.0, size[1])[:, None, None]
    green = Image.fromarray((np.array([10, 230, 20])[None, None, :] * yy * np.ones((size[1], size[0], 1))).astype(np.uint8))
    img.paste(green, (0, 0), mask)
    if mouse:
        ImageDraw.Draw(img).ellipse([820, 760, 960, 960], fill=(245, 245, 245))
    img.save(path)


def plain_template(path: Path, size=(1200, 1600)) -> None:
    Image.new("RGB", size, (230, 228, 236)).save(path)


def templates(dir_: Path) -> Path:
    for scene in ("hero", "office", "glide", "print", "protect", "base"):
        green_template(dir_ / f"{scene}.png")
    plain_template(dir_ / "compact.png")
    return dir_


def print_png(size=(440, 360)) -> bytes:
    img = Image.new("RGB", size, (200, 60, 160))
    ImageDraw.Draw(img).rectangle([0, 0, size[0] // 2, size[1] // 2], fill=(30, 40, 220))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


class FakeStorage:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def url(self, bucket: str, key: str) -> str:
        return f"https://s3/{bucket}/{key}"

    async def put(self, bucket: str, key: str, data: bytes, content_type: str) -> str:
        self.objects[f"{bucket}/{key}"] = data
        return self.url(bucket, key)

    async def get(self, bucket: str, key: str) -> bytes:
        return self.objects[f"{bucket}/{key}"]

    async def exists(self, bucket: str, key: str) -> bool:
        return f"{bucket}/{key}" in self.objects

    async def delete(self, bucket: str, keys: list[str]) -> int:
        for key in keys:
            self.objects.pop(f"{bucket}/{key}", None)
        return len(keys)


class FakeGenerator:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def preview_print(self, theme: str) -> bytes:
        self.calls.append("preview")
        return print_png()

    async def theme_print(self, theme: dict, direction: str, drawn: list[str]) -> bytes:
        self.calls.append("theme")
        self.theme_args = (theme["key"], direction, drawn)
        return print_png()

    async def copy_from_photo(self, photo: bytes, note: str = "") -> bytes:
        self.calls.append("copy")
        return print_png()

    async def name_print(self, png: bytes) -> str:
        self.calls.append("name")
        return "пастельные котики"


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
        return {"task_id": 1, "offers": [i["offer_id"] for i in items], "product_ids": [501], "errors": []}

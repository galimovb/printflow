"""Принт отдельной картинкой на хромакее #90EE90 (шопперы, термонаклейки): фон вырезается тем же
алгоритмом, что у футболок (server.print_raster), принт обрезается по содержимому.

Сюжет принта по тематике придумывает текстовая модель (она видит уже нарисованное в тематике),
картинка рисуется только по сюжету: модель картинок не умеет «не рисуй X» и повторяет список.
Промпты задаёт товар (products/<товар>/domain/prompts.py).
"""
from __future__ import annotations

import io
from abc import abstractmethod
from typing import Any

from PIL import Image

from server.print_raster import PRINT_CHROMAKEY_HEX, strip_print_background_image
from printflow.config import OpenAISettings
from printflow.domain.errors import ShopperError
from printflow.services.printing.generator import ImagePrintGenerator


def finalize_print(png: bytes) -> bytes:
    """Хромакей → прозрачность, обрезка по непрозрачному содержимому."""
    img = strip_print_background_image(Image.open(io.BytesIO(png)))
    bbox = img.getchannel("A").point(lambda a: 255 if a > 8 else 0).getbbox()
    if bbox:
        img = img.crop(bbox)
    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


def on_chromakey(png: bytes) -> bytes:
    """Прозрачный принт на сплошном #90EE90 — вход для перерисовки."""
    art = Image.open(io.BytesIO(png)).convert("RGBA")
    canvas = Image.new("RGBA", art.size, PRINT_CHROMAKEY_HEX)
    canvas.alpha_composite(art)
    out = io.BytesIO()
    canvas.convert("RGB").save(out, format="PNG")
    return out.getvalue()


class ChromakeyPrintGenerator(ImagePrintGenerator):
    """Общий генератор принта на хромакее; товар задаёт промпты."""

    def __init__(self, settings: OpenAISettings, generation: dict[str, Any], name_prompt: str) -> None:
        super().__init__(settings, generation, name_prompt)
        self.area = tuple(generation["print_area_cm"])

    @abstractmethod
    def subject_prompt(self, theme: dict[str, Any], drawn: list[str]) -> str:
        """Текстовой модели: один новый сюжет тематики с учётом уже нарисованного."""

    @abstractmethod
    def subject_image_prompt(self, theme: dict[str, Any], subject: str) -> str:
        """Модели картинок: принт по готовому сюжету."""

    async def pick_subject(self, theme: dict[str, Any], drawn: list[str]) -> str:
        response = await self._call(self.client.chat.completions.create(
            model=self.naming.model,
            messages=[{"role": "user", "content": self.subject_prompt(theme, drawn)}],
            temperature=1.0, max_tokens=80,
        ))
        subject = (response.choices[0].message.content or "").strip().strip("«»\"'.").strip()
        if not subject or "\n" in subject or len(subject) > 160:
            raise ShopperError(f"Не удалось придумать сюжет: {subject[:80]!r}")
        return subject

    async def subject_print(self, theme: dict[str, Any], subject: str) -> bytes:
        return await self._generate(self.subject_image_prompt(theme, subject))

    async def theme_print(self, theme: dict[str, Any], direction: str, drawn: list[str]) -> bytes:
        return await self.subject_print(theme, await self.pick_subject(theme, drawn))

    def theme_prompt(self, theme: dict[str, Any], direction: str, drawn: list[str]) -> str:
        return self.subject_image_prompt(theme, direction)

    def finalize(self, png: bytes) -> bytes:
        return finalize_print(png)

    def prepare_hires(self, preview_png: bytes) -> bytes:
        return on_chromakey(preview_png)

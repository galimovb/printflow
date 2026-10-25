"""Общий клиент генерации и описания принтов; геометрия и промпты задаются товаром."""
from __future__ import annotations

import base64
import io
from abc import ABC, abstractmethod
from typing import Any

import openai
from openai import AsyncOpenAI
from PIL import Image

from printflow.config import OpenAISettings
from printflow.domain.errors import PermanentError, ShopperError


def to_png(image_bytes: bytes, max_side: int) -> bytes:
    image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    image.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


def image_bytes(result: Any) -> bytes:
    data = result.data[0].b64_json if result.data else None
    if not data:
        raise ShopperError("OpenAI вернул ответ без картинки")
    return base64.b64decode(data)


class ImagePrintGenerator(ABC):
    def __init__(self, settings: OpenAISettings, generation: dict[str, Any], name_prompt: str) -> None:
        if not settings.api_key:
            raise ShopperError("Не задан OPENAI_API_KEY")
        self.client = AsyncOpenAI(api_key=settings.api_key, base_url=settings.base_url, timeout=settings.timeout_sec)
        self.model = settings.image_model
        self.naming = settings.naming
        self.name_prompt = name_prompt
        self.reference_max_side = settings.reference_max_side
        self.preview = generation["preview"]
        self.reference = generation.get("reference") or generation["preview"]
        self.hires = generation["hires"]

    @abstractmethod
    def preview_prompt(self, theme: str) -> str: ...

    @abstractmethod
    def theme_prompt(self, theme: dict[str, Any], direction: str, drawn: list[str]) -> str: ...

    @abstractmethod
    def finalize(self, png: bytes) -> bytes: ...

    @abstractmethod
    def reference_prompt(self, note: str) -> str: ...

    @abstractmethod
    def hires_prompt(self) -> str: ...

    def prepare_hires(self, preview_png: bytes) -> bytes:
        """По умолчанию плоский принт готов к перерисовке; товар может подготовить фон."""
        return preview_png

    async def _edit(self, png: bytes, filename: str, prompt: str, options: dict[str, Any]) -> bytes:
        result = await self._call(self.client.images.edit(
            model=self.model, image=(filename, png, "image/png"), prompt=prompt,
            size=options["size"], quality=options["quality"],
        ))
        return self.finalize(image_bytes(result))

    async def copy_from_photo(self, photo: bytes, note: str = "") -> bytes:
        return await self._edit(to_png(photo, self.reference_max_side), "reference.png",
                                self.reference_prompt(note), self.reference)

    async def hires_print(self, preview_png: bytes) -> bytes:
        return await self._edit(self.prepare_hires(preview_png), "print.png", self.hires_prompt(), self.hires)

    async def _generate(self, prompt: str) -> bytes:
        result = await self._call(self.client.images.generate(
            model=self.model, prompt=prompt, size=self.preview["size"], quality=self.preview["quality"],
        ))
        return self.finalize(image_bytes(result))

    async def preview_print(self, theme: str) -> bytes:
        return await self._generate(self.preview_prompt(theme))

    async def theme_print(self, theme: dict[str, Any], direction: str, drawn: list[str]) -> bytes:
        return await self._generate(self.theme_prompt(theme, direction, drawn))

    async def name_print(self, png: bytes) -> str:
        small = Image.open(io.BytesIO(png)).convert("RGB")
        small.thumbnail((self.naming.image_side, self.naming.image_side))
        buf = io.BytesIO()
        small.save(buf, format="JPEG", quality=self.naming.jpeg_quality)
        data_url = "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
        response = await self._call(self.client.chat.completions.create(
            model=self.naming.model,
            messages=[{"role": "user", "content": [
                {"type": "text", "text": self.name_prompt},
                {"type": "image_url", "image_url": {"url": data_url, "detail": self.naming.detail}},
            ]}],
            temperature=self.naming.temperature, max_tokens=self.naming.max_tokens,
        ))
        text = (response.choices[0].message.content or "").strip().strip("«»\"'.").strip()
        if not text or len(text) > self.naming.max_chars or "\n" in text:
            raise ShopperError(f"Не удалось описать рисунок: {text[:80]!r}")
        return text[0].lower() + text[1:]

    @staticmethod
    async def _call(request):
        try:
            return await request
        except openai.BadRequestError as exc:
            raise PermanentError(f"OpenAI отклонил запрос: {exc}") from exc

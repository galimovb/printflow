"""Генерация принта коврика через OpenAI Images: по теме, копия с фото товара, hi-res для печати.

GPT сразу отдаёт плоскую поверхность коврика от края до края (prompts._surface_rule), поэтому ни
хромакея, ни вырезания фона нет: результат только доводится до точных пропорций коврика (size_cm из product.json)
обрезкой по центру.
"""
from __future__ import annotations

import io
from typing import Any

from PIL import Image

from printflow.products.mousepad.domain.prompts import (
    NAME_PROMPT,
    hires_prompt,
    preview_prompt,
    reference_prompt,
    theme_prompt,
)
from printflow.config import OpenAISettings
from printflow.services.printing.generator import ImagePrintGenerator


def fit_surface(png: bytes, size_cm: tuple[float, float]) -> bytes:
    """Ровно пропорции коврика: лишнее по длинной стороне обрезается по центру. PNG без альфы."""
    img = Image.open(io.BytesIO(png)).convert("RGB")
    aspect = size_cm[0] / size_cm[1]
    w, h = img.size
    if w / h > aspect:
        new_w = round(h * aspect)
        img = img.crop(((w - new_w) // 2, 0, (w - new_w) // 2 + new_w, h))
    elif w / h < aspect:
        new_h = round(w / aspect)
        img = img.crop((0, (h - new_h) // 2, w, (h - new_h) // 2 + new_h))
    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


class PadPrintGenerator(ImagePrintGenerator):
    def __init__(self, settings: OpenAISettings, product: dict[str, Any]) -> None:
        super().__init__(settings, product["generation"], NAME_PROMPT)
        self.margin_cm = float(product["generation"]["safe_margin_cm"])
        self.size_cm = tuple(product["size_cm"])

    def preview_prompt(self, theme: str) -> str:
        return preview_prompt(theme, self.size_cm, self.margin_cm)

    def theme_prompt(self, theme: dict[str, Any], direction: str, drawn: list[str]) -> str:
        return theme_prompt(theme, direction, drawn, self.size_cm, self.margin_cm)

    def finalize(self, png: bytes) -> bytes:
        return fit_surface(png, self.size_cm)

    def reference_prompt(self, note: str) -> str:
        return reference_prompt(note, self.size_cm, self.margin_cm)

    def hires_prompt(self) -> str:
        return hires_prompt(self.hires["size"], self.size_cm, self.margin_cm)

"""Общие примитивы холста; товар задаёт шрифт, цвет и межстрочный интервал."""
from __future__ import annotations

from abc import ABC, abstractmethod

from PIL import Image, ImageDraw, ImageFont


class TextCanvas(ABC):
    ink: tuple[int, int, int]
    text_spacing: float

    def __init__(self, img: Image.Image):
        self.img = img.convert("RGBA")
        self.W, self.H = self.img.size
        self.u = self.W / 1000.0
        self.draw = ImageDraw.Draw(self.img, "RGBA")

    @abstractmethod
    def font(self, size: float, weight: str = "regular") -> ImageFont.FreeTypeFont: ...

    def text_w(self, text: str, f) -> float:
        return self.draw.textlength(text, font=f)

    def fit(self, text: str, max_size: float, max_w: float, weight: str = "black"):
        size = max_size
        while size > 12 and any(self.text_w(line, self.font(size, weight)) > max_w for line in text.split("\n")):
            size *= 0.95
        return self.font(size, weight)

    def text(self, xy, text: str, f, fill=None, anchor="la", spacing: float | None = None) -> float:
        fill = self.ink if fill is None else fill
        spacing = self.text_spacing if spacing is None else spacing
        x, y = xy
        for line in text.split("\n"):
            self.draw.text((x, y), line, font=f, fill=fill, anchor=anchor)
            y += f.size * spacing
        return y

    def result(self) -> Image.Image:
        return self.img.convert("RGB")

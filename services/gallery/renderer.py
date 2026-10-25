"""Общая упаковка слайдов: порядок, размер, имена файлов и JPEG."""
from __future__ import annotations

import io
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Sequence

from PIL import Image


class JpegGalleryRenderer(ABC):
    slides: Sequence[str]
    compact_numbering = False

    def __init__(self, product: dict[str, Any], templates_dir: Path) -> None:
        self.product = product
        self.templates_dir = templates_dir

    @abstractmethod
    def compose_print(self, print_png: bytes, variant: str) -> dict[str, Image.Image]:
        """Товар размещает рисунок и оформляет слайды; общий слой только экспортирует."""

    def render(self, print_png: bytes, variant: str) -> list[tuple[str, bytes]]:
        composed = self.compose_print(print_png, variant)
        size = tuple(self.product["gallery"]["size"])
        out = []
        for position, slide in enumerate(self.slides):
            if slide not in composed:
                continue
            buf = io.BytesIO()
            composed[slide].resize(size, Image.Resampling.LANCZOS).save(
                buf, format="JPEG", quality=92, optimize=True,
            )
            number = len(out) if self.compact_numbering else position
            out.append((f"{number:02d}_{slide}", buf.getvalue()))
        return out

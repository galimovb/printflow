"""Галерея коврика: принт во весь коврик → каркасы сцен → готовые фото для Ozon (3:4). GPT здесь не вызывается.

Порядок SLIDES = порядок фото в карточке; первое (hero) — главное. Слайд без каркаса пропускается.
Сцена с "print": false (свёрнутый коврик изнанкой) идёт без принта, только с текстом.
"""
from __future__ import annotations

import io

from PIL import Image

from printflow.services.gallery.renderer import JpegGalleryRenderer

from printflow.products.mousepad.infrastructure.gallery.geometry import analyse_template, place_on_surface, template_path
from printflow.products.mousepad.infrastructure.gallery.slides import SLIDE_LAYOUTS
from printflow.domain.errors import ShopperError

SLIDES = ["hero", "office", "glide", "print", "protect", "base", "compact"]
MAIN = "hero"


class PadGalleryRenderer(JpegGalleryRenderer):
    slides = SLIDES
    compact_numbering = True

    def compose(self, print_img: Image.Image, only: set[str] | None = None) -> dict[str, Image.Image]:
        cfg, texts = self.product["gallery"], self.product["texts"]
        out: dict[str, Image.Image] = {}
        for slide in SLIDES:
            scene = cfg["scenes"].get(slide)
            path = template_path(slide, self.templates_dir)
            if scene is None or (only and slide not in only) or not path.is_file():
                continue
            img = Image.open(path).convert("RGB")
            if scene.get("print", True):
                alpha, quad = analyse_template(path)
                quad = scene.get("quad") or quad
                if quad is None:
                    raise ShopperError(f"Каркас {path.name}: не найдена зелёная поверхность коврика")
                img = place_on_surface(img, print_img, quad, alpha, float(cfg.get("shade", 0.55)))
            out[slide] = SLIDE_LAYOUTS[slide](img, texts[slide], texts.get("footer", ""))
        return out

    def compose_print(self, print_png: bytes, variant: str) -> dict[str, Image.Image]:
        return self.compose(Image.open(io.BytesIO(print_png)).convert("RGB"))

    def render(self, print_png: bytes, variant: str = "main") -> list[tuple[str, bytes]]:
        return super().render(print_png, variant)

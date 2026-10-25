"""Галерея карточки: принт + каркасы → готовые фото для Ozon (3:4). GPT здесь не вызывается.

Принт накладывается на каждый каркас с перспективой и с проступанием складок и теней ткани;
заголовки, плашки, стрелки размеров и иконки рисуются кодом в одном стиле.
Порядок SLIDES = порядок фото в карточке. Слайд без каркаса пропускается.
"""
from __future__ import annotations

import io
from pathlib import Path
from typing import Any

from PIL import Image

from printflow.services.gallery.renderer import JpegGalleryRenderer

from printflow.products.shopper.infrastructure.gallery.geometry import bag_mask, load_print, place_print, scene_geometry, template_path, warm_background
from printflow.products.shopper.infrastructure.gallery.slides import (
    slide_care,
    slide_hero,
    slide_model,
    slide_specs,
    slide_title_bottom,
    slide_title_left,
    slide_title_top,
)

SLIDES = ["hero", "main", "specs", "lifestyle", "closeup", "flatlay", "model", "care"]
SCENE_FOR = {"main": "packshot", "hero": "hero", "specs": "front", "lifestyle": "lifestyle",
             "closeup": "closeup", "flatlay": "flatlay", "model": "model"}


def compose_one(print_img: Image.Image, color: str, product: dict[str, Any], templates_dir: Path,
                only: set[str]) -> dict[str, Image.Image]:
    cfg, texts = product["gallery"], product["texts"]
    print_cm = tuple(product["generation"]["print_area_cm"])
    out: dict[str, Image.Image] = {}
    base_size = None
    for slide, scene in SCENE_FOR.items():
        path = template_path(scene, color, templates_dir)
        if slide not in only or scene not in cfg["scenes"] or not path.is_file():
            continue
        body, zone = scene_geometry(scene, cfg, print_cm, templates_dir)
        if zone is None:
            continue
        tpl = Image.open(path).convert("RGB")
        if scene == "packshot" and (mask := bag_mask(scene, templates_dir)) is not None:
            tpl = warm_background(tpl, mask)
        base_size = base_size or tpl.size
        img = place_print(tpl, print_img, zone, print_cm[0] / print_cm[1], float(cfg["shade"][color]))
        if slide == "hero":
            img = slide_hero(img, texts["hero"])
        elif slide == "specs":
            xs, ys = [p[0] for p in body], [p[1] for p in body]
            img = slide_specs(img, texts["specs"], [min(xs), min(ys), max(xs), max(ys)])
        elif slide == "lifestyle":
            img = slide_title_top(img, texts["lifestyle"])
        elif slide == "closeup":
            img = slide_title_left(img, texts["closeup"])
        elif slide == "flatlay":
            img = slide_title_bottom(img, texts["flatlay"])
        elif slide == "model":
            img = slide_model(img, texts["model"])
        out[slide] = img
    if "care" in only:
        out["care"] = slide_care(base_size or (1536, 2048), texts["care"])
    return out


class GalleryRenderer(JpegGalleryRenderer):
    slides = SLIDES

    def compose_print(self, print_png: bytes, variant: str) -> dict[str, Image.Image]:
        return compose_one(load_print(io.BytesIO(print_png)), variant, self.product,
                           self.templates_dir, set(self.slides))

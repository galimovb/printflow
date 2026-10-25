"""Коврик для мыши (размер — product.json, сейчас 24×20 см, 5 мм): принт во весь коврик, один товар на дизайн."""
from __future__ import annotations

from typing import Any

from printflow.products.base import Product

VARIANT = "main"  # цветов нет — один вариант


class Mousepad(Product):
    name = "mousepad"
    env_prefix = "MOUSEPAD"
    title = "Коврики для мыши"
    main_slide = "hero"
    default_card_name = None  # название собирается из шаблона и описания рисунка (names_designs)
    names_designs = True
    ozon_type_name = "Коврик для мышки"

    def variants(self, spec) -> list[str]:
        return [VARIANT]

    def generator(self, openai):
        from printflow.products.mousepad.infrastructure.print_generator import PadPrintGenerator

        return PadPrintGenerator(openai, self.config)

    def gallery(self):
        from printflow.products.mousepad.infrastructure.gallery.renderer import PadGalleryRenderer

        return PadGalleryRenderer(self.config, self.templates_dir)

    def build_items(self, article, images, product_name, group, design=None) -> list[dict[str, Any]]:
        from printflow.products.mousepad.infrastructure.ozon_listing import build_items

        return build_items(article, images[VARIANT], self.config, product_name, group, design)

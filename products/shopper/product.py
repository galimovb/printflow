"""Шоппер 38×42 см: принт DTF на хромакее, два цвета сумки (молочный, чёрный) — товар на каждый цвет."""
from __future__ import annotations

from typing import Any

from printflow.products.base import Product


class Shopper(Product):
    name = "shopper"
    env_prefix = "SHOPPER"
    title = "Шопперы"
    main_slide = "main"
    default_card_name = "Сумка-шоппер с принтом"
    ozon_type_name = "Сумка"
    picks_subjects = True  # сюжет по тематике придумывает текстовая модель, картинка — только по нему

    def variants(self, spec) -> list[str]:
        return list(spec.colors)

    def generator(self, openai):
        from printflow.products.shopper.infrastructure.print_generator import PrintGenerator

        return PrintGenerator(openai, self.config["generation"])

    def gallery(self):
        from printflow.products.shopper.infrastructure.gallery.renderer import GalleryRenderer

        return GalleryRenderer(self.config, self.templates_dir)

    def build_items(self, article, images, product_name, group, design=None) -> list[dict[str, Any]]:
        from printflow.products.shopper.infrastructure.ozon_listing import build_items

        return build_items(article, images, self.config, product_name, group)

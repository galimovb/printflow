"""Общее для скриптов: выбор товара (--product), его настройки и UTF-8 в консоли Windows."""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass

from printflow.config import AppSettings, ProductSettings, load_app_settings, load_product_settings
from printflow.products import PRODUCTS, get_product
from printflow.products.base import Product


def utf8_console() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except AttributeError:
        pass


def add_product_arg(parser: argparse.ArgumentParser, *, required: bool = True) -> None:
    parser.add_argument("--product", required=required, choices=list(PRODUCTS),
                        help="товар" + ("" if required else " (по умолчанию все)"))


@dataclass(frozen=True)
class Target:
    """Выбранный товар со всеми настройками."""

    product: Product
    settings: ProductSettings
    app: AppSettings

    @property
    def api_prefix(self) -> str:
        return f"/api/v1/{self.product.name}"


def target(name: str) -> Target:
    product = get_product(name)
    return Target(product, load_product_settings(product.env_prefix), load_app_settings())

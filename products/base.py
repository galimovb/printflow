"""Интерфейс товара. Конвейер (очередь, база, Ozon, S3, сертификаты, заказы, API) общий для всех товаров;
товар отвечает только за то, чем он отличается. Раскладка у всех товаров одинаковая:

  products/<товар>/
    product.py                          — Product: фасад товара, связывает части ниже
    config/product.json                 — артикулы, бакеты, генерация, галерея, тексты, карточка Ozon
    config/themes.json                  — тематики принтов (единый формат у всех товаров)
    domain/prompts.py                   — промпты и правила принта (знание предметной области)
    infrastructure/print_generator.py   — генерация принта через OpenAI Images
    infrastructure/ozon_listing.py      — тело импорта Ozon
    infrastructure/gallery/             — фото карточки из принта и каркасов
    assets/                             — каркасы (assets/templates), шрифты, картинки
    scripts/                            — разовые инструменты товара (каркасы, превью)

Новый товар = такая же папка + запись в products/__init__.py.
"""
from __future__ import annotations

import json
import sys
from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING, Any

from printflow.domain.ports import Gallery, PrintGenerator

if TYPE_CHECKING:
    from printflow.config import OpenAISettings
    from printflow.domain.models import CardSpec, MergeGroup


class Product(ABC):
    name: str               # shopper, mousepad — префикс API (/api/v1/<name>) и метка задач в базе
    env_prefix: str         # SHOPPER, MOUSEPAD — ключи окружения <PREFIX>_*
    title: str              # для людей: «Шопперы», «Коврики для мыши»
    main_slide: str         # имя главного фото — без него карточку не выкладываем
    default_card_name: str | None  # название карточки при постановке из XLSX; None — из шаблона товара
    names_designs: bool = False     # True — после принта второй запрос: описание рисунка для названия карточки
    picks_subjects: bool = False    # True — сюжет принта по тематике придумывает текстовая модель (result.subject)
    ozon_type_name: str     # тип товара в дереве категорий Ozon (scripts/ozon_prepare_card)

    @property
    def directory(self) -> Path:
        return Path(sys.modules[type(self).__module__].__file__).resolve().parent  # type: ignore[arg-type]

    @property
    def config_path(self) -> Path:
        return self.directory / "config" / "product.json"

    @property
    def templates_dir(self) -> Path:
        return self.directory / "assets" / "templates"

    @property
    def config(self) -> dict[str, Any]:
        cached = self.__dict__.get("_config")
        if cached is None:
            cached = self.__dict__["_config"] = json.loads(self.config_path.read_text(encoding="utf-8"))
        return cached

    def save_config(self, config: dict[str, Any]) -> None:
        self.config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        self.__dict__["_config"] = config

    @property
    def themes(self) -> dict[str, dict[str, Any]]:
        """Тематики принтов (products/<товар>/config/themes.json) по ключу; у товара без файла — пусто."""
        cached = self.__dict__.get("_themes")
        if cached is None:
            path = self.directory / "config" / "themes.json"
            items = json.loads(path.read_text(encoding="utf-8"))["themes"] if path.is_file() else []
            cached = self.__dict__["_themes"] = {t["key"]: t for t in items}
        return cached

    def theme_direction(self, theme: dict[str, Any], number: int) -> str:
        """Направление принта: список «что уже продаётся» тематики по кругу (по номеру задачи)."""
        directions = [part.strip() for part in theme["known"].split(",") if part.strip()]
        return directions[number % len(directions)]

    @property
    def article_prefix(self) -> str:
        return self.config["article_prefix"]

    @property
    def buckets(self) -> dict[str, str]:
        return self.config["buckets"]

    def validate_publication(self) -> None:
        """Product-specific checks before an external import; previews need no marketplace setup."""

    @abstractmethod
    def variants(self, spec: CardSpec) -> list[str]:
        """Варианты одного дизайна — по ним галерея и товары в карточке."""

    @abstractmethod
    def generator(self, openai: OpenAISettings) -> PrintGenerator: ...

    @abstractmethod
    def gallery(self) -> Gallery: ...

    @abstractmethod
    def build_items(self, article: str, images: dict[str, list[str]], product_name: str | None,
                    group: MergeGroup, design: str | None = None) -> list[dict[str, Any]]:
        """Тело /v3/product/import: images — ссылки на фото по вариантам."""

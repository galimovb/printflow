"""Карточка Ozon из дизайна: по SKU на цвет, все SKU объединены в одну карточку. Чистые функции, без сети."""
from __future__ import annotations

from typing import Any

from printflow.domain.models import MergeGroup
from printflow.domain.errors import ShopperError
from printflow.services.ozon.attributes import (
    ATTR_COLOR,
    ATTR_COLOR_NAME,
    ATTR_DESCRIPTION,
    ATTR_HASHTAGS,
    ATTR_MERGE_CARD,
    ATTR_NAME,
    ATTR_SELLER_CODE,
    SET_BY_CODE,
    color_variant_name,
)

def offer_id(article: str, color: str, product: dict[str, Any]) -> str:
    return f"{article}-{product['colors'][color]['suffix']}"


def build_items(
    article: str,
    images: dict[str, list[str]],
    product: dict[str, Any],
    product_name: str | None = None,
    group: MergeGroup | None = None,
) -> list[dict[str, Any]]:
    """Тело /v3/product/import. Объединение — одинаковое «Название модели» (артикул дизайна) у всех цветов.

    product_name — готовое название карточки вместо ozon.name_template (например, для копий из XLSX).
    group — с какими дизайнами объединять: одинаковое «Название модели» (BAG-0001) у всей группы, а
    «Название цвета» — номер дизайна в группе + цвет («3 молочный», «3 черный»): варианты разных принтов
    не совпадают, а оба цвета одного принта стоят рядом. Без группы — дизайн отдельной карточкой.
    """
    group = group or MergeGroup(key=article, position=None)
    ozon = product["ozon"]
    base = [a for a in ozon["attributes"] if int(a["id"]) not in SET_BY_CODE]
    package = ozon["package"]
    items = []
    for color, urls in images.items():
        if not urls:
            raise ShopperError(f"{article} {color}: нет фото")
        spec = product["colors"][color]
        oid = offer_id(article, color, product)
        name = product_name or ozon["name_template"].format(color_name=spec["name"])
        own = {
            ATTR_NAME: [{"value": name}],
            ATTR_DESCRIPTION: [{"value": ozon["description_template"].format(color_name=spec["name"])}],
            ATTR_MERGE_CARD: [{"value": group.key}],
            ATTR_SELLER_CODE: [{"value": oid}],
            ATTR_COLOR: spec["ozon_value"],
            ATTR_COLOR_NAME: [{"value": color_variant_name(spec["name"], group)}],
            ATTR_HASHTAGS: [{"value": " ".join(ozon["hashtags"])}],
        }
        item = {
            "offer_id": oid,
            "name": name[:500],
            "description_category_id": ozon["category_id"],
            "type_id": ozon["type_id"],
            "currency_code": "RUB",
            "price": str(ozon["price"]),
            "vat": str(ozon["vat"]),
            "width": package["width_mm"],
            "height": package["height_mm"],
            "depth": package["depth_mm"],
            "dimension_unit": "mm",
            "weight": package["weight_g"],
            "weight_unit": "g",
            "images": urls[:15],
            "attributes": base + [{"complex_id": 0, "id": aid, "values": values} for aid, values in own.items()],
        }
        if ozon.get("old_price"):
            item["old_price"] = str(ozon["old_price"])
        items.append(item)
    return items

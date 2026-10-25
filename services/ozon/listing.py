"""Тело /v3/product/import для товара «один дизайн — один товар» (коврики, термонаклейки):
название из шаблона и описания рисунка, rich-контент, объединение дизайнов в одну карточку
(«Название модели» — id группы, «Название цвета» — номер дизайна в группе). Тексты и атрибуты —
config/product.json товара (раздел ozon).
"""
from __future__ import annotations

import json
from typing import Any

from printflow.domain.errors import ShopperError
from printflow.domain.models import MergeGroup
from printflow.services.ozon.attributes import (
    ATTR_COLOR,
    ATTR_COLOR_NAME,
    ATTR_DESCRIPTION,
    ATTR_HASHTAGS,
    ATTR_MERGE_CARD,
    ATTR_NAME,
    ATTR_RICH_CONTENT,
    ATTR_SELLER_CODE,
    SET_BY_CODE,
    color_variant_name,
)


def card_name(ozon: dict[str, Any], design: str | None) -> str:
    """«Коврик для мыши с принтом пастельные котики 24x20 см, 5 мм»; без описания рисунка — базовое название."""
    if design:
        return ozon["name_template"].format(design=design)
    return ozon["name_fallback"]


def _rich_text(content: str, size: str, align: str = "left") -> dict[str, Any]:
    return {"align": align, "color": "color1", "size": size, "items": [{"type": "text", "content": content}]}


def rich_content(rich: dict[str, Any], image: str, design: str | None) -> str:
    """Rich-контент JSON: шахматка (главное фото + заголовок + преимущества) и блок про коллекцию."""
    title = rich["title_template"].format(design=design) if design else rich["title_fallback"]
    features: list[dict[str, Any]] = [{"type": "br"}]
    for feature in rich["features"]:
        features += [{"type": "text", "content": feature["title"]}, {"type": "br"},
                     {"type": "text", "content": feature["text"]}, {"type": "br"}, {"type": "br"}]
    picture = {"src": image, "srcMobile": image, "alt": title, "position": "to_the_edge",
               "positionMobile": "to_the_edge"}
    content = [
        {"widgetName": "raShowcase", "type": "chess", "blocks": [{
            "img": picture, "imgLink": "", "reverse": False,
            "title": _rich_text(title.upper(), "size4"),
            "text": {**_rich_text("", "size2"), "items": features},
        }]},
        {"widgetName": "raTextBlock", "theme": "primary", "gapSize": "m", "padding": "type2",
         "title": {k: v for k, v in _rich_text(rich["collection_title"], "size5").items() if k != "align"},
         "text": _rich_text(rich["collection_text"], "size2")},
    ]
    return json.dumps({"content": content, "version": 0.3}, ensure_ascii=False)


def build_items(
    article: str,
    images: list[str],
    product: dict[str, Any],
    product_name: str | None = None,
    group: MergeGroup | None = None,
    design: str | None = None,
) -> list[dict[str, Any]]:
    if not images:
        raise ShopperError(f"{article}: нет фото")
    group = group or MergeGroup(key=article, position=None)
    ozon = product["ozon"]
    color = next(iter(product["colors"].values()))
    name = product_name or card_name(ozon, design)
    own = {
        ATTR_NAME: [{"value": name}],
        ATTR_DESCRIPTION: [{"value": ozon["description_template"]}],
        ATTR_MERGE_CARD: [{"value": group.key}],
        ATTR_SELLER_CODE: [{"value": article}],
        ATTR_COLOR: color["ozon_value"],
        ATTR_COLOR_NAME: [{"value": color_variant_name(color["name"], group)}],
        ATTR_HASHTAGS: [{"value": " ".join(ozon["hashtags"])}],
        ATTR_RICH_CONTENT: [{"value": rich_content(ozon["rich"], images[0], design)}],
    }
    base = [a for a in ozon["attributes"] if int(a["id"]) not in SET_BY_CODE]
    package = ozon["package"]
    item = {
        "offer_id": article,
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
        "images": images[:15],
        "attributes": base + [{"complex_id": 0, "id": aid, "values": values} for aid, values in own.items()],
    }
    if ozon.get("old_price"):
        item["old_price"] = str(ozon["old_price"])
    return [item]

"""Общие атрибуты Ozon для любого товара: их значения задаёт код (остальные — product.json → ozon.attributes)."""
from __future__ import annotations

from printflow.domain.models import MergeGroup

ATTR_NAME = 4180
ATTR_DESCRIPTION = 4191
ATTR_MERGE_CARD = 9048  # «Название модели (для объединения в одну карточку)»
ATTR_SELLER_CODE = 9024
ATTR_COLOR = 10096
ATTR_COLOR_NAME = 10097
ATTR_HASHTAGS = 23171
ATTR_TYPE = 8229  # = type_id, в импорт не передаётся
ATTR_RICH_CONTENT = 11254  # «Rich-контент JSON»
SET_BY_CODE = {ATTR_NAME, ATTR_DESCRIPTION, ATTR_MERGE_CARD, ATTR_SELLER_CODE, ATTR_COLOR, ATTR_COLOR_NAME, ATTR_HASHTAGS,
               ATTR_RICH_CONTENT}


def color_variant_name(color_name: str, group: MergeGroup) -> str:
    """«Название цвета»: «молочный» у отдельного дизайна; «3 молочный» в группе (номер с нулями по ширине
    размера группы — при 10+ местах «03 молочный», чтобы сортировка шла по порядку)."""
    if group.position is None:
        return color_name
    return f"{group.position:0{len(str(group.size))}d} {color_name}"

"""Доменные модели: задача очереди и её содержимое. Без инфраструктуры (SQL, HTTP, S3)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Callable


# Сохранить промежуточный результат задачи: (этап, результат). Воркер передаёт его в сценарий.
SaveProgress = Callable[[str, dict[str, Any]], None]


class JobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class JobKind(StrEnum):
    WB_DISCOVER = "wb_discover"
    WB_CARD = "wb_card"
    WB_PUBLISH = "wb_publish"
    CARD = "card"    # новый дизайн: принт → галерея → карточка Ozon
    HIRES = "hires"  # перерисовка принта для печати, когда пришёл заказ
    CERTIFICATE = "certificate"  # привязка выложенных товаров к сертификату качества


@dataclass
class Job:
    """Задача очереди. payload — что сделать (неизменно), result — что уже сделано (растёт по шагам)."""

    id: str
    number: int
    status: JobStatus
    payload: dict[str, Any]
    result: dict[str, Any] = field(default_factory=dict)
    product: str = ""                  # товар: shopper, mousepad (см. products/), migrations/0005
    external_id: str | None = None
    stage: str | None = None
    error: str | None = None
    attempts: int = 0
    created_at: str = ""
    updated_at: str = ""
    started_at: str | None = None
    finished_at: str | None = None
    available_at: str | None = None
    group_id: int | None = None        # группа объединения (карточка Ozon), см. migrations/0003
    group_position: int | None = None  # место дизайна в группе: 1…N
    design_number: int | None = None   # сквозной номер дизайна → артикул BAG-001001, см. migrations/0004

    @property
    def kind(self) -> JobKind:
        return JobKind(self.payload.get("kind", JobKind.CARD))


@dataclass(frozen=True)
class CardSpec:
    """Что нужно для карточки: тема или фото товара (принт копируется 1:1), цвета, название."""

    assortment: str | None = None  # thermo: single / set
    product_config: dict[str, Any] | None = None  # immutable job snapshot
    theme: str = ""
    theme_key: str | None = None  # тематика из products/<товар>/config/themes.json: идею придумывает GPT
    theme_step: int | None = None  # порядковый номер принта в тематике → направление (по кругу)
    reference_url: str | None = None
    product_name: str | None = None
    design_name: str | None = None  # готовое описание рисунка для названия (идеи) — без запроса name_print
    colors: tuple[str, ...] = ("white", "black")
    upload_to_ozon: bool = True
    dry_run: bool = False

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> CardSpec:
        return cls(
            assortment=payload.get("assortment"),
            product_config=payload.get("product_config"),
            theme=payload.get("theme") or "",
            theme_key=payload.get("theme_key"),
            theme_step=payload.get("theme_step"),
            reference_url=payload.get("reference_url"),
            product_name=payload.get("product_name"),
            design_name=payload.get("design_name"),
            colors=tuple(payload.get("colors") or ("white", "black")),
            upload_to_ozon=payload.get("upload_to_ozon", True),
            dry_run=payload.get("dry_run", False),
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "kind": JobKind.CARD.value,
            **({"assortment": self.assortment} if self.assortment else {}),
            **({"product_config": self.product_config} if self.product_config else {}),
            "theme": self.theme,
            "theme_key": self.theme_key,
            "theme_step": self.theme_step,
            "reference_url": self.reference_url,
            "product_name": self.product_name,
            "design_name": self.design_name,
            "colors": list(self.colors),
            "upload_to_ozon": self.upload_to_ozon,
            "dry_run": self.dry_run,
        }


# ───────────────────────── артикулы ─────────────────────────
# Артикул дизайна — сквозной номер: BAG-001001, товары BAG-001001-W / -B.
# «Название модели» (одна карточка Ozon на группу) — id группы: BAG-000001.
# Исторические форматы, которые уже выложены и понимаются при разборе:
#   BAG-000467  — номер задачи (до групп);  BAG-0001-03 / модель BAG-0001 — первая группа.

def format_article(prefix: str, number: int) -> str:
    """Номер → артикул дизайна: 1001 → BAG-001001 (так же выглядел старый артикул по номеру задачи)."""
    return f"{prefix}{number:06d}"


def group_article(prefix: str, group_id: int, position: int) -> str:
    """Исторический формат первой группы: (1, 3) → BAG-0001-03."""
    return f"{prefix}{group_id:04d}-{position:02d}"


def group_model_name(prefix: str, group_id: int) -> str:
    """«Название модели» в Ozon — id группы, одинаковое у всех товаров группы: 2 → BAG-000002."""
    return f"{prefix}{group_id:06d}"


@dataclass(frozen=True)
class MergeGroup:
    """Куда попадает дизайн: key — «Название модели» (одна карточка Ozon), position — место в группе
    (входит в «Название цвета», чтобы варианты разных принтов не совпали), size — мест в группе."""

    key: str
    position: int | None = None
    size: int = 1


def design_article(prefix: str, job: Job) -> str:
    if job.design_number:
        return format_article(prefix, job.design_number)
    if job.group_id and job.group_position:  # первая группа, выложена до сквозных номеров
        return group_article(prefix, job.group_id, job.group_position)
    return format_article(prefix, job.number)  # задачи до групп


def design_merge_group(prefix: str, job: Job, size: int) -> MergeGroup:
    if job.group_id and job.group_position:
        key = (group_model_name(prefix, job.group_id) if job.design_number
               else f"{prefix}{job.group_id:04d}")  # первая группа уже выложена с моделью BAG-0001
        return MergeGroup(key, job.group_position, size)
    return MergeGroup(design_article(prefix, job))  # без группы — дизайн своей карточкой


def _design_regex(prefix: str) -> str:
    return rf"{re.escape(prefix)}(?:\d{{4,}}-\d{{2}}|\d{{6}})"


def article_pattern(prefix: str) -> re.Pattern[str]:
    """Артикул дизайна в любом формате: BAG-0001-03 или BAG-000467."""
    return re.compile(rf"^{_design_regex(prefix)}$")


def article_from_offer(offer_id: str, prefix: str) -> str | None:
    """Артикул товара → артикул дизайна: BAG-0001-03-W → BAG-0001-03, BAG-000007-B → BAG-000007;
    чужие (TEE- и т.п.) → None."""
    match = re.match(rf"^({_design_regex(prefix)})(-[A-Z])?$", offer_id.strip().upper())
    return match.group(1) if match else None


def hires_external_id(article: str) -> str:
    """Одна задача hi-res на артикул: повторные заказы принт заново не рисуют."""
    return f"hires:{article}"


def certificate_external_id(article: str) -> str:
    """Одна задача привязки сертификата на артикул дизайна."""
    return f"certificate:{article}"

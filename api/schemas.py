"""VIEW: схемы запросов и ответов API. Контроллеры принимают и отдают только их."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, HttpUrl, field_validator, model_validator

from printflow.domain.models import CardSpec, Job


class CardJobRequest(BaseModel):
    theme: str = Field(default="", max_length=1000, description="Тема принта (можно пусто, если есть reference_url)")
    theme_key: str | None = Field(default=None, max_length=64,
                                  description="Тематика из products/<товар>/config/themes.json — идею придумывает GPT")
    theme_step: int | None = Field(default=None, ge=0,
                                   description="Номер принта в тематике: направления идут по кругу; "
                                               "без него — по номеру задачи")
    reference_url: HttpUrl | None = Field(default=None, description="Фото товара: принт копируется с него 1:1")
    product_name: str | None = Field(default=None, max_length=200,
                                     description="Готовое название карточки вместо шаблона из product.json")
    design_name: str | None = Field(default=None, max_length=80,
                                    description="Описание рисунка для названия («пастельные котики»); "
                                                "без него товар с naming описывает принт отдельным запросом")
    colors: list[Literal["white", "black"]] = Field(default_factory=lambda: ["white", "black"], min_length=1)
    upload_to_ozon: bool = True
    dry_run: bool = Field(default=False, description="Собрать SKU, но не отправлять в Ozon")
    external_id: str | None = Field(default=None, max_length=200, description="Ключ идемпотентности")

    @field_validator("colors")
    @classmethod
    def _unique(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(value))

    @model_validator(mode="after")
    def _theme_or_reference(self) -> CardJobRequest:
        if len(self.theme.strip()) < 2 and self.reference_url is None and not self.theme_key:
            raise ValueError("Нужна тема (theme), тематика (theme_key) или фото товара (reference_url)")
        return self

    def to_spec(self) -> CardSpec:
        return CardSpec(
            theme=self.theme,
            theme_key=self.theme_key,
            theme_step=self.theme_step,
            reference_url=str(self.reference_url) if self.reference_url else None,
            product_name=self.product_name,
            design_name=self.design_name,
            colors=tuple(self.colors),
            upload_to_ozon=self.upload_to_ozon,
            dry_run=self.dry_run,
        )


class CardJobBatchRequest(BaseModel):
    jobs: list[CardJobRequest] = Field(min_length=1, max_length=500)


class JobView(BaseModel):
    id: str
    number: int
    external_id: str | None
    status: str
    stage: str | None
    attempts: int
    error: str | None
    payload: dict[str, Any]
    result: dict[str, Any]
    created_at: str
    updated_at: str
    started_at: str | None
    finished_at: str | None
    available_at: str | None
    group_id: int | None
    group_position: int | None
    design_number: int | None

    @classmethod
    def of(cls, job: Job) -> JobView:
        return cls(
            id=job.id, number=job.number, external_id=job.external_id, status=job.status.value,
            stage=job.stage, attempts=job.attempts, error=job.error, payload=job.payload, result=job.result,
            created_at=job.created_at, updated_at=job.updated_at, started_at=job.started_at,
            finished_at=job.finished_at, available_at=job.available_at,
            group_id=job.group_id, group_position=job.group_position, design_number=job.design_number,
        )


class JobListView(BaseModel):
    jobs: list[JobView]


class BatchJobView(BaseModel):
    id: str
    external_id: str | None
    created: bool


class JobBatchView(BaseModel):
    created: int
    existing: int
    jobs: list[BatchJobView]


class HealthView(BaseModel):
    status: str
    queue: dict[str, int]

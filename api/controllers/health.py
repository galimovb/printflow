"""CONTROLLER: проверка живости (без авторизации) и размер очереди — всего приложения и каждого товара."""
from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter

from printflow.api.schemas import HealthView

if TYPE_CHECKING:
    from printflow.container import AppContainer, ProductContainer


def router(pc: ProductContainer) -> APIRouter:
    r = APIRouter(tags=[pc.name])

    @r.get("/health", response_model=HealthView)
    def health() -> HealthView:
        return HealthView(status="ok", queue=pc.job_repository.count_by_status(pc.name))

    return r


def app_router(app: AppContainer) -> APIRouter:
    r = APIRouter(tags=["health"])

    @r.get("/api/v1/health", response_model=HealthView)
    def health() -> HealthView:
        return HealthView(status="ok", queue=app.job_repository.count_by_status())

    return r

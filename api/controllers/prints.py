"""CONTROLLER: принты для печати (hi-res при заказе) — по артикулу товара."""
from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException, Response, status

from printflow.api.dependencies import token_checker
from printflow.api.schemas import JobView
from printflow.domain.models import article_pattern

if TYPE_CHECKING:
    from printflow.container import ProductContainer


def router(pc: ProductContainer) -> APIRouter:
    r = APIRouter(prefix="/prints", tags=[pc.name], dependencies=[Depends(token_checker(pc))])

    @r.post("/{article}/hires", status_code=status.HTTP_202_ACCEPTED, response_model=JobView)
    def create_hires(article: str, response: Response) -> JobView:
        """202 — перерисовка поставлена; для этого артикула уже есть задача → 200 и она же."""
        prefix = pc.product.article_prefix
        article = article.upper()
        if not article_pattern(prefix).match(article):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Артикул вида {prefix}000001")
        job, created = pc.jobs.enqueue_hires(article)
        if not created:
            response.status_code = status.HTTP_200_OK
        return JobView.of(job)

    return r

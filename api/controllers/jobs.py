"""CONTROLLER: задачи карточек товара. Принимает запрос, вызывает JobService товара, отдаёт JobView."""
from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from printflow.api.dependencies import token_checker
from printflow.api.schemas import BatchJobView, CardJobBatchRequest, CardJobRequest, JobBatchView, JobListView, JobView
from printflow.domain.errors import InvalidJobState, JobNotFound
from printflow.domain.models import JobStatus

if TYPE_CHECKING:
    from printflow.container import ProductContainer


def router(pc: ProductContainer) -> APIRouter:
    r = APIRouter(prefix="/jobs", tags=[pc.name], dependencies=[Depends(token_checker(pc))])

    @r.post("", status_code=status.HTTP_202_ACCEPTED, response_model=JobView)
    def create_card(body: CardJobRequest, response: Response) -> JobView:
        """202 — задача в очереди; повтор с тем же external_id → 200 и та же задача."""
        try:
            job, created = pc.jobs.enqueue_card(body.to_spec(), external_id=body.external_id)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if not created:
            response.status_code = status.HTTP_200_OK
        return JobView.of(job)

    @r.post("/batch", response_model=JobBatchView)
    def create_cards(body: CardJobBatchRequest) -> JobBatchView:
        """Пачка карточек (до 500) одной транзакцией; уже существующие external_id — created=false."""
        try:
            result = pc.jobs.enqueue_cards([(item.to_spec(), item.external_id) for item in body.jobs])
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        created = sum(1 for _, is_new in result if is_new)
        return JobBatchView(
            created=created, existing=len(result) - created,
            jobs=[BatchJobView(id=job.id, external_id=job.external_id, created=is_new) for job, is_new in result],
        )

    @r.get("", response_model=JobListView)
    def list_jobs(
        status_filter: JobStatus | None = Query(default=None, alias="status"),
        limit: int = Query(default=50, ge=1, le=500),
    ) -> JobListView:
        return JobListView(jobs=[JobView.of(job) for job in pc.jobs.list(status=status_filter, limit=limit)])

    @r.get("/{job_id}", response_model=JobView)
    def get_job(job_id: str) -> JobView:
        try:
            return JobView.of(pc.jobs.get(job_id))
        except JobNotFound as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc

    @r.post("/{job_id}/retry", response_model=JobView)
    def retry_job(job_id: str) -> JobView:
        """Перезапуск упавшей задачи с места падения."""
        try:
            return JobView.of(pc.jobs.retry(job_id))
        except JobNotFound as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
        except InvalidJobState as exc:
            raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc

    return r

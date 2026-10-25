import hmac
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field, HttpUrl

from printflow.api.schemas import JobView
from printflow.config import read_env
from printflow.domain.errors import PermanentError
from printflow.domain.models import JobKind, JobStatus
from printflow.wb_studio.config import default_colors
from printflow.wb_studio.domain.models import PRODUCT
from printflow.wb_studio.paths import CONFIG_DIR


class Campaign(BaseModel):
    algorithm: Literal["standard", "source_redraw"] = "standard"
    design_limit: int | None = Field(default=None, ge=1, le=20)
    themes: list[str] = Field(min_length=1, max_length=200)
    limit: int = Field(default=10, ge=10, le=20)
    colors: list[Literal["white", "black"]] = Field(
        default_factory=lambda: default_colors(read_env()), min_length=1, max_length=2
    )


class Source(BaseModel):
    url: HttpUrl
    image: HttpUrl
    title: str = ""
    images: list[HttpUrl] = Field(default_factory=list, max_length=20)


class SourceBatch(BaseModel):
    algorithm: Literal["standard", "source_redraw"] = "standard"
    theme: str = Field(min_length=2, max_length=500)
    sources: list[Source] = Field(min_length=1, max_length=20)
    colors: list[Literal["white", "black"]] = Field(
        default_factory=lambda: default_colors(read_env()), min_length=1, max_length=2
    )


class UrlBatch(BaseModel):
    urls: list[HttpUrl] = Field(min_length=1, max_length=20)
    theme: str = "Футболки по ссылкам"
    algorithm: Literal["standard", "source_redraw"] = "source_redraw"
    colors: list[Literal["white", "black"]] = Field(
        default_factory=lambda: default_colors(read_env()), min_length=1, max_length=2
    )


def router(container):
    r = APIRouter()

    def auth(authorization: str | None = Header(default=None)):
        env = read_env()
        expected = env.get("PRINTFLOW_WB_API_TOKEN", "")
        token = (authorization or "").removeprefix("Bearer ").strip()
        if not expected or not hmac.compare_digest(token, expected):
            raise HTTPException(401, "Invalid studio API token")

    @r.get("/studio/wb", response_class=HTMLResponse)
    def page():
        return Path(__file__).with_name("studio.html").read_text(encoding="utf-8")

    secure = APIRouter(prefix="/api/v1/wb-studio", dependencies=[Depends(auth)], tags=["WB Studio"])

    @secure.get("/themes")
    def themes():
        return {"themes": (CONFIG_DIR / "themes.txt").read_text(encoding="utf-8").splitlines()}

    @secure.post("/sources")
    def import_sources(body: SourceBatch):
        import hashlib
        import json

        from printflow.wb_studio.infrastructure.wb.search import normalize_cards

        raw = [
            {"url": str(x.url), "image": str(x.image), "title": x.title, "images": [str(url) for url in x.images]}
            for x in body.sources
        ]
        sources = normalize_cards(raw, len(raw))
        if len(sources) != len(raw):
            raise HTTPException(422, "Нужны уникальные ссылки карточек WB и HTTPS фотографии")
        config = container.wb_studio.configuration(body.colors, body.algorithm)
        payload = {"kind": JobKind.WB_DISCOVER.value, "theme": body.theme, "limit": len(sources), "config": config}
        digest = hashlib.sha256(
            json.dumps([payload, sources], sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()[:24]
        job, created = container.job_repository.create(payload, product=PRODUCT, external_id="wb-sources:" + digest)
        if created:
            container.job_repository.save_progress(
                job.id,
                stage="sources_imported",
                result={"sources": sources, "query": body.theme, "sort": "imported", "origin": "manual_source_list"},
            )
        return {"id": job.id, "created": created}

    @secure.post("/urls")
    def import_urls(body: UrlBatch):
        try:
            job, created = container.wb_studio.urls(
                [str(url) for url in body.urls], body.theme, body.colors, body.algorithm
            )
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        return {"id": job.id, "created": created}

    @secure.post("/campaigns")
    def campaigns(body: Campaign):
        if not any(x.strip() for x in body.themes):
            raise HTTPException(422, "Укажите тему")
        result = container.wb_studio.campaign(
            body.themes, body.limit, list(dict.fromkeys(body.colors)), body.design_limit, body.algorithm
        )
        return {"jobs": [{"id": job.id, "created": created} for job, created in result]}

    @secure.get("/jobs")
    def jobs():
        return {"jobs": [JobView.of(x) for x in container.job_repository.list(product=PRODUCT, limit=200)]}

    @secure.get("/jobs/{job_id}")
    def job(job_id: str):
        value = container.job_repository.get(job_id)
        if not value or value.product != PRODUCT:
            raise HTTPException(404, "Job not found")
        return JobView.of(value)

    @secure.post("/cards/{card_id}/publish")
    def publish(card_id: str):
        try:
            value, created = container.wb_studio.enqueue_publication(card_id)
        except (ValueError, RuntimeError, PermanentError) as exc:
            raise HTTPException(422, str(exc)) from exc
        return {"id": value.id, "created": created}

    @secure.post("/jobs/{job_id}/retry")
    def retry(job_id: str):
        value = container.job_repository.get(job_id)
        if not value or value.product != PRODUCT:
            raise HTTPException(404, "Job not found")
        if value.status != JobStatus.FAILED:
            raise HTTPException(409, "Only failed jobs can be retried")
        return JobView.of(container.job_repository.reset_failed(job_id))

    r.include_router(secure)
    return r

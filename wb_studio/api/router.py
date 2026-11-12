import hmac
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, Response
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field, HttpUrl

from printflow.api.schemas import JobView
from printflow.config import read_env
from printflow.domain.errors import PermanentError
from printflow.domain.models import JobStatus
from printflow.wb_studio.config import default_colors
from printflow.wb_studio.domain.models import PRODUCT
from printflow.wb_studio.paths import CONFIG_DIR

from . import session


class Campaign(BaseModel):
    algorithm: Literal["standard", "source_redraw", "model_reference", "template_mockup"] = "standard"
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
    # True when the sender already collected the full gallery: the queue then never opens a browser.
    gallery_complete: bool = False


class SourceBatch(BaseModel):
    algorithm: Literal["standard", "source_redraw", "model_reference", "template_mockup"] = "standard"
    theme: str = Field(min_length=2, max_length=500)
    sources: list[Source] = Field(min_length=1, max_length=60)
    # Cards to generate; the remaining sources are a reserve that replaces rejected prints.
    design_limit: int | None = Field(default=None, ge=1, le=20)
    colors: list[Literal["white", "black"]] = Field(
        default_factory=lambda: default_colors(read_env()), min_length=1, max_length=2
    )


class UrlBatch(BaseModel):
    urls: list[HttpUrl] = Field(min_length=1, max_length=20)
    theme: str = "Футболки по ссылкам"
    algorithm: Literal["standard", "source_redraw", "model_reference", "template_mockup"] = "source_redraw"
    colors: list[Literal["white", "black"]] = Field(
        default_factory=lambda: default_colors(read_env()), min_length=1, max_length=2
    )


class ThemeRequest(BaseModel):
    themes: list[str] = Field(min_length=1, max_length=100)
    count: int = Field(default=20, ge=1, le=20)
    search: int = Field(default=50, ge=1, le=60)
    algorithm: Literal["source_redraw", "model_reference", "template_mockup"] = "template_mockup"
    colors: list[Literal["white", "black"]] = Field(
        default_factory=lambda: default_colors(read_env()), min_length=1, max_length=2
    )


class ParserSignal(BaseModel):
    current: str | None = Field(default=None, max_length=300)


class ParserFinish(BaseModel):
    status: Literal["queued", "empty", "failed"]
    campaign_id: str | None = None
    message: str = Field(default="", max_length=500)


PARSER_ONLINE_SEC = 120  # the host parser signals every 20-60 s while it waits or works


class SignIn(BaseModel):
    token: str = Field(min_length=1, max_length=500)


class RetryJobs(BaseModel):
    ids: list[str] = Field(min_length=1, max_length=500)


class Decision(BaseModel):
    approved: bool
    reason: str = Field(default="", max_length=300)


def router(container):
    r = APIRouter()

    def token_ok(token: str) -> bool:
        expected = read_env().get("PRINTFLOW_WB_API_TOKEN", "")
        return bool(expected) and hmac.compare_digest(token, expected)

    def auth(
        authorization: str | None = Header(default=None),
        cookie: str | None = Cookie(default=None, alias=session.COOKIE),
    ):
        """Scripts send the bearer API token; the studio pages send the session cookie from a sign-in."""
        if token_ok((authorization or "").removeprefix("Bearer ").strip()):
            return
        if cookie and session.valid(cookie, session.signing_key(read_env())):
            return
        raise HTTPException(401, "Нужно войти: токен студии")

    @r.post("/api/v1/wb-studio/session")
    def sign_in(body: SignIn, response: Response):
        if not token_ok(body.token.strip()):
            raise HTTPException(401, "Неверный токен")
        value = session.issue(session.signing_key(read_env()))
        # Strict: only the studio pages send it; another site can neither read it nor post with it.
        response.set_cookie(session.COOKIE, value, max_age=session.TTL_SEC, httponly=True, samesite="strict", path="/")
        return {"ok": True, "days": session.TTL_SEC // 86400}

    @r.post("/api/v1/wb-studio/session/end")
    def sign_out(response: Response):
        response.delete_cookie(session.COOKIE, path="/")
        return {"ok": True}

    @r.get("/studio/wb", response_class=HTMLResponse)
    def page():
        """The start page is the theme launcher; the old all-in-one page is gone (queue and review have tabs)."""
        return Path(__file__).with_name("themes.html").read_text(encoding="utf-8")

    @r.get("/studio/wb/studio.css")
    def common_css():
        return Response(Path(__file__).with_name("studio.css").read_text(encoding="utf-8"), media_type="text/css")

    @r.get("/studio/wb/review", response_class=HTMLResponse)
    def review_page():
        return Path(__file__).with_name("review.html").read_text(encoding="utf-8")

    secure = APIRouter(prefix="/api/v1/wb-studio", dependencies=[Depends(auth)], tags=["WB Studio"])

    @secure.get("/themes")
    def themes():
        return {"themes": (CONFIG_DIR / "themes.txt").read_text(encoding="utf-8").splitlines()}

    @secure.post("/sources")
    def import_sources(body: SourceBatch):
        from printflow.wb_studio.infrastructure.wb.search import normalize_cards

        raw = [
            {
                "url": str(x.url),
                "image": str(x.image),
                "title": x.title,
                "images": [str(url) for url in x.images],
                "gallery_complete": x.gallery_complete and bool(x.images),
            }
            for x in body.sources
        ]
        sources = normalize_cards(raw, len(raw))
        if len(sources) != len(raw):
            raise HTTPException(422, "Нужны уникальные ссылки карточек WB и HTTPS фотографии")
        job, created = container.wb_studio.sources(body.theme, sources, body.colors, body.algorithm, body.design_limit)
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

    # --- themes requested from the interface; the host parser takes them --------------------------------

    @secure.get("/theme-requests")
    def theme_requests():
        repo = container.job_repository
        state = repo.wb_parser_state()
        online = False
        if state:
            seen = datetime.fromisoformat(state["seen_at"])
            online = (datetime.now(UTC) - seen).total_seconds() < PARSER_ONLINE_SEC
        return {"requests": repo.wb_theme_requests(), "parser": {**(state or {}), "online": online}}

    @secure.get("/queue")
    def queue(view: Literal["active", "failed", "done", "all"] = "active", limit: int = 300):
        return container.job_repository.wb_queue(view, max(1, min(limit, 1000)))

    @secure.get("/jobs/{job_id}/detail")
    def job_detail(job_id: str):
        """Mini report of one queue job: what it was made from, what came out, what it cost, where it went."""
        from printflow.wb_studio.infrastructure import usage

        repo = container.job_repository
        job = repo.get(job_id)
        if not job or job.product != PRODUCT:
            raise HTTPException(404, "Job not found")
        payload, result = job.payload, job.result or {}
        kind = payload.get("kind")
        out = {
            "id": job.id, "kind": kind, "number": job.design_number, "theme": payload.get("theme"),
            "status": job.status.value, "stage": job.stage, "attempts": job.attempts, "error": job.error,
            "created_at": job.created_at, "started_at": job.started_at, "finished_at": job.finished_at,
            "updated_at": job.updated_at,
        }  # fmt: skip
        if kind == "wb_publish":
            cards = []
            for card_id in payload.get("card_ids", []):
                card = repo.get(card_id)
                codes = (card.result or {}).get("vendor_codes", {}) if card else {}
                links = {color: (result.get("cards") or {}).get(code, {}).get("nmID") for color, code in codes.items()}
                cards.append({"id": card_id, "number": card.design_number if card else None,
                              "title": ((card.result or {}).get("text") or {}).get("title") if card else None,
                              "nm": links})  # fmt: skip
            out.update(cards=cards, merge_group=payload.get("merge_group"))
            return out
        if kind == "wb_discover":
            out.update(found=len(result.get("sources") or payload.get("sources") or []),
                       design_limit=payload.get("design_limit"), algorithm=(payload.get("config") or {}).get("algorithm"))  # fmt: skip
            return out
        source = payload.get("source") or {}
        analysis = result.get("analysis") or {}
        gallery = source.get("images") or ([source["image"]] if source.get("image") else [])
        roles = {p.get("index"): p for p in analysis.get("photos") or [] if isinstance(p, dict)}
        filt = analysis.get("filter") or {}
        lines = usage.lines_for(job.id)
        by_purpose: dict[str, dict] = {}
        for line in lines:
            item = by_purpose.setdefault(line.get("purpose") or "?", {"purpose": line.get("purpose") or "?", "n": 0, "cost": 0.0})
            item["n"] += 1
            item["cost"] += line.get("cost_usd") or 0
        publications = []
        for pub in repo.wb_card_publications(job.id):
            nm = {color: (pub["result"].get("cards") or {}).get(code, {}).get("nmID")
                  for color, code in (result.get("vendor_codes") or {}).items()}  # fmt: skip
            publications.append({"id": pub["id"], "status": pub["status"], "error": pub["error"], "nm": nm})
        out.update(
            algorithm=(payload.get("config") or {}).get("algorithm"),
            source={"url": source.get("url"), "title": source.get("title"), "photos": gallery,
                    "print_source": analysis.get("print_source"),
                    "roles": {str(i): {k: roles[i].get(k) for k in ("role", "whole_print", "same_print", "adult")}
                              for i in roles}},  # fmt: skip
            analysis={"audience": analysis.get("audience"), "shirt_color": analysis.get("shirt_color"),
                      "recolor": analysis.get("recolor"), "reasons": filt.get("reasons") or [],
                      "theme_reason": filt.get("theme_reason"), "print_reason": filt.get("print_reason"),
                      "series": result.get("template_series"), "frames": result.get("template_frames"),
                      "frames_reason": result.get("frame_plan_reason")},  # fmt: skip
            prints=result.get("print_variants") or {},
            checks=result.get("print_checks") or {},
            print_attempts=result.get("print_attempts") or {},
            images=result.get("images") or {},
            text=result.get("text") or analysis.get("text") or {},
            vendor_codes=result.get("vendor_codes") or {},
            approval=result.get("approval"),
            publications=publications,
            usage={"total": round(sum(i["cost"] for i in by_purpose.values()), 4), "requests": len(lines),
                   "by_purpose": sorted(by_purpose.values(), key=lambda i: -i["cost"]),
                   "logged_since": "2026-11-06"},  # fmt: skip
        )
        return out

    @r.get("/studio/wb/studio-common.js")
    def common_js():
        return Response(Path(__file__).with_name("studio-common.js").read_text(encoding="utf-8"),
                        media_type="text/javascript")  # fmt: skip

    @r.get("/studio/wb/queue", response_class=HTMLResponse)
    def queue_page():
        return Path(__file__).with_name("queue.html").read_text(encoding="utf-8")

    @secure.get("/theme-catalog")
    def theme_catalog():
        """The saved theme list with what each theme already produced; themes run outside the list come last."""
        stats = container.job_repository.wb_theme_stats()
        saved = (CONFIG_DIR / "themes.txt").read_text(encoding="utf-8-sig").splitlines()
        listed = [t for t in dict.fromkeys(x.strip() for x in saved) if t]
        empty = {"runs": 0, "last_at": None, "done": 0, "failed": 0, "errors": 0, "working": 0, "on_wb": 0, "request": None}
        themes = [{"theme": t, "listed": True, **stats.get(t.lower(), empty)} for t in listed]
        known = {t.lower() for t in listed}
        themes += [{"theme": t, "listed": False, **s} for t, s in sorted(stats.items()) if t not in known]
        return {"themes": themes}

    @secure.post("/theme-requests")
    def add_theme_requests(body: ThemeRequest):
        themes = list(dict.fromkeys(t.strip() for t in body.themes if t.strip()))
        if not themes:
            raise HTTPException(422, "Укажите хотя бы одну тему")
        added = container.job_repository.wb_theme_add(
            themes, count=body.count, search=max(body.search, body.count), algorithm=body.algorithm,
            colors=list(dict.fromkeys(body.colors)),
        )  # fmt: skip
        return {"added": len(added), "skipped": len(themes) - len(added)}

    @secure.post("/theme-requests/{request_id}/cancel")
    def cancel_theme_request(request_id: str):
        if not container.job_repository.wb_theme_cancel(request_id):
            raise HTTPException(409, "Тему уже взял парсер или её нет")
        return {"id": request_id}

    @secure.post("/parser/claim")
    def parser_claim(body: ParserSignal):
        repo = container.job_repository
        request = repo.wb_theme_claim()
        repo.wb_parser_seen(request["theme"] if request else body.current)
        return {"request": request}

    @secure.post("/parser/heartbeat")
    def parser_heartbeat(body: ParserSignal):
        container.job_repository.wb_parser_seen(body.current)
        return {"ok": True}

    @secure.post("/theme-requests/{request_id}/finish")
    def finish_theme_request(request_id: str, body: ParserFinish):
        if not container.job_repository.wb_theme_finish(
            request_id, body.status, campaign_id=body.campaign_id, message=body.message
        ):
            raise HTTPException(409, "Заявка не в разборе")
        return {"id": request_id}

    @r.get("/studio/wb/themes", response_class=HTMLResponse)
    def themes_page():
        return Path(__file__).with_name("themes.html").read_text(encoding="utf-8")

    @secure.get("/review")
    def review():
        """Finished cards waiting for a decision or for publication, with what the reviewer has to see."""
        cards = []
        for row in container.wb_studio.review_queue():
            source = row["source"]
            gallery = source.get("images") or [source.get("image", "")]
            index = row["print_source"]
            cards.append(
                {
                    "id": row["id"],
                    "number": row["design_number"],
                    "theme": row["theme"] or "",
                    "title": row["title"] or "",
                    "source_url": source.get("url", ""),
                    "seller_photo": gallery[index] if isinstance(index, int) and index < len(gallery) else gallery[0],
                    "prints": row["prints"],
                    "images": row["images"],
                    "recolor": row["recolor"],
                    "approval": row["approval"],
                    "finished_at": row["finished_at"],
                }
            )
        return {"cards": cards, "auto_publish": read_env().get("PRINTFLOW_WB_AUTO_PUBLISH", "") in ("1", "true", "yes")}

    @secure.post("/cards/{card_id}/decision")
    def decision(card_id: str, body: Decision):
        try:
            container.wb_studio.decide(card_id, body.approved, body.reason.strip())
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        return {"id": card_id, "approved": body.approved}

    @secure.post("/publish-approved")
    def publish_approved():
        try:
            created = container.wb_studio.publish_approved()
        except (ValueError, RuntimeError, PermanentError) as exc:
            raise HTTPException(422, str(exc)) from exc
        return {"publications": [{"id": job.id, "created": was} for job, was in created]}

    @secure.post("/jobs/retry")
    def retry_many(body: RetryJobs):
        """Manual restart of failed jobs picked in the queue: each continues from its saved steps, attempts reset."""
        repo = container.job_repository
        retried, skipped = [], []
        for job_id in dict.fromkeys(body.ids):
            value = repo.get(job_id)
            if value and value.product == PRODUCT and value.status == JobStatus.FAILED and repo.reset_failed(job_id):
                retried.append(job_id)
            else:
                skipped.append(job_id)
        return {"retried": retried, "skipped": skipped}

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

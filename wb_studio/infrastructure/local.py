"""Standalone generation through the same persistent QueueWorker as the application."""

import asyncio
import copy
import hashlib
import html
import io
import json
import zipfile
from pathlib import Path

from PIL import Image

from printflow.domain.models import JobKind, JobStatus
from printflow.migrations.runner import migrate
from printflow.repositories.jobs import JobRepository
from printflow.wb_studio.application.studio import Studio
from printflow.wb_studio.domain.models import PRODUCT


class LocalStorage:
    def __init__(self, root):
        self.root = Path(root).resolve()

    def path(self, bucket, key):
        path = (self.root / bucket / key).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError("Invalid storage path")
        return path

    def url(self, bucket, key):
        return self.path(bucket, key).as_uri()

    async def exists(self, bucket, key):
        return self.path(bucket, key).is_file()

    async def get(self, bucket, key):
        return self.path(bucket, key).read_bytes()

    async def put(self, bucket, key, data, content_type):
        path = self.path(bucket, key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path.as_uri()


async def generate(body, output, env, *, generator=None, search=None, fetch=None):
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    migrate(output / "jobs.db")
    repo = JobRepository(output / "jobs.db", timeout_sec=30)
    storage = LocalStorage(output / "files")
    options = {"generator": generator, "fetch": fetch}
    if search:
        options["search"] = search
    studio = Studio(repo, storage, env, **options)
    if any(
        j.kind == JobKind.WB_PUBLISH and j.status in (JobStatus.PENDING, JobStatus.RUNNING)
        for j in repo.list(product=PRODUCT, limit=500)
    ):
        raise ValueError("Локальный запуск не выполняет публикации: выберите отдельную папку генерации")
    if "sources" in body:
        from printflow.wb_studio.infrastructure.wb.search import normalize_cards

        sources = normalize_cards(body["sources"], len(body["sources"]))
        if not sources:
            raise ValueError("No valid WB sources")
        config = studio.configuration(body.get("colors"), body.get("algorithm", "standard"))
        key = hashlib.sha256(json.dumps([body, config], sort_keys=True).encode()).hexdigest()[:24]
        job, created = repo.create(
            {"kind": JobKind.WB_DISCOVER.value, "theme": body["theme"], "limit": len(sources), "config": config},
            product=PRODUCT,
            external_id="local-sources:" + key,
        )
        if created:
            repo.save_progress(job.id, stage="sources_imported", result={"sources": sources, "sort": "imported"})
        campaigns = [(repo.get(job.id), created)]
    elif "urls" in body:
        campaigns = [
            studio.urls(
                body["urls"],
                body.get("theme", "Футболки по ссылкам"),
                body.get("colors"),
                body.get("algorithm", "source_redraw"),
            )
        ]
    else:
        campaigns = studio.campaign(
            body["themes"],
            body["limit"],
            body.get("colors"),
            body.get("design_limit"),
            body.get("algorithm", "standard"),
        )
    # A repeated local command is an explicit retry of transient failures only.
    for job in repo.list(product=PRODUCT, limit=500):
        if job.status == JobStatus.FAILED and job.result.get("failure", {}).get("retryable"):
            repo.reset_failed(job.id)
    from printflow.wb_studio.application.worker import worker

    from .errors import failure

    queue = worker(studio, env, publication=False)
    for kind, handler in list(queue.handlers.items()):

        async def wrapped(job, save, handler=handler):
            try:
                return await handler(job, save)
            except Exception as exc:
                current = repo.get(job.id)
                progress = copy.deepcopy(current.result)
                stage = current.stage
                if stage == "started":
                    stage = progress.get("failure", {}).get("stage", stage)
                progress["failure"] = failure(exc, stage)
                save(stage or "failed", progress)
                raise

        queue.handlers[kind] = wrapped
    stop = asyncio.Event()
    task = asyncio.create_task(queue.run(stop))
    try:
        last = None
        while True:
            if task.done():
                await task
            roots = [repo.get(j.id) for j, _ in campaigns]
            children = [repo.get(c["id"]) for j in roots for c in j.result.get("cards", [])]
            snapshot = [(j.id, j.status.value, j.stage) for j in roots + children]
            if snapshot != last:
                for job in roots + children:
                    if last is None or (job.id, job.status.value, job.stage) not in last:
                        print(job.id[:8], job.status.value, job.stage, flush=True)
                last = snapshot
            if all(j.status in (JobStatus.DONE, JobStatus.FAILED) for j in roots + children):
                break
            await asyncio.sleep(0.05)
    finally:
        stop.set()
        await task
    completed = []
    errors = []
    groups = {}
    roots = [repo.get(j.id) for j, _ in campaigns]
    jobs = roots + [repo.get(c["id"]) for j in roots for c in j.result.get("cards", [])]
    for job in jobs:
        if job.kind == JobKind.WB_CARD:
            key = job.payload.get("merge_group", job.id)
            group = groups.setdefault(
                key,
                {
                    "key": key,
                    "designs": job.payload.get("merge_group_size", 1),
                    "limit": job.payload.get("merge_designs", 1),
                    "cards": [],
                },
            )
            group["cards"].append(
                {"id": job.id, "status": job.status.value, "vendor_codes": job.result.get("vendor_codes", {})}
            )
        if job.status == JobStatus.FAILED:
            errors.append(
                {
                    "id": job.id,
                    **job.result.get("failure", {"message": job.error, "retryable": True, "stage": job.stage}),
                }
            )
        elif job.kind == JobKind.WB_CARD and job.status == JobStatus.DONE:
            completed.append({"id": job.id, "result": job.result})
    blocks = []
    exported = []
    for entry in completed:
        job = repo.get(entry["id"])
        result = entry["result"]
        name = f"{job.design_number:06}-{job.id[:8]}"
        entry["folder"] = name
        folder = output / "cards" / name
        folder.mkdir(parents=True, exist_ok=True)
        buckets = studio.storage_buckets(result)
        (folder / "print.png").write_bytes(await storage.get(buckets["prints"], f"printflow-wb/{job.id}/print.png"))
        (folder / "listing.json").write_text(json.dumps(result["text"], ensure_ascii=False, indent=2), encoding="utf-8")
        blocks.append("<h2>" + html.escape(result["text"]["title"]) + "</h2>")
        for color, photos in result["images"].items():
            dest = folder / color
            dest.mkdir(exist_ok=True)
            if color in result.get("print_variants", {}):
                key = (
                    f"{result['vendor_codes'][color]}.png"
                    if color in result.get("article_prints", {})
                    else f"printflow-wb/{job.id}/prints/{color}.png"
                )
                (dest / "print.png").write_bytes(await storage.get(buckets["prints"], key))
            sheet = Image.new("RGB", (1800, 1600), "white")
            for index in range(len(photos)):
                raw = await storage.get(buckets["mockups"], f"printflow-wb/{job.id}/{color}/{index+1:02}.jpg")
                (dest / f"{index+1:02}.jpg").write_bytes(raw)
                with Image.open(io.BytesIO(raw)) as im:
                    im = im.convert("RGB")
                    im.thumbnail((600, 800))
                    sheet.paste(im, ((index % 3) * 600, (index // 3) * 800))
            sheet.save(dest / "all.jpg", quality=95)
            blocks.append(f'<h3>{html.escape(color)}</h3><img src="cards/{name}/{color}/all.jpg">')
        exported.extend(f for f in folder.rglob("*") if f.is_file())
    for error in errors:
        blocks.append("<p>Ошибка " + html.escape(error["id"][:8]) + ": " + html.escape(error["message"]) + "</p>")
    for name, data in [("results", completed), ("errors", errors), ("groups", list(groups.values()))]:
        (output / f"{name}.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    (output / "gallery.html").write_text(
        '<meta charset="utf-8"><title>PrintFlow — локальная очередь</title><style>body{font:18px system-ui;background:#eee;margin:24px}img{width:100%;max-width:1800px}</style>'
        + "".join(blocks),
        encoding="utf-8",
    )
    with zipfile.ZipFile(output / "ready-cards.zip", "w", zipfile.ZIP_DEFLATED) as archive:
        for file in exported:
            archive.write(file, file.relative_to(output))
        for name in ("gallery.html", "groups.json"):
            archive.write(output / name, name)
    print(f'Завершено: {len(completed)} готово, {len(errors)} ошибок. {output/"gallery.html"}', flush=True)
    return completed

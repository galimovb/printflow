"""Card generation: run the algorithm of a card job and leave a finished draft for publication."""

import asyncio
import copy
from collections.abc import Awaitable

from printflow.domain.errors import PermanentError
from printflow.wb_studio.domain.models import PRODUCT, vendor_codes
from printflow.wb_studio.infrastructure.generation import Generator
from printflow.wb_studio.infrastructure.model_library import ModelLibrary
from printflow.wb_studio.infrastructure.rendering.info_slides import check_information
from printflow.wb_studio.infrastructure.template_library import TemplateLibrary
from printflow.wb_studio.infrastructure.wb.downloads import CdnDownloader

from .card_files import CardFiles
from .model_reference import ModelReferencePipeline
from .redraw import RedrawPipeline
from .standard import StandardPipeline
from .template_mockup import TemplatePipeline

PIPELINES = {
    "standard": StandardPipeline,
    "source_redraw": RedrawPipeline,
    "model_reference": ModelReferencePipeline,
    "template_mockup": TemplatePipeline,
}


class CardService:
    """Shared resources of every pipeline: storage buckets, photo download, the image request limit."""

    def __init__(self, repository, storage, env, *, generator=None, fetch=None, models=None, templates=None):
        self.repo = repository
        self.storage = storage
        self.env = env
        self.generator_override = generator
        self.fetch_override = fetch
        self.models = models or ModelLibrary.from_env(env)
        self.templates = templates or TemplateLibrary.from_env(storage, env)
        self.photo_slots = asyncio.Semaphore(max(1, int(env.get("PRINTFLOW_WB_IMAGE_CONCURRENCY", "120"))))
        self.photo_timeout = float(env.get("PRINTFLOW_WB_PHOTO_TIMEOUT_SEC", "240"))
        self.downloader = CdnDownloader(int(env.get("PRINTFLOW_WB_DOWNLOADS", "32")), self.observed_images)
        # Existing buckets; all studio files live under printflow-wb/.
        self.legacy_bucket = env.get("PRINTFLOW_WB_BUCKET", "tee-prints")
        self.prints_bucket = env.get("PRINTFLOW_WB_PRINTS_BUCKET", "tee-prints")
        self.mockups_bucket = env.get("PRINTFLOW_WB_MOCKUPS_BUCKET", "tee-mockups")
        self.temporary_bucket = env.get("PRINTFLOW_WB_TEMPORARY_BUCKET", "tee-temporary-storage")
        # Local review runs keep seller photos next to the results for side-by-side comparison.
        self.keep_temporary = env.get("PRINTFLOW_WB_KEEP_TEMPORARY", "").lower() in ("1", "true", "yes")

    def storage_buckets(self, result: dict) -> dict:
        """Frozen per job, so interrupted jobs from the single-bucket era keep their files."""
        if "storage_buckets" not in result:
            legacy = any(result.get(key) for key in ("source", "print", "images"))
            result["storage_buckets"] = (
                {"prints": self.legacy_bucket, "mockups": self.legacy_bucket}
                if legacy
                else {"prints": self.prints_bucket, "mockups": self.mockups_bucket}
            )
        # Jobs created before the temporary bucket get it on their next run.
        result["storage_buckets"].setdefault("temporary", self.temporary_bucket)
        return result["storage_buckets"]

    async def card(self, job, save):
        result = copy.deepcopy(job.result)
        if result.get("review_required"):
            return result  # finished: nothing to redo, and its working files are already gone
        result.pop("failure", None)
        config = job.payload["config"]
        generator = self.generator_override or Generator(self.env, config)
        if self.generator_override is None:
            check_information(config)
        files = CardFiles(self.storage, self.storage_buckets(result), job.id, result, save)
        try:
            await PIPELINES[config["algorithm"]](self, job, generator, files).run()
        except PermanentError:
            # A rejected card will never resume; transient failures keep files for the retry.
            await self.remove_temporary(files)
            raise
        await self.remove_temporary(files)
        save("ready_for_review", self.finished(job, result))
        return result

    @staticmethod
    def finished(job, result: dict) -> dict:
        config = {**job.payload["config"], "colors": result.get("colors", job.payload["config"]["colors"])}
        result.update(
            vendor_codes=vendor_codes(job.design_number, config["colors"]),
            source_url=job.payload["source"].get("url", ""),
            algorithm=config["algorithm"],
            config=config,
            review_required=True,
        )
        if job.payload.get("merge_group"):
            result["merge_group"] = {
                "key": job.payload["merge_group"],
                "designs": job.payload["merge_group_size"],
                "position": job.payload["merge_position"],
                "limit": job.payload["merge_designs"],
            }
        return result

    async def remove_temporary(self, files: CardFiles) -> None:
        if self.keep_temporary or not files.result.get("temporary_files"):
            return
        await files.remove_temporary()
        # Keep the current stage: a rejected card must still read as rejected.
        files.persist(files.last_stage, files.result)

    async def save_article_prints(self, job, result: dict, files: CardFiles) -> dict:
        """Printable PNGs named by WB vendor code; job files stay resumable."""
        codes = vendor_codes(job.design_number, result.get("colors", job.payload["config"]["colors"]))
        result["vendor_codes"] = codes
        canonical = result.setdefault("article_prints", {})
        for color, code in codes.items():
            if color in canonical:
                continue
            name = f"prints/{color}.png" if color in result.get("print_variants", {}) else "print.png"
            canonical[color] = await files.put_shared("prints", f"{code}.png", await files.get("prints", name))
            files.save(f"article_print_ready:{color}", result)
        result.setdefault("print_variants", {}).update(canonical)
        files.save("article_prints_ready", result)
        return canonical

    async def fetch_photo(self, url: str) -> bytes:
        if self.fetch_override:
            return await self.fetch_override(url)
        return await self.downloader.fetch(url)

    async def with_photo_timeout(self, request: Awaitable[bytes]) -> bytes:
        return await asyncio.wait_for(request, self.photo_timeout)

    def observed_images(self):
        for card in self.repo.all(PRODUCT):
            yield from card.payload.get("source", {}).get("images", [])

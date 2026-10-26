"""Persistent WB studio jobs on the PrintFlow queue and S3.

discover -> one WB_CARD job per product -> manual review -> WB_PUBLISH per merge group.
"""

import asyncio
import copy
import hashlib
import json
from collections.abc import Awaitable
from datetime import UTC, datetime

from printflow.domain.errors import PermanentError
from printflow.domain.models import JobKind, JobStatus
from printflow.wb_studio.config import build_config, default_colors, load_config, merge_designs
from printflow.wb_studio.domain.models import ALGORITHMS, PRODUCT, group_number, vendor_codes
from printflow.wb_studio.infrastructure.generation import Generator
from printflow.wb_studio.infrastructure.rendering.info_slides import check_information
from printflow.wb_studio.infrastructure.wb import search
from printflow.wb_studio.infrastructure.wb.downloads import CdnDownloader
from printflow.wb_studio.infrastructure.wb.publisher import Publisher, validate, validate_group
from printflow.wb_studio.infrastructure.wb.search import NO_PHOTOS, discover, parsing_batch, validate_product_urls

from .card_files import CardFiles
from .redraw import RedrawPipeline
from .standard import StandardPipeline

PIPELINES = {"standard": StandardPipeline, "source_redraw": RedrawPipeline}
# Publication re-reads these from config.json, so price and characteristics stay current.
LIVE_PUBLISH_KEYS = (
    "price",
    "dimensions",
    "characteristics",
    "subject_id",
    "sizes",
    "brand",
    "color_attribute_id",
    "kiz_marked",
)

__all__ = ["Studio"]


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:24]


class Studio:
    def __init__(self, repository, storage, env, *, search=discover, generator=None, publisher=None, fetch=None):
        self.repo = repository
        self.storage = storage
        self.env = env
        self.search = search
        self.generator_override = generator
        self.fetch_override = fetch
        self.publisher = publisher or Publisher(env.get("PRINTFLOW_WB_API_KEY") or env.get("WB_API_KEY", ""))
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

    # --- configuration and job creation -----------------------------------------

    def configuration(self, colors=None, algorithm="standard") -> dict:
        if algorithm not in ALGORITHMS:
            raise ValueError("Unknown WB generation algorithm")
        return build_config(colors or default_colors(self.env), algorithm, merge_designs(self.env))

    def campaign(self, themes, limit, colors=None, design_limit=None, algorithm="standard"):
        config = self.configuration(colors, algorithm)
        jobs = []
        for theme in dict.fromkeys(x.strip() for x in themes if x.strip()):
            key = digest([theme, limit, colors, config, design_limit])
            payload = {
                "kind": JobKind.WB_DISCOVER.value,
                "theme": theme,
                "theme_key": "wb-search",
                "limit": limit,
                "config": config,
                "design_limit": design_limit,
            }
            jobs.append(self.repo.create(payload, product=PRODUCT, external_id="wb-search:" + key))
        return jobs

    def urls(self, urls, theme="Футболки по ссылкам", colors=None, algorithm="source_redraw"):
        urls = validate_product_urls(urls)
        payload = {
            "kind": JobKind.WB_DISCOVER.value,
            "theme": theme,
            "theme_key": "wb-search",
            "limit": len(urls),
            "source_urls": urls,
            "config": self.configuration(colors, algorithm),
        }
        return self.repo.create(payload, product=PRODUCT, external_id="wb-urls:" + digest(payload))

    # --- discovery --------------------------------------------------------------

    @parsing_batch
    async def discovery(self, job, save):
        result = copy.deepcopy(job.result)
        if not result.get("sources"):
            if job.payload.get("source_urls"):
                sources = await search.resolve_product_urls(job.payload["source_urls"])
            else:
                sources = await self.search(job.payload["theme"], job.payload["limit"])
            if not sources:
                raise PermanentError("WB returned no source products")
            result.update(
                sources=sources,
                query=job.payload["theme"],
                sort="popular",
                captured_at=datetime.now(UTC).isoformat(),
                requested=job.payload["limit"],
                actual=len(sources),
                partial=len(sources) < job.payload["limit"],
            )
            save("discovered", result)
        config = job.payload["config"]
        wanted = job.payload.get("design_limit")
        if config["algorithm"] == "source_redraw":
            selected = await self.complete_galleries(result, wanted or len(result["sources"]), save)
        else:
            selected = result["sources"][:wanted]
        result["cards"] = self.enqueue_cards(job, selected)
        save("cards_queued", result)
        return result

    async def complete_galleries(self, result, wanted, save):
        """source_redraw needs the full gallery; search results carry only the first photo."""
        galleries = result.setdefault("source_galleries", {})
        skipped = result.setdefault("skipped_sources", {})
        selected = []
        for source in result["sources"]:
            url = source["url"]
            if url in skipped:
                continue
            if not source.get("gallery_complete") and url not in galleries:
                try:
                    resolved = await search.resolve_product_urls([url])
                except PermanentError as exc:
                    # Only a product without photos is skipped; access limits stop the batch.
                    if not str(exc).startswith(NO_PHOTOS):
                        raise
                    skipped[url] = str(exc)
                    save("source_skipped", result)
                    continue
                if not resolved or not resolved[0].get("images"):
                    skipped[url] = "Недостаточно исходных фото"
                    save("source_skipped", result)
                    continue
                galleries[url] = resolved[0]["images"][:20]
                save("source_gallery_parsed", result)
            if url in galleries:
                source["images"] = galleries[url]
                source["gallery_complete"] = True
            source["image"] = source["images"][0]
            selected.append(source)
            if len(selected) >= wanted:
                break
        if not selected:
            raise PermanentError("Не найдено карточек с исходными фото")
        return selected

    def enqueue_cards(self, job, selected):
        config = job.payload["config"]
        size = config.get("merge_designs") or merge_designs(self.env)
        items = []
        for index, source in enumerate(selected):
            group = f"PFWG-{job.id}-{index // size + 1}"
            payload = {
                "kind": JobKind.WB_CARD.value,
                "theme": job.payload["theme"],
                "source": source,
                "config": config,
                "campaign_id": job.id,
                "merge_group": group,
                "merge_designs": size,
                "merge_group_size": min(size, len(selected) - (index // size) * size),
                "merge_position": index % size + 1,
            }
            items.append((payload, "wb-card:" + digest([source["sku"], config, group])))
        created = self.repo.create_many(items, product=PRODUCT, numbered=True)
        return [
            {"id": card.id, "sku": source["sku"], "created": was_created, "merge_group": card.payload["merge_group"]}
            for source, (card, was_created) in zip(selected, created, strict=False)
        ]

    # --- card generation --------------------------------------------------------

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
        result.update(
            vendor_codes=vendor_codes(job.design_number, config["colors"], group_number(job.payload.get("merge_group"))),
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
        save("ready_for_review", result)
        return result

    async def remove_temporary(self, files: CardFiles) -> None:
        if self.keep_temporary or not files.result.get("temporary_files"):
            return
        await files.remove_temporary()
        # Keep the current stage: a rejected card must still read as rejected.
        files.persist(files.last_stage, files.result)

    async def save_article_prints(self, job, result: dict, files: CardFiles) -> dict:
        """Printable PNGs named by WB vendor code; job files stay resumable."""
        codes = vendor_codes(job.design_number, job.payload["config"]["colors"], group_number(job.payload.get("merge_group")))
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
        for card in self.repo.list(product=PRODUCT, limit=1000):
            yield from card.payload.get("source", {}).get("images", [])

    # --- publication ------------------------------------------------------------

    def enqueue_publication(self, card_id):
        card = self.repo.get(card_id)
        if not card or card.product != PRODUCT or card.kind != JobKind.WB_CARD:
            raise ValueError("Studio card not found")
        if card.status != JobStatus.DONE or not card.result.get("review_required"):
            raise ValueError("Card is not ready for review")
        group = card.payload.get("merge_group")
        members = self.repo.wb_group_cards(group) if group else [card]
        if group and len(members) != card.payload["merge_group_size"]:
            raise ValueError("Состав группы ещё не сформирован")
        if any(m.status != JobStatus.DONE or not m.result.get("review_required") for m in members):
            raise ValueError("Сначала дождитесь готовности и проверьте все принты группы")
        # Keep the exact immutable member list, including the final partial group.
        current = load_config()
        drafts = []
        for member in members:
            draft = copy.deepcopy(member.result)
            for key in LIVE_PUBLISH_KEYS:
                if key in current:
                    draft["config"][key] = copy.deepcopy(current[key])
            validate(draft["config"])
            drafts.append(draft)
        validate_group(drafts)
        payload = {
            "kind": JobKind.WB_PUBLISH.value,
            "card_id": card_id,
            "card_ids": [m.id for m in members],
            "merge_group": group,
            "drafts": drafts,
        }
        external_id = "wb-publish-group:" + group if group else "wb-publish:" + card_id
        return self.repo.create(payload, product=PRODUCT, external_id=external_id)

    async def publish(self, job, save):
        drafts = job.payload.get("drafts")
        if drafts:
            state = await self.publisher.publish_group(drafts, job.result, lambda value: save("wb_publish", value))
        else:
            drafts = [job.payload["draft"]]
            state = await self.publisher.publish(drafts[0], job.result, lambda value: save("wb_publish", value))
        links = []
        grouped = bool(job.payload.get("drafts"))
        for draft in drafts:
            for color, vendor in draft["vendor_codes"].items():
                card = state.get("cards", {}).get(vendor if grouped else color, {})
                if card.get("nmID"):
                    links.append(
                        {
                            "source_url": draft.get("source_url", ""),
                            "color": color,
                            "vendor_code": vendor,
                            "url": f"https://www.wildberries.ru/catalog/{card['nmID']}/detail.aspx",
                        }
                    )
        state["source_links"] = links
        save("wb_links_ready", state)
        return state

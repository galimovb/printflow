"""Persistent WB studio jobs on the PrintFlow queue and S3.

discover -> one WB_CARD job per product -> manual review -> WB_PUBLISH per merge group.
"""

import asyncio
import collections
import contextlib
import copy
import hashlib
import json
import logging
from collections.abc import Awaitable
from datetime import UTC, datetime

from printflow.domain.errors import PermanentError
from printflow.domain.models import JobKind, JobStatus
from printflow.wb_studio.config import build_config, default_colors, group_cards, load_config, merge_designs
from printflow.wb_studio.domain.models import ALGORITHMS, PRODUCT, vendor_codes
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
    "gender_attribute_id",
    "kiz_marked",
)

__all__ = ["Studio"]

logger = logging.getLogger(__name__)


def transient(job) -> bool:
    """Failed on an error worth retrying (balance, network), not on a rejection of the print itself."""
    return job.status == JobStatus.FAILED and not (job.error or "").startswith("PermanentError")


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
        config = build_config(colors or default_colors(self.env), algorithm, merge_designs(self.env))
        # Frozen per job: only cards created while auto-publication is on are ever published automatically.
        config["auto_publish"] = self.env.get("PRINTFLOW_WB_AUTO_PUBLISH", "").lower() in ("1", "true", "yes")
        return config

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
        if not result.get("sources") and job.payload.get("sources"):
            result.update(sources=job.payload["sources"], query=job.payload["theme"], sort="imported")
            save("sources_imported", result)
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

    def enqueue_cards(self, job, selected, first_group=1):
        config = job.payload["config"]
        size = config.get("merge_designs") or merge_designs(self.env)
        items = []
        for index, source in enumerate(selected):
            group = f"PFWG-{job.id}-{first_group + index // size}"
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
        config = {**config, "colors": result.get("colors", config["colors"])}
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

    # --- publication ------------------------------------------------------------

    def enqueue_publication(self, card_id):
        """Manual publication after review: the whole merge group must be finished and reviewed."""
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
        return self.create_publication(card_id, group, members)

    def create_publication(self, card_id, group, members):
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

    def publish_finished_groups(self) -> list:
        """Auto-publication: a merge group goes to WB once every member has finished.

        Only cards created with auto_publish in their config qualify; older cards always wait for review.
        Failed members are left out, so one rejected print never blocks the other designs.
        """
        jobs = self.repo.all(PRODUCT)
        published = {j.payload.get("merge_group") for j in jobs if j.kind == JobKind.WB_PUBLISH}
        themed = {j.id for j in jobs if j.kind == JobKind.WB_DISCOVER and j.payload.get("design_limit")}
        groups = collections.defaultdict(list)
        for job in jobs:
            group = job.payload.get("merge_group")
            auto = job.payload.get("config", {}).get("auto_publish") is True
            if job.payload.get("campaign_id") in themed:
                continue  # regrouped by publish_finished_themes
            if job.kind == JobKind.WB_CARD and group and auto and group not in published:
                groups[group].append(job)
        created = self.publish_finished_themes(jobs, published)
        for group, members in groups.items():
            if len(members) != members[0].payload["merge_group_size"]:
                continue
            if any(m.status not in (JobStatus.DONE, JobStatus.FAILED) for m in members):
                continue
            ready = sorted(
                (m for m in members if m.status == JobStatus.DONE and m.result.get("review_required")),
                key=lambda m: m.design_number,
            )
            if ready:
                created.append(self.create_publication(ready[0].id, group, ready))
        return created

    def publish_finished_themes(self, jobs, published) -> list:
        """A theme with a reserve goes to WB once nothing is left to generate or refill.

        Its finished cards are regrouped in order, group_cards WB cards per group with every color counted,
        so only the last group of a theme can be partial.
        """
        per_group = group_cards(self.env)
        # A print already sent in any publication (an older per-batch group included) is never sent again.
        sent = {card for job in jobs if job.kind == JobKind.WB_PUBLISH for card in job.payload.get("card_ids", [])}
        created = []
        for campaign, members in self.themes(jobs):
            if not campaign.payload["config"].get("auto_publish") or self.refill(campaign, members):
                continue
            if any(m.status not in (JobStatus.DONE, JobStatus.FAILED) or transient(m) for m in members):
                continue
            ready = sorted(
                (
                    m
                    for m in members
                    if m.status == JobStatus.DONE and m.result.get("review_required") and m.id not in sent
                ),
                key=lambda m: m.design_number,
            )
            # A print may have one or two colors; every color is a WB card.
            groups, current, cards = [], [], 0
            for member in ready:
                count = len(member.result.get("vendor_codes") or campaign.payload["config"]["colors"])
                if current and cards + count > per_group:
                    groups.append(current)
                    current, cards = [], 0
                current.append(member)
                cards += count
            if current:
                groups.append(current)
            for members in groups:
                # Named by its first print: stays unique when later prints of the theme are grouped again.
                group = f"PFWG-{campaign.id}-t{members[0].design_number}"
                if group not in published:
                    created.append(self.create_publication(members[0].id, group, members))
        return created

    @staticmethod
    def themes(jobs):
        """Finished theme searches with a design limit, each with all of its cards."""
        cards = collections.defaultdict(list)
        for job in jobs:
            if job.kind == JobKind.WB_CARD and job.payload.get("campaign_id"):
                cards[job.payload["campaign_id"]].append(job)
        for campaign in jobs:
            done = campaign.kind == JobKind.WB_DISCOVER and campaign.status == JobStatus.DONE
            if done and campaign.payload.get("design_limit"):
                yield campaign, cards[campaign.id]

    @staticmethod
    def refill(campaign, members) -> list:
        """Reserve sources a theme still needs: one for every card it lost to a permanent rejection."""
        rejected = sum(m.status == JobStatus.FAILED and not transient(m) for m in members)
        missing = campaign.payload["design_limit"] - (len(members) - rejected)
        used = {m.payload["source"]["sku"] for m in members}
        standard = campaign.payload["config"]["algorithm"] == "standard"
        reserve = [
            s for s in campaign.result.get("sources", [])
            if s["sku"] not in used and (standard or s.get("gallery_complete"))
        ]  # fmt: skip
        return reserve[: max(0, missing)]

    def top_up_campaigns(self) -> list:
        """Reserve sources replace rejected prints, so a theme generates only as many cards as it still lacks.

        Only a permanent rejection frees a slot; a card that failed on a transient error waits for a retry.
        """
        created = []
        for campaign, members in self.themes(self.repo.all(PRODUCT)):
            if portion := self.refill(campaign, members):
                groups = {m.payload["merge_group"] for m in members}
                created += self.enqueue_cards(campaign, portion, first_group=len(groups) + 1)
        return created

    async def supervise(self, stop: asyncio.Event, publish: bool, interval: float = 60) -> None:
        """Background loop: refill themes from their reserve and, if enabled, publish finished groups."""
        while not stop.is_set():
            added = [card for card in self.top_up_campaigns() if card["created"]]
            if added:
                logger.info("WB: из запаса добавлено %s товаров", len(added))
            for job, was_created in self.publish_finished_groups() if publish else ():
                if was_created:
                    logger.info("WB: группа %s поставлена на публикацию", job.payload["merge_group"])
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), interval)

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

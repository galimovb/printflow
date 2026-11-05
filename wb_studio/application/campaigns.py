"""Theme searches: find WB products for a theme and queue one card job per product."""

import copy
import hashlib
import json
from datetime import UTC, datetime

from printflow.domain.errors import PermanentError
from printflow.domain.models import JobKind
from printflow.wb_studio.config import build_config, default_colors, merge_designs
from printflow.wb_studio.domain.campaign_state import refill, themes
from printflow.wb_studio.domain.models import ALGORITHMS, PRODUCT, REDRAW_ALGORITHMS
from printflow.wb_studio.infrastructure.wb import search
from printflow.wb_studio.infrastructure.wb.browser import parsing_batch
from printflow.wb_studio.infrastructure.wb.search import NO_PHOTOS, validate_product_urls

MAX_GALLERY_PHOTOS = 20


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:24]


class Campaigns:
    def __init__(self, repository, env, search_products):
        self.repo = repository
        self.env = env
        self.search = search_products

    # --- job creation -----------------------------------------------------------

    def configuration(self, colors=None, algorithm="standard") -> dict:
        if algorithm not in ALGORITHMS:
            raise ValueError("Unknown WB generation algorithm")
        config = build_config(colors or default_colors(self.env), algorithm, merge_designs(self.env))
        # Frozen per job: only cards created while auto-publication is on are ever published automatically.
        config["auto_publish"] = self.env.get("PRINTFLOW_WB_AUTO_PUBLISH", "").lower() in ("1", "true", "yes")
        return config

    def campaign(self, theme_list, limit, colors=None, design_limit=None, algorithm="standard"):
        config = self.configuration(colors, algorithm)
        jobs = []
        for theme in dict.fromkeys(x.strip() for x in theme_list if x.strip()):
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

    def sources(self, theme, sources, colors=None, algorithm="source_redraw", design_limit=None):
        """A theme parsed on the host: the products come with the job, no search runs in the container."""
        payload = {
            "kind": JobKind.WB_DISCOVER.value,
            "theme": theme,
            "limit": len(sources),
            "config": self.configuration(colors, algorithm),
            "design_limit": design_limit,
            # In the payload, not saved afterwards: a worker may claim the job the moment it exists.
            "sources": sources,
        }
        return self.repo.create(payload, product=PRODUCT, external_id="wb-sources:" + digest(payload))

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
            await self.find_sources(job, result, save)
        wanted = job.payload.get("design_limit")
        if job.payload["config"]["algorithm"] in REDRAW_ALGORITHMS:
            selected = await self.complete_galleries(result, wanted or len(result["sources"]), save)
        else:
            selected = result["sources"][:wanted]
        result["cards"] = self.enqueue_cards(job, selected)
        save("cards_queued", result)
        return result

    async def find_sources(self, job, result, save) -> None:
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

    async def complete_galleries(self, result, wanted, save):
        """Redraw algorithms need the full gallery; search results carry only the first photo."""
        galleries = result.setdefault("source_galleries", {})
        skipped = result.setdefault("skipped_sources", {})
        selected = []
        for source in result["sources"]:
            url = source["url"]
            if url in skipped:
                continue
            if not source.get("gallery_complete") and url not in galleries:
                gallery = await self.gallery(url)
                if isinstance(gallery, str):
                    skipped[url] = gallery
                    save("source_skipped", result)
                    continue
                galleries[url] = gallery
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

    @staticmethod
    async def gallery(url) -> list[str] | str:
        """Photo URLs of a product, or the reason it is skipped."""
        try:
            resolved = await search.resolve_product_urls([url])
        except PermanentError as exc:
            # Only a product without photos is skipped; access limits stop the batch.
            if not str(exc).startswith(NO_PHOTOS):
                raise
            return str(exc)
        if not resolved or not resolved[0].get("images"):
            return "Недостаточно исходных фото"
        return resolved[0]["images"][:MAX_GALLERY_PHOTOS]

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

    # --- reserve ----------------------------------------------------------------

    def top_up(self) -> list:
        """Reserve sources replace rejected prints, so a theme generates only as many cards as it still lacks.

        Only a permanent rejection frees a slot; a card that failed on a transient error waits for a retry.
        """
        created = []
        for campaign, members in themes(self.repo.all(PRODUCT)):
            if portion := refill(campaign, members):
                groups = {m.payload["merge_group"] for m in members}
                created += self.enqueue_cards(campaign, portion, first_group=len(groups) + 1)
        return created

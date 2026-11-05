"""Publication: group finished cards and create them on WB."""

import collections
import copy

from printflow.domain.models import JobKind
from printflow.wb_studio.config import group_cards, load_config
from printflow.wb_studio.domain.campaign_state import refill, reviewed, settled, themes, transient
from printflow.wb_studio.domain.models import PRODUCT
from printflow.wb_studio.infrastructure.wb.payloads import validate, validate_group

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


def product_url(nm_id) -> str:
    return f"https://www.wildberries.ru/catalog/{nm_id}/detail.aspx"


class Publications:
    def __init__(self, repository, env, publisher):
        self.repo = repository
        self.env = env
        self.publisher = publisher

    # --- creating publication jobs -----------------------------------------------

    def enqueue_publication(self, card_id):
        """Manual publication after review: the whole merge group must be finished and reviewed."""
        card = self.repo.get(card_id)
        if not card or card.product != PRODUCT or card.kind != JobKind.WB_CARD:
            raise ValueError("Studio card not found")
        if not reviewed(card):
            raise ValueError("Card is not ready for review")
        group = card.payload.get("merge_group")
        members = self.repo.wb_group_cards(group) if group else [card]
        if group and len(members) != card.payload["merge_group_size"]:
            raise ValueError("Состав группы ещё не сформирован")
        if not all(reviewed(m) for m in members):
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

    # --- automatic publication ---------------------------------------------------

    def publish_finished_groups(self) -> list:
        """Auto-publication: a merge group goes to WB once every member has finished.

        Only cards created with auto_publish in their config qualify; older cards always wait for review.
        Failed members are left out, so one rejected print never blocks the other designs.
        """
        jobs = self.repo.all(PRODUCT)
        published = {j.payload.get("merge_group") for j in jobs if j.kind == JobKind.WB_PUBLISH}
        created = self.publish_finished_themes(jobs, published)
        for group, members in self.batch_groups(jobs, published).items():
            if len(members) != members[0].payload["merge_group_size"] or not all(settled(m) for m in members):
                continue
            ready = sorted((m for m in members if reviewed(m)), key=lambda m: m.design_number)
            if ready:
                created.append(self.create_publication(ready[0].id, group, ready))
        return created

    @staticmethod
    def batch_groups(jobs, published) -> dict:
        """Auto-published merge groups of URL and batch searches; themes with a reserve are regrouped instead."""
        themed = {j.id for j in jobs if j.kind == JobKind.WB_DISCOVER and j.payload.get("design_limit")}
        groups = collections.defaultdict(list)
        for job in jobs:
            group = job.payload.get("merge_group")
            auto = job.payload.get("config", {}).get("auto_publish") is True
            own_group = job.payload.get("campaign_id") not in themed
            if job.kind == JobKind.WB_CARD and group and auto and group not in published and own_group:
                groups[group].append(job)
        return groups

    def publish_finished_themes(self, jobs, published) -> list:
        """A theme with a reserve goes to WB once nothing is left to generate or refill.

        Its finished cards are regrouped in order, group_cards WB cards per group with every color counted,
        so only the last group of a theme can be partial.
        """
        # A print already sent in any publication (an older per-batch group included) is never sent again.
        sent = {card for job in jobs if job.kind == JobKind.WB_PUBLISH for card in job.payload.get("card_ids", [])}
        created = []
        for campaign, members in themes(jobs):
            if not campaign.payload["config"].get("auto_publish") or refill(campaign, members):
                continue
            if any(not settled(m) or transient(m) for m in members):
                continue
            ready = sorted((m for m in members if reviewed(m) and m.id not in sent), key=lambda m: m.design_number)
            for group_members in self.split(ready, campaign.payload["config"]["colors"]):
                # Named by its first print: stays unique when later prints of the theme are grouped again.
                group = f"PFWG-{campaign.id}-t{group_members[0].design_number}"
                if group not in published:
                    created.append(self.create_publication(group_members[0].id, group, group_members))
        return created

    def split(self, cards, colors) -> list[list]:
        """Groups of at most group_cards WB cards; a print may have one or two colors, every color is a card."""
        per_group = group_cards(self.env)
        groups, current, count = [], [], 0
        for card in cards:
            size = len(card.result.get("vendor_codes") or colors)
            if current and count + size > per_group:
                groups.append(current)
                current, count = [], 0
            current.append(card)
            count += size
        if current:
            groups.append(current)
        return groups

    # --- the publication job -------------------------------------------------------

    async def publish(self, job, save):
        drafts = job.payload.get("drafts")
        grouped = bool(drafts)
        if grouped:
            state = await self.publisher.publish_group(drafts, job.result, lambda value: save("wb_publish", value))
        else:
            drafts = [job.payload["draft"]]
            state = await self.publisher.publish(drafts[0], job.result, lambda value: save("wb_publish", value))
        links = []
        for draft in drafts:
            for color, vendor in draft["vendor_codes"].items():
                card = state.get("cards", {}).get(vendor if grouped else color, {})
                if card.get("nmID"):
                    links.append(
                        {
                            "source_url": draft.get("source_url", ""),
                            "color": color,
                            "vendor_code": vendor,
                            "url": product_url(card["nmID"]),
                        }
                    )
        state["source_links"] = links
        save("wb_links_ready", state)
        return state

"""Create new WB cards only. Retry reconciles exact vendor codes before media upload."""

import asyncio
import copy
from datetime import UTC, datetime

from printflow.domain.errors import PermanentError, RetryLater

from .content_api import ContentApi
from .payloads import build_group_payload, build_payload, validate, validate_group


class Publisher:
    def __init__(self, token, request=None):
        self.api = ContentApi(token, request)

    async def publish(self, draft, state, save):
        return await self._publish(draft, state, save)

    async def publish_group(self, drafts, state, save):
        validate_group(drafts)
        flat = copy.deepcopy(drafts[0])
        flat["images"] = {}
        flat["vendor_codes"] = {}
        for draft in drafts:
            for color, images in draft["images"].items():
                vendor = draft["vendor_codes"][color]
                flat["images"][vendor] = images
                flat["vendor_codes"][vendor] = vendor
        return await self._publish(
            flat, state, save, build=lambda codes: build_group_payload(drafts, codes), ensure_merged=True
        )

    async def _publish(self, draft, state, save, *, build=None, ensure_merged=False):
        validate(draft["config"])
        state = copy.deepcopy(state)
        if state.get("complete"):
            return state
        # New vendor codes never collide with the cabinet, so cards are looked up only after upload.
        found = dict.fromkeys(draft["vendor_codes"])
        if state.get("submission_started"):
            found = await self.api.find_all(draft["vendor_codes"])
        if not state.get("barcodes"):
            count = len(draft["images"]) * len(draft["config"]["sizes"])
            data = await self.api.request("/content/v2/barcodes", {"count": count})
            state["barcodes"] = data["data"]
            save(state)
        if not state.get("submission_started"):
            payload = build(state["barcodes"]) if build else build_payload(draft, state["barcodes"])
            state["submission_started"] = True
            state["creation_price"] = draft["config"]["price"]
            state["price_source"] = "sizes[].price in cards/upload"
            state["submitted_at"] = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
            save(state)
            await self.api.request("/content/v2/cards/upload", payload)
            state["submitted"] = True
            save(state)
        if not all(found.values()):
            for _ in range(6):
                await asyncio.sleep(3)
                found = await self.api.find_all(draft["vendor_codes"])
                if all(found.values()):
                    break
        if not all(found.values()):
            missing = [draft["vendor_codes"][key] for key, card in found.items() if not card]
            rejected = await self.api.import_errors(missing, state.get("submitted_at", ""))
            if rejected:
                reasons = sorted({message for messages in rejected.values() for message in messages})
                raise PermanentError("WB отклонил загрузку: " + "; ".join(reasons)[:500])
            state["checks"] = state.get("checks", 0) + 1
            save(state)
            if state["checks"] >= 20:
                raise PermanentError(
                    "WB creation is unresolved. Check WB import errors before retry; no duplicate creation was sent."
                )
            raise RetryLater("WB has not returned all new cards yet; reconcile on retry", delay_sec=60)
        if ensure_merged:
            # Upload variants normally creates one imtID; reconcile without creating duplicates.
            target = state.get("target_imt") or next(iter(found.values())).get("imtID")
            if not target:
                raise RetryLater("WB ещё не вернул imtID новой группы", delay_sec=60)
            state["target_imt"] = target
            if any(card.get("imtID") != target for card in found.values()):
                if not state.get("merge_requested"):
                    save(state)
                    await self.api.request(
                        "/content/v2/cards/moveNm",
                        {"targetIMT": target, "nmIDs": [card["nmID"] for card in found.values()]},
                    )
                    state["merge_requested"] = True
                    save(state)
                state["merge_checks"] = state.get("merge_checks", 0) + 1
                save(state)
                if state["merge_checks"] >= 20:
                    raise PermanentError("WB не подтвердил объединение; проверьте группу в кабинете")
                raise RetryLater("WB подтверждает объединение новой группы", delay_sec=60)
            state["merged"] = True
            save(state)
        media = state.setdefault("media", {})
        # Initial price is already included in every size in cards/upload.
        # Prices API is needed for later changes, not for publishing new cards.
        for color, card in found.items():
            if media.get(color):
                continue
            await self.api.request("/content/v3/media/save", {"nmId": card["nmID"], "data": draft["images"][color]})
            media[color] = True
            save(state)
        state["cards"] = {color: {"nmID": card["nmID"], "imtID": card.get("imtID")} for color, card in found.items()}
        state["complete"] = True
        save(state)
        return state

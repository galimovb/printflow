"""Create new WB cards only. Retry reconciles exact vendor codes before media upload."""

import asyncio
import copy

import httpx

from printflow.domain.errors import PermanentError, RetryLater


def validate(config):
    missing = []
    if not config.get("subject_id"):
        missing.append("subject_id")
    if not config.get("price") or config["price"] <= 0:
        missing.append("price")
    if not config.get("sizes"):
        missing.append("sizes")
    if not config.get("characteristics"):
        missing.append("characteristics")
    for key in ("length", "width", "height", "weightBrutto"):
        if not config.get("dimensions", {}).get(key) or config["dimensions"][key] <= 0:
            missing.append("dimensions." + key)
    if missing:
        raise PermanentError("WB: заполните wb_studio/config/config.json: " + ", ".join(missing))


def build_payload(draft, barcodes):
    config = draft["config"]
    validate(config)
    if len(barcodes) != len(draft["images"]) * len(config["sizes"]):
        raise PermanentError("WB returned an unexpected barcode count")
    variants = []
    offset = 0
    for color in draft["images"]:
        entries = []
        for size in config["sizes"]:
            entries.append({**size, "price": config["price"], "skus": [barcodes[offset]]})
            offset += 1
        characteristics = copy.deepcopy(config["characteristics"])
        # Color ID comes from the configured subject dictionary, not an assumed constant.
        if config.get("color_attribute_id"):
            characteristics = [x for x in characteristics if int(x["id"]) != int(config["color_attribute_id"])]
            characteristics.append(
                {"id": config["color_attribute_id"], "value": ["белый" if color == "white" else "черный"]}
            )
        variants.append(
            {
                "vendorCode": draft["vendor_codes"][color],
                "title": draft["text"]["title"],
                "description": draft["text"]["description"],
                "brand": config.get("brand", ""),
                "dimensions": config["dimensions"],
                "characteristics": characteristics,
                "sizes": entries,
                "kizMarked": bool(config.get("kiz_marked", False)),
            }
        )
    if offset != len(barcodes):
        raise ValueError("WB barcode count mismatch")
    return [{"subjectID": config["subject_id"], "variants": variants}]


def validate_group(drafts):
    if not drafts:
        raise PermanentError("WB: пустая группа публикации")
    variants = sum(len(d["images"]) for d in drafts)
    if variants > 30:
        raise PermanentError("WB: не более 30 цветовых вариантов в группе")
    base = drafts[0]["config"]
    vendors = []
    for draft in drafts:
        validate(draft["config"])
        if any(draft["config"].get(k) != base.get(k) for k in ("subject_id", "brand", "sizes", "price")):
            raise PermanentError("WB: предмет, бренд, размеры и цена должны совпадать внутри группы")
        for color in draft["images"]:
            vendors.append(draft["vendor_codes"][color])
    if len(vendors) != len(set(vendors)):
        raise PermanentError("WB: повтор артикула внутри группы")


def build_group_payload(drafts, barcodes):
    validate_group(drafts)
    expected = sum(len(d["images"]) * len(d["config"]["sizes"]) for d in drafts)
    if len(barcodes) != expected:
        raise PermanentError("WB returned an unexpected group barcode count")
    variants = []
    offset = 0
    for draft in drafts:
        count = len(draft["images"]) * len(draft["config"]["sizes"])
        variants.extend(build_payload(draft, barcodes[offset : offset + count])[0]["variants"])
        offset += count
    return [{"subjectID": drafts[0]["config"]["subject_id"], "variants": variants}]


class Publisher:
    def __init__(self, token, request=None):
        self.token = token
        self.transport = request

    async def request(self, path, body):
        if self.transport:
            return await self.transport(path, body)
        if not self.token:
            raise PermanentError("Не задан PRINTFLOW_WB_API_KEY (или WB_API_KEY)")
        async with httpx.AsyncClient(timeout=90) as client:
            for attempt in range(5):
                base = (
                    "https://discounts-prices-api.wildberries.ru"
                    if path.startswith("/api/v2/")
                    else "https://content-api.wildberries.ru"
                )
                response = await client.post(base + path, json=body, headers={"Authorization": self.token})
                if response.status_code == 429:
                    await asyncio.sleep(min(60, 5 * (attempt + 1)))
                    continue
                response.raise_for_status()
                data = response.json()
                if isinstance(data, dict) and data.get("error"):
                    raise PermanentError("WB: " + str(data.get("errorText") or data.get("additionalErrors") or data))
                return data
        raise RetryLater("WB rate limit", delay_sec=60)

    async def lookup(self, vendor):
        data = await self.request(
            "/content/v2/get/cards/list",
            {"settings": {"cursor": {"limit": 100}, "filter": {"textSearch": vendor, "withPhoto": -1}}},
        )
        return next((x for x in data.get("cards", []) if x.get("vendorCode") == vendor), None)

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
        found = {color: await self.lookup(vendor) for color, vendor in draft["vendor_codes"].items()}
        if any(found.values()) and not state.get("submission_started"):
            raise PermanentError(
                "Vendor code already exists outside this publication. Existing cards are not modified."
            )
        if not state.get("barcodes"):
            count = len(draft["images"]) * len(draft["config"]["sizes"])
            data = await self.request("/content/v2/barcodes", {"count": count})
            state["barcodes"] = data["data"]
            save(state)
        if not state.get("submission_started"):
            payload = build(state["barcodes"]) if build else build_payload(draft, state["barcodes"])
            state["submission_started"] = True
            state["creation_price"] = draft["config"]["price"]
            state["price_source"] = "sizes[].price in cards/upload"
            save(state)
            await self.request("/content/v2/cards/upload", payload)
            state["submitted"] = True
            save(state)
        if not all(found.values()):
            for _ in range(6):
                await asyncio.sleep(3)
                found = {color: await self.lookup(vendor) for color, vendor in draft["vendor_codes"].items()}
                if all(found.values()):
                    break
        if not all(found.values()):
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
                    await self.request(
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
            await self.request("/content/v3/media/save", {"nmId": card["nmID"], "data": draft["images"][color]})
            media[color] = True
            save(state)
        state["cards"] = {color: {"nmID": card["nmID"], "imtID": card.get("imtID")} for color, card in found.items()}
        state["complete"] = True
        save(state)
        return state

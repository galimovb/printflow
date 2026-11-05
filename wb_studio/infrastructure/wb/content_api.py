"""WB content API client: requests with rate-limit retries, card lookup and import errors."""

import asyncio

import httpx

from printflow.domain.errors import PermanentError, RetryLater

PRICES_API = "https://discounts-prices-api.wildberries.ru"
CONTENT_API = "https://content-api.wildberries.ru"


class ContentApi:
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
                base = PRICES_API if path.startswith("/api/v2/") else CONTENT_API
                try:
                    response = await client.post(base + path, json=body, headers={"Authorization": self.token})
                except httpx.TransportError:
                    await asyncio.sleep(5 * (attempt + 1))
                    continue
                if response.status_code == 429:
                    await asyncio.sleep(min(60, 5 * (attempt + 1)))
                    continue
                response.raise_for_status()
                data = response.json()
                if isinstance(data, dict) and data.get("error"):
                    raise PermanentError("WB: " + str(data.get("errorText") or data.get("additionalErrors") or data))
                return data
        raise RetryLater("WB rate limit or connection drops", delay_sec=60)

    async def find_all(self, codes: dict) -> dict:
        """Cards of one upload share an imtID: one exact lookup plus one listing by imtID instead of one per code.

        A code missing from that group (not merged yet) falls back to its own exact lookup.
        """
        vendors = list(codes.values())
        first = await self.lookup(vendors[0])
        group = {}
        if first and first.get("imtID"):
            data = await self.request(
                "/content/v2/get/cards/list",
                {"settings": {"cursor": {"limit": 100}, "filter": {"imtID": first["imtID"], "withPhoto": -1}}},
            )
            group = {card.get("vendorCode"): card for card in data.get("cards", [])}
        group[vendors[0]] = first
        return {key: group.get(vendor) or await self.lookup(vendor) for key, vendor in codes.items()}

    async def lookup(self, vendor):
        data = await self.request(
            "/content/v2/get/cards/list",
            {"settings": {"cursor": {"limit": 100}, "filter": {"textSearch": vendor, "withPhoto": -1}}},
        )
        return next((x for x in data.get("cards", []) if x.get("vendorCode") == vendor), None)

    async def import_errors(self, vendors, since: str = "", pages: int = 10) -> dict:
        """WB import errors of these vendor codes reported after `since`, newest first.

        A rejected upload never creates a card, so without this the lookup would wait for it forever.
        """
        vendors = set(vendors)
        errors = {}
        cursor = {"limit": 100}
        for _ in range(pages):
            body = {"cursor": cursor, "order": {"ascending": False}}
            data = (await self.request("/content/v2/cards/error/list", body)).get("data") or {}
            items = data.get("items") or []
            for item in items:
                if since and (item.get("updatedAt") or "") < since:
                    return errors
                for vendor, messages in (item.get("errors") or {}).items():
                    if vendor in vendors:
                        errors.setdefault(vendor, messages)
            following = data.get("cursor") or {}
            if not items or not following.get("next") or vendors <= errors.keys():
                break
            cursor = {"limit": 100, "updatedAt": following.get("updatedAt"), "batchUUID": following.get("batchUUID")}
        return errors

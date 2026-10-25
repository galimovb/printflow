"""Выкладка на Ozon: импорт, ожидание результата импорта, себестоимость и остатки (если заданы)."""
from __future__ import annotations

import asyncio
from typing import Any

from printflow.config import OzonSettings
from printflow.services.ozon.client import OzonError
from printflow.domain.ports import JsonApiClient


class OzonPublisher:
    def __init__(self, client: JsonApiClient, product: dict[str, Any], settings: OzonSettings) -> None:
        self.client = client
        self.ozon = product["ozon"]
        self.poll_sec = settings.import_poll_sec
        self.poll_attempts = settings.import_poll_attempts

    async def publish(self, items: list[dict[str, Any]]) -> dict[str, Any]:
        task_id = (await self.client.post("/v3/product/import", {"items": items}))["result"]["task_id"]
        statuses = await self._wait_import(task_id)
        imported = [oid for oid, s in statuses.items() if _accepted(s)]
        errors = [f"{oid}: {s['status']} {s['errors'] or s['raw']}" for oid, s in statuses.items()
                  if not _accepted(s)]
        if not imported:
            raise OzonError("Ozon не принял ни одного SKU: " + "; ".join(errors))
        await self._set_net_prices(imported)
        await self._set_stocks(imported)
        product_ids = [statuses[oid]["raw"].get("product_id") for oid in imported]
        return {"task_id": task_id, "offers": imported, "product_ids": [p for p in product_ids if p], "errors": errors}

    async def _wait_import(self, task_id: int) -> dict[str, dict[str, Any]]:
        for _ in range(self.poll_attempts):
            result = (await self.client.post("/v1/product/import/info", {"task_id": task_id}))["result"]
            items = result.get("items") or []
            if items and all(i["status"] in ("imported", "failed", "skipped") for i in items):
                return {i["offer_id"]: {"status": i["status"], "errors": i.get("errors") or [], "raw": i} for i in items}
            await asyncio.sleep(self.poll_sec)
        raise OzonError(
            f"Импорт {task_id} не завершился за {self.poll_attempts * self.poll_sec:.0f} с — проверьте в личном кабинете"
        )

    async def _set_net_prices(self, offers: list[str]) -> None:
        if not self.ozon.get("net_price"):
            return
        prices = [
            {"offer_id": oid, "currency_code": "RUB", "price": str(self.ozon["price"]),
             "net_price": str(self.ozon["net_price"])}
            for oid in offers
        ]
        await self.client.post("/v1/product/import/prices", {"prices": prices})

    async def _set_stocks(self, offers: list[str]) -> None:
        if not self.ozon.get("warehouse_id") or self.ozon.get("stock") is None:
            return
        stocks = [
            {"offer_id": oid, "stock": int(self.ozon["stock"]), "warehouse_id": int(self.ozon["warehouse_id"])}
            for oid in offers
        ]
        await self.client.post("/v2/products/stocks", {"stocks": stocks})


def _accepted(status: dict[str, Any]) -> bool:
    """imported — создан или обновлён; skipped с product_id — товар уже есть и данные не изменились
    (повтор импорта после сбоя, когда первая попытка успела создать товар). skipped без product_id — отказ."""
    return status["status"] == "imported" or (status["status"] == "skipped" and bool(status["raw"].get("product_id")))

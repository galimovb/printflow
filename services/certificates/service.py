"""Сценарий «товары выложены → привязать к сертификату качества» — отдельная задача очереди.

Задачу ставит CardService после выкладки (payload: артикул, product_id товаров, id сертификата).
Ozon привязывает к сертификату только товары с SKU, а SKU появляется после модерации. Поэтому
задача сначала проверяет SKU: если их ещё нет — откладывается (RetryLater, попытка не тратится)
с нарастающей паузой (15 с, 30 с, потом раз в минуту — SHOPPER_OZON_CERTIFICATE_WAIT_SEC), пока не
истечёт предельное время ожидания. Число проверок хранится в задаче (result.sku_checks).
Ошибка Ozon (лимиты, сбой) — ждём сброса лимитов в 03:00 (OzonRetryPolicy), а не долбим.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable

from printflow.config import OzonSettings
from printflow.domain.errors import PermanentError, RetryLater
from printflow.domain.models import Job, SaveProgress
from printflow.services.ozon.certificates import CertificateBinder
from printflow.services.ozon.client import OzonError
from printflow.domain.ports import JsonApiClient
from printflow.services.ozon.retry import OzonRetryPolicy


class CertificateService:
    def __init__(self, client: Callable[[], JsonApiClient], settings: OzonSettings) -> None:
        self.client = client  # фабрика: клиент Ozon создаётся при первой задаче
        self.wait_sec = settings.certificate_wait_sec
        self.max_wait_sec = settings.certificate_max_wait_hours * 3600
        self.ozon_retry = OzonRetryPolicy(settings)

    async def run(self, job: Job, save: SaveProgress) -> dict[str, Any]:
        try:
            return await self._run(job, save)
        except OzonError as exc:
            result = {**job.result, "article": job.payload["article"]}
            error = self.ozon_retry.on_error(exc, result)
            save("ozon_wait", result)
            raise error from exc

    async def _run(self, job: Job, save: SaveProgress) -> dict[str, Any]:
        payload = job.payload
        client = self.client()
        product_ids = [int(pid) for pid in payload["product_ids"]]

        without_sku = await self._without_sku(client, product_ids)
        if without_sku:
            waited = (datetime.now(timezone.utc) - datetime.fromisoformat(job.created_at)).total_seconds()
            if waited > self.max_wait_sec:
                raise PermanentError(
                    f"Товары {without_sku} не получили SKU за {self.max_wait_sec // 3600} ч — проверьте модерацию"
                )
            checks = int(job.result.get("sku_checks", 0))
            save("waiting_sku", {**job.result, "article": payload["article"], "sku_checks": checks + 1})
            delay = self.wait_sec[min(checks, len(self.wait_sec) - 1)]
            raise RetryLater(f"ждём SKU после модерации: {len(without_sku)} из {len(product_ids)}", delay)

        save("binding", {**job.result, "article": payload["article"]})
        binder = CertificateBinder(client, int(payload["certificate_id"]))
        bound = await binder.bind(product_ids)
        return {"article": payload["article"], "certificate_id": binder.certificate_id, "products": bound}

    @staticmethod
    async def _without_sku(client: JsonApiClient, product_ids: list[int]) -> list[int]:
        items = (await client.post("/v3/product/info/list", {"product_id": product_ids})).get("items") or []
        with_sku = {int(item["id"]) for item in items if item.get("sku")}
        return [pid for pid in product_ids if pid not in with_sku]

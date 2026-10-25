"""Обработчик заказов — та же логика, что у fbs_watch футболок, без Диска и Telegram.

Раз в N минут читает FBS-отправления кабинета шопперов в статусах «Ожидают сборки» и
«Ожидают отгрузки» (/v3/posting/fbs/unfulfilled/list) и на каждый артикул BAG- ставит задачу
hires. Задача на артикул одна, поэтому повторные опросы и заказы принт заново не рисуют.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from printflow.config import OrdersSettings
from printflow.domain.models import article_from_offer
from printflow.services.jobs.service import JobService
from printflow.domain.ports import JsonApiClient

logger = logging.getLogger("printflow.orders")


class OrderWatcher:
    def __init__(self, client: JsonApiClient, jobs: JobService, article_prefix: str, settings: OrdersSettings) -> None:
        self.client = client
        self.jobs = jobs
        self.prefix = article_prefix
        self.settings = settings
        self.interval_sec = settings.interval_min * 60

    async def run(self, stop: asyncio.Event) -> None:
        logger.info("Обработчик заказов: опрос раз в %s мин", self.interval_sec // 60)
        while not stop.is_set():
            try:
                await self.poll_once()
            except Exception:  # noqa: BLE001 — сбой опроса не должен останавливать обработчик
                logger.exception("Заказы: опрос не удался, повтор через %s мин", self.interval_sec // 60)
            try:
                await asyncio.wait_for(stop.wait(), timeout=self.interval_sec)
            except asyncio.TimeoutError:
                pass

    async def poll_once(self) -> list[str]:
        """Ставит hi-res для новых заказанных артикулов; возвращает, для каких поставил."""
        new = [article for article in sorted(await self.ordered_articles()) if self.jobs.enqueue_hires(article)[1]]
        if new:
            logger.info("Заказы: hi-res поставлен для %s", ", ".join(new))
        return new

    async def ordered_articles(self) -> set[str]:
        articles: set[str] = set()
        for status in self.settings.fbs_statuses:
            for posting in await self._postings(status):
                for product in posting.get("products") or []:
                    if article := article_from_offer(str(product.get("offer_id") or ""), self.prefix):
                        articles.add(article)
        return articles

    async def _postings(self, status: str) -> list[dict[str, Any]]:
        now = datetime.now(timezone.utc)
        fmt = "%Y-%m-%dT%H:%M:%SZ"
        postings: list[dict[str, Any]] = []
        offset = 0
        while True:
            body = {
                "dir": "ASC",
                "filter": {
                    "cutoff_from": (now - timedelta(days=self.settings.lookback_days)).strftime(fmt),
                    "cutoff_to": (now + timedelta(days=self.settings.cutoff_future_days)).strftime(fmt),
                    "status": status,
                },
                "limit": self.settings.page_size,
                "offset": offset,
            }
            result = (await self.client.post("/v3/posting/fbs/unfulfilled/list", body)).get("result") or {}
            batch = result.get("postings") or []
            postings += batch
            # Ozon не всегда отдаёт has_next — тогда ориентируемся на count и размер страницы.
            done = not result.get("has_next") if "has_next" in result else (
                offset + len(batch) >= int(result.get("count") or 0) or len(batch) < self.settings.page_size
            )
            if not batch or done:
                return postings
            offset += self.settings.page_size

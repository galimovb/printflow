"""Что делать задаче, если Ozon ответил ошибкой: не долбить, а ждать сброса суточных лимитов.

Любая ошибка Ozon (кроме лимита «в секунду») откладывает задачу до ближайшего SHOPPER_OZON_RETRY_AT
по SHOPPER_OZON_RETRY_UTC_OFFSET (по умолчанию 03:00 МСК) — попытка не тратится. Лимит «в секунду»
(HTTP 429 … per second) сбрасывается сразу — повтор через SHOPPER_OZON_RATE_LIMIT_WAIT_SEC.
Ночей ожидания не больше SHOPPER_OZON_RETRY_NIGHTS: если и тогда Ozon отказывает — задача failed
(ошибка, скорее всего, в данных, а не в лимитах). Счётчик ночей хранится в result.ozon_nights.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from printflow.config import OzonSettings
from printflow.domain.errors import PermanentError, RetryLater, ShopperError
from printflow.services.ozon.client import OzonError

WAIT_REASON = "Ozon: ждём сброса лимитов"  # начало job.error у отложенных задач — по нему считает progress


def is_per_second_limit(exc: OzonError) -> bool:
    text = str(exc).lower()
    return "http 429" in text and "per second" in text


class OzonRetryPolicy:
    def __init__(self, settings: OzonSettings) -> None:
        self.retry_at = settings.retry_at
        self.tz = timezone(timedelta(hours=settings.retry_utc_offset))
        self.max_nights = settings.retry_nights
        self.rate_limit_wait_sec = settings.rate_limit_wait_sec

    def on_error(self, exc: OzonError, result: dict[str, Any], *, now: datetime | None = None) -> ShopperError:
        """Ошибка, которую задача должна бросить. Меняет result (счётчик ночей) — вызывающий сохраняет его."""
        if is_per_second_limit(exc):
            return RetryLater(f"Ozon: лимит запросов в секунду — {exc}", self.rate_limit_wait_sec)
        nights = int(result.get("ozon_nights", 0))
        if nights >= self.max_nights:
            return PermanentError(f"Ozon отказывает {nights} ночи подряд — {exc}")
        result["ozon_nights"] = nights + 1
        delay = self.seconds_until_reset(now or datetime.now(timezone.utc))
        at = self.retry_at.strftime("%H:%M")
        return RetryLater(f"{WAIT_REASON} ({at}, попытка {nights + 1}/{self.max_nights}) — {exc}", delay)

    def seconds_until_reset(self, now: datetime) -> float:
        local = now.astimezone(self.tz)
        target = local.replace(hour=self.retry_at.hour, minute=self.retry_at.minute, second=0, microsecond=0)
        if target <= local:
            target += timedelta(days=1)
        return (target - local).total_seconds()

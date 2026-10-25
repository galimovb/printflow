from __future__ import annotations

import asyncio
import unittest
from dataclasses import replace
from datetime import datetime, timezone

from support import SHOPPER, FakeFetcher, FakeGallery, FakeGenerator, FakeStorage, TempDir, new_repository

from printflow.config import load_product_settings
from printflow.domain.errors import PermanentError, RetryLater
from printflow.domain.models import CardSpec
from printflow.services.cards.service import CardService
from printflow.services.certificates.service import CertificateService
from printflow.services.jobs.service import JobService
from printflow.services.ozon.client import OzonError
from printflow.services.ozon.retry import WAIT_REASON, OzonRetryPolicy

PRODUCT = SHOPPER
SETTINGS = replace(load_product_settings("SHOPPER").ozon, retry_utc_offset=3, retry_nights=3, rate_limit_wait_sec=60)
DAILY = OzonError('Ozon /v3/product/import: HTTP 429 {"message":"daily limit exceeded"}')
PER_SECOND = OzonError('Ozon /v3/product/info/list: HTTP 429 {"message":"You have reached request rate limit per second"}')


def utc(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 10, 6, hour, minute, tzinfo=timezone.utc)


class OzonRetryPolicyTest(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = OzonRetryPolicy(SETTINGS)

    def test_waits_until_3am_moscow(self) -> None:
        self.assertEqual(self.policy.seconds_until_reset(utc(20)), 4 * 3600)  # 23:00 МСК → 03:00
        self.assertEqual(self.policy.seconds_until_reset(utc(23, 30)), 30 * 60)  # 02:30 МСК
        self.assertEqual(self.policy.seconds_until_reset(utc(0)), 24 * 3600)  # ровно 03:00 — уже завтра

    def test_error_postpones_and_counts_nights(self) -> None:
        result: dict = {}
        error = self.policy.on_error(DAILY, result, now=utc(20))
        self.assertIsInstance(error, RetryLater)
        self.assertEqual(error.delay_sec, 4 * 3600)
        self.assertTrue(str(error).startswith(WAIT_REASON))
        self.assertEqual(result["ozon_nights"], 1)
        result["ozon_nights"] = 3
        self.assertIsInstance(self.policy.on_error(DAILY, result), PermanentError)  # не ждём вечно

    def test_per_second_limit_retries_soon(self) -> None:
        result: dict = {}
        error = self.policy.on_error(PER_SECOND, result)
        self.assertEqual((type(error), error.delay_sec), (RetryLater, 60))
        self.assertNotIn("ozon_nights", result)


class FailingPublisher:
    async def publish(self, items):
        raise DAILY


class ServicesWaitForResetTest(unittest.TestCase):
    def test_card_publish_error_waits_for_reset(self) -> None:
        with TempDir() as tmp:
            repo = new_repository(tmp)
            service = CardService(PRODUCT, FakeStorage(), FakeGenerator(), FakeGallery(), lambda: FailingPublisher(),
                                  FakeFetcher(), ozon_retry=OzonRetryPolicy(SETTINGS))
            job, _ = repo.create(product="shopper", payload=CardSpec(theme="кот").to_payload())
            saved: list = []
            with self.assertRaises(RetryLater):
                asyncio.run(service.run(job, lambda stage, result: saved.append((stage, dict(result)))))
        self.assertEqual(saved[-1][0], "ozon_wait")
        self.assertEqual(saved[-1][1]["ozon_nights"], 1)
        self.assertIn("images", saved[-1][1])  # галерея сохранена — ночью только выкладка

    def test_certificate_error_waits_for_reset(self) -> None:
        class FakeOzon:
            async def post(self, path, body):
                raise DAILY

        with TempDir() as tmp:
            job, _ = JobService(new_repository(tmp), product="shopper").enqueue_certificate("BAG-000001", [101], 5432232)
        saved: list = []
        with self.assertRaises(RetryLater) as ctx:
            asyncio.run(CertificateService(lambda: FakeOzon(), SETTINGS).run(job, lambda s, r: saved.append((s, r))))
        self.assertTrue(str(ctx.exception).startswith(WAIT_REASON))
        self.assertEqual(saved[-1], ("ozon_wait", {"article": "BAG-000001", "ozon_nights": 1}))


if __name__ == "__main__":
    unittest.main()

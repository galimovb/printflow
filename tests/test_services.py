from __future__ import annotations

import asyncio
import unittest

from support import (
    SHOPPER,
    FakeFetcher,
    FakeGallery,
    FakeGenerator,
    FakePublisher,
    FakeStorage,
    TempDir,
    new_repository,
)

from printflow.config import load_product_settings
from printflow.domain.models import CardSpec, JobKind
from printflow.services.cards.service import CardService
from printflow.services.certificates.service import CertificateService
from printflow.services.hires.service import HiresService
from printflow.services.jobs.service import JobService
from printflow.services.orders.watcher import OrderWatcher

PRODUCT = SHOPPER
BUCKETS = PRODUCT.buckets


class CardServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = TempDir()
        self.repo = new_repository(self.tmp.__enter__())
        self.storage, self.generator, self.publisher = FakeStorage(), FakeGenerator(), FakePublisher()
        self.service = CardService(PRODUCT, self.storage, self.generator, FakeGallery(), lambda: self.publisher,
                                   FakeFetcher())

    def tearDown(self) -> None:
        self.tmp.__exit__()

    def _run(self, spec: CardSpec, result: dict | None = None):
        job, _ = self.repo.create(product="shopper", payload=spec.to_payload())
        job.result = result or {}
        stages: list[str] = []
        out = asyncio.run(self.service.run(job, lambda stage, _r: stages.append(stage)))
        return job, out, stages

    def test_theme_card_end_to_end(self) -> None:
        job, result, stages = self._run(CardSpec(theme="кот в очках"))
        article = f"BAG-{job.number:06d}"  # задача без группы (merge_designs=1) — артикул по номеру
        self.assertEqual(result["article"], article)
        self.assertEqual(self.generator.calls, ["preview"])  # одна генерация — только принт
        self.assertEqual(sorted(result["images"]), ["black", "white"])
        self.assertEqual(result["ozon"]["offers"], [f"{article}-W", f"{article}-B"])
        self.assertEqual(stages[0], "print")
        self.assertEqual(stages[-1], "ozon_done")

    def test_copy_from_photo_uses_fixed_title(self) -> None:
        _, result, _ = self._run(CardSpec(reference_url="https://ozon/1.jpg", product_name="Сумка-шоппер с принтом"))
        self.assertEqual(self.generator.calls, ["copy"])
        self.assertNotIn("design_label", result)
        self.assertEqual({item["name"] for item in self.publisher.items}, {"Сумка-шоппер с принтом"})

    def test_certificate_job_queued_after_publish_once(self) -> None:
        jobs = JobService(self.repo, product="shopper")
        self.service.enqueue_certificate = lambda article, ids: jobs.enqueue_certificate(article, ids, 5432232)
        _, result, stages = self._run(CardSpec(theme="кот"))
        cert = jobs.get(result["certificate_job"])
        self.assertEqual(cert.kind, JobKind.CERTIFICATE)
        self.assertEqual(cert.payload, {"kind": "certificate", "article": result["article"],
                                        "product_ids": [101, 102], "certificate_id": 5432232})
        self.assertEqual(stages[-1], "certificate_queued")
        _, again, _ = self._run(CardSpec(theme="кот"), result=dict(result))  # повтор карточки — без дубля
        self.assertEqual(again["certificate_job"], cert.id)
        self.assertEqual(sum(j.kind == JobKind.CERTIFICATE for j in jobs.list()), 1)

    def test_no_certificate_job_for_dry_run(self) -> None:
        calls = []
        self.service.enqueue_certificate = lambda article, ids: calls.append(article)
        self._run(CardSpec(theme="кот", dry_run=True))
        self.assertEqual(calls, [])


    def test_resume_skips_done_steps(self) -> None:
        done = {"article": "BAG-000001", "print": "url",
                "images": {"white": ["u1"], "black": ["u2"]}}
        self.storage.objects[f"{BUCKETS['prints']}/BAG-000001.png"] = b"png"
        _, result, stages = self._run(CardSpec(theme="кот", dry_run=True), result=done)
        self.assertEqual(self.generator.calls, [])  # принт не перегенерируется
        self.assertEqual(stages, ["ozon", "ozon_done"])
        self.assertTrue(result["ozon"]["dry_run"])


class CertificateServiceTest(unittest.TestCase):
    def _run(self, skus: dict[int, int], *, created_at: str | None = None, checks: int = 0):
        sent = []

        class FakeOzon:
            async def post(self, path, body):
                sent.append(path)
                if path == "/v3/product/info/list":
                    return {"items": [{"id": pid, "sku": skus.get(pid, 0)} for pid in body["product_id"]]}
                return {}

        with TempDir() as tmp:
            job, _ = JobService(new_repository(tmp), product="shopper").enqueue_certificate("BAG-000001", [101, 102], 5432232)
        if created_at:
            job.created_at = created_at
        job.result = {"sku_checks": checks} if checks else {}
        service = CertificateService(lambda: FakeOzon(), load_product_settings("SHOPPER").ozon)
        return sent, asyncio.run(service.run(job, lambda *_: None))

    def test_binds_when_all_have_sku(self) -> None:
        sent, result = self._run({101: 5001, 102: 5002})
        self.assertEqual(sent, ["/v3/product/info/list", "/v1/product/certificate/bind"])
        self.assertEqual(result, {"article": "BAG-000001", "certificate_id": 5432232, "products": 2})

    def test_waits_for_sku_with_growing_pauses(self) -> None:
        from printflow.domain.errors import RetryLater

        delays = []
        for checks in (0, 1, 2, 5):  # 1-я, 2-я, 3-я и дальнейшие проверки
            with self.assertRaises(RetryLater) as ctx:
                self._run({101: 5001}, checks=checks)  # у второго товара SKU ещё нет
            delays.append(ctx.exception.delay_sec)
        self.assertEqual(delays, [15, 30, 60, 60])

    def test_gives_up_after_max_wait(self) -> None:
        from printflow.domain.errors import PermanentError

        with self.assertRaises(PermanentError):
            self._run({}, created_at="2020-01-01T00:00:00+00:00")


class HiresServiceTest(unittest.TestCase):
    def _run(self, existing: bool):
        tmp = TempDir()
        repo = new_repository(tmp.__enter__())
        hires_key = f"{BUCKETS['hires']}/BAG-000001.png"
        storage = FakeStorage({hires_key} if existing else set())
        storage.objects[f"{BUCKETS['prints']}/BAG-000001.png"] = b"preview"
        generator = FakeGenerator()
        job, _ = repo.create(product="shopper", payload={"kind": "hires", "article": "BAG-000001"})
        result = asyncio.run(HiresService(PRODUCT.config, storage, generator).run(job, lambda *_: None))
        tmp.__exit__()
        return result, generator, storage

    def test_existing_hires_not_regenerated(self) -> None:
        result, generator, storage = self._run(existing=True)
        self.assertEqual((generator.calls, storage.puts), ([], []))
        self.assertTrue(result["existing"])

    def test_missing_hires_generated(self) -> None:
        _, generator, storage = self._run(existing=False)
        self.assertEqual(generator.calls, ["hires"])
        self.assertEqual(storage.puts, [f"{BUCKETS['hires']}/BAG-000001.png"])


class OrderWatcherTest(unittest.TestCase):
    def test_enqueues_hires_once_per_article(self) -> None:
        class FakeOzon:
            async def post(self, path, body):
                if body["filter"]["status"] != "awaiting_packaging":
                    return {"result": {"postings": [], "has_next": False}}
                products = [{"offer_id": "BAG-000001-W"}, {"offer_id": "BAG-000001-B"}, {"offer_id": "TEE-000009-W"},
                            {"offer_id": "BAG-0003-02-W"}]
                return {"result": {"postings": [{"products": products}], "has_next": False}}

        with TempDir() as tmp:
            jobs = JobService(new_repository(tmp), product="shopper")
            watcher = OrderWatcher(FakeOzon(), jobs, "BAG-", load_product_settings("SHOPPER").orders)
            self.assertEqual(asyncio.run(watcher.poll_once()), ["BAG-0003-02", "BAG-000001"][::-1])
            self.assertEqual(asyncio.run(watcher.poll_once()), [])  # второй опрос — без дублей
            listed = jobs.list()
        self.assertEqual(sorted(j.payload["article"] for j in listed), ["BAG-000001", "BAG-0003-02"])
        self.assertEqual({j.kind for j in listed}, {JobKind.HIRES})


if __name__ == "__main__":
    unittest.main()

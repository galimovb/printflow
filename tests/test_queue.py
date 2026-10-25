from __future__ import annotations

import asyncio
import unittest

from support import TempDir, new_repository, queue_settings

from printflow.domain.errors import PermanentError
from printflow.domain.models import JobKind, JobStatus
from printflow.workers.queue import QueueWorker


class QueueWorkerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = TempDir()
        self.repo = new_repository(self.tmp.__enter__())

    def tearDown(self) -> None:
        self.tmp.__exit__()

    def _run(self, handler, *, seconds: float = 0.4, **settings) -> None:
        worker = QueueWorker(self.repo, {JobKind.CARD: handler}, queue_settings(**settings), product="shopper")

        async def run():
            stop = asyncio.Event()
            task = asyncio.create_task(worker.run(stop))
            await asyncio.sleep(seconds)
            stop.set()
            await task

        asyncio.run(run())

    def test_worker_survives_database_error(self) -> None:
        """Сбой базы при взятии задачи не останавливает очередь навсегда (раньше воркер молча умирал)."""
        job, _ = self.repo.create(product="shopper", payload={"kind": "card"})
        real_claim, calls = self.repo.claim_next, []

        def flaky_claim(product=None):
            calls.append(product)
            if len(calls) == 1:
                raise RuntimeError("database is locked")
            return real_claim(product)

        self.repo.claim_next = flaky_claim  # type: ignore[method-assign]

        async def handler(job, save):
            return {"done": True}

        with self.assertLogs("printflow.queue", level="ERROR"):
            self._run(handler, error_pause_sec=0.05)
        self.assertEqual(self.repo.get(job.id).status, JobStatus.DONE)

    def test_success_and_progress(self) -> None:
        job, _ = self.repo.create(product="shopper", payload={"kind": "card"})

        async def handler(job, save):
            save("step", {"half": True})
            return {"done": True}

        self._run(handler)
        done = self.repo.get(job.id)
        self.assertEqual((done.status, done.result), (JobStatus.DONE, {"done": True}))

    def test_retries_then_succeeds(self) -> None:
        job, _ = self.repo.create(product="shopper", payload={"kind": "card"})
        calls = []

        async def handler(job, save):
            calls.append(job.attempts)
            if len(calls) < 3:
                raise TimeoutError("OpenAI timeout")
            return {"ok": True}

        self._run(handler, seconds=1.0)  # три попытки подряд — с запасом под нагрузкой полного прогона
        self.assertEqual(calls, [1, 2, 3])
        self.assertEqual(self.repo.get(job.id).status, JobStatus.DONE)

    def test_fails_after_max_attempts(self) -> None:
        job, _ = self.repo.create(product="shopper", payload={"kind": "card"})

        async def handler(job, save):
            raise ValueError("boom")

        self._run(handler)
        failed = self.repo.get(job.id)
        self.assertEqual((failed.status, failed.attempts, failed.error), (JobStatus.FAILED, 3, "ValueError: boom"))

    def test_permanent_error_not_retried(self) -> None:
        job, _ = self.repo.create(product="shopper", payload={"kind": "card"})

        async def handler(job, save):
            raise PermanentError("safety system")

        self._run(handler)
        self.assertEqual((self.repo.get(job.id).status, self.repo.get(job.id).attempts), (JobStatus.FAILED, 1))

    def test_retry_later_postpones_without_attempt(self) -> None:
        from printflow.domain.errors import RetryLater

        job, _ = self.repo.create(product="shopper", payload={"kind": "card"})

        async def handler(job, save):
            raise RetryLater("ждём SKU", 3600)

        self._run(handler, seconds=0.2)
        waiting = self.repo.get(job.id)
        self.assertEqual((waiting.status, waiting.stage, waiting.attempts), (JobStatus.PENDING, "waiting", 0))
        self.assertIsNone(self.repo.claim_next())  # не раньше, чем через час

    def test_concurrency_limit(self) -> None:
        for _ in range(6):
            self.repo.create(product="shopper", payload={"kind": "card"})
        active, peak = 0, 0

        async def handler(job, save):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0.05)
            active -= 1
            return {}

        self._run(handler, seconds=0.6)
        self.assertEqual(peak, 3)
        self.assertEqual(self.repo.count_by_status(), {"done": 6})


if __name__ == "__main__":
    unittest.main()

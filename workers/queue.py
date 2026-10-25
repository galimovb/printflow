"""Воркер очереди: пул до N задач одновременно (как p-limit), диспетчеризация по типу задачи и
автоповтор упавших.

Ошибка задачи → повтор через SHOPPER_RETRY_DELAYS_SEC, пока не исчерпаны попытки (SHOPPER_MAX_ATTEMPTS);
PermanentError (например, отказ фильтра OpenAI) — сразу failed. Повтор продолжает с места падения:
результат каждого шага уже сохранён в задаче.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable, Mapping

from printflow.config import QueueSettings
from printflow.domain.errors import PermanentError, RetryLater
from printflow.domain.models import Job, JobKind, SaveProgress
from printflow.repositories.jobs import JobRepository

logger = logging.getLogger("printflow.queue")

Handler = Callable[[Job, SaveProgress], Awaitable[dict[str, Any]]]


class QueueWorker:
    def __init__(
        self,
        repository: JobRepository,
        handlers: Mapping[JobKind, Handler],
        settings: QueueSettings,
        *,
        product: str,
    ) -> None:
        self.repository = repository
        self.product = product  # воркер берёт только задачи своего товара (свои лимиты, свой кабинет)
        self.handlers = handlers
        self.concurrency = settings.workers
        self.max_attempts = settings.max_attempts
        self.poll_sec = settings.poll_sec
        self.retry_delays_sec = settings.retry_delays_sec
        self.error_pause_sec = settings.error_pause_sec  # после сбоя базы (блокировка SQLite, диск)

    async def run(self, stop: asyncio.Event) -> None:
        """Держит до concurrency задач одновременно, пока не выставлен stop; дожидается запущенных."""
        if recovered := self.repository.recover_interrupted(max_attempts=self.max_attempts, product=self.product):
            logger.warning("%s: возвращено в очередь после перезапуска: %s", self.product, recovered)
        logger.info("%s: до %s задач одновременно, до %s попыток", self.product, self.concurrency, self.max_attempts)
        running: set[asyncio.Task] = set()
        while not stop.is_set():
            pause = self.poll_sec
            try:
                while len(running) < self.concurrency and (job := self.repository.claim_next(self.product)):
                    task = asyncio.create_task(self.process(job))
                    running.add(task)
                    task.add_done_callback(running.discard)
            except Exception:  # noqa: BLE001 — сбой базы (блокировка, диск) не должен останавливать очередь навсегда
                logger.exception("%s: не удалось взять задачу из базы, повтор через %s с", self.product,
                                 self.error_pause_sec)
                pause = self.error_pause_sec
            try:
                await asyncio.wait_for(stop.wait(), timeout=pause)
            except asyncio.TimeoutError:
                pass
        await asyncio.gather(*running, return_exceptions=True)

    async def process(self, job: Job) -> None:
        logger.info("job %s (%s №%s, %s): старт, попытка %s", job.id, job.product, job.number, job.kind.value,
                    job.attempts)

        def save(stage: str, result: dict[str, Any]) -> None:
            self.repository.save_progress(job.id, stage=stage, result=result)

        try:
            try:
                result = await self.handlers[job.kind](job, save)
            except Exception as exc:  # noqa: BLE001 — любая ошибка задачи → повтор или failed с текстом
                self._handle_failure(job, exc)
                return
            self.repository.complete(job.id, result)
            logger.info("job %s: готово", job.id)
        except Exception:  # noqa: BLE001 — не записалось в базу: задача остаётся running и вернётся в очередь
            logger.exception("job %s: не удалось записать результат в базу — вернётся в очередь после перезапуска",
                             job.id)

    def _handle_failure(self, job: Job, exc: Exception) -> None:
        if isinstance(exc, RetryLater):
            logger.info("job %s: отложена на %s с — %s", job.id, exc.delay_sec, exc)
            self.repository.postpone(job.id, reason=str(exc), delay_sec=exc.delay_sec)
            return
        error = f"{type(exc).__name__}: {exc}"
        if isinstance(exc, PermanentError) or job.attempts >= self.max_attempts:
            logger.error("job %s: failed после %s попыток — %s", job.id, job.attempts, error)
            self.repository.fail(job.id, error)
            return
        delay = self.retry_delays_sec[min(job.attempts - 1, len(self.retry_delays_sec) - 1)]
        logger.warning("job %s: ошибка, повтор через %s с (попытка %s/%s) — %s",
                       job.id, delay, job.attempts, self.max_attempts, error)
        self.repository.requeue(job.id, error=error, delay_sec=delay)

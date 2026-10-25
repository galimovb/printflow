"""Хранилище задач на SQLite. Только SQL и преобразование строк в Job — без бизнес-логики.

Схему создают и обновляют миграции (shopper/migrations, сервис migrate в docker-compose);
репозиторий при старте только проверяет, что они применены.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

from printflow.domain.models import Job, JobStatus
from printflow.migrations.runner import design_counter, ensure_current


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _iso(value: datetime) -> str:
    return value.isoformat()


class JobRepository:
    def __init__(self, path: Path, *, timeout_sec: float) -> None:
        ensure_current(path)
        self.path = path
        self.timeout_sec = timeout_sec
        self._lock = threading.Lock()

    # ───────── инфраструктура ─────────

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path, timeout=self.timeout_sec, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        try:
            yield db
        finally:
            db.close()

    @staticmethod
    def _to_job(row: sqlite3.Row | None) -> Job | None:
        if row is None:
            return None
        data = dict(row)
        return Job(
            id=data["id"],
            product=data["product"],
            number=data["number"],
            status=JobStatus(data["status"]),
            payload=json.loads(data["payload"]),
            result=json.loads(data["result"]) if data["result"] else {},
            external_id=data["external_id"],
            stage=data["stage"],
            error=data["error"],
            attempts=data["attempts"],
            created_at=data["created_at"],
            updated_at=data["updated_at"],
            started_at=data["started_at"],
            finished_at=data["finished_at"],
            available_at=data.get("available_at"),
            group_id=data.get("group_id"),
            group_position=data.get("group_position"),
            design_number=data.get("design_number"),
        )

    # ───────── чтение ─────────

    def get(self, job_id: str) -> Job | None:
        with self._conn() as db:
            return self._to_job(db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone())

    def find_card_article(self, product: str, article: str) -> Job | None:
        with self._conn() as db:
            row = db.execute("SELECT * FROM jobs WHERE product = ? AND json_extract(result, '$.article') = ? "
                             "AND json_extract(payload, '$.kind') = 'card' ORDER BY created_at DESC LIMIT 1",
                             (product, article)).fetchone()
            return self._to_job(row)

    def get_by_external_id(self, external_id: str) -> Job | None:
        with self._conn() as db:
            return self._to_job(db.execute("SELECT * FROM jobs WHERE external_id = ?", (external_id,)).fetchone())

    def list(self, *, product: str | None = None, status: JobStatus | None = None, limit: int = 50) -> list[Job]:
        where, args = [], []
        if product:
            where.append("product = ?")
            args.append(product)
        if status:
            where.append("status = ?")
            args.append(status.value)
        sql = "SELECT * FROM jobs" + (" WHERE " + " AND ".join(where) if where else "")
        sql += " ORDER BY number DESC LIMIT ?"
        args.append(max(1, min(500, limit)))
        with self._conn() as db:
            return [self._to_job(r) for r in db.execute(sql, args).fetchall()]  # type: ignore[misc]

    def count_by_status(self, product: str | None = None) -> dict[str, int]:
        sql = "SELECT status, count(*) FROM jobs" + (" WHERE product = ?" if product else "") + " GROUP BY status"
        with self._conn() as db:
            return {row[0]: row[1] for row in db.execute(sql, (product,) if product else ())}

    def wb_group_cards(self, key: str) -> list[Job]:
        """Exact persistent members of one WB group; no listing/pagination truncation."""
        with self._conn() as db:
            return [self._to_job(row) for row in db.execute(
                "SELECT * FROM jobs WHERE product = 'tee_wb' AND json_extract(payload, '$.kind') = 'wb_card'"
                " AND json_extract(payload, '$.merge_group') = ? ORDER BY number", (key,))]

    # ───────── запись ─────────

    def create(
        self,
        payload: dict[str, Any],
        *,
        product: str,
        external_id: str | None = None,
        numbered: bool = False,
        group_size: int | None = None,
    ) -> tuple[Job, bool]:
        """Новая задача товара; при повторе того же external_id — существующая (created=False)."""
        return self.create_many([(payload, external_id)], product=product, numbered=numbered,
                                group_size=group_size)[0]

    def create_many(
        self,
        items: list[tuple[dict[str, Any], str | None]],
        *,
        product: str,
        numbered: bool = False,
        group_size: int | None = None,
    ) -> list[tuple[Job, bool]]:
        """Пачка задач товара (payload, external_id) одной транзакцией, в порядке items. Повтор external_id
        (в базе или внутри пачки) — существующая задача (created=False).

        numbered — выдать сквозной номер дизайна (артикул); group_size — место в группе объединения
        (последняя незаполненная группа или новая). Всё в одной транзакции: параллельные запросы
        не получат один номер или одно место, а при ошибке не останется половины пачки.
        """
        now = _iso(_now())
        ids: list[tuple[str, bool]] = []
        seen: dict[str, str] = {}  # external_id → id задачи в этой пачке
        with self._lock, self._conn() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                for payload, external_id in items:
                    if external_id:
                        if external_id in seen:
                            ids.append((seen[external_id], False))
                            continue
                        existing = db.execute("SELECT id FROM jobs WHERE external_id = ?", (external_id,)).fetchone()
                        if existing:
                            seen[external_id] = existing["id"]
                            ids.append((existing["id"], False))
                            continue
                    group_id, position = (self._take_group_slot(db, product, group_size, now) if group_size
                                          else (None, None))
                    design_number = self._next_design_number(db, product) if numbered else None
                    job_id = uuid.uuid4().hex
                    db.execute(
                        "INSERT INTO jobs (id, product, external_id, status, stage, payload, created_at, updated_at,"
                        " group_id, group_position, design_number)"
                        " VALUES (?, ?, ?, 'pending', 'queued', ?, ?, ?, ?, ?, ?)",
                        (job_id, product, external_id, json.dumps(payload, ensure_ascii=False), now, now, group_id,
                         position, design_number),
                    )
                    if external_id:
                        seen[external_id] = job_id
                    ids.append((job_id, True))
                db.execute("COMMIT")
            except BaseException:
                db.execute("ROLLBACK")
                raise
            jobs = self._get_many(db, [job_id for job_id, _ in ids])
        return [(jobs[job_id], created) for job_id, created in ids]

    def _get_many(self, db: sqlite3.Connection, job_ids: list[str]) -> dict[str, Job]:
        jobs: dict[str, Job] = {}
        unique = list(dict.fromkeys(job_ids))
        for start in range(0, len(unique), 500):  # лимит параметров SQLite
            chunk = unique[start:start + 500]
            rows = db.execute(f"SELECT * FROM jobs WHERE id IN ({','.join('?' * len(chunk))})", chunk)
            jobs.update({row["id"]: self._to_job(row) for row in rows})  # type: ignore[misc]
        return jobs

    @staticmethod
    def _next_design_number(db: sqlite3.Connection, product: str) -> int:
        name = design_counter(product)
        db.execute("INSERT OR IGNORE INTO counters (name, value) VALUES (?, 0)", (name,))
        db.execute("UPDATE counters SET value = value + 1 WHERE name = ?", (name,))
        return db.execute("SELECT value FROM counters WHERE name = ?", (name,)).fetchone()[0]

    @staticmethod
    def _take_group_slot(db: sqlite3.Connection, product: str, size: int, now: str) -> tuple[int, int]:
        """Следующее место в последней группе товара, если в ней есть свободные; иначе новая группа."""
        last = db.execute("SELECT id, size FROM merge_groups WHERE product = ? ORDER BY id DESC LIMIT 1",
                          (product,)).fetchone()
        if last is not None:
            taken = db.execute("SELECT count(*) FROM jobs WHERE group_id = ?", (last["id"],)).fetchone()[0]
            if taken < last["size"]:
                return last["id"], taken + 1
        group_id = db.execute("INSERT INTO merge_groups (product, size, created_at) VALUES (?, ?, ?)",
                              (product, size, now)).lastrowid
        return group_id, 1

    def drawn_titles(self, product: str, theme_key: str, limit: int, field: str = "design_name") -> list[str]:
        """Последние принты тематики по полю результата (design_name — описание рисунка, subject — сюжет,
        придуманный текстовой моделью) — новые принты их не повторяют."""
        if field not in ("design_name", "subject"):
            raise ValueError(f"drawn_titles: неизвестное поле {field!r}")
        path = f"$.{field}"
        with self._conn() as db:
            rows = db.execute(
                "SELECT json_extract(result, ?) AS title FROM jobs"
                " WHERE product = ? AND json_extract(payload, '$.theme_key') = ?"
                " AND json_extract(result, ?) IS NOT NULL ORDER BY updated_at DESC LIMIT ?",
                (path, product, theme_key, path, limit),
            ).fetchall()
        return [row["title"] for row in rows]

    def claim_next(self, product: str | None = None) -> Job | None:
        """Атомарно берёт готовую к запуску pending-задачу: сначала короткие (сертификаты, hi-res по заказам),
        потом карточки — иначе тысяча карточек в очереди держит привязку сертификатов; внутри — самую старую.

        Принты одной тематики (payload.theme_key) — строго по одному: пока в тематике товара есть running-задача,
        следующая не берётся. Так каждый принт видит уже нарисованные (drawn_titles) и не повторяет их;
        разные тематики идут параллельно."""
        now = _iso(_now())
        with self._lock, self._conn() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT id FROM jobs WHERE status = 'pending' AND (available_at IS NULL OR available_at <= ?)"
                + (" AND product = ?" if product else "")
                + " AND (json_extract(payload, '$.theme_key') IS NULL OR NOT EXISTS ("
                "SELECT 1 FROM jobs AS busy WHERE busy.status = 'running' AND busy.product = jobs.product"
                " AND json_extract(busy.payload, '$.theme_key') = json_extract(jobs.payload, '$.theme_key')))"
                + " AND (product != 'tee_wb' OR json_extract(payload, '$.kind') = 'wb_discover' OR NOT EXISTS ("
                "SELECT 1 FROM jobs AS discovery WHERE discovery.product = 'tee_wb'"
                " AND json_extract(discovery.payload, '$.kind') = 'wb_discover'"
                " AND discovery.status IN ('pending', 'running')))"
                + " ORDER BY ifnull(json_extract(payload, '$.kind'), 'card') = 'card', number LIMIT 1",
                (now, product) if product else (now,),
            ).fetchone()
            if row is None:
                db.execute("COMMIT")
                return None
            db.execute(
                "UPDATE jobs SET status = 'running', stage = 'started', attempts = attempts + 1,"
                " started_at = ?, updated_at = ?, available_at = NULL WHERE id = ?",
                (now, now, row["id"]),
            )
            db.execute("COMMIT")
        return self.get(row["id"])

    def save_progress(self, job_id: str, *, stage: str, result: dict[str, Any]) -> None:
        with self._conn() as db:
            db.execute(
                "UPDATE jobs SET stage = ?, result = ?, updated_at = ? WHERE id = ?",
                (stage, json.dumps(result, ensure_ascii=False), _iso(_now()), job_id),
            )

    def complete(self, job_id: str, result: dict[str, Any]) -> None:
        now = _iso(_now())
        with self._conn() as db:
            db.execute(
                "UPDATE jobs SET status = 'done', stage = 'done', result = ?, error = NULL,"
                " finished_at = ?, updated_at = ? WHERE id = ?",
                (json.dumps(result, ensure_ascii=False), now, now, job_id),
            )

    def fail(self, job_id: str, error: str) -> None:
        now = _iso(_now())
        with self._conn() as db:
            db.execute(
                "UPDATE jobs SET status = 'failed', stage = 'failed', error = ?, finished_at = ?, updated_at = ?"
                " WHERE id = ?",
                (error, now, now, job_id),
            )

    def requeue(self, job_id: str, *, error: str, delay_sec: float) -> None:
        """Вернуть в очередь после ошибки с паузой; результат шагов сохраняется — продолжит с места падения."""
        now = _now()
        with self._conn() as db:
            db.execute(
                "UPDATE jobs SET status = 'pending', stage = 'retry_wait', error = ?, available_at = ?,"
                " updated_at = ? WHERE id = ?",
                (error, _iso(now + timedelta(seconds=delay_sec)), _iso(now), job_id),
            )

    def postpone(self, job_id: str, *, reason: str, delay_sec: float) -> None:
        """Отложить без траты попытки: задача ждёт внешнего события (модерации), это не ошибка."""
        now = _now()
        with self._conn() as db:
            db.execute(
                "UPDATE jobs SET status = 'pending', stage = 'waiting', error = ?, available_at = ?,"
                " attempts = max(attempts - 1, 0), updated_at = ? WHERE id = ?",
                (reason, _iso(now + timedelta(seconds=delay_sec)), _iso(now), job_id),
            )

    def reset_failed(self, job_id: str) -> Job | None:
        """Ручной повтор упавшей задачи: попытки считаются заново."""
        with self._conn() as db:
            db.execute(
                "UPDATE jobs SET status = 'pending', stage = 'queued', error = NULL, finished_at = NULL,"
                " attempts = 0, available_at = NULL, updated_at = ? WHERE id = ? AND status = 'failed'",
                (_iso(_now()), job_id),
            )
        return self.get(job_id)

    def release_ozon_waits(self, product: str, reason_prefix: str) -> int:
        """Задачи товара, отложенные до сброса лимитов Ozon (job.error начинается с reason_prefix), —
        в очередь сейчас; попытки и счётчик ночей не трогаются."""
        now = _iso(_now())
        with self._lock, self._conn() as db:
            return db.execute(
                "UPDATE jobs SET stage = 'queued', error = NULL, available_at = NULL, updated_at = ?"
                " WHERE product = ? AND status = 'pending' AND substr(error, 1, ?) = ?",
                (now, product, len(reason_prefix), reason_prefix),
            ).rowcount

    def publish_dry_runs(self, product: str) -> int:
        """Пробные карточки товара (dry_run, готовы) → в очередь на настоящую выкладку: флаг dry_run снимается,
        пробный результат Ozon убирается; принт и галерея остаются — повторно не генерируются."""
        now = _iso(_now())
        with self._lock, self._conn() as db:
            return db.execute(
                "UPDATE jobs SET status = 'pending', stage = 'queued', error = NULL, finished_at = NULL, attempts = 0,"
                " available_at = NULL, updated_at = ?, payload = json_set(payload, '$.dry_run', json('false')),"
                " result = json_remove(result, '$.ozon')"
                " WHERE product = ? AND status = 'done' AND json_extract(payload, '$.kind') = 'card'"
                " AND json_extract(payload, '$.dry_run') = 1",
                (now, product),
            ).rowcount

    def recover_interrupted(self, *, max_attempts: int, product: str | None = None) -> int:
        """После перезапуска running-задачи товара возвращаются в очередь (или падают по лимиту попыток)."""
        now = _iso(_now())
        only = " AND product = ?" if product else ""
        tail = (product,) if product else ()
        with self._conn() as db:
            db.execute(
                "UPDATE jobs SET status = 'failed', stage = 'failed', finished_at = ?, updated_at = ?,"
                " error = 'Превышено число попыток после перезапуска воркера'"
                " WHERE status = 'running' AND attempts >= ?" + only,
                (now, now, max_attempts, *tail),
            )
            return db.execute(
                "UPDATE jobs SET status = 'pending', stage = 'queued', updated_at = ? WHERE status = 'running'" + only,
                (now, *tail),
            ).rowcount

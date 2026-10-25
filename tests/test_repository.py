from __future__ import annotations

import sqlite3
import unittest

from support import TempDir, new_repository

from printflow.domain.models import JobStatus
from printflow.migrations.runner import SchemaOutdated, latest_version, migrate, migration_files, reserve_numbers
from printflow.repositories.jobs import JobRepository


class JobRepositoryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = TempDir()
        self.repo = new_repository(self.tmp.__enter__())


    def test_one_running_job_per_theme(self) -> None:
        """Тематика — по одному принту за раз; другие тематики и задачи без тематики не ждут."""
        def make(product, theme_key=None):
            payload = {"kind": "card", **({"theme_key": theme_key} if theme_key else {})}
            return self.repo.create(product=product, payload=payload)[0]

        cats1, cats2, space1 = make("mousepad", "cats"), make("mousepad", "cats"), make("mousepad", "space")
        plain, shopper_cats = make("mousepad"), make("shopper", "cats")
        taken = [self.repo.claim_next("mousepad").id for _ in range(3)]
        self.assertEqual(taken, [cats1.id, space1.id, plain.id])  # второй кот ждёт первого
        self.assertIsNone(self.repo.claim_next("mousepad"))
        self.assertEqual(self.repo.claim_next("shopper").id, shopper_cats.id)  # у другого товара своя очередь
        self.repo.complete(cats1.id, {})
        self.assertEqual(self.repo.claim_next("mousepad").id, cats2.id)

    def test_drawn_titles_by_theme(self) -> None:
        """Уже нарисованное в тематике: только свой товар и своя тематика, с описанием рисунка."""
        def made(product, theme_key, title):
            job, _ = self.repo.create(product=product, payload={"kind": "card", "theme_key": theme_key})
            if title:
                self.repo.save_progress(job.id, stage="named", result={"design_name": title})

        made("mousepad", "cats", "кот в коробке")
        made("mousepad", "cats", None)
        made("mousepad", "space", "комета")
        made("shopper", "cats", "кот шоппера")
        self.assertEqual(self.repo.drawn_titles("mousepad", "cats", 10), ["кот в коробке"])
    def tearDown(self) -> None:
        self.tmp.__exit__()

    def test_lifecycle(self) -> None:
        job, created = self.repo.create(product="shopper", payload={"theme": "x"}, external_id="ext-1")
        self.assertTrue(created)
        self.assertEqual((job.number, job.status), (1, JobStatus.PENDING))
        again, created = self.repo.create(product="shopper", payload={"theme": "y"}, external_id="ext-1")
        self.assertFalse(created)
        self.assertEqual(again.id, job.id)
        self.assertEqual(self.repo.claim_next().status, JobStatus.RUNNING)
        self.assertIsNone(self.repo.claim_next())
        self.repo.save_progress(job.id, stage="print_done", result={"print": "url"})
        self.repo.fail(job.id, "boom")
        retried = self.repo.reset_failed(job.id)
        self.assertEqual((retried.status, retried.attempts), (JobStatus.PENDING, 0))
        self.assertEqual(retried.result["print"], "url")  # результат сохранился для продолжения

    def test_group_slots_fill_then_new_group(self) -> None:
        slots = [self.repo.create(product="shopper", payload={"kind": "card"}, group_size=7)[0] for _ in range(9)]
        self.assertEqual([(j.group_id, j.group_position) for j in slots],
                         [(1, p) for p in range(1, 8)] + [(2, 1), (2, 2)])
        hires, _ = self.repo.create(product="shopper", payload={"kind": "hires"})  # перерисовка места в группе не занимает
        self.assertIsNone(hires.group_id)
        self.assertEqual(self.repo.create(product="shopper", payload={"kind": "card"}, group_size=7)[0].group_position, 3)
        again, created = self.repo.create(product="shopper", payload={"kind": "card"}, external_id="x", group_size=7)
        same, created2 = self.repo.create(product="shopper", payload={"kind": "card"}, external_id="x", group_size=7)
        self.assertEqual((created2, same.group_position), (False, again.group_position))  # повтор — то же место

    def test_create_many_in_order_with_duplicates(self) -> None:
        self.repo.create(product="shopper", payload={"kind": "card"}, external_id="old", numbered=True, group_size=7)
        items = [({"kind": "card"}, f"e{i}") for i in range(8)] + [({"kind": "card"}, "old"), ({"kind": "card"}, "e0")]
        result = self.repo.create_many(items, product="shopper", numbered=True, group_size=7)
        self.assertEqual([created for _, created in result], [True] * 8 + [False, False])
        jobs = [job for job, _ in result]
        self.assertEqual([j.design_number for j in jobs[:8]], list(range(2, 10)))  # по порядку пачки
        self.assertEqual([(j.group_id, j.group_position) for j in jobs[:8]],
                         [(1, p) for p in range(2, 8)] + [(2, 1), (2, 2)])
        self.assertEqual((jobs[8].design_number, jobs[9].id), (1, jobs[0].id))  # дубли — те же задачи

    def test_create_many_rolls_back_whole_batch(self) -> None:
        with self.assertRaises(TypeError):
            self.repo.create_many([({"kind": "card"}, "a"), ({"bad": object()}, "b")], product="shopper", numbered=True,
                                  group_size=7)
        self.assertIsNone(self.repo.get_by_external_id("a"))
        self.assertEqual(self.repo.create(product="shopper", payload={"kind": "card"}, numbered=True)[0].design_number, 1)  # номер не потерян

    def test_short_jobs_claimed_before_cards(self) -> None:
        old_card = self.repo.create(product="shopper", payload={"theme": "без kind — старая карточка"})[0]
        card = self.repo.create(product="shopper", payload={"kind": "card"})[0]
        cert = self.repo.create(product="shopper", payload={"kind": "certificate"})[0]
        hires = self.repo.create(product="shopper", payload={"kind": "hires"})[0]
        claimed = [self.repo.claim_next().id for _ in range(4)]
        self.assertEqual(claimed, [cert.id, hires.id, old_card.id, card.id])

    def test_requeue_waits_until_available(self) -> None:
        job, _ = self.repo.create(product="shopper", payload={"theme": "x"})
        self.repo.claim_next()
        self.repo.requeue(job.id, error="timeout", delay_sec=3600)
        self.assertIsNone(self.repo.claim_next())  # пауза ещё не прошла
        self.repo.requeue(job.id, error="timeout", delay_sec=0)
        self.assertEqual(self.repo.claim_next().id, job.id)

    def test_recover_interrupted(self) -> None:
        job, _ = self.repo.create(product="shopper", payload={"theme": "x"})
        self.repo.claim_next()
        self.assertEqual(self.repo.recover_interrupted(max_attempts=3), 1)
        self.assertEqual(self.repo.get(job.id).status, JobStatus.PENDING)
        for _ in range(3):
            self.repo.claim_next()
            self.repo.recover_interrupted(max_attempts=3)
        self.assertEqual(self.repo.get(job.id).status, JobStatus.FAILED)

    def test_design_numbers_sequential_from_first_number(self) -> None:
        with TempDir() as tmp:
            path = tmp / "jobs.db"
            migrate(path)
            self.assertEqual(reserve_numbers(path, "shopper", 1001), 1001)
            repo = JobRepository(path, timeout_sec=30)
            first = repo.create(product="shopper", payload={"kind": "card"}, numbered=True)[0]
            hires = repo.create(product="shopper", payload={"kind": "hires"})[0]  # перерисовка номер дизайна не занимает
            second = repo.create(product="shopper", payload={"kind": "card"}, numbered=True)[0]
            again = repo.create(product="shopper", payload={"kind": "card"}, external_id="x", numbered=True)[0]
            same = repo.create(product="shopper", payload={"kind": "card"}, external_id="x", numbered=True)[0]  # повтор — тот же номер
            self.assertEqual((first.design_number, hires.design_number, second.design_number), (1001, None, 1002))
            self.assertEqual((again.design_number, same.design_number), (1003, 1003))
            self.assertEqual(reserve_numbers(path, "shopper", 1), 1004)  # счётчик не откатывается назад

    def test_repository_refuses_outdated_schema(self) -> None:
        with TempDir() as tmp:
            with self.assertRaises(SchemaOutdated):
                JobRepository(tmp / "missing.db", timeout_sec=30)
            path = tmp / "v1.db"
            db = sqlite3.connect(path)
            db.executescript(migration_files()[0].read_text(encoding="utf-8"))
            db.close()
            with self.assertRaises(SchemaOutdated):
                JobRepository(path, timeout_sec=30)  # миграция 0002 не применена
            self.assertEqual(migrate(path), [f.name for f in migration_files()[1:]])
            self.assertEqual(migrate(path), [])  # повторный запуск ничего не делает
            JobRepository(path, timeout_sec=30)

    def test_migrates_database_created_before_migrations(self) -> None:
        with TempDir() as tmp:
            path = tmp / "old.db"
            db = sqlite3.connect(path)
            db.executescript(migration_files()[0].read_text(encoding="utf-8"))  # схема до миграций, user_version = 0
            db.execute("INSERT INTO jobs (id, status, payload, created_at, updated_at)"
                       " VALUES ('a', 'pending', '{\"kind\": \"card\"}', 't', 't')")
            db.commit()
            db.close()
            migrate(path)
            repo = JobRepository(path, timeout_sec=30)
            self.assertEqual(repo.get("a").number, 1)  # очередь на месте
            self.assertIsNone(repo.get("a").available_at)  # новая колонка добавлена
            check = sqlite3.connect(path)
            version = check.execute("PRAGMA user_version").fetchone()[0]
            check.close()
            self.assertEqual(version, latest_version())


if __name__ == "__main__":
    unittest.main()

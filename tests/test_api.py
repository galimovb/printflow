from __future__ import annotations

import unittest

from fastapi.testclient import TestClient
from support import TOKEN, TempDir, test_container

from printflow.api.app import create_app


class ApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = TempDir()
        app = create_app(test_container(cls.tmp.__enter__()), background=False)
        cls.client = TestClient(app)
        cls.headers = {"Authorization": f"Bearer {TOKEN}"}

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tmp.__exit__()

    def test_auth_required_and_health(self) -> None:
        self.assertEqual(self.client.post("/api/v1/shopper/jobs", json={}).status_code, 401)
        health = self.client.get("/api/v1/shopper/health")
        self.assertEqual(health.status_code, 200)
        self.assertIn("charset=utf-8", health.headers["content-type"])  # кириллица в PowerShell 5.1

    def test_card_job_idempotent(self) -> None:
        body = {"theme": "кот в очках", "external_id": "crm-42"}
        first = self.client.post("/api/v1/shopper/jobs", json=body, headers=self.headers)
        self.assertEqual(first.status_code, 202, first.text)
        job = first.json()
        self.assertEqual((job["payload"]["kind"], job["payload"]["colors"]), ("card", ["white", "black"]))
        self.assertIsNotNone(job["design_number"])  # сквозной номер выдан при постановке
        again = self.client.post("/api/v1/shopper/jobs", json=body, headers={"X-API-Key": TOKEN})
        self.assertEqual((again.status_code, again.json()["id"]), (200, job["id"]))
        self.assertEqual(self.client.get(f"/api/v1/shopper/jobs/{job['id']}", headers=self.headers).json()["number"],
                         job["number"])
        retry = self.client.post(f"/api/v1/shopper/jobs/{job['id']}/retry", headers=self.headers)
        self.assertEqual(retry.status_code, 409)

    def test_batch_jobs(self) -> None:
        jobs = [{"theme": f"пачка {i}", "external_id": f"batch-{i}"} for i in range(3)]
        first = self.client.post("/api/v1/shopper/jobs/batch", json={"jobs": jobs}, headers=self.headers)
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual((first.json()["created"], first.json()["existing"]), (3, 0))
        again = self.client.post("/api/v1/shopper/jobs/batch", json={"jobs": jobs[1:] + [{"theme": "новая"}]},
                                 headers=self.headers).json()
        self.assertEqual((again["created"], again["existing"]), (1, 2))
        self.assertEqual(again["jobs"][0]["id"], first.json()["jobs"][1]["id"])
        too_many = self.client.post("/api/v1/shopper/jobs/batch", json={"jobs": [jobs[0]] * 501}, headers=self.headers)
        self.assertEqual(too_many.status_code, 422)

    def test_reference_job_without_theme(self) -> None:
        body = {"reference_url": "https://ir.ozone.ru/s3/multimedia-1/123.jpg", "dry_run": True,
                "product_name": "Сумка-шоппер с принтом"}
        ok = self.client.post("/api/v1/shopper/jobs", json=body, headers=self.headers)
        self.assertEqual(ok.status_code, 202, ok.text)
        payload = ok.json()["payload"]
        self.assertEqual((payload["reference_url"], payload["product_name"]), (body["reference_url"], body["product_name"]))
        self.assertNotIn("design_label", payload)  # название принта не генерируется
        empty = self.client.post("/api/v1/shopper/jobs", json={"dry_run": True}, headers=self.headers)
        self.assertEqual(empty.status_code, 422)  # нужна тема или фото

    def test_hires_job(self) -> None:
        self.assertEqual(self.client.post("/api/v1/shopper/prints/TEE-000001/hires", headers=self.headers).status_code, 422)
        ok = self.client.post("/api/v1/shopper/prints/bag-000001/hires", headers=self.headers)
        self.assertEqual(ok.status_code, 202, ok.text)
        self.assertEqual(ok.json()["payload"], {"kind": "hires", "article": "BAG-000001"})
        again = self.client.post("/api/v1/shopper/prints/BAG-000001/hires", headers=self.headers)
        self.assertEqual(again.status_code, 200)
        grouped = self.client.post("/api/v1/shopper/prints/bag-0001-03/hires", headers=self.headers)
        self.assertEqual((grouped.status_code, grouped.json()["payload"]["article"]), (202, "BAG-0001-03"))

    def test_validation_and_filters(self) -> None:
        body = {"theme": "кот", "colors": ["red"]}
        self.assertEqual(self.client.post("/api/v1/shopper/jobs", json=body, headers=self.headers).status_code, 422)
        self.assertEqual(self.client.get("/api/v1/shopper/jobs?status=bad", headers=self.headers).status_code, 422)
        self.assertEqual(self.client.get("/api/v1/shopper/jobs/nope", headers=self.headers).status_code, 404)
        listed = self.client.get("/api/v1/shopper/jobs?status=pending", headers=self.headers)
        self.assertTrue(all(job["status"] == "pending" for job in listed.json()["jobs"]))


if __name__ == "__main__":
    unittest.main()

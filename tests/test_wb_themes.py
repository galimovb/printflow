import unittest
from unittest.mock import patch

from support import TempDir, new_repository


class ThemeRequestsTest(unittest.TestCase):
    def test_requests_go_waiting_parsing_queued_with_card_progress(self):
        with TempDir() as tmp:
            repo = new_repository(tmp)
            options = {"count": 20, "search": 50, "algorithm": "template_mockup", "colors": ["white", "black"]}
            first = repo.wb_theme_add(["лиса", "Лиса", "волк"], **options)
            self.assertEqual(len(first), 2)  # the same theme once
            self.assertEqual(repo.wb_theme_add(["волк", "медведь"], **options).__len__(), 1)  # волк still waits
            self.assertEqual(repo.wb_theme_stats()["лиса"]["request"], "waiting")

            claimed = repo.wb_theme_claim()
            self.assertEqual((claimed["theme"], claimed["colors"]), ("лиса", ["white", "black"]))
            self.assertTrue(repo.wb_theme_cancel(first[1]))  # волк was not taken yet
            self.assertFalse(repo.wb_theme_cancel(claimed["id"]))  # лиса is being parsed
            campaign, _ = repo.create({"kind": "wb_discover", "theme": "лиса", "config": {}}, product="tee_wb")
            card, _ = repo.create({"kind": "wb_card", "theme": "лиса", "campaign_id": campaign.id, "source": {"sku": "1"}},
                                  product="tee_wb")
            repo.complete(card.id, {"review_required": True, "approval": "approved"})
            self.assertTrue(repo.wb_theme_finish(claimed["id"], "queued", campaign_id=campaign.id, message="в работу 1"))
            self.assertFalse(repo.wb_theme_finish(claimed["id"], "failed"))  # only once
            rows = {r["theme"]: r for r in repo.wb_theme_requests()}
            self.assertEqual(rows["лиса"]["status"], "queued")
            self.assertEqual(rows["лиса"]["cards"], {"approved": 1})
            self.assertEqual(rows["медведь"]["status"], "waiting")
            self.assertNotIn("волк", rows)
            stats = repo.wb_theme_stats()["лиса"]
            self.assertEqual((stats["runs"], stats["done"], stats["on_wb"], stats["request"]), (1, 1, 0, None))

            self.assertIsNone(repo.wb_parser_state())
            repo.wb_parser_seen("медведь")
            self.assertEqual(repo.wb_parser_state()["current"], "медведь")

    def test_routes_add_claim_and_finish(self):
        from fastapi.testclient import TestClient

        from printflow.api.app import create_app
        from test_wb_studio import test_container

        auth = {"Authorization": "Bearer test"}
        with TempDir() as tmp:
            app = test_container(tmp)
            with patch("printflow.wb_studio.api.router.read_env", return_value={"PRINTFLOW_WB_API_TOKEN": "test"}):
                client = TestClient(create_app(app, background=False))
                self.assertEqual(client.get("/studio/wb/themes").status_code, 200)
                self.assertEqual(client.post("/api/v1/wb-studio/theme-requests", json={"themes": ["лиса"]}).status_code, 401)
                added = client.post("/api/v1/wb-studio/theme-requests", headers=auth, json={"themes": ["лиса", " "], "count": 5})
                self.assertEqual(added.json(), {"added": 1, "skipped": 0})
                listing = client.get("/api/v1/wb-studio/theme-requests", headers=auth).json()
                self.assertFalse(listing["parser"]["online"])
                request = client.post("/api/v1/wb-studio/parser/claim", headers=auth, json={}).json()["request"]
                self.assertEqual((request["theme"], request["count"], request["search"]), ("лиса", 5, 50))
                self.assertTrue(client.get("/api/v1/wb-studio/theme-requests", headers=auth).json()["parser"]["online"])
                done = client.post(f"/api/v1/wb-studio/theme-requests/{request['id']}/finish", headers=auth,
                                   json={"status": "empty", "message": "нет товаров"})  # fmt: skip
                self.assertEqual(done.status_code, 200)
                self.assertIsNone(client.post("/api/v1/wb-studio/parser/claim", headers=auth, json={}).json()["request"])
                catalog = client.get("/api/v1/wb-studio/theme-catalog", headers=auth).json()["themes"]
                self.assertTrue(catalog and all(t["listed"] for t in catalog))  # nothing run yet: the saved list only
                self.assertEqual(catalog[0]["runs"], 0)


class StudioSessionTest(unittest.TestCase):
    def test_jwt_is_signed_and_expires(self):
        from printflow.wb_studio.api import session

        key = session.signing_key({"PRINTFLOW_WB_API_TOKEN": "t"})
        token = session.issue(key, ttl=60, now=1000)
        self.assertTrue(session.valid(token, key, now=1059))
        self.assertFalse(session.valid(token, key, now=1061))  # expired
        self.assertFalse(session.valid(token, session.signing_key({"PRINTFLOW_WB_API_TOKEN": "other"}), now=1000))
        header, claims, signature = token.split(".")
        self.assertFalse(session.valid(f"{header}.{claims}x.{signature}", key, now=1000))  # tampered
        self.assertFalse(session.valid("garbage", key))
        self.assertEqual(session.signing_key({}), b"")  # no API token: nobody signs in

    def test_sign_in_once_then_the_cookie_opens_every_page_and_the_queue(self):
        from fastapi.testclient import TestClient

        from printflow.api.app import create_app
        from test_wb_studio import test_container

        with TempDir() as tmp:
            app = test_container(tmp)
            with patch("printflow.wb_studio.api.router.read_env", return_value={"PRINTFLOW_WB_API_TOKEN": "test"}):
                client = TestClient(create_app(app, background=False))
                for page in ("/studio/wb", "/studio/wb/queue", "/studio/wb/themes", "/studio/wb/review",
                             "/studio/wb/studio-common.js", "/studio/wb/studio.css"):
                    self.assertEqual(client.get(page).status_code, 200, page)
                self.assertEqual(client.get("/api/v1/wb-studio/queue").status_code, 401)
                self.assertEqual(client.post("/api/v1/wb-studio/session", json={"token": "wrong"}).status_code, 401)
                signed = client.post("/api/v1/wb-studio/session", json={"token": "test"})
                self.assertEqual(signed.status_code, 200)
                self.assertIn("httponly", signed.headers["set-cookie"].lower())
                queue = client.get("/api/v1/wb-studio/queue?view=all").json()  # the cookie is enough now
                self.assertEqual((queue["rows"], queue["running"]), ([], 0))
                client.post("/api/v1/wb-studio/session/end")
                self.assertEqual(client.get("/api/v1/wb-studio/queue").status_code, 401)


class RetryJobsTest(unittest.TestCase):
    def test_picked_failed_jobs_restart_and_the_rest_are_skipped(self):
        from fastapi.testclient import TestClient

        from printflow.api.app import create_app
        from test_wb_studio import test_container

        auth = {"Authorization": "Bearer test"}
        with TempDir() as tmp:
            app = test_container(tmp)
            repo = app.job_repository
            failed, _ = repo.create({"kind": "wb_card", "theme": "лиса"}, product="tee_wb", numbered=True)
            repo.fail(failed.id, "RuntimeError: credit_balance_exhausted")
            done, _ = repo.create({"kind": "wb_card", "theme": "кот"}, product="tee_wb", numbered=True)
            repo.complete(done.id, {})
            with patch("printflow.wb_studio.api.router.read_env", return_value={"PRINTFLOW_WB_API_TOKEN": "test"}):
                client = TestClient(create_app(app, background=False))
                answer = client.post("/api/v1/wb-studio/jobs/retry", json={"ids": [failed.id, done.id, "nope"]}, headers=auth)
            self.assertEqual(answer.status_code, 200)
            self.assertEqual(answer.json(), {"retried": [failed.id], "skipped": [done.id, "nope"]})
            again = repo.get(failed.id)
            self.assertEqual((again.status.value, again.attempts, again.error), ("pending", 0, None))
            self.assertEqual(repo.get(done.id).status.value, "done")


class JobDetailTest(unittest.TestCase):
    def test_card_detail_shows_source_decisions_frames_wb_and_cost(self):
        import json
        import os

        from fastapi.testclient import TestClient

        from printflow.api.app import create_app
        from test_wb_studio import test_container

        auth = {"Authorization": "Bearer test"}
        with TempDir() as tmp:
            app = test_container(tmp)
            repo = app.job_repository
            card, _ = repo.create({"kind": "wb_card", "theme": "лиса", "config": {"algorithm": "template_mockup"},
                                   "source": {"sku": "1", "url": "https://wb/1", "images": ["https://p/1.jpg", "https://p/2.jpg"]}},
                                  product="tee_wb", numbered=True)  # fmt: skip
            repo.complete(card.id, {
                "analysis": {"print_source": 1, "audience": "female", "recolor": {"white": "none", "black": "tone"},
                             "photos": [{"index": 0, "role": "front", "whole_print": False}, {"index": 1, "role": "front", "whole_print": True}]},
                "print_variants": {"white": "https://s3/w.png"}, "print_checks": {"base": {"accepted": True, "text": "ЛИСА"}},
                "images": {"white": ["https://s3/1.jpg"]}, "text": {"title": "Футболка с лисой"},
                "vendor_codes": {"white": "TEE-1W"}, "review_required": True, "approval": "approved"})  # fmt: skip
            publication, _ = repo.create({"kind": "wb_publish", "card_ids": [card.id]}, product="tee_wb")
            repo.complete(publication.id, {"cards": {"TEE-1W": {"nmID": 555}}})
            log = os.path.join(tmp, "usage.jsonl")
            with open(log, "w", encoding="utf-8") as file:
                for purpose, cost in (("analysis", 0.01), ("frame", 0.02), ("frame", 0.02)):
                    file.write(json.dumps({"job": card.id, "purpose": purpose, "cost_usd": cost}) + "\n")
                file.write(json.dumps({"job": "other", "purpose": "frame", "cost_usd": 9}) + "\n")
            with patch("printflow.wb_studio.api.router.read_env", return_value={"PRINTFLOW_WB_API_TOKEN": "test"}), \
                    patch.dict(os.environ, {"PRINTFLOW_WB_USAGE_LOG": log}):  # fmt: skip
                client = TestClient(create_app(app, background=False))
                d = client.get(f"/api/v1/wb-studio/jobs/{card.id}/detail", headers=auth).json()
                self.assertEqual(d["source"]["print_source"], 1)
                self.assertFalse(d["source"]["roles"]["0"]["whole_print"])
                self.assertEqual(d["analysis"]["recolor"]["black"], "tone")
                self.assertEqual(d["checks"]["base"]["text"], "ЛИСА")
                self.assertEqual(d["publications"][0]["nm"], {"white": 555})
                self.assertEqual((d["usage"]["requests"], d["usage"]["total"]), (3, 0.05))
                self.assertEqual(d["usage"]["by_purpose"][0]["purpose"], "frame")
                pub = client.get(f"/api/v1/wb-studio/jobs/{publication.id}/detail", headers=auth).json()
                self.assertEqual(pub["cards"][0]["nm"], {"white": 555})
                self.assertEqual(client.get("/api/v1/wb-studio/jobs/none/detail", headers=auth).status_code, 404)

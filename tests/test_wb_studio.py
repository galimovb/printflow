"""standard algorithm, discovery, local runner, publication and routes."""

import asyncio
import copy
import io
import json
import unittest
from unittest.mock import AsyncMock, patch

from PIL import Image
from support import TempDir, new_repository, test_container
from support_mousepad import FakeStorage

from printflow.domain.errors import PermanentError, RetryLater
from printflow.wb_studio.application.studio import Studio
from printflow.wb_studio.config import load_config
from printflow.wb_studio.domain import prompts
from printflow.wb_studio.infrastructure.generation import Generator
from printflow.wb_studio.infrastructure.wb.publisher import Publisher
from printflow.wb_studio.infrastructure.wb.search import normalize_cards

GENERATOR = "printflow.wb_studio.application.studio.Generator"


def image():
    out = io.BytesIO()
    Image.new("RGB", (1200, 1600), "white").save(out, format="PNG")
    return out.getvalue()


class Images:
    """Fake generator for the standard algorithm; records every paid call."""

    def __init__(self):
        self.calls = []
        self.products = {}
        self.fail = False

    async def extract(self, source, theme):
        self.calls.append("extract")
        return image()

    async def describe(self, art, theme):
        self.calls.append("describe")
        return {"title": "Футболка с принтом лиса", "description": "Рисунок лисы"}

    async def adapt_print(self, art, color):
        self.calls.append(("adapt", color))
        return image()

    async def standard_photo(self, art, product, color, index, white_scene=None):
        if self.fail and index == 2:
            raise RuntimeError("transient")
        self.calls.append((color, index, white_scene is not None))
        self.products[color, index] = product
        return image()


def one_source(sku="123"):
    async def search(query, limit):
        return [{"sku": sku, "image": "https://basket.test/a.jpg", "rank": 1}]

    return search


async def fetch_image(url):
    return image()


class StandardPipelineTest(unittest.TestCase):
    def test_hero_is_local_and_black_frames_repeat_the_white_scene(self):
        async def run():
            with TempDir() as tmp:
                repo = new_repository(tmp)
                storage = FakeStorage()
                generator = Images()
                studio = Studio(repo, storage, {}, search=one_source(), fetch=fetch_image)
                campaign, _ = studio.campaign(["лиса"], 10, ["white", "black"], 1)[0]
                result = await studio.discovery(campaign, lambda *_: None)
                job = repo.get(result["cards"][0]["id"])

                def save(stage, value):
                    repo.save_progress(job.id, stage=stage, result=value)

                with patch(GENERATOR, return_value=generator):
                    result = await studio.card(job, save)
                photos = [call for call in generator.calls if isinstance(call, tuple) and call[0] != "adapt"]
                self.assertEqual(sorted(photos), sorted((c, i, c == "black") for c in ("white", "black") for i in (1, 2, 3)))
                self.assertEqual([call for call in generator.calls if call[0] == "adapt"], [("adapt", "white"), ("adapt", "black")])
                self.assertEqual(set(result["hero_placement"]), {"white", "black"})
                self.assertEqual([len(result["images"][c]) for c in ("white", "black")], [6, 6])
                # The flat lay wears the hero shirt; lifestyle shots wear the straight reference.
                hero = await storage.get("tee-mockups", f"printflow-wb/{job.id}/white/01.png")
                self.assertEqual(generator.products["white", 3], hero)
                self.assertNotEqual(generator.products["white", 1], hero)

        asyncio.run(run())

    def test_resume_never_repeats_paid_images(self):
        async def run():
            with TempDir() as tmp:
                repo = new_repository(tmp)
                generator = Images()
                studio = Studio(repo, FakeStorage(), {}, search=one_source(), generator=generator, fetch=fetch_image)
                campaign, created = studio.campaign(["лиса", "лиса"], 10, ["white"])[0]
                self.assertTrue(created)
                self.assertFalse(studio.campaign(["лиса"], 10, ["white"])[0][1])
                result = await studio.discovery(campaign, lambda *_: None)
                again = await studio.discovery(campaign, lambda *_: None)
                self.assertEqual(result["cards"][0]["id"], again["cards"][0]["id"])
                job = repo.get(result["cards"][0]["id"])

                def save(stage, value):
                    repo.save_progress(job.id, stage=stage, result=value)

                generator.fail = True
                with self.assertRaises(RuntimeError):
                    await studio.card(job, save)
                generator.fail = False
                result = await studio.card(repo.get(job.id), save)
                self.assertEqual(generator.calls.count("extract"), 1)
                self.assertEqual(generator.calls.count("describe"), 1)
                photos = [call for call in generator.calls if isinstance(call, tuple) and call[0] != "adapt"]
                self.assertEqual(sorted(photos), [("white", 1, False), ("white", 2, False), ("white", 3, False)])
                self.assertEqual(len(result["images"]["white"]), 6)
                self.assertRegex(result["vendor_codes"]["white"], r"^TEE-\d{9}-100W$")
                self.assertTrue(all("printflow-wb/" in url for url in result["images"]["white"]))
                self.assertNotIn("wb", result)  # publication never happens during generation

        asyncio.run(run())

    def test_information_slides_are_prebuilt(self):
        from printflow.wb_studio.infrastructure.rendering.info_slides import INFORMATION_DIR, info_slide

        builder = "printflow.wb_studio.infrastructure.rendering.info_slides.build_info_slide"
        with patch(builder, side_effect=AssertionError("Do not rebuild for each card")):
            self.assertEqual(info_slide(4, "white", load_config()), (INFORMATION_DIR / "white/05-fit.png").read_bytes())
        with patch(f"{builder.rsplit('.', 1)[0]}.INFORMATION_DIR", new=INFORMATION_DIR / "missing"):
            with self.assertRaises(RetryLater):
                info_slide(5, "black", load_config())


class StandardGeneratorTest(unittest.TestCase):
    def test_follow_up_photo_sends_the_finished_shirt_first(self):
        calls = []

        async def edit(files, prompt, **options):
            calls.append(([name for name, *_ in files], prompt, options))
            return image()

        async def run():
            generator = Generator({}, load_config())
            generator.edit = edit
            await generator.standard_photo(image(), b"shirt", "white", 1)
            await generator.standard_photo(image(), b"hero", "black", 3, white_scene=b"scene")

        asyncio.run(run())
        self.assertEqual(calls[0][0], ["main-product.png", "artwork.png"])
        self.assertEqual(calls[1][0], ["main-product.png", "artwork.png", "same-scene-white-shirt.png"])
        self.assertIn("lounging naturally in a chair", calls[0][1])
        self.assertIn("outfit flat-lay", calls[1][1])
        self.assertTrue(all("Keep the same print 1:1" in call[1] for call in calls))
        self.assertTrue(all(call[2] == {"request_timeout": 180} for call in calls))

    def test_lifestyle_prompts_keep_regular_fit(self):
        for index in (1, 2):
            prompt = prompts.standard_model_prompt("white", index)
            self.assertIn("standard regular fit", prompt)
            self.assertIn("slightly closer", prompt)
            self.assertIn("No oversized or boxy silhouette", prompt)
            self.assertIn("wide-leg baggy", prompt)
            self.assertIn("adults aged 18–25", prompt)
        self.assertNotEqual(prompts.standard_model_prompt("white", 1), prompts.standard_model_prompt("white", 2))

    def test_color_adaptation_uses_original_ozon_tee_prompts(self):
        from server.prompts import products_import_extract_print_prompt

        sent = []

        async def edit(files, prompt, **_):
            sent.append(prompt)
            return image()

        async def run():
            generator = Generator({}, load_config())
            generator.edit = edit
            with patch("printflow.wb_studio.infrastructure.generation.finalize_print", side_effect=lambda raw: raw):
                for color in ("white", "black"):
                    await generator.adapt_print(image(), color)

        asyncio.run(run())
        self.assertEqual(sent, [products_import_extract_print_prompt(shirt_color=c) for c in ("white", "black")])

    def test_moderation_is_permanent_and_request_id_is_kept(self):
        import httpx
        from openai import BadRequestError

        from printflow.wb_studio.infrastructure.errors import generation_errors

        @generation_errors
        async def rejected():
            request = httpx.Request("POST", "https://example.test/images")
            response = httpx.Response(400, request=request, headers={"x-request-id": "req_test"})
            raise BadRequestError("rejected", response=response, body={"code": "moderation_blocked"})

        with self.assertRaisesRegex(PermanentError, "moderation_blocked.*req_test"):
            asyncio.run(rejected())


class LocalRunnerTest(unittest.TestCase):
    def test_failure_continues_and_resume_repeats_only_transient_work(self):
        from printflow.wb_studio.infrastructure.local import generate

        class FailingImages(Images):
            async def extract(self, source, theme):
                self.calls.append("extract:" + theme)
                if theme == "blocked":
                    raise PermanentError("moderation_blocked")
                return image()

        async def search(query, limit):
            return [{"sku": "123" if query == "blocked" else "456", "image": "https://basket.test/a.jpg", "rank": 1}]

        async def run():
            with TempDir() as tmp:
                generator = FailingImages()
                generator.fail = True
                body = {"themes": ["blocked", "valid"], "limit": 10, "colors": ["white"]}
                env = {"PRINTFLOW_WB_MAX_ATTEMPTS": "1", "PRINTFLOW_WB_QUEUE_POLL_SEC": ".01"}
                first = await generate(body, tmp, env, generator=generator, search=search, fetch=fetch_image)
                self.assertEqual(first, [])
                errors = json.loads((tmp / "errors.json").read_text(encoding="utf-8"))
                self.assertEqual([e["retryable"] for e in errors], [False, True])
                generator.fail = False
                result = await generate(body, tmp, env, generator=generator, search=search, fetch=fetch_image)
                self.assertEqual(len(result), 1)
                self.assertEqual(generator.calls.count("extract:blocked"), 1)
                self.assertEqual(generator.calls.count("extract:valid"), 1)
                self.assertEqual(generator.calls.count(("white", 1, False)), 1)
                self.assertIn("moderation_blocked", (tmp / "gallery.html").read_text(encoding="utf-8"))

        asyncio.run(run())

    def test_standalone_generation_needs_no_server_s3_or_wb_and_resumes(self):
        from printflow.wb_studio.infrastructure.local import generate

        async def run():
            with TempDir() as tmp:
                generator = Images()
                body = {"themes": ["лиса"], "limit": 10, "design_limit": 1, "colors": ["white"]}
                with patch("httpx.AsyncClient", side_effect=AssertionError("No real HTTP in local test")):
                    result = await generate(body, tmp, {}, generator=generator, search=one_source(), fetch=fetch_image)
                    calls = list(generator.calls)
                    await generate(body, tmp, {}, generator=generator, search=one_source(), fetch=fetch_image)
                self.assertEqual(generator.calls, calls)
                self.assertEqual(len(result), 1)
                self.assertTrue((tmp / "gallery.html").is_file())
                self.assertTrue((tmp / "results.json").is_file())
                self.assertTrue(all(url.startswith("file:") for url in result[0]["result"]["images"]["white"]))

        asyncio.run(run())


class DiscoveryTest(unittest.TestCase):
    def test_pilot_discovers_ten_but_enqueues_one_card(self):
        async def run():
            with TempDir() as tmp:

                async def search(query, limit):
                    self.assertEqual(limit, 10)
                    return [{"sku": str(i), "image": "https://basket.test/a.jpg", "rank": i} for i in range(1, 11)]

                studio = Studio(new_repository(tmp), FakeStorage(), {}, search=search)
                job, _ = studio.campaign(["футболка с лисой"], 10, ["white"], design_limit=1)[0]
                result = await studio.discovery(job, lambda *_: None)
                self.assertEqual(len(result["sources"]), 10)
                self.assertEqual(len(result["cards"]), 1)

        asyncio.run(run())

    def test_parser_catalog_envelopes_and_persistent_profile(self):
        from printflow.wb_studio.infrastructure.wb.catalog import catalog_cards
        from printflow.wb_studio.infrastructure.wb.search import browser_options

        products = [
            {"id": 155420906, "subjectId": 192, "name": "Футболка", "supplierId": 123},
            {"id": 10, "subjectId": 1, "name": "Обувь"},
        ]
        for envelope in ({"products": products}, {"data": {"products": products}}, {"result": {"products": products}}):
            cards = catalog_cards(envelope)
            self.assertEqual(len(cards), 1)
            self.assertEqual(
                cards[0]["image"], "https://basket-10.wbbasket.ru/vol1554/part155420/155420906/images/big/1.webp"
            )
        with TempDir() as tmp:
            options = browser_options({"PRINTFLOW_WB_BROWSER_PROFILE": str(tmp), "PRINTFLOW_WB_HEADLESS": "0"})
            self.assertEqual(options["user_data_dir"], str(tmp.resolve()))
            self.assertFalse(options["headless"])
            self.assertEqual(options["timezone_id"], "Europe/Moscow")

    def test_search_order_deduplicates_without_inventing_products(self):
        raw = [
            {"url": "https://www.wildberries.ru/catalog/123/detail.aspx", "image": "https://basket.test/a.jpg", "title": "Лиса"},
            {"url": "https://www.wildberries.ru/catalog/123/detail.aspx", "image": "https://basket.test/b.jpg"},
            {"url": "/advertising", "image": "https://basket.test/c.jpg"},
            {"url": "https://www.wildberries.ru/catalog/124/detail.aspx", "image": "https://basket.test/d.jpg"},
        ]  # fmt: skip
        result = normalize_cards(raw, 20)
        self.assertEqual([x["sku"] for x in result], ["123", "124"])
        self.assertEqual([x["rank"] for x in result], [1, 2])

    def test_delayed_wb_challenge_is_not_empty_search(self):
        from printflow.wb_studio.infrastructure.wb.search import access_is_pending, wait_for_access

        self.assertTrue(access_is_pending("", "...", 498))
        self.assertTrue(access_is_pending("Подозрительная активность. Новая попытка через 00:46"))
        self.assertFalse(access_is_pending("Футболки " + ("товары " * 30), "Каталог", 498))

        class Page:
            def __init__(self, texts):
                self.texts = iter(texts)

            def locator(self, _):
                return self

            async def inner_text(self, **kwargs):
                return next(self.texts)

            async def title(self):
                return "Каталог"

        async def run():
            with patch("printflow.wb_studio.infrastructure.wb.search.asyncio.sleep", new_callable=AsyncMock):
                await wait_for_access(Page(["Подозрительная активность", "Товары", "Товары"]), False, seconds=4)
                with self.assertRaisesRegex(PermanentError, "ограничение доступа"):
                    await wait_for_access(Page(["Подозрительная активность"] * 3), False, seconds=4)
                with self.assertRaisesRegex(PermanentError, "wb_session"):
                    await wait_for_access(Page(["Подозрительная активность"]), True)

        asyncio.run(run())


class PublicationTest(unittest.TestCase):
    def test_new_only_publication_and_media_order_are_idempotent(self):
        async def run():
            config = load_config()
            config.update(
                price=1200,
                characteristics=[{"id": 1, "value": ["test"]}],
                sizes=[{"techSize": "L", "wbSize": "50"}],
                dimensions={"length": 30, "width": 25, "height": 2, "weightBrutto": 0.2},
            )
            draft = {
                "config": config,
                "text": {"title": "Футболка", "description": "Принт"},
                "images": {"white": ["https://s3/1.jpg", "https://s3/2.jpg"]},
                "vendor_codes": {"white": "TEE-000000001-100W"},
            }
            calls = []
            created = False

            async def request(path, body):
                nonlocal created
                calls.append((path, copy.deepcopy(body)))
                if path.endswith("/list"):
                    return {"cards": [{"vendorCode": "TEE-000000001-100W", "nmID": 123, "imtID": 12}] if created else []}
                if path.endswith("/barcodes"):
                    return {"data": ["barcode"]}
                if path.endswith("/upload"):
                    created = True
                return {"error": False}

            state = {}

            def save(value):
                state.clear()
                state.update(copy.deepcopy(value))

            publisher = Publisher("test", request)
            with patch("printflow.wb_studio.infrastructure.wb.publisher.asyncio.sleep", return_value=None):
                result = await publisher.publish(draft, {}, save)
                result = await publisher.publish(draft, result, save)
            self.assertTrue(result["complete"])
            self.assertEqual(sum(path.endswith("/upload") for path, _ in calls), 1)
            self.assertEqual(sum(path.endswith("/media/save") for path, _ in calls), 1)
            media = next(body for path, body in calls if path.endswith("/media/save"))
            self.assertEqual(media["data"], draft["images"]["white"])
            with self.assertRaises(PermanentError):
                await publisher.publish(draft, {}, save)
            self.assertFalse(any("/update" in path for path, _ in calls))

        asyncio.run(run())

    def test_studio_routes_require_token_and_no_automatic_publishing(self):
        from fastapi.testclient import TestClient

        from printflow.api.app import create_app

        auth = {"Authorization": "Bearer test"}
        with TempDir() as tmp:
            app = test_container(tmp)
            with patch("printflow.wb_studio.api.router.read_env", return_value={"PRINTFLOW_WB_API_TOKEN": "test"}):
                client = TestClient(create_app(app, background=False))
                self.assertEqual(client.get("/studio/wb").status_code, 200)
                self.assertEqual(client.get("/api/v1/wb-studio/jobs").status_code, 401)
                self.assertEqual(client.get("/api/v1/wb-studio/jobs", headers=auth).status_code, 200)
                self.assertEqual(client.get("/api/v1/wb-studio/themes", headers=auth).status_code, 200)
                invalid = client.post("/api/v1/wb-studio/campaigns", headers=auth, json={"themes": ["лиса"], "limit": 21})
                self.assertEqual(invalid.status_code, 422)
                imported = client.post(
                    "/api/v1/wb-studio/sources",
                    headers=auth,
                    json={
                        "theme": "футболка с лисой",
                        "sources": [
                            {
                                "url": "https://www.wildberries.ru/catalog/123/detail.aspx",
                                "image": "https://basket.test/1.jpg",
                                "title": "Лиса",
                            }
                        ],
                    },
                )
                self.assertEqual(imported.status_code, 200, imported.text)
                job = app.job_repository.get(imported.json()["id"])
                self.assertEqual(job.result["sort"], "imported")
                self.assertEqual(job.result["sources"][0]["sku"], "123")


if __name__ == "__main__":
    unittest.main()

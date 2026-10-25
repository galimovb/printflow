from __future__ import annotations

import asyncio
import base64
import io
import unittest
from contextlib import redirect_stdout
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from PIL import Image, ImageDraw
from fastapi.testclient import TestClient
from support import (
    SHOPPER, MOUSEPAD, FakeGallery, FakeStorage, FakeFetcher, FakePublisher,
    TempDir, product_settings, test_container,
)
from support_mousepad import FakeGenerator, print_png

from printflow.domain.errors import ShopperError
from printflow.domain.models import CardSpec
from printflow.services.cards.service import CardService
from printflow.services.printing.generator import ImagePrintGenerator
from printflow.api.app import create_app
from printflow.scripts import themes
from printflow.scripts._cli import Target


def generated_image() -> bytes:
    image = Image.new("RGB", (220, 180), "#90EE90")
    ImageDraw.Draw(image).rectangle((60, 40, 159, 139), fill=(210, 45, 70))
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


class SharedGeneratorTest(unittest.TestCase):
    def test_both_products_use_shared_generation_with_their_own_finish(self) -> None:
        for product in (SHOPPER, MOUSEPAD):
            with self.subTest(product=product.name):
                settings = replace(product_settings(product.env_prefix).openai, api_key="test-key")
                generator = product.generator(settings)
                self.assertIsInstance(generator, ImagePrintGenerator)
                response = SimpleNamespace(data=[SimpleNamespace(b64_json=base64.b64encode(generated_image()).decode())])
                generate = AsyncMock(return_value=response)
                # шоппер: сюжет сначала придумывает текстовая модель (она и видит уже нарисованное)
                chat = AsyncMock(return_value=SimpleNamespace(choices=[SimpleNamespace(
                    message=SimpleNamespace(content="a sleepy cat on a windowsill"))]))
                generator.client = SimpleNamespace(images=SimpleNamespace(generate=generate),
                                                   chat=SimpleNamespace(completions=SimpleNamespace(create=chat)))
                theme = product.themes["cats"]
                png = asyncio.run(generator.theme_print(theme, "коты с кофе", ["кот за компьютером"]))
                prompt = generate.call_args.kwargs["prompt"]
                if product.name == "mousepad":
                    self.assertIs(type(generator).theme_print, ImagePrintGenerator.theme_print)
                    self.assertIn("кот за компьютером", prompt)
                    self.assertIn("коты с кофе", prompt)
                else:  # в картинку — только придуманный сюжет, без списка повторов и направления
                    self.assertIn("кот за компьютером", chat.call_args.kwargs["messages"][0]["content"])
                    self.assertIn("Subject: a sleepy cat on a windowsill", prompt)
                    self.assertNotIn("кот за компьютером", prompt)
                    self.assertNotIn("коты с кофе", prompt)
                image = Image.open(io.BytesIO(png))
                if product.name == "shopper":
                    self.assertEqual(image.mode, "RGBA")
                    self.assertLess(image.width, 220)
                    self.assertIn("DTF", prompt)
                else:
                    self.assertEqual(image.mode, "RGB")
                    w, h = product.config["size_cm"]
                    self.assertAlmostEqual(image.width / image.height, w / h, places=2)
                    self.assertIn("edge to edge", prompt)
                    self.assertIn("Russian caption", prompt)
                generator.client.images.generate.reset_mock()
                asyncio.run(generator.preview_print("A cat with coffee"))
                self.assertIn("A cat with coffee", generate.call_args.kwargs["prompt"])

    def test_shared_naming_normalizes_and_rejects_invalid_results(self) -> None:
        for product in (SHOPPER, MOUSEPAD):
            settings = replace(product_settings(product.env_prefix).openai, api_key="test-key")
            generator = product.generator(settings)
            create = AsyncMock(return_value=SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='«Кот с кофе».'))]))
            generator.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
            self.assertEqual(asyncio.run(generator.name_print(generated_image())), "кот с кофе")
            create.return_value.choices[0].message.content = ""
            with self.assertRaises(ShopperError):
                asyncio.run(generator.name_print(generated_image()))

    def test_all_catalog_directions_are_usable(self) -> None:
        for product in (SHOPPER, MOUSEPAD):
            self.assertTrue(product.themes)
            for key, theme in product.themes.items():
                self.assertEqual(key, theme["key"])
                directions = [part.strip() for part in theme["known"].split(",") if part.strip()]
                self.assertTrue(directions)
                self.assertEqual(product.theme_direction(theme, len(directions)), directions[0])


class SubjectGenerator(FakeGenerator):
    """Генератор шоппера: сюжет придумывает текстовая модель, картинка — только по сюжету."""

    def __init__(self) -> None:
        super().__init__()
        self.subjects = iter(["a cat sleeping on a windowsill", "a cat chasing a feather"])
        self.drawn_seen: list[list[str]] = []

    async def pick_subject(self, theme: dict, drawn: list[str]) -> str:
        self.calls.append("subject")
        self.drawn_seen.append(list(drawn))
        return next(self.subjects)

    async def subject_print(self, theme: dict, subject: str) -> bytes:
        self.calls.append("theme")
        self.theme_args = (theme["key"], subject, [])
        return print_png()


class ShopperThemeServiceTest(unittest.TestCase):
    def test_history_is_saved_reused_and_isolated_from_mousepads(self) -> None:
        with TempDir() as tmp:
            container = test_container(tmp)
            repo = container.job_repository
            other, _ = repo.create(CardSpec(theme_key="cats").to_payload(), product="mousepad")
            repo.complete(other.id, {"design_name": "чужая коллекция", "subject": "чужой сюжет"})
            generator, publisher = SubjectGenerator(), FakePublisher()
            service = CardService(SHOPPER, FakeStorage(), generator, FakeGallery(), lambda: publisher,
                                  FakeFetcher(), drawn_titles=container.products["shopper"]._drawn_titles)
            job, _ = repo.create(CardSpec(theme_key="cats", theme_step=0, dry_run=True).to_payload(), product="shopper")
            save = lambda stage, result: repo.save_progress(job.id, stage=stage, result=result)
            result = asyncio.run(service.run(job, save))
            self.assertEqual(generator.calls, ["subject", "theme", "name"])
            self.assertEqual(generator.drawn_seen, [[]])  # чужой товар не в счёт
            self.assertEqual(result["subject"], "a cat sleeping on a windowsill")
            self.assertEqual(result["design_name"], "пастельные котики")
            self.assertEqual(len(result["ozon"]["offers"]), 2)
            self.assertEqual(publisher.items, [])
            self.assertEqual(repo.drawn_titles("shopper", "cats", 20, "subject"), ["a cat sleeping on a windowsill"])
            generator.calls.clear()
            asyncio.run(service.run(repo.get(job.id), save))
            self.assertEqual(generator.calls, [])  # повтор не генерирует и не описывает заново
            second, _ = repo.create(CardSpec(theme_key="cats", theme_step=1, dry_run=True,
                                             design_name="кот с гитарой").to_payload(), product="shopper")
            result = asyncio.run(service.run(second, lambda *_: None))
            self.assertEqual(generator.calls, ["subject", "theme"])
            self.assertEqual(generator.drawn_seen[-1], ["a cat sleeping on a windowsill"])  # видит прежний сюжет
            self.assertEqual(generator.theme_args[1], "a cat chasing a feather")
            self.assertEqual(result["design_name"], "кот с гитарой")


class ThemeBatchTest(unittest.TestCase):
    def test_same_cli_enqueues_themes_for_both_product_apis(self) -> None:
        for product in (SHOPPER, MOUSEPAD):
            with self.subTest(product=product.name), TempDir() as tmp:
                container = test_container(tmp)
                settings = container.products[product.name].settings
                target = Target(product, settings, container.settings)
                client = TestClient(create_app(container, background=False),
                                    headers={"Authorization": f"Bearer {settings.api.token}"})
                argv = ["themes", "--product", product.name, "--theme", "cats", "japan_asia",
                        "--count", "2", "--batch-size", "2", "--dry-run"]
                with patch.object(themes, "target", return_value=target), \
                     patch.object(themes.httpx, "Client", return_value=client), \
                     patch("sys.argv", argv), redirect_stdout(io.StringIO()):
                    self.assertEqual(themes.main(), 0)
                jobs = container.job_repository.list(product=product.name)
                self.assertEqual(len(jobs), 4)
                self.assertEqual({(j.payload["theme_key"], j.payload["theme_step"]) for j in jobs},
                                 {("cats", 0), ("japan_asia", 0), ("cats", 1), ("japan_asia", 1)})
                self.assertTrue(all(j.payload["dry_run"] for j in jobs))
                other = "mousepad" if product.name == "shopper" else "shopper"
                self.assertEqual(container.job_repository.list(product=other), [])

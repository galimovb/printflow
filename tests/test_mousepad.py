from __future__ import annotations

import asyncio
import io
import subprocess
import sys
import unittest
from pathlib import Path

import numpy as np
from fastapi.testclient import TestClient
from PIL import Image
from support import MOUSEPAD, TOKEN, TempDir, test_container
from support_mousepad import (
    QUAD,
    FakeFetcher,
    FakeGenerator,
    FakePublisher,
    FakeStorage,
    green_template,
    print_png,
    templates,
)

from printflow.products.mousepad.infrastructure.gallery.geometry import analyse_template, place_on_surface
from printflow.products.mousepad.infrastructure.gallery.renderer import SLIDES, PadGalleryRenderer
from printflow.products.mousepad.infrastructure.ozon_listing import build_items
from printflow.products.mousepad.infrastructure.print_generator import fit_surface
from printflow.api.app import create_app
from printflow.domain.models import CardSpec, MergeGroup
from printflow.migrations.runner import migrate
from printflow.repositories.jobs import JobRepository
from printflow.services.cards.service import CardService
from printflow.services.ozon.attributes import ATTR_COLOR_NAME, ATTR_MERGE_CARD, ATTR_SELLER_CODE

PRODUCT = MOUSEPAD.config
API_PREFIX = "/api/v1/mousepad"
ROOT = Path(__file__).resolve().parents[2]


class GeometryTest(unittest.TestCase):
    def test_finds_corners_despite_rounding_and_mouse(self) -> None:
        with TempDir() as tmp:
            path = tmp / "hero.png"
            green_template(path)
            alpha, quad = analyse_template(path)
        self.assertIsNotNone(quad)
        for found, true in zip(quad, QUAD):  # TL, TR, BR, BL
            self.assertLess(np.hypot(found[0] - true[0], found[1] - true[1]), 6, (quad, QUAD))
        self.assertEqual(float(alpha[860, 890]), 0.0)  # мышь поверх коврика не закрашивается принтом

    def test_print_fills_surface_only(self) -> None:
        with TempDir() as tmp:
            path = tmp / "hero.png"
            green_template(path, mouse=False)
            alpha, quad = analyse_template(path)
            out = np.asarray(place_on_surface(Image.open(path), Image.open(io.BytesIO(print_png())), quad, alpha))
        center = out[850, 600]
        self.assertLess(int(center[1]), 120)  # центр поверхности — принт, а не зелёный
        self.assertEqual(tuple(out[100, 100]), (226, 224, 232))  # стол не тронут
        green_left = (out[..., 1].astype(int) - np.maximum(out[..., 0], out[..., 2]).astype(int)) > 60
        self.assertLess(green_left.mean(), 0.001)  # ни зелёной поверхности, ни ореола

    def test_designed_pad_has_true_proportions(self) -> None:
        from printflow.products.mousepad.infrastructure.gallery.geometry import pad_outline

        quad, _ = pad_outline((22, 18), (1536, 2048), tilt=0, yaw=0, center=(0.5, 0.6), width=0.9)
        (x0, y0), (x1, _), (_, y2), _ = quad
        self.assertAlmostEqual((x1 - x0) / (y2 - y0), 22 / 18, places=3)  # вид сверху — ровно 22:18
        tl, tr, br, bl = pad_outline((22, 18), (1536, 2048), tilt=45, yaw=0, center=(0.5, 0.6), width=0.9)[0]
        self.assertLess(tr[0] - tl[0], br[0] - bl[0])  # дальний край короче ближнего

    def test_fit_surface_keeps_pad_aspect(self) -> None:
        buf = io.BytesIO()
        Image.new("RGB", (1536, 1024)).save(buf, format="PNG")
        w, h = Image.open(io.BytesIO(fit_surface(buf.getvalue(), (22, 18)))).size
        self.assertAlmostEqual(w / h, 22 / 18, places=2)


class GalleryTest(unittest.TestCase):
    def test_all_slides_in_order(self) -> None:
        with TempDir() as tmp:
            slides = PadGalleryRenderer(PRODUCT, templates(tmp)).render(print_png())
        self.assertEqual([name for name, _ in slides], [f"{i:02d}_{s}" for i, s in enumerate(SLIDES)])
        self.assertEqual(Image.open(io.BytesIO(slides[0][1])).size, tuple(PRODUCT["gallery"]["size"]))


class ListingTest(unittest.TestCase):
    def test_one_item_per_design_merged_by_group(self) -> None:
        items = build_items("MSE-000003", ["u1", "u2"], PRODUCT, "Коврик", MergeGroup("MSE-000001", 3, 14))
        self.assertEqual(len(items), 1)
        item = items[0]
        attrs = {a["id"]: a["values"] for a in item["attributes"]}
        self.assertEqual((item["offer_id"], item["description_category_id"], item["type_id"]),
                         ("MSE-000003", 18262715, 96808))
        self.assertEqual(attrs[ATTR_SELLER_CODE], [{"value": "MSE-000003"}])
        self.assertEqual(attrs[ATTR_MERGE_CARD], [{"value": "MSE-000001"}])
        self.assertEqual(attrs[ATTR_COLOR_NAME], [{"value": "03 разноцветный"}])
        self.assertEqual(item["images"], ["u1", "u2"])


class CardNameTest(unittest.TestCase):
    def test_name_from_design_or_fallback(self) -> None:
        group = MergeGroup("MSE-000001", 1, 14)
        named = build_items("MSE-000001", ["u"], PRODUCT, None, group, "японская волна")[0]
        plain = build_items("MSE-000001", ["u"], PRODUCT, None, group)[0]
        self.assertEqual(named["name"], "Коврик для мыши с принтом японская волна 24x20 см, 5 мм")
        self.assertEqual(plain["name"], "Коврик для мыши с принтом 24x20 см, 5 мм")
        self.assertNotIn("×", named["name"])  # Ozon выбрасывает «×» из названия

    def test_rich_content(self) -> None:
        """Rich-контент: шахматка с главным фото и заголовком по рисунку, затем блок про коллекцию."""
        import json

        item = build_items("MSE-000001", ["hero.jpg", "2.jpg"], PRODUCT, design="японская волна")[0]
        rich = json.loads(next(a for a in item["attributes"] if a["id"] == 11254)["values"][0]["value"])
        chess, block = rich["content"]
        self.assertEqual((chess["widgetName"], chess["type"], block["widgetName"]), ("raShowcase", "chess", "raTextBlock"))
        self.assertEqual(chess["blocks"][0]["img"]["src"], "hero.jpg")
        self.assertEqual(chess["blocks"][0]["title"]["items"][0]["content"], "ЯПОНСКАЯ ВОЛНА НА ВАШЕМ СТОЛЕ")


class CardServiceTest(unittest.TestCase):
    def test_print_gallery_publish(self) -> None:
        with TempDir() as tmp:
            migrate(tmp / "jobs.db")
            repo = JobRepository(tmp / "jobs.db", timeout_sec=30)
            storage, generator, publisher = FakeStorage(), FakeGenerator(), FakePublisher()
            service = CardService(MOUSEPAD, storage, generator, PadGalleryRenderer(PRODUCT, templates(tmp)),
                                  lambda: publisher, FakeFetcher(), merge_designs=14)
            job, _ = repo.create(CardSpec(reference_url="https://ozon/1.jpg").to_payload(), product="mousepad",
                                 numbered=True, group_size=14)
            stages: list[str] = []
            result = asyncio.run(service.run(job, lambda stage, _r: stages.append(stage)))
        self.assertEqual(result["article"], "MSE-000001")
        self.assertEqual(generator.calls, ["copy", "name"])  # принт, потом описание рисунка
        self.assertEqual(result["design_name"], "пастельные котики")
        self.assertEqual(publisher.items[0]["name"], "Коврик для мыши с принтом пастельные котики 24x20 см, 5 мм")
        self.assertEqual(len(result["images"]["main"]), len(SLIDES))
        self.assertTrue(result["images"]["main"][0].endswith("mse-mockups/MSE-000001/main/00_hero.jpg"))
        self.assertIn("mse-print/MSE-000001.png", storage.objects)
        self.assertEqual(result["ozon"]["offers"], ["MSE-000001"])
        self.assertEqual(result["merge_group"], "MSE-000001")
        self.assertEqual(stages[-1], "ozon_done")

    def test_theme_job_gets_direction_and_drawn(self) -> None:
        """Тематика: направление по кругу, уже нарисованное из базы, описание рисунка — вторым запросом."""
        with TempDir() as tmp:
            migrate(tmp / "jobs.db")
            repo = JobRepository(tmp / "jobs.db", timeout_sec=30)
            generator, publisher = FakeGenerator(), FakePublisher()
            drawn_for: list[str] = []
            service = CardService(MOUSEPAD, FakeStorage(), generator, PadGalleryRenderer(PRODUCT, templates(tmp)),
                                  lambda: publisher, FakeFetcher(), merge_designs=14,
                                  drawn_titles=lambda key: drawn_for.append(key) or ["кот в коробке"])
            job, _ = repo.create(CardSpec(theme_key="cats", theme_step=1).to_payload(), product="mousepad",
                                 numbered=True, group_size=14)
            result = asyncio.run(service.run(job, lambda *_: None))
        self.assertEqual(generator.calls, ["theme", "name"])
        key, direction, drawn = generator.theme_args
        self.assertEqual((key, drawn, drawn_for), ("cats", ["кот в коробке"], ["cats"]))
        self.assertEqual(direction, MOUSEPAD.theme_direction(MOUSEPAD.themes["cats"], 1))
        self.assertEqual(result["design_name"], "пастельные котики")

    def test_unknown_theme_is_permanent_error(self) -> None:
        from printflow.domain.errors import PermanentError

        with TempDir() as tmp:
            migrate(tmp / "jobs.db")
            repo = JobRepository(tmp / "jobs.db", timeout_sec=30)
            service = CardService(MOUSEPAD, FakeStorage(), FakeGenerator(),
                                  PadGalleryRenderer(PRODUCT, templates(tmp)), lambda: FakePublisher(), FakeFetcher())
            job, _ = repo.create(CardSpec(theme_key="nope").to_payload(), product="mousepad", numbered=True)
            with self.assertRaises(PermanentError):
                asyncio.run(service.run(job, lambda *_: None))

    def test_idea_with_design_name_skips_naming_request(self) -> None:
        """Идея уже несёт описание рисунка — второй запрос к текстовой модели не делается."""
        with TempDir() as tmp:
            migrate(tmp / "jobs.db")
            repo = JobRepository(tmp / "jobs.db", timeout_sec=30)
            generator, publisher = FakeGenerator(), FakePublisher()
            service = CardService(MOUSEPAD, FakeStorage(), generator, PadGalleryRenderer(PRODUCT, templates(tmp)),
                                  lambda: publisher, FakeFetcher(), merge_designs=14)
            spec = CardSpec(theme="A cat in a box. Style: flat vector.", design_name="кот в коробке")
            job, _ = repo.create(spec.to_payload(), product="mousepad", numbered=True, group_size=14)
            result = asyncio.run(service.run(job, lambda *_: None))
        self.assertEqual(generator.calls, ["preview"])
        self.assertEqual(publisher.items[0]["name"], "Коврик для мыши с принтом кот в коробке 24x20 см, 5 мм")


class ThemesTest(unittest.TestCase):
    def test_directions_cycle_and_captions_flag(self) -> None:
        cats = MOUSEPAD.themes["cats"]
        first = MOUSEPAD.theme_direction(cats, 0)
        count = len(cats["known"].split(","))
        self.assertEqual(MOUSEPAD.theme_direction(cats, count), first)
        self.assertTrue(cats.get("captions"))
        self.assertFalse(MOUSEPAD.themes["nature"].get("captions"))

    def test_prompt_text_rules(self) -> None:
        from printflow.products.mousepad.domain.prompts import theme_prompt

        with_caption = theme_prompt(MOUSEPAD.themes["office_humor"], "усталость", ["мозг в холодильнике"], (22, 18), 1.2)
        no_text = theme_prompt(MOUSEPAD.themes["nature"], "горы", [], (22, 18), 1.2)
        self.assertIn("Russian caption", with_caption)
        self.assertIn("мозг в холодильнике", with_caption)
        self.assertIn("No text at all", no_text)
        self.assertNotIn("Already drawn", no_text)
        self.assertIn("no stitching", no_text)


class ApiTest(unittest.TestCase):
    def test_batch_under_mousepad_prefix(self) -> None:
        with TempDir() as tmp:
            app = create_app(test_container(tmp), background=False)
            client = TestClient(app)
            headers = {"Authorization": f"Bearer {TOKEN}"}
            body = {"jobs": [{"reference_url": "https://ir.ozone.ru/1.jpg", "external_id": "ref:1"}]}
            res = client.post(f"{API_PREFIX}/jobs/batch", json=body, headers=headers)
            self.assertEqual(res.status_code, 200, res.text)
            job = client.get(f"{API_PREFIX}/jobs/{res.json()['jobs'][0]['id']}", headers=headers).json()
            self.assertEqual((job["design_number"], job["group_position"]), (1, 1))
            self.assertEqual(client.get(f"{API_PREFIX}/health").status_code, 200)
            shopper = client.get("/api/v1/shopper/health").json()["queue"]
            self.assertEqual(shopper, {})  # задача коврика не видна шопперам
            self.assertEqual(client.get("/api/v1/health").json()["queue"], {"pending": 1})
            themed = client.post(f"{API_PREFIX}/jobs/batch", json={"jobs": [{"theme_key": "space"}]}, headers=headers)
            self.assertEqual(themed.status_code, 200, themed.text)
            empty = client.post(f"{API_PREFIX}/jobs/batch", json={"jobs": [{}]}, headers=headers)
            self.assertEqual(empty.status_code, 422)


class IsolationTest(unittest.TestCase):
    def test_mousepad_needs_no_tee_core(self) -> None:
        """Коврики работают без модулей ядра футболок (их тянет только принт шоппера)."""
        code = (
            "import sys, printflow.products.mousepad.scripts.generate_blanks,"
            " printflow.products.mousepad.scripts.preview_gallery,"
            " printflow.products.mousepad.infrastructure.print_generator, printflow.container;"
            "print(' '.join(sorted(m for m in sys.modules if m == 'server' or m.startswith('server.'))))"
        )
        out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, check=True)
        self.assertEqual(out.stdout.split(), [])


if __name__ == "__main__":
    unittest.main()

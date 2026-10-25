from __future__ import annotations

import io
import re
import unittest

from PIL import Image
from support import SHOPPER, TempDir

from printflow.config import load_product_settings


TEE_WORDS = re.compile(r"t-?shirt|\bshirt\b|\bchest\b|\bsleeve", re.I)


class PromptTest(unittest.TestCase):
    def test_prompts_are_about_bags(self) -> None:
        from printflow.products.shopper.domain.prompts import hires_prompt, preview_prompt, reference_prompt

        for text in (preview_prompt("кот в очках", (26, 30)), hires_prompt("2880x2880", (26, 30)),
                     reference_prompt("", (26, 30))):
            self.assertNotRegex(text, TEE_WORDS)
            self.assertIn("tote bag", text)
            self.assertIn("#90EE90", text)


class FinalizePrintTest(unittest.TestCase):
    def test_chromakey_removed_and_cropped(self) -> None:
        from printflow.services.printing.chromakey import finalize_print, on_chromakey

        img = Image.new("RGB", (200, 200), (0x90, 0xEE, 0x90))
        img.paste((200, 20, 20), (50, 60, 150, 140))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        out = Image.open(io.BytesIO(finalize_print(buf.getvalue())))
        self.assertEqual(out.mode, "RGBA")
        self.assertLessEqual(abs(out.width - 100) + abs(out.height - 80), 4)
        clear = io.BytesIO()
        Image.new("RGBA", (10, 10), (0, 0, 0, 0)).save(clear, format="PNG")
        back = Image.open(io.BytesIO(on_chromakey(clear.getvalue()))).convert("RGB")
        self.assertEqual(back.getpixel((0, 0)), (0x90, 0xEE, 0x90))


class OzonListingTest(unittest.TestCase):
    def test_one_sku_per_color_merged_by_model_name(self) -> None:
        from printflow.products.shopper.infrastructure.ozon_listing import (
            ATTR_COLOR,
            ATTR_COLOR_NAME,
            ATTR_MERGE_CARD,
            ATTR_SELLER_CODE,
            ATTR_DESCRIPTION,
            build_items,
        )

        items = build_items("BAG-000007", {"white": ["https://x/1.jpg"], "black": ["https://x/2.jpg"]},
                            SHOPPER.config)
        self.assertEqual([i["offer_id"] for i in items], ["BAG-000007-W", "BAG-000007-B"])
        white, black = ({a["id"]: a["values"] for a in i["attributes"]} for i in items)
        self.assertEqual(items[0]["name"], "Шоппер с принтом, молочный")
        self.assertTrue(white[ATTR_DESCRIPTION][0]["value"].startswith("Шоппер с принтом из 100% хлопка."))
        self.assertEqual(white[ATTR_SELLER_CODE], [{"value": "BAG-000007-W"}])
        self.assertEqual(white[ATTR_COLOR][0]["value"], "молочный")
        self.assertEqual(white[ATTR_MERGE_CARD], black[ATTR_MERGE_CARD])
        fixed = build_items("BAG-000008", {"white": ["https://x/1.jpg"]}, SHOPPER.config,
                            product_name="Сумка-шоппер с принтом")
        self.assertEqual(fixed[0]["name"], "Сумка-шоппер с принтом")
        self.assertEqual(white[ATTR_MERGE_CARD], [{"value": "BAG-000007"}])  # без группы — дизайн отдельно
        self.assertEqual(white[ATTR_COLOR_NAME], [{"value": "молочный"}])

    def test_designs_of_one_group_share_card(self) -> None:
        from printflow.domain.models import MergeGroup
        from printflow.products.shopper.infrastructure.ozon_listing import ATTR_COLOR_NAME, ATTR_MERGE_CARD, build_items, color_variant_name

        rows = []
        for position in (1, 2):
            article = f"BAG-0001-{position:02d}"
            items = build_items(article, {"white": ["u"], "black": ["u"]}, SHOPPER.config,
                                group=MergeGroup("BAG-0001", position, 7))
            for item in items:
                attrs = {a["id"]: a["values"][0]["value"] for a in item["attributes"]}
                rows.append((item["offer_id"], attrs[ATTR_MERGE_CARD], attrs[ATTR_COLOR_NAME]))
        self.assertEqual(rows, [
            ("BAG-0001-01-W", "BAG-0001", "1 молочный"), ("BAG-0001-01-B", "BAG-0001", "1 черный"),
            ("BAG-0001-02-W", "BAG-0001", "2 молочный"), ("BAG-0001-02-B", "BAG-0001", "2 черный"),
        ])  # одна карточка, варианты не совпадают, оба цвета одного принта рядом
        self.assertEqual(color_variant_name("черный", MergeGroup("BAG-0002", 3, 14)), "03 черный")


class OzonPublisherTest(unittest.TestCase):
    def test_skipped_existing_product_is_accepted(self) -> None:
        import asyncio

        from printflow.services.ozon.client import OzonError
        from printflow.services.ozon.publisher import OzonPublisher

        def publisher(items):
            class FakeOzon:
                async def post(self, path, body):
                    if path == "/v3/product/import":
                        return {"result": {"task_id": 7}}
                    return {"result": {"items": items}}
            return OzonPublisher(FakeOzon(), SHOPPER.config, load_product_settings("SHOPPER").ozon)

        repeat = [{"offer_id": "BAG-000002-W", "product_id": 11, "status": "skipped", "errors": []},
                  {"offer_id": "BAG-000002-B", "product_id": 12, "status": "imported", "errors": []}]
        result = asyncio.run(publisher(repeat).publish([]))
        self.assertEqual((result["offers"], result["product_ids"]), (["BAG-000002-W", "BAG-000002-B"], [11, 12]))
        refused = [{"offer_id": "BAG-000001-W", "product_id": 0, "status": "skipped", "errors": []}]
        with self.assertRaises(OzonError):
            asyncio.run(publisher(refused).publish([]))


class GalleryTest(unittest.TestCase):
    def test_place_print_changes_zone_only(self) -> None:
        from printflow.products.shopper.infrastructure.gallery.geometry import place_print

        tpl = Image.new("RGB", (300, 400), (240, 240, 240))
        art = Image.new("RGBA", (100, 100), (200, 20, 20, 255))
        out = place_print(tpl, art, [[100, 100], [200, 100], [200, 220], [100, 220]], aspect=100 / 120, shade=0)
        self.assertEqual(out.size, tpl.size)
        self.assertEqual(out.getpixel((10, 10)), (240, 240, 240))
        self.assertGreater(out.getpixel((150, 160))[0], 150)

    def test_body_detected_and_zone_inside(self) -> None:
        from printflow.products.shopper.infrastructure.gallery.geometry import detect_body, print_zone

        with TempDir() as tmp:
            img = Image.new("RGB", (600, 800), (235, 235, 235))
            img.paste((30, 30, 30), (150, 300, 450, 640))  # корпус
            img.paste((30, 30, 30), (220, 100, 250, 300))  # ручка
            img.save(tmp / "black.png")
            body = detect_body("packshot", tmp)
        self.assertEqual([tuple(map(round, p)) for p in body], [(150, 300), (448, 300), (448, 638), (150, 638)])
        zone = print_zone(body, {"bag_cm": [34, 38], "print_top_cm": 3.5}, (26, 30))
        self.assertTrue(all(150 < x < 448 and 300 < y < 638 for x, y in zone))

    def test_renderer_on_real_templates(self) -> None:
        from printflow.products.shopper.infrastructure.gallery.renderer import SLIDES, GalleryRenderer

        art = io.BytesIO()
        Image.new("RGBA", (300, 340), (30, 90, 200, 255)).save(art, format="PNG")
        slides = GalleryRenderer(SHOPPER.config, SHOPPER.templates_dir).render(art.getvalue(), "black")
        names = [name for name, _ in slides]
        self.assertIn("01_main", names)
        self.assertEqual(names, sorted(names))
        self.assertTrue(set(n.split("_", 1)[1] for n in names) <= set(SLIDES))


if __name__ == "__main__":
    unittest.main()

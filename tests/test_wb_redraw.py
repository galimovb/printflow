"""source_redraw: gallery filter, one extracted print, parallel model photos."""

import asyncio
import io
import unittest
from unittest.mock import patch

from PIL import Image
from support import TempDir, new_repository
from support_mousepad import FakeStorage
from test_wb_studio import image

from printflow.domain.errors import PermanentError
from printflow.wb_studio.application.studio import Studio
from printflow.wb_studio.config import load_config
from printflow.wb_studio.domain.print_contrast import vanishing_ink
from printflow.wb_studio.domain.prompts import live_photo_prompt
from printflow.wb_studio.infrastructure.generation import Generator
from printflow.wb_studio.infrastructure.wb.search import NO_PHOTOS, validate_product_urls

PRODUCT_URL = "https://www.wildberries.ru/catalog/123/detail.aspx"
GENERATOR = "printflow.wb_studio.application.studio.Generator"
RESOLVER = "printflow.wb_studio.infrastructure.wb.search.resolve_product_urls"


def listing(count=1, complete=True, sku="123"):
    return {
        "sku": sku,
        "url": f"https://www.wildberries.ru/catalog/{sku}/detail.aspx",
        "image": "https://image.test/0.png",
        "gallery_complete": complete,
        "images": [f"https://image.test/{i}.png" for i in range(count)],
    }


class RedrawImages:
    """Fake generator: accepts everything unless told otherwise and records every paid call."""

    def __init__(self, selected=(0,), audience="male", accepted=True):
        self.calls = []
        self.selected = list(selected)
        self.audience = audience
        self.accepted = accepted
        self.reject_prints = False

    async def analyze_gallery(self, photos, theme):
        self.calls.append("analysis")
        frames = self.selected + [self.selected[0]] * (4 - len(self.selected))
        return {
            "accepted": self.accepted,
            "selected": frames,
            "print_source": self.selected[0],
            "filter": {"accepted": self.accepted, "reasons": [] if self.accepted else ["Не та тема"],
                       "original_selected": self.selected},
            "audience": self.audience,
            "text": {"title": "Футболка с принтом кот", "description": "Кот"},
        }  # fmt: skip

    async def extract_print(self, source, expected="", feedback=""):
        self.calls.append(("extract", feedback))
        return image()

    async def recolor_print(self, art, color, feedback=""):
        self.calls.append(("recolor", color))
        return image()

    async def verify_prints(self, source, prints, expected=""):
        self.calls.append(("verify", tuple(prints)))
        reason = "seller poster instead of actual ink" if self.reject_prints else ""
        return {key: {"accepted": not self.reject_prints, "reason": reason} for key in prints}

    async def live_photo(self, product, art, color, index, audience="unisex", pose=None):
        self.calls.append(("live", color, index, audience, pose is not None))
        return image()


def temporary_keys(studio):
    return [key for key in studio.storage.objects if key.startswith("tee-temporary-storage/")]


async def queued_card(tmp, sources):
    repo = new_repository(tmp)

    async def search(*_):
        return sources

    async def fetch(*_):
        return image()

    studio = Studio(repo, FakeStorage(), {}, search=search, fetch=fetch)
    root, _ = studio.campaign(["кот"], 20, design_limit=1, algorithm="source_redraw")[0]
    result = await studio.discovery(root, lambda *_: None)
    job = repo.get(result["cards"][0]["id"])

    def save(stage, value):
        repo.save_progress(job.id, stage=stage, result=value)

    return studio, repo, job, save


class RedrawPipelineTest(unittest.TestCase):
    def test_card_uses_twelve_requests_and_resume_repeats_none(self):
        async def run():
            with TempDir() as tmp:
                studio, repo, job, save = await queued_card(tmp, [listing(6)])
                generator = RedrawImages(selected=(0, 2))
                with patch(GENERATOR, return_value=generator):
                    result = await studio.card(job, save)
                    # analysis + extract + white recolor (white ink on white) + one check + 8 photos
                    self.assertEqual(len(generator.calls), 12)
                    await studio.card(repo.get(job.id), save)
                    self.assertEqual(len(generator.calls), 12)
                self.assertIn(("verify", ("base", "white")), generator.calls)
                self.assertNotIn(("recolor", "black"), generator.calls)
                live = [call for call in generator.calls if call[0] == "live"]
                self.assertEqual(len(live), 8)
                self.assertTrue(all(call[3] == "male" for call in live))
                self.assertEqual({call[2] for call in live if call[4]}, {0, 1})
                self.assertEqual([len(result["images"][c]) for c in ("white", "black")], [6, 6])
                self.assertEqual(len(result["source_photos"]), 6)
                self.assertEqual(set(result["print_variants"]), {"white", "black"})
                self.assertTrue(result["review_required"])
                # Seller photos and print candidates are deleted once the card is ready.
                self.assertTrue(result["temporary_removed"])
                self.assertFalse(temporary_keys(studio))
                self.assertTrue(any(key.startswith("tee-mockups/") for key in studio.storage.objects))

        asyncio.run(run())

    def test_rejected_print_is_retried_once_then_stops_before_photos(self):
        async def run():
            with TempDir() as tmp:
                studio, repo, job, save = await queued_card(tmp, [listing()])
                generator = RedrawImages()
                generator.reject_prints = True
                with patch(GENERATOR, return_value=generator), self.assertRaises(PermanentError):
                    await studio.card(job, save)
                saved = repo.get(job.id).result
                self.assertEqual(saved["print_attempts"]["base"], 2)
                self.assertIn(("extract", "seller poster instead of actual ink"), generator.calls)
                self.assertFalse(saved.get("print_variants"))
                self.assertNotIn("images", saved)
                self.assertFalse(any(call[0] == "live" for call in generator.calls))
                self.assertFalse(temporary_keys(studio))  # rejected cards never resume

        asyncio.run(run())

    def test_transient_failure_keeps_working_files_for_the_retry(self):
        class Unavailable(RedrawImages):
            async def live_photo(self, *args, **kwargs):
                raise RuntimeError("network")

        async def run():
            with TempDir() as tmp:
                studio, repo, job, save = await queued_card(tmp, [listing(3)])
                with patch(GENERATOR, return_value=Unavailable()), self.assertRaises(RuntimeError):
                    await studio.card(job, save)
                self.assertEqual(len([key for key in temporary_keys(studio) if "/sources/" in key]), 3)
                self.assertFalse(repo.get(job.id).result.get("temporary_removed"))

        asyncio.run(run())

    def test_rejected_source_is_saved_without_any_image_generation(self):
        async def run():
            with TempDir() as tmp:
                studio, repo, job, save = await queued_card(tmp, [listing(4)])
                generator = RedrawImages(accepted=False)
                with patch(GENERATOR, return_value=generator), self.assertRaises(PermanentError):
                    await studio.card(job, save)
                self.assertEqual(generator.calls, ["analysis"])
                self.assertEqual(repo.get(job.id).stage, "source_rejected")
                self.assertFalse(repo.get(job.id).result["source_filter"]["accepted"])

        asyncio.run(run())

    def test_incomplete_gallery_is_completed_before_analysis(self):
        async def resolve(urls):
            return [{"images": [f"https://image.test/{i}.png" for i in range(12)]}]

        async def run():
            with TempDir() as tmp, patch(RESOLVER, side_effect=resolve) as resolver:
                studio, repo, job, _ = await queued_card(tmp, [listing(1, complete=False)])
                self.assertEqual(resolver.call_count, 1)
                self.assertEqual(len(job.payload["source"]["images"]), 12)
                self.assertTrue(job.payload["source"]["gallery_complete"])

        asyncio.run(run())

    def test_product_without_photos_is_skipped_and_next_product_is_used(self):
        async def resolve(urls):
            if "/1/" in urls[0]:
                raise PermanentError(f"{NO_PHOTOS}: {urls[0]}")
            return [{"images": [f"https://image.test/2/{i}.png" for i in range(4)]}]

        async def run():
            with TempDir() as tmp, patch(RESOLVER, side_effect=resolve):
                sources = [listing(complete=False, sku="1"), listing(complete=False, sku="2")]
                studio, repo, job, _ = await queued_card(tmp, sources)
                self.assertEqual(job.payload["source"]["sku"], "2")
                self.assertEqual(len(job.payload["source"]["images"]), 4)

        asyncio.run(run())

    def test_algorithms_have_distinct_queue_identity(self):
        with TempDir() as tmp:
            studio = Studio(new_repository(tmp), FakeStorage(), {})
            standard, _ = studio.campaign(["гонки"], 20, design_limit=20)[0]
            redraw, _ = studio.campaign(["гонки"], 20, design_limit=20, algorithm="source_redraw")[0]
            self.assertNotEqual(standard.id, redraw.id)
            self.assertEqual(standard.payload["config"]["algorithm"], "standard")
            self.assertEqual(redraw.payload["config"]["max_print_width"], 0.8)
            self.assertNotIn("max_print_width", standard.payload["config"])
            with self.assertRaises(ValueError):
                studio.configuration(algorithm="unknown")

    def test_urls_are_validated_and_queued_for_the_existing_browser_worker(self):
        self.assertEqual(validate_product_urls([PRODUCT_URL, PRODUCT_URL]), [PRODUCT_URL])
        for invalid in (
            "https://evil.test/catalog/123/detail.aspx",
            "http://www.wildberries.ru/catalog/123/detail.aspx",
            "https://www.wildberries.ru.evil.test/catalog/123/detail.aspx",
        ):
            with self.assertRaises(ValueError):
                validate_product_urls([invalid])
        with TempDir() as tmp:
            job, _ = Studio(new_repository(tmp), FakeStorage(), {}).urls([PRODUCT_URL])
            self.assertEqual(job.payload["source_urls"], [PRODUCT_URL])
            self.assertEqual(job.payload["config"]["algorithm"], "source_redraw")


class RedrawGeneratorTest(unittest.TestCase):
    def test_photo_generation_gets_only_the_shirt_print_and_optional_pose(self):
        calls = []

        async def edit(files, prompt):
            calls.append(([name for name, *_ in files], prompt))
            return image()

        async def run():
            generator = Generator({}, load_config())
            generator.edit = edit
            await generator.live_photo(b"shirt", image(), "white", 0, "female")
            await generator.live_photo(b"shirt", image(), "white", 1, "female", pose=b"seller-pose")

        asyncio.run(run())
        self.assertEqual(calls[0][0], ["main-product.png", "artwork.png"])
        self.assertEqual(calls[1][0], ["main-product.png", "artwork.png", "pose-reference.png"])
        self.assertIn("a young woman aged 18–25", calls[0][1])
        self.assertIn("Repeat the pose", calls[1][1])

    def test_live_photo_prompt_follows_audience_and_pose(self):
        for index in range(4):
            for color in ("white", "black"):
                prompt = live_photo_prompt(color, index)
                self.assertIn("SHIRT: solid " + color.upper(), prompt)
                self.assertIn("any gender", prompt)
                for stale in ("seller", "Extract the ink"):
                    self.assertNotIn(stale, prompt)
        self.assertIn("a young man", live_photo_prompt("white", 0, "male"))
        posed = live_photo_prompt("black", 3, pose=True)
        self.assertIn("ignore its shirt and print", posed)
        self.assertNotIn("PRINT AND FIT VIEW", posed)
        self.assertIn("the face may be outside the crop", live_photo_prompt("black", 3))

    def test_gallery_analysis_normalizes_echoed_photo_reference(self):
        answer = {
            "photos": [
                {"label": "PHOTO_INDEX=0", "role": "back", "same_print": True, "normal_light": True, "adult": True},
                {"label": "PHOTO_INDEX=1", "role": "front", "same_print": True, "normal_light": True, "adult": True},
            ],
            "selected": [1],
            "print_source": {"label": "PHOTO_INDEX=1"},
            "theme_match": True,
            "main_print_side": "front",
            "single_print": True,
            "print_count": 1,
            "print_width": 0.5,
            "audience": "female",
            "title": "Футболка с принтом кот",
            "description": "Кот",
        }

        async def chat_json(content, **_):
            self.assertIn('"кот"', content[0]["text"])
            return answer

        async def run():
            generator = Generator({}, load_config())
            generator.chat_json = chat_json
            return await generator.analyze_gallery([image(), image()], "кот")

        result = asyncio.run(run())
        self.assertTrue(result["accepted"])
        self.assertEqual(result["print_source"], 1)
        self.assertEqual(result["audience"], "female")
        self.assertEqual(result["filter"]["original_selected"], [1])


class PrintContrastTest(unittest.TestCase):
    def test_only_vanishing_ink_needs_a_color_version(self):
        def print_file(color):
            canvas = Image.new("RGBA", (100, 100), (0, 0, 0, 0))
            canvas.paste(Image.new("RGBA", (60, 60), color), (20, 20))
            out = io.BytesIO()
            canvas.save(out, format="PNG")
            return out.getvalue()

        self.assertTrue(vanishing_ink(print_file((255, 255, 255, 255)), "white"))
        self.assertFalse(vanishing_ink(print_file((255, 255, 255, 255)), "black"))
        self.assertTrue(vanishing_ink(print_file((10, 10, 10, 255)), "black"))
        self.assertFalse(vanishing_ink(print_file((200, 60, 40, 255)), "white"))
        self.assertFalse(vanishing_ink(print_file((200, 60, 40, 255)), "black"))


if __name__ == "__main__":
    unittest.main()

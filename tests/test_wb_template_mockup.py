"""template_mockup: the model frames of a card are ready mockup photos with the print added."""

import asyncio
import unittest
from unittest.mock import patch

from support import FakeStorage, TempDir
from test_wb_redraw import GENERATOR, RedrawImages, image, listing, queued_card

from printflow.wb_studio.application.template_mockup import TEMPLATE_SLOTS
from printflow.wb_studio.domain.prompts import RECOLOR_ACTIONS, recolor_print_prompt, template_photo_prompt
from printflow.wb_studio.infrastructure.template_library import (
    TemplateLibrary,
    TemplateSeries,
)


class Templates:
    """Fake library: always series 7 of the audience's set, records every frame it hands out."""

    def __init__(self):
        self.photos = []

    def pick(self, audience, seed):
        return TemplateSeries(audience if audience in ("female", "male") else "female", 7)

    async def photo(self, series, color, slot):
        self.photos.append((series.gender, color, slot))
        return image()


class TemplatePipelineTest(unittest.TestCase):
    def run_card(self, audience):
        async def run():
            with TempDir() as tmp:
                templates = Templates()
                studio, _, job, save = await queued_card(tmp, [listing(6)], "template_mockup", templates=templates)
                generator = RedrawImages(selected=(0, 2), audience=audience, shirt_color="white")
                with patch(GENERATOR, return_value=generator):
                    result = await studio.card(job, save)
                return result, generator, templates

        return asyncio.run(run())

    def test_a_male_print_takes_frames_1_3_4_5_of_one_mens_series(self):
        result, generator, templates = self.run_card("male")
        self.assertEqual(
            sorted(templates.photos),
            sorted(("male", color, slot) for color in ("white", "black") for slot in TEMPLATE_SLOTS),
        )
        self.assertEqual(result["template_series"], {"gender": "male", "number": 7})
        self.assertEqual({color: len(frames) for color, frames in result["images"].items()}, {"white": 6, "black": 6})

    def test_both_colors_come_from_one_extracted_print(self):
        result, generator, _ = self.run_card("male")
        self.assertEqual(sorted(result["colors"]), ["black", "white"])
        self.assertEqual(len([call for call in generator.calls if call[0] == "extract"]), 1)

    def test_only_the_color_the_analysis_names_is_recolored(self):
        _, generator, _ = self.run_card("male")
        # the fake analysis asks to change white only; black takes the extracted print as it is
        self.assertEqual([call for call in generator.calls if call[0] == "recolor"], [("recolor", "white")])

    def test_the_print_goes_onto_the_front_frames_only(self):
        _, generator, _ = self.run_card("female")
        # frames 01, 03 and 05 get the print; the back view 04 is used as it is
        self.assertEqual(
            sorted(call for call in generator.calls if call[0] == "template"),
            [("template", "black")] * 3 + [("template", "white")] * 3,
        )
        self.assertFalse([call for call in generator.calls if call[0] == "live"])

    def test_the_prompt_keeps_the_photo_and_adds_only_the_print(self):
        prompt = template_photo_prompt("black")
        self.assertIn("template.png", prompt)
        self.assertIn("Everything else stays identical", prompt)
        # only template.png and artwork.png are attached
        geometry = {"body_cm": [54, 70], "width_cm": 30.0, "height_cm": 30.0, "top_cm": 8}
        self.assertNotIn("main-product.png", template_photo_prompt("black", geometry))


class RecolorActionTest(unittest.TestCase):
    def test_one_action_always_gives_the_same_instruction(self):
        prompt = recolor_print_prompt("black", "outlines")
        self.assertEqual(prompt, recolor_print_prompt("black", "outlines"))
        self.assertIn("thin black or very dark outlines", prompt)
        self.assertIn("into white", prompt)

    def test_an_unknown_action_from_the_analysis_means_none(self):
        from printflow.wb_studio.infrastructure.generation import Generator

        answer = {
            "photos": [{"index": 0, "role": "front", "same_print": True, "normal_light": True, "adult": True}],
            "title": "Футболка с принтом",
            "description": "Череп",
            "recolor": {"white": "make it pop", "black": "outlines"},
        }
        generator = Generator({}, {"image_quality": "low", "name_model": "gpt-4.1-mini"})

        async def chat_json(*_, **__):
            return answer

        with patch.object(generator, "chat_json", chat_json):
            analysis = asyncio.run(generator.analyze_gallery([image()], "черепа"))
        self.assertEqual(analysis["recolor"], {"white": "none", "black": "outlines"})

    def test_all_is_gone_so_no_print_is_inverted(self):
        self.assertNotIn("all", RECOLOR_ACTIONS)
        portrait = recolor_print_prompt("black", "tone")
        self.assertIn("NOT a negative", portrait)
        self.assertIn("becomes white ink", portrait)  # light skin stays light on the black shirt
        self.assertIn("becomes black ink", recolor_print_prompt("white", "tone"))

    def test_invert_flat_keeps_the_shape_and_only_changes_the_ink(self):
        import io

        from PIL import Image

        from printflow.wb_studio.domain.print_tone import invert_flat

        art = Image.new("RGBA", (4, 4), (0, 0, 0, 0))
        art.putpixel((1, 1), (255, 255, 255, 255))
        raw = io.BytesIO()
        art.save(raw, format="PNG")
        for color, ink in (("white", (0, 0, 0, 255)), ("black", (255, 255, 255, 255))):
            out = Image.open(io.BytesIO(invert_flat(raw.getvalue(), color)))
            self.assertEqual(out.getpixel((1, 1)), ink)
            # Never white under the transparency: the image model then ignored the artwork.
            self.assertEqual(out.getpixel((0, 0)), (0, 0, 0, 0))

    def test_the_photo_model_gets_the_print_on_its_fabric_without_transparency(self):
        import io

        from PIL import Image

        from printflow.wb_studio.infrastructure.images import on_fabric

        art = Image.new("RGBA", (4, 4), (0, 0, 0, 0))
        art.putpixel((1, 1), (0, 0, 0, 255))
        raw = io.BytesIO()
        art.save(raw, format="PNG")
        white = Image.open(io.BytesIO(on_fabric(raw.getvalue(), "white")))
        self.assertEqual(white.mode, "RGB")
        self.assertEqual((white.getpixel((0, 0)), white.getpixel((1, 1))), ((255, 255, 255), (0, 0, 0)))
        black = Image.open(io.BytesIO(on_fabric(raw.getvalue(), "black")))
        self.assertEqual(black.getpixel((0, 0)), (0, 0, 0))


class TemplateLibraryTest(unittest.TestCase):
    def library(self, existing=()):
        return TemplateLibrary(FakeStorage(set(existing)), {"female": "women", "male": "men"}, series=103)

    def test_the_audience_picks_the_set_and_the_vendor_number_the_series(self):
        library = self.library()
        self.assertEqual(library.pick("male", 5).gender, "male")
        self.assertEqual(library.pick("female", 5), library.pick("female", 5))
        self.assertGreater(len({library.pick("female", seed).number for seed in range(50)}), 30)

    def test_a_unisex_print_takes_either_set(self):
        library = self.library()
        self.assertEqual(
            {library.pick("unisex", seed).gender for seed in range(40)},
            {"female", "male"},
        )

    def test_a_series_whose_hero_shows_the_back_takes_its_front_frame(self):
        library = self.library({"women/series_88/black/06_alternative.png", "women/series_7/black/01_hero.png"})

        async def run():
            return [
                await library.photo(TemplateSeries("female", 88), "black", 1),
                await library.photo(TemplateSeries("female", 7), "black", 1),
            ]

        self.assertEqual(asyncio.run(run()), [b"x", b"x"])  # 88 has no 01_hero here: only 06 can resolve

    def test_a_seated_series_with_other_frame_names_still_resolves(self):
        library = self.library(
            {
                "women/series_3/black/03_seated_front.png",
                "women/series_3/black/05_fabric_detail.png",
            }
        )

        async def run():
            series = TemplateSeries("female", 3)
            return [await library.photo(series, "black", slot) for slot in (3, 5)]

        self.assertEqual(asyncio.run(run()), [b"x", b"x"])


if __name__ == "__main__":
    unittest.main()

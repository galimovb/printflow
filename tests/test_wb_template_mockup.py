"""template_mockup: the model frames of a card are ready mockup photos with the print added."""

import asyncio
import unittest
from unittest.mock import patch

from support import FakeStorage, TempDir
from test_wb_redraw import GENERATOR, RedrawImages, image, listing, queued_card

from printflow.domain.errors import PermanentError
from printflow.wb_studio.application.template_mockup import TEMPLATE_SLOTS
from printflow.wb_studio.domain.prompts import RECOLOR_ACTIONS, recolor_print_prompt
from printflow.wb_studio.domain.frame_plan import choose_frames
from printflow.wb_studio.infrastructure.template_library import (
    REMOVED,
    TemplateLibrary,
    TemplateSeries,
    TemplateShot,
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

    def candidates(self, audience, seed, count=8):
        gender = audience if audience in ("female", "male") else "female"
        return [TemplateShot(gender, 11 + i, slot) for i, slot in enumerate((1, 2, 3, 4, 5, 6, 1, 3)[:count])]

    async def shot(self, shot, color):
        self.photos.append(("shot", shot.series, shot.slot, color))
        return image()


class TemplatePipelineTest(unittest.TestCase):
    def run_card(self, audience, frame_plan=None, spoiled=(), frame_check=True, frame_redraw=True):
        async def run():
            with TempDir() as tmp:
                templates = Templates()
                studio, _, job, save = await queued_card(tmp, [listing(6)], "template_mockup", templates=templates)
                generator = RedrawImages(selected=(0, 2), audience=audience, shirt_color="white")
                generator.frame_plan = frame_plan
                generator.spoiled = list(spoiled)
                generator.frame_check = frame_check
                generator.frame_redraw = frame_redraw
                with patch(GENERATOR, return_value=generator):
                    result = await studio.card(job, save)
                return result, generator, templates

        return asyncio.run(run())

    def test_a_male_print_takes_frames_1_3_4_5_of_one_mens_series(self):
        result, generator, templates = self.run_card("male")
        # the fake plan answer is unusable, so the card keeps one series (candidates were only looked at)
        self.assertEqual(
            sorted(p for p in templates.photos if p[0] != "shot"),
            sorted(("male", color, slot) for color in ("white", "black") for slot in TEMPLATE_SLOTS),
        )
        self.assertEqual(result["template_series"], {"gender": "male", "number": 7})
        self.assertEqual(
            {color: len(frames) for color, frames in result["images"].items()},
            {"white": 6, "black": 6},
        )

    def test_both_colors_come_from_one_extracted_print(self):
        result, generator, _ = self.run_card("male")
        self.assertEqual(sorted(result["colors"]), ["black", "white"])
        self.assertEqual(len([call for call in generator.calls if call[0] == "extract"]), 1)

    def test_only_the_color_the_analysis_names_is_recolored(self):
        _, generator, _ = self.run_card("male")
        # the fake analysis asks to change white only; black takes the extracted print as it is
        self.assertEqual(
            [call for call in generator.calls if call[0] == "recolor"],
            [("recolor", "white")],
        )

    def test_a_print_that_loses_nothing_on_white_is_not_recolored(self):
        async def run():
            with TempDir() as tmp:
                studio, _, job, save = await queued_card(tmp, [listing(6)], "template_mockup", templates=Templates())
                generator = RedrawImages(selected=(0, 2), audience="male", shirt_color="white")
                generator.lost = {"white": False}  # the analysis asked for lettering; the extracted file is fine
                with patch(GENERATOR, return_value=generator):
                    return await studio.card(job, save), generator

        result, generator = asyncio.run(run())
        self.assertIn(("recolor_needed", ("white",)), generator.calls)
        self.assertFalse([c for c in generator.calls if c[0] in ("recolor", "tone")])
        self.assertEqual(result["analysis"]["recolor"]["white"], "none")
        self.assertEqual(result["recolor_review"]["white"], {"asked": "lettering", "lost": False})
        self.assertEqual({color: len(frames) for color, frames in result["images"].items()}, {"white": 6, "black": 6})

    def test_the_print_goes_onto_the_front_frames_only(self):
        result, generator, _ = self.run_card("female")
        # two 2x2 collages, each row one pose in both colors: frames 01+03, then 04+05; the back view 04 goes into the
        # collage only for the layout and is stored as its clean template
        white, black = "white", "black"
        self.assertEqual([c for c in generator.calls if c[0] == "collage"],
                         [("collage", (white, black, white, black))] * 2)  # fmt: skip
        self.assertFalse([c for c in generator.calls if c[0] == "live"])
        self.assertEqual(
            {color: len(frames) for color, frames in result["images"].items()},
            {"white": 6, "black": 6},
        )

    def test_every_drawn_frame_is_checked_against_its_print_and_the_back_view_is_not(self):
        _, generator, _ = self.run_card("female")
        white, black = "white", "black"
        # collage 1: frames 01 and 03 in both colors; collage 2: the back view 04 (a clean template) and 05
        self.assertEqual(sorted(c for c in generator.calls if c[0] == "check"),
                         sorted([("check", (white, black, white, black)), ("check", (white, black))]))  # fmt: skip

    def test_a_spoiled_print_redraws_its_collage_once(self):
        result, generator, _ = self.run_card("female", spoiled=[(1,)])
        self.assertEqual(len([c for c in generator.calls if c[0] == "collage"]), 3)
        self.assertEqual(len([c for c in generator.calls if c[0] == "check"]), 3)
        self.assertEqual(sorted(result["frame_attempts"].values()), [1, 2])
        self.assertEqual({color: len(frames) for color, frames in result["images"].items()}, {"white": 6, "black": 6})

    def test_a_print_spoiled_again_after_the_redraw_fails_the_card(self):
        with self.assertRaises(PermanentError) as error:
            self.run_card("female", spoiled=[(0,), (0,), (0,)])
        self.assertIn("голова гнома расплылась", str(error.exception))

    def test_with_the_check_off_no_frame_is_judged_or_redrawn(self):
        result, generator, _ = self.run_card("female", spoiled=[(0,), (0,)], frame_check=False)
        self.assertFalse([c for c in generator.calls if c[0] == "check"])
        self.assertEqual(len([c for c in generator.calls if c[0] == "collage"]), 2)
        self.assertFalse(result.get("frame_checks"))

    def test_without_redraw_a_spoiled_print_is_only_marked(self):
        result, generator, _ = self.run_card("female", spoiled=[(1,), (1,)], frame_redraw=False)
        self.assertEqual(len([c for c in generator.calls if c[0] == "collage"]), 2)
        self.assertEqual(len([c for c in generator.calls if c[0] == "check"]), 2)
        marked = [p for problems in result["frame_problems"].values() for p in problems]
        self.assertEqual(len(marked), 2)
        self.assertTrue(all(p["reason"] == "голова гнома расплылась" for p in marked))
        self.assertEqual({color: len(frames) for color, frames in result["images"].items()}, {"white": 6, "black": 6})

    def test_mixed_frames_come_from_different_series_in_the_models_order(self):
        views = ["front", "side", "front", "back", "closeup", "front", "front", "front"]
        answer = {"photos": [{"index": i, "view": v, "chest_clear": i != 5} for i, v in enumerate(views)],
                  "order": [2, 3, 0, 4], "reason": "hero, back, candid, closeup"}  # fmt: skip
        result, generator, templates = self.run_card("female", answer)
        self.assertEqual([(f["series"], f["slot"], f["draw"]) for f in result["template_frames"]],
                         [(13, 3, True), (14, 4, False), (11, 1, True), (15, 5, True)])  # fmt: skip
        self.assertEqual(result["template_series"], {"gender": "female", "number": 13})  # the hero's series
        self.assertEqual(result["frame_plan_reason"], "hero, back, candid, closeup")
        # 8 candidates looked at in white; the frames themselves in both colors; the back is not drawn
        self.assertEqual(
            len([p for p in templates.photos if p[0] == "shot" and p[3] == "white"]),
            8 + 4,
        )
        self.assertEqual(len([c for c in generator.calls if c[0] == "collage"]), 2)  # 4 frames x 2 colors in 2 collages
        self.assertFalse([p for p in templates.photos if p[0] != "shot"])  # no single-series frames

    def test_a_one_ink_dark_print_is_flipped_by_code_for_black_whatever_the_analysis_says(
        self,
    ):
        async def run():
            with TempDir() as tmp:
                studio, _, job, save = await queued_card(tmp, [listing(6)], "template_mockup", templates=Templates())
                generator = RedrawImages(selected=(0, 2), audience="male", shirt_color="white")
                dark = PrintCleanupTest.png([((5, 5, 30, 30), (10, 10, 10, 255))])

                async def extract_print(source, expected="", feedback=""):
                    generator.calls.append(("extract", feedback))
                    return dark

                generator.extract_print = extract_print
                with patch(GENERATOR, return_value=generator):
                    return await studio.card(job, save), generator

        result, generator = asyncio.run(run())
        self.assertEqual(result["analysis"]["recolor"]["black"], "invert_flat")  # the analysis said none
        self.assertFalse([c for c in generator.calls if c[0] in ("tone",) or c == ("recolor", "black")])

    def test_an_unusable_plan_keeps_one_series(self):
        result, generator, templates = self.run_card("male", {"photos": [{"index": 0, "view": "back"}], "order": [0]})
        self.assertEqual(result["template_frames"], [])
        self.assertEqual(sorted(p for p in templates.photos if p[0] != "shot"),
                         sorted(("male", color, slot) for color in ("white", "black") for slot in TEMPLATE_SLOTS))  # fmt: skip


class TemplateCollageTest(unittest.TestCase):
    def test_one_request_draws_two_poses_in_both_colors_from_the_flat_references(self):
        from printflow.wb_studio.domain.prompts import frame_collage_prompt
        from printflow.wb_studio.infrastructure.generation import Generator

        generator = Generator({}, {"image_quality": "low", "name_model": "gpt-4.1-mini", "image_model": "m"})
        sent = {}

        async def edit(files, prompt, **kwargs):
            sent.update(names=[f[0] for f in files], prompt=prompt, size=kwargs["size"], quality=kwargs["quality"])
            return image()

        colors = ["white", "black", "white", "black"]
        with patch.object(generator, "edit", edit):
            asyncio.run(generator.frame_collage(image(), {"white": image(), "black": image()}, colors))
        # no separate print file: one flat shirt per color
        self.assertEqual(sent["names"], ["template.png", "main-product-white.png", "main-product-black.png"])
        self.assertEqual(sent["size"], "2048x3072")  # each cell at the template's 1024x1536
        self.assertEqual(sent["quality"], "low")  # frames follow image_quality
        self.assertEqual(sent["prompt"], frame_collage_prompt(colors))
        self.assertIn("top-left in a blank WHITE T-shirt, top-right in a blank BLACK T-shirt", sent["prompt"])
        self.assertIn("Each row is one person and pose shown twice", sent["prompt"])
        self.assertIn("exactly the same size, position and bend on the two shirts", sent["prompt"])
        self.assertIn("stays in front", sent["prompt"])
        self.assertIn("never fades", sent["prompt"])

    def test_one_color_takes_four_poses_without_the_pairing_sentence(self):
        from printflow.wb_studio.domain.prompts import frame_collage_prompt

        prompt = frame_collage_prompt(["black"] * 4)
        self.assertIn("main-product-black.png", prompt)
        self.assertNotIn("WHITE", prompt)
        self.assertNotIn("shown twice", prompt)

    def test_a_collage_is_cut_back_into_its_four_photos_in_order(self):
        import io

        from PIL import Image

        from printflow.wb_studio.infrastructure.images import collage, collage_cells

        def photo(color):
            out = io.BytesIO()
            Image.new("RGB", (1024, 1536), color).save(out, format="PNG")
            return out.getvalue()

        colors = [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0)]
        sheet = collage([photo(c) for c in colors])
        self.assertEqual(Image.open(io.BytesIO(sheet)).size, (1024, 1536))
        cells = [Image.open(io.BytesIO(c)).convert("RGB") for c in collage_cells(sheet)]
        self.assertEqual([c.getpixel((100, 100)) for c in cells], colors)
        self.assertEqual(cells[0].size, (512, 768))


class RecolorActionTest(unittest.TestCase):
    def test_one_action_always_gives_the_same_instruction(self):
        prompt = recolor_print_prompt("black", "outlines")
        self.assertEqual(prompt, recolor_print_prompt("black", "outlines"))
        self.assertIn("thin black or very dark outlines", prompt)
        self.assertIn("into white", prompt)

    def test_an_unknown_action_from_the_analysis_means_none(self):
        from printflow.wb_studio.infrastructure.generation import Generator

        answer = {
            "photos": [
                {
                    "index": 0,
                    "role": "front",
                    "same_print": True,
                    "normal_light": True,
                    "adult": True,
                }
            ],
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
        library = self.library(
            {
                "women/series_88/black/06_alternative.png",
                "women/series_7/black/01_hero.png",
            }
        )

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


class FramePlanTest(unittest.TestCase):
    def answer(self, views, order, covered=()):
        return {"photos": [{"index": i, "view": v, "chest_clear": i not in covered} for i, v in enumerate(views)],
                "order": order}  # fmt: skip

    def test_the_models_order_is_kept_when_it_is_valid(self):
        plan = choose_frames(self.answer(["front", "back", "front", "closeup"], [0, 2, 1, 3]), 4, 4)
        self.assertEqual(plan, [{"index": 0, "draw": True}, {"index": 2, "draw": True},
                                {"index": 1, "draw": False}, {"index": 3, "draw": True}])  # fmt: skip

    def test_side_covered_extra_backs_and_a_back_first_are_dropped_and_refilled(self):
        views = ["back", "side", "front", "front", "back", "front", "front"]
        plan = choose_frames(self.answer(views, [0, 1, 2, 3, 4, 5], covered=(3,)), 4, len(views))
        # back first is skipped, side and covered never used, one back kept, the gap filled with photo 6
        self.assertEqual(
            [(p["index"], p["draw"]) for p in plan],
            [(2, True), (4, False), (5, True), (6, True)],
        )

    def test_not_enough_usable_photos_is_no_plan(self):
        self.assertIsNone(choose_frames(self.answer(["front", "back", "side"], [0, 1, 2]), 4, 3))
        self.assertIsNone(choose_frames({"photos": "x", "order": None}, 4, 8))


class TemplateCandidatesTest(unittest.TestCase):
    def test_candidates_differ_in_series_and_slot_and_repeat_for_a_seed(self):
        library = TemplateLibrary(FakeStorage(set()), {"female": "women", "male": "men"}, series=103)
        shots = library.candidates("female", "5643:url", 8)
        self.assertEqual(len({s.series for s in shots}), 8)  # 8 different people and places
        self.assertEqual({s.slot for s in shots[:6]} | {s.slot for s in shots}, {1, 2, 3, 4, 5, 6})
        self.assertEqual({s.gender for s in shots}, {"female"})
        self.assertEqual(shots, library.candidates("female", "5643:url", 8))
        self.assertNotEqual(shots, library.candidates("female", "5644:url", 8))

    def test_deleted_photos_are_never_offered_and_the_fallback_skips_their_series(self):
        library = TemplateLibrary(FakeStorage(set()), {"female": "women", "male": "men"}, series=103)
        removed = REMOVED["female"]
        offered = {(s.series, s.slot) for seed in range(3000) for s in library.candidates("female", seed, 8)}
        self.assertFalse(offered & removed)
        self.assertTrue({72, 49, 99} & {series for series, _ in offered})  # the rest of those series stays
        picked = {library.pick("female", seed).number for seed in range(3000)}
        self.assertFalse(picked & {72, 49, 99})


class PrintCleanupTest(unittest.TestCase):
    @staticmethod
    def png(pixels):
        import io

        from PIL import Image

        art = Image.new("RGBA", (40, 40), (0, 0, 0, 0))
        for (x0, y0, x1, y1), color in pixels:
            for x in range(x0, x1):
                for y in range(y0, y1):
                    art.putpixel((x, y), color)
        out = io.BytesIO()
        art.save(out, format="PNG")
        return out.getvalue()

    def test_one_flat_ink_is_recognised_colors_and_grays_are_not(self):
        from printflow.wb_studio.domain.print_tone import one_color_ink

        self.assertEqual(one_color_ink(self.png([((5, 5, 30, 30), (10, 10, 10, 255))])), "dark")
        self.assertEqual(one_color_ink(self.png([((5, 5, 30, 30), (250, 250, 250, 255))])), "light")
        mixed = self.png([((5, 5, 30, 18), (10, 10, 10, 255)), ((5, 18, 30, 30), (200, 30, 30, 255))])
        self.assertIsNone(one_color_ink(mixed))
        self.assertIsNone(one_color_ink(image()))  # an opaque photo is no cut-out print

    def test_the_key_cast_leaves_edges_and_green_ink_stays(self):
        import io

        from PIL import Image

        from printflow.wb_studio.domain.print_tone import despill

        raw = self.png([((5, 5, 15, 15), (90, 140, 90, 255)),  # gray shadow tinted by the #90EE90 key
                        ((20, 5, 30, 15), (20, 170, 40, 255))])  # a green bulb  # fmt: skip
        out = Image.open(io.BytesIO(despill(raw))).convert("RGBA")
        self.assertEqual(out.getpixel((10, 10)), (90, 90, 90, 255))
        self.assertEqual(out.getpixel((25, 10)), (20, 170, 40, 255))


class VanishingInkTest(unittest.TestCase):
    @staticmethod
    def art(panel: bool) -> bytes:
        import io

        from PIL import Image, ImageDraw

        art = Image.new("RGBA", (200, 120), (0, 0, 0, 0))
        draw = ImageDraw.Draw(art)
        draw.rectangle((10, 10, 190, 70), fill=(200, 90, 40, 255))  # the picture
        if panel:
            draw.rectangle((10, 75, 190, 110), fill=(0, 0, 0, 255))  # a black strip the print keeps
        for x in range(20, 180, 16):
            draw.rectangle((x, 82, x + 9, 104), fill=(255, 255, 255, 255))  # white letters
        out = io.BytesIO()
        art.save(out, format="PNG")
        return out.getvalue()

    def test_white_letters_cut_free_of_their_strip_vanish_on_white(self):
        from printflow.wb_studio.domain.print_tone import MIN_VANISHING_PIXELS, vanishing_ink

        self.assertGreaterEqual(vanishing_ink(self.art(panel=False), "white"), MIN_VANISHING_PIXELS)

    def test_letters_on_their_own_strip_and_the_strip_itself_never_count(self):
        from printflow.wb_studio.domain.print_tone import vanishing_ink

        self.assertEqual(vanishing_ink(self.art(panel=True), "white"), 0)
        self.assertEqual(vanishing_ink(self.art(panel=True), "black"), 0)

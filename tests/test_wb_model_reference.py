"""model_reference: the frames of a card use ready model photos picked by the print audience."""

import asyncio
import unittest
from unittest.mock import patch

from support import TempDir
from test_wb_redraw import GENERATOR, RedrawImages, listing, queued_card

from printflow.wb_studio.domain.prompts import live_photo_prompt
from printflow.wb_studio.infrastructure.model_library import ModelLibrary, ModelPhoto


class Models:
    """Fake library: the photo bytes name the gender and the frame."""

    def pick(self, gender, seed, frame):
        return ModelPhoto(gender, f"{gender}-{frame}".encode())


class ModelReferenceTest(unittest.TestCase):
    def frames(self, audience):
        async def run():
            with TempDir() as tmp:
                studio, _, job, save = await queued_card(tmp, [listing(6)], "model_reference", Models())
                generator = RedrawImages(selected=(0, 2), audience=audience, shirt_color="white")
                with patch(GENERATOR, return_value=generator):
                    await studio.card(job, save)
                live = [call for call in generator.calls if call[0] == "live"]
                return [(call[2], call[3], person) for call, person in zip(live, generator.people, strict=True)]

        return sorted(asyncio.run(run()))

    def test_a_female_print_is_worn_by_four_women(self):
        self.assertEqual(
            self.frames("female"),
            [(i, "female", f"female-{i}".encode()) for i in range(4)],
        )

    def test_a_unisex_print_gets_two_men_and_two_women(self):
        self.assertEqual(
            self.frames("unisex"),
            [(0, "male", b"male-0"), (1, "male", b"male-1"), (2, "female", b"female-2"), (3, "female", b"female-3")],
        )

    def test_the_prompt_takes_the_person_from_the_reference_photo(self):
        prompt = live_photo_prompt("white", 0, "female", person=True)
        self.assertIn("person-reference.png", prompt)
        self.assertNotIn("Looks:", prompt)


class ModelLibraryTest(unittest.TestCase):
    def test_every_frame_of_a_card_gets_a_different_model(self):
        with TempDir() as tmp:
            for i in range(6):
                (tmp / "male").mkdir(exist_ok=True)
                (tmp / "male" / f"{i}.jpg").write_bytes(bytes([i]))
            library = ModelLibrary(tmp)
            photos = [library.pick("male", 42, frame).photo for frame in range(4)]
            self.assertEqual(len(set(photos)), 4)
            self.assertEqual(photos, [library.pick("male", 42, frame).photo for frame in range(4)])


if __name__ == "__main__":
    unittest.main()

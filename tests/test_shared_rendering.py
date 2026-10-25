from __future__ import annotations

import asyncio
import base64
import io
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from PIL import Image
import numpy as np
from support import SHOPPER, MOUSEPAD, product_settings

from printflow.services.gallery.renderer import JpegGalleryRenderer
from printflow.services.printing.generator import ImagePrintGenerator
from printflow.products.shopper.infrastructure.gallery.renderer import GalleryRenderer
from printflow.products.mousepad.infrastructure.gallery.renderer import PadGalleryRenderer
from printflow.products.shopper.infrastructure.gallery.theme import Canvas as BagCanvas
from printflow.products.mousepad.infrastructure.gallery.theme import Canvas as PadCanvas
from printflow.services.gallery.geometry import homography


def png(mode="RGB", color=(200, 40, 60), size=(220, 180)):
    buf = io.BytesIO()
    Image.new(mode, size, color).save(buf, format="PNG")
    return buf.getvalue()


class SharedEditingTest(unittest.TestCase):
    def test_photo_and_hires_keep_product_preparation(self):
        for product in (SHOPPER, MOUSEPAD):
            with self.subTest(product=product.name):
                settings = replace(product_settings(product.env_prefix).openai, api_key="test-key",
                                   reference_max_side=100)
                generator = product.generator(settings)
                self.assertIs(type(generator).copy_from_photo, ImagePrintGenerator.copy_from_photo)
                self.assertIs(type(generator).hires_print, ImagePrintGenerator.hires_print)
                response = SimpleNamespace(data=[SimpleNamespace(b64_json=base64.b64encode(png()).decode())])
                edit = AsyncMock(return_value=response)
                generator.client = SimpleNamespace(images=SimpleNamespace(edit=edit))
                copied = asyncio.run(generator.copy_from_photo(png(), "keep lettering"))
                args = edit.call_args.kwargs
                self.assertEqual(args["size"], generator.reference["size"])
                self.assertEqual(args["quality"], generator.reference["quality"])
                self.assertIn("keep lettering", args["prompt"])
                self.assertEqual(args["image"][0], "reference.png")
                self.assertEqual(max(Image.open(io.BytesIO(args["image"][1])).size), 100)
                preview = png("RGBA", (0, 0, 0, 0), (20, 20))
                hires = asyncio.run(generator.hires_print(preview))
                args = edit.call_args.kwargs
                self.assertEqual(args["size"], generator.hires["size"])
                self.assertEqual(args["quality"], generator.hires["quality"])
                self.assertEqual(args["image"][0], "print.png")
                if product.name == "shopper":
                    prepared = Image.open(io.BytesIO(args["image"][1]))
                    self.assertEqual(prepared.mode, "RGB")
                    self.assertEqual(prepared.getpixel((0, 0)), (0x90, 0xEE, 0x90))
                    self.assertEqual(Image.open(io.BytesIO(hires)).mode, "RGBA")
                else:
                    self.assertEqual(args["image"][1], preview)
                    self.assertEqual(Image.open(io.BytesIO(copied)).mode, "RGB")

    def test_incomplete_generator_cannot_be_instantiated(self):
        class Incomplete(ImagePrintGenerator):
            pass
        with self.assertRaises(TypeError):
            Incomplete(None, {}, "")


class SharedGalleryTest(unittest.TestCase):
    def test_text_fits_and_preserves_each_products_line_spacing(self):
        for canvas_type, spacing in ((BagCanvas, 1.12), (PadCanvas, 1.08)):
            canvas = canvas_type(Image.new("RGB", (500, 700), "white"))
            text = "Long heading\nSecond line"
            f = canvas.fit(text, 50, 300)
            self.assertTrue(all(canvas.text_w(line, f) <= 300 for line in text.split("\n")))
            self.assertAlmostEqual(canvas.text((30, 40), text, f), 40 + 2 * f.size * spacing)
            self.assertAlmostEqual(canvas.text((30, 40), text, f, spacing=1.3), 40 + 2 * f.size * 1.3)
            self.assertEqual(canvas.result().mode, "RGB")

    def test_perspective_maps_all_four_corners(self):
        source = [(0, 0), (100, 0), (100, 80), (0, 80)]
        destination = [(10, 20), (120, 10), (130, 100), (5, 110)]
        h = homography(source, destination)
        for src, dst in zip(source, destination):
            point = h @ np.array([*src, 1])
            np.testing.assert_allclose(point[:2] / point[2], dst, atol=1e-8)

    def test_missing_slides_keep_product_numbering_and_jpeg_format(self):
        cases = [
            (GalleryRenderer, SHOPPER, ["hero", "specs"], "white", ["00_hero", "02_specs"]),
            (PadGalleryRenderer, MOUSEPAD, ["hero", "glide"], "main", ["00_hero", "01_glide"]),
        ]
        for renderer, product, names, variant, expected in cases:
            with self.subTest(product=product.name):
                gallery = renderer(product.config, Path("unused"))
                self.assertIsInstance(gallery, JpegGalleryRenderer)
                images = {name: Image.new("RGB", (20, 30), "red") for name in reversed(names)}
                with patch.object(gallery, "compose_print", return_value=images) as compose:
                    slides = gallery.render(b"print", variant)
                compose.assert_called_once_with(b"print", variant)
                self.assertEqual([name for name, _ in slides], expected)
                for _, data in slides:
                    image = Image.open(io.BytesIO(data))
                    self.assertEqual(image.format, "JPEG")
                    self.assertEqual(image.size, tuple(product.config["gallery"]["size"]))

    def test_incomplete_gallery_cannot_be_instantiated(self):
        class Incomplete(JpegGalleryRenderer):
            pass
        with self.assertRaises(TypeError):
            Incomplete({}, Path("unused"))

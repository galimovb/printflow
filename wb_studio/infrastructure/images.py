"""Image preparation for paid requests: smaller inputs, readable labels, neutral backgrounds."""

import base64
import io

from PIL import Image, ImageDraw, ImageFilter, ImageFont


def data_url(raw: bytes, mime: str = "image/jpeg") -> str:
    return f"data:{mime};base64," + base64.b64encode(raw).decode()


def jpeg(image: Image.Image, quality: int = 90) -> bytes:
    out = io.BytesIO()
    image.convert("RGB").save(out, format="JPEG", quality=quality)
    return out.getvalue()


def png(image: Image.Image) -> bytes:
    out = io.BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


def label_font(size: int) -> ImageFont.ImageFont:
    for name in ("C:/Windows/Fonts/arial.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def numbered_photo(raw: bytes, index: int) -> bytes:
    """Gallery photo with a visible PHOTO_INDEX header, so answers cite the right photo."""
    image = Image.open(io.BytesIO(raw)).convert("RGB")
    image.thumbnail((900, 900))
    numbered = Image.new("RGB", (image.width, image.height + 65), "white")
    numbered.paste(image, (0, 65))
    ImageDraw.Draw(numbered).text((10, 10), f"PHOTO_INDEX={index}", font=label_font(34), fill="black")
    return jpeg(numbered, quality=85)


def on_gray(raw: bytes, fabric: str = "#bbbbbb") -> bytes:
    """Transparent prints on neutral gray, so the judge never mistakes background for ink.

    fabric: a shirt color instead, to show a color version exactly as it will look printed.
    """
    image = Image.open(io.BytesIO(raw)).convert("RGBA")
    image.thumbnail((1024, 1024))
    background = Image.new("RGBA", image.size, fabric)
    background.alpha_composite(image)
    return jpeg(background)


def on_canvas(raw: bytes, ratio: float) -> bytes:
    """Print centered on a chromakey canvas of the output aspect, so the model has no reason to extend it."""
    image = Image.open(io.BytesIO(raw)).convert("RGBA")
    width = max(image.width, round(image.height * ratio)) + image.width // 5
    height = round(width / ratio)
    canvas = Image.new("RGBA", (width, height), "#90EE90")
    canvas.alpha_composite(image, ((width - image.width) // 2, (height - image.height) // 2))
    return png(canvas.convert("RGB"))


def blurred(raw: bytes, side: int = 1200) -> bytes:
    """Pose stays readable, the seller's print and its placement do not."""
    image = Image.open(io.BytesIO(raw)).convert("RGB")
    image.thumbnail((side * 3 // 4, side))
    return png(image.filter(ImageFilter.GaussianBlur(max(6, image.width // 60))))


def shrunk(raw: bytes, side: int) -> bytes:
    """Input images are billed by size; model photos need only the layout, not the full resolution."""
    image = Image.open(io.BytesIO(raw))
    if max(image.size) <= side:
        return raw
    image.thumbnail((side, side), Image.Resampling.LANCZOS)
    return png(image)


COLLAGE_CELL = (512, 768)  # a 2:3 template photo in the input collage


def collage(photos: list[bytes], cell: tuple[int, int] = COLLAGE_CELL) -> bytes:
    """Four photos as a 2x2 collage, row by row: one image request draws all of them."""
    sheet = Image.new("RGB", (cell[0] * 2, cell[1] * 2), "white")
    for index, raw in enumerate(photos):
        photo = Image.open(io.BytesIO(raw)).convert("RGB").resize(cell, Image.Resampling.LANCZOS)
        sheet.paste(photo, ((index % 2) * cell[0], (index // 2) * cell[1]))
    return png(sheet)


def collage_cells(raw: bytes) -> list[bytes]:
    """The four cells of a 2x2 collage, row by row, at the collage's own resolution."""
    sheet = Image.open(io.BytesIO(raw)).convert("RGB")
    width, height = sheet.size[0] // 2, sheet.size[1] // 2
    boxes = [((i % 2) * width, (i // 2) * height, (i % 2 + 1) * width, (i // 2 + 1) * height) for i in range(4)]
    return [png(sheet.crop(box)) for box in boxes]

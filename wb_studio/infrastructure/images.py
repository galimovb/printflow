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


def on_fabric(raw: bytes, color: str) -> bytes:
    """The print laid on its shirt color, opaque: the photo model ignores dark ink on a transparent PNG
    and invents a foreign print instead (5/5 white frames of 5252, 2026-11-05); on the fabric it is copied."""
    image = Image.open(io.BytesIO(raw)).convert("RGBA")
    background = Image.new("RGBA", image.size, (255, 255, 255, 255) if color == "white" else (0, 0, 0, 255))
    background.alpha_composite(image)
    return png(background.convert("RGB"))


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

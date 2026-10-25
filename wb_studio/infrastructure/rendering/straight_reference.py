"""Fold-free orthographic service templates; never a published gallery slide."""

import io

from PIL import Image, ImageDraw

from printflow.products.shopper.infrastructure.gallery.geometry import load_print
from printflow.wb_studio.paths import ASSETS

ROOT = ASSETS / "straight-regular-v2"
SIZE = (1200, 1600)
BODY = (276, 280, 924, 1120)  # 54 x 70 cm at 12 px/cm.


def build_template(color):
    if color not in ("white", "black"):
        raise ValueError(color)
    scale = 3
    image = Image.new("RGB", (SIZE[0] * scale, SIZE[1] * scale), "#d8d8d8")
    draw = ImageDraw.Draw(image)

    def points(values):
        return [(int(x * scale), int(y * scale)) for x, y in values]

    fill = "#fafafa" if color == "white" else "#202020"
    seam = "#d0d0d0" if color == "white" else "#4b4b4b"
    outline = [
        (470, 250),
        (350, 280),
        (276, 300),
        (160, 405),
        (225, 495),
        (276, 455),
        (276, 1120),
        (924, 1120),
        (924, 455),
        (975, 495),
        (1040, 405),
        (924, 300),
        (850, 280),
        (730, 250),
        (700, 285),
        (660, 310),
        (600, 320),
        (540, 310),
        (500, 285),
    ]
    draw.polygon(points(outline), fill=fill)
    draw.line(points(outline + [outline[0]]), fill=seam, width=scale * 2)
    for line in [
        [(276, 1102), (924, 1102)],
        [(170, 400), (234, 483)],
        [(1030, 400), (966, 483)],
        [(276, 455), (276, 1097)],
        [(924, 455), (924, 1097)],
    ]:
        draw.line(points(line), fill=seam, width=scale * 2)
    draw.arc((470 * scale, 210 * scale, 730 * scale, 340 * scale), 0, 180, fill=seam, width=scale * 9)
    return image.resize(SIZE, Image.Resampling.LANCZOS)


def prepare_straight_reference(art, color, config=None):
    ROOT.mkdir(parents=True, exist_ok=True)
    path = ROOT / f"{color}.png"
    if not path.exists():
        build_template(color).save(path)
    base = Image.open(path).convert("RGBA")
    artwork = load_print(io.BytesIO(art))
    width = 30.0
    height = width * artwork.height / artwork.width
    if height > 39:
        width *= 39 / height
        height = 39.0
    px = round(width * 12)
    py = round(height * 12)
    ink = artwork.convert("RGBA").resize((px, py), Image.Resampling.LANCZOS)
    base.alpha_composite(ink, (600 - px // 2, 280 + 8 * 12))
    out = io.BytesIO()
    base.convert("RGB").save(out, format="PNG")
    return out.getvalue(), {
        "body_cm": [54, 70],
        "width_cm": width,
        "height_cm": height,
        "top_cm": 8,
        "angle_degrees": 0,
        "template": str(path),
    }

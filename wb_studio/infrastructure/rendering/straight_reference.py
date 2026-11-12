"""The flat reference shirt the photo model copies the print's size from; never a published gallery slide.

The templates are our oversize shirt laid flat (assets/straight-oversize-v3, made by the image model from
assets/garments/black.png on 2026-11-09, white from the black one). Measured on them: the body is 716 px across at
the chest, taken as 54 cm; the front collar seam is lowest at y=472.
"""

import io

from PIL import Image

from printflow.products.shopper.infrastructure.gallery.geometry import load_print
from printflow.wb_studio.domain.print_box import print_size_cm
from printflow.wb_studio.paths import ASSETS

ROOT = ASSETS / "straight-oversize-v3"
BODY_CM = (54, 74)  # chest width, neck point to hem
PX_PER_CM = 716 / 54
CENTER_X = 600
FRONT_COLLAR_Y = 472
PRINT_TOP_CM = 5  # below the front collar seam


def prepare_straight_reference(art, color, config=None):
    if color not in ("white", "black"):
        raise ValueError(color)
    path = ROOT / f"{color}.png"
    base = Image.open(path).convert("RGBA")
    artwork = load_print(io.BytesIO(art))
    width, height = print_size_cm(artwork.width / artwork.height)
    px, py = round(width * PX_PER_CM), round(height * PX_PER_CM)
    ink = artwork.convert("RGBA").resize((px, py), Image.Resampling.LANCZOS)
    base.alpha_composite(ink, (CENTER_X - px // 2, round(FRONT_COLLAR_Y + PRINT_TOP_CM * PX_PER_CM)))
    out = io.BytesIO()
    base.convert("RGB").save(out, format="PNG")
    return out.getvalue(), {
        "body_cm": list(BODY_CM),
        "width_cm": width,
        "height_cm": height,
        "top_cm": PRINT_TOP_CM,
        "angle_degrees": 0,
        "template": str(path),
    }

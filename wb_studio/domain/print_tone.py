"""invert_flat by pixels: a flat one-color logo takes the contrast ink, its shape and openings stay exact.

The gallery analysis picks the action; this one is plain pixel work, so it costs no request and never drifts.
"""

import io

import numpy as np
from PIL import Image

CONTRAST = {"white": (0, 0, 0), "black": (255, 255, 255)}


def invert_flat(raw: bytes, color: str) -> bytes:
    rgba = np.array(Image.open(io.BytesIO(raw)).convert("RGBA"))
    ink = rgba[..., 3] > 0
    rgba[ink, :3] = CONTRAST[color]
    # Transparent pixels stay plain transparent black, like every extracted print. White under the
    # transparency of a white-shirt print made the image model drop the artwork and invent a foreign
    # print on all 51 such frames (2026-11-05); transparent black never did.
    rgba[~ink] = (0, 0, 0, 0)
    out = io.BytesIO()
    Image.fromarray(rgba, "RGBA").save(out, format="PNG")
    return out.getvalue()

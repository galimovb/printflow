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


def one_color_ink(raw: bytes) -> str | None:
    """ "dark" or "light" when the print is one flat ink (black or white, no colors, no gray tones), else None.

    Such a print never needs a redraw for the other fabric: flipping its ink (invert_flat) keeps every shape.
    A file without a transparent background is not a cut-out print and gets None.
    """
    rgba = np.asarray(Image.open(io.BytesIO(raw)).convert("RGBA")).astype(int)
    alpha = rgba[..., 3]
    if (alpha == 0).mean() < 0.05:
        return None
    ink = rgba[alpha > 200][:, :3]
    if len(ink) < 100:
        return None
    luma = ink @ np.array([0.299, 0.587, 0.114])
    neutral = (ink.max(1) - ink.min(1)) < 45
    if (neutral & (luma < 80)).mean() > 0.97:
        return "dark"
    if (neutral & (luma > 185)).mean() > 0.97:
        return "light"
    return None


def despill(raw: bytes, band: int = 30) -> bytes:
    """Removes the green cast the #90EE90 cut-out background leaves in soft edges and ground shadows.

    The cast is the key color blended into gray: red and blue stay nearly equal and green exceeds them by at most
    about 1.8 times. Only such pixels within `band` px of the transparent background change, so green ink
    (leaves, bulbs: much greener, red and blue unequal) keeps its color.
    """
    from scipy import ndimage

    rgba = np.array(Image.open(io.BytesIO(raw)).convert("RGBA"))
    alpha = rgba[..., 3]
    near_edge = ndimage.binary_dilation(alpha < 8, iterations=band) & (alpha > 0)
    rgb = rgba[..., :3].astype(int)
    red, green, blue = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    limit = np.maximum(red, blue)
    cast = near_edge & (abs(red - blue) < 24) & (green > limit + 6) & (green <= limit * 1.8 + 12)
    if not cast.any():
        return raw
    rgba[..., 1] = np.where(cast, limit, green).astype(np.uint8)
    out = io.BytesIO()
    Image.fromarray(rgba, "RGBA").save(out, format="PNG")
    return out.getvalue()


# Fewer pixels than this are specks of the cut-out edge, not a letter or a line that would vanish.
MIN_VANISHING_PIXELS = 300


def vanishing_ink(raw: bytes, color: str) -> int:
    """Pixels of ink that would vanish on a `color` shirt: near-white (white shirt) or near-black (black shirt) shapes
    lying on the bare fabric, i.e. surrounded mostly by transparency, like letters cut free of their panel.

    Ink of that color inside the picture (dark trees in a photo, a black panel the print keeps) borders other ink and
    is not counted. 5929: a cut-out that dropped the black strip under white «SHADOW PROJECT» had 28-39 such letters
    on white (3900-6600 px); the files that kept the strip had none, on either fabric.
    """
    from scipy import ndimage

    rgba = np.asarray(Image.open(io.BytesIO(raw)).convert("RGBA")).astype(int)
    alpha, rgb = rgba[..., 3], rgba[..., :3]
    bare = alpha < 30
    ink = (alpha > 200) & ((rgb.min(-1) > 215) if color == "white" else (rgb.max(-1) < 45))
    labels, _ = ndimage.label(ink)
    lost = 0
    for index, box in enumerate(ndimage.find_objects(labels), 1):
        box = tuple(slice(max(s.start - 3, 0), s.stop + 3) for s in box)
        shape = labels[box] == index
        ring = ndimage.binary_dilation(shape, iterations=3) & ~shape & ~ink[box]
        if ring.any() and (ring & bare[box]).sum() > ring.sum() / 2:
            lost += int(shape.sum())
    return lost

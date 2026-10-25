"""Local check whether a print has ink that would vanish on the shirt fabric."""

import io

from PIL import Image


def vanishing_ink(png, color, share=0.04):
    """True when enough opaque ink is near-white on white or near-black on black fabric."""
    im = Image.open(io.BytesIO(png)).convert("RGBA")
    im.thumbnail((512, 512))
    opaque = vanishing = 0
    for r, g, b, a in im.getdata():
        if a < 128:
            continue
        opaque += 1
        light = (r * 299 + g * 587 + b * 114) // 1000
        neutral = max(r, g, b) - min(r, g, b) < 30
        if neutral and (light > 225 if color == "white" else light < 40):
            vanishing += 1
    return bool(opaque) and vanishing / opaque > share

"""Calibrated print placement; AI is responsible only for fabric finish."""

import hashlib
import io
import json
import math
from pathlib import Path

import numpy as np
from PIL import Image

from printflow.domain.errors import PermanentError
from printflow.products.shopper.infrastructure.gallery.geometry import load_print, place_print
from printflow.wb_studio.paths import ASSETS, ROOT

DEFAULT_DIR = ASSETS / "hero"


def load_calibration(config=None):
    filename = (config or {}).get("hero_calibration", "assets/hero/calibration.json")
    path = Path(filename)
    if not path.is_absolute():
        path = ROOT / path
    return json.loads(path.read_text(encoding="utf-8")), path.parent


def placement_geometry(art_size, template_size, calibration):
    """Shared orthogonal garment basis, independent of colour and artwork content."""
    w, h = template_size
    rw, rh = calibration["reference_size"]
    scale = w / rw
    if abs(w / h - rw / rh) > 0.001:
        raise PermanentError("Hero template aspect differs from calibration")
    px_per_cm = calibration["body_width_reference_px"] / calibration["shirt_body_width_cm"] * scale
    width = calibration["print_width_cm"] * px_per_cm
    height = width * art_size[1] / art_size[0]
    fit = min(1, calibration["max_print_height_cm"] * px_per_cm / height)
    width *= fit
    height *= fit
    angle = math.radians(calibration["angle_degrees"])
    across = np.array([math.cos(angle), -math.sin(angle)])
    down = np.array([math.sin(angle), math.cos(angle)])
    top = np.array(calibration["top_center"]) * [w, h]
    corners = np.array(
        [
            top - across * width / 2,
            top + across * width / 2,
            top + across * width / 2 + down * height,
            top - across * width / 2 + down * height,
        ]
    )
    if np.any(corners < 0) or np.any(corners[:, 0] >= w) or np.any(corners[:, 1] >= h):
        raise PermanentError("Calibrated hero print extends outside the image")
    return {
        "corners_px": corners.tolist(),
        "top_center_px": top.tolist(),
        "bottom_center_px": (top + down * height).tolist(),
        "angle_degrees": calibration["angle_degrees"],
        "width_px": width,
        "height_px": height,
        "width_cm": width / px_per_cm,
        "height_cm": height / px_per_cm,
        "height_limited": fit < 1,
    }


def prepare_hero(art, color, config=None):
    calibration, root = load_calibration(config)
    spec = calibration["templates"][color]
    filename = (config or {}).get("hero_templates", {}).get(color, str(root / spec["filename"]))
    path = Path(filename)
    if not path.is_absolute():
        path = ROOT / path
    template = path.read_bytes()
    if hashlib.sha256(template).hexdigest() != spec["sha256"]:
        raise PermanentError("Hero template changed: recalibrate before placing prints")
    base = Image.open(io.BytesIO(template)).convert("RGB")
    artwork = load_print(io.BytesIO(art))
    if not artwork.getchannel("A").getbbox():
        raise PermanentError("Empty hero artwork")
    geometry = placement_geometry(artwork.size, base.size, calibration)
    # Exactly opaque ink: no precomputed fold warp or lighting, reserved for the model.
    rendered = place_print(base, artwork, geometry["corners_px"], artwork.width / artwork.height, shade=0, opacity=1)
    out = io.BytesIO()
    rendered.save(out, format="PNG")
    return out.getvalue(), geometry

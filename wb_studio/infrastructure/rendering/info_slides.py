"""Two shared, typeset information slides: product features and the size chart.

The slides are rendered once by scripts/generate_wb_information.py and reused by every card.
"""

import hashlib
import io
import json
import math
import os
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from printflow.domain.errors import RetryLater
from printflow.wb_studio.paths import ASSETS

INFORMATION_DIR = ASSETS / "information"
GARMENTS_DIR = ASSETS / "garments"
SLIDE_FILES = {4: "05-fit.png", 5: "06-size.png"}
INFORMATION_VERSION = 5

ACCENT = "#A77954"
INK = "#171B1A"
BACKGROUND = "#FCFBF8"
GRID = "#79736B"
RULE = "#D9CABB"
ROW_FILL = "#F2EEE8"


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    windows = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / ("arialbd.ttf" if bold else "arial.ttf")
    linux = Path("/usr/share/fonts/truetype/dejavu") / ("DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf")
    return ImageFont.truetype(str(next(path for path in (windows, linux) if path.exists())), size)


def png(image: Image.Image) -> bytes:
    out = io.BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


@lru_cache(maxsize=2)
def garment_cutout(color: str) -> Image.Image:
    """The real photographed blank shirt, cut out from its plain background."""
    import numpy as np
    from scipy import ndimage

    with Image.open(GARMENTS_DIR / f"{color}.png") as source:
        image = source.convert("RGB")
    pixels = np.asarray(image, dtype=float)
    light = pixels.mean(axis=2)
    spread = pixels.max(axis=2) - pixels.min(axis=2)
    mask = ((light > 170) & (spread < 32)) if color == "white" else ((light < 85) & (spread < 42))
    labels, count = ndimage.label(ndimage.binary_opening(mask, iterations=2))
    if not count:
        raise RuntimeError("Не удалось выделить футболку для инфографики")
    sizes = np.bincount(labels.ravel())
    sizes[0] = 0
    mask = ndimage.binary_fill_holes(ndimage.binary_closing(labels == sizes.argmax(), iterations=4))
    alpha = Image.fromarray((mask * 255).astype("uint8")).filter(ImageFilter.GaussianBlur(1))
    image = image.convert("RGBA")
    image.putalpha(alpha)
    bbox = alpha.getbbox()
    if not bbox:
        raise RuntimeError("Пустая маска футболки")
    return image.crop(bbox)


def paste_garment(image: Image.Image, color: str, box: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    shirt = garment_cutout(color).copy()
    shirt.thumbnail((box[2], box[3]), Image.Resampling.LANCZOS)
    x = box[0] + (box[2] - shirt.width) // 2
    y = box[1] + (box[3] - shirt.height) // 2
    shadow = Image.new("RGBA", image.size)
    ink = Image.new("RGBA", shirt.size, (0, 0, 0, 0))
    ink.putalpha(shirt.getchannel("A").point(lambda a: int(a * 0.18)))
    shadow.alpha_composite(ink, (x + 10, y + 18))
    image.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(14)))
    image.alpha_composite(shirt, (x, y))
    return x, y, shirt.width, shirt.height


def measure_arrow(draw: ImageDraw.ImageDraw, start, end, color: str) -> None:
    draw.line((start, end), fill=color, width=4)
    angle = math.atan2(end[1] - start[1], end[0] - start[0])
    for point, direction in ((start, angle), (end, angle + math.pi)):
        draw.polygon(
            [
                point,
                (point[0] + 17 * math.cos(direction + 0.4), point[1] + 17 * math.sin(direction + 0.4)),
                (point[0] + 17 * math.cos(direction - 0.4), point[1] + 17 * math.sin(direction - 0.4)),
            ],
            fill=color,
        )


def feature_icon(draw: ImageDraw.ImageDraw, x: int, y: int, kind: int, color: str) -> None:
    draw.ellipse((x, y, x + 102, y + 102), outline=color, width=3)
    if kind == 0:  # cotton
        for box in [
            (x + 27, y + 28, x + 58, y + 62),
            (x + 45, y + 17, x + 77, y + 53),
            (x + 55, y + 37, x + 87, y + 70),
        ]:
            draw.ellipse(box, outline=color, width=3)
        draw.line((x + 53, y + 53, x + 53, y + 84), fill=color, width=3)
        draw.line((x + 53, y + 70, x + 35, y + 57), fill=color, width=3)
    elif kind == 1:  # straight cut
        points = [
            (x + 32, y + 25), (x + 42, y + 32), (x + 60, y + 32), (x + 70, y + 25), (x + 88, y + 43),
            (x + 76, y + 57), (x + 68, y + 51), (x + 68, y + 80), (x + 34, y + 80), (x + 34, y + 51),
            (x + 26, y + 57), (x + 14, y + 43),
        ]  # fmt: skip
        draw.line(points + [points[0]], fill=color, width=3, joint="curve")
    elif kind == 2:  # printer
        draw.rounded_rectangle((x + 22, y + 37, x + 82, y + 72), radius=4, outline=color, width=3)
        draw.rectangle((x + 34, y + 20, x + 70, y + 42), outline=color, width=3)
        draw.rectangle((x + 33, y + 56, x + 71, y + 85), outline=color, width=3)
        draw.line((x + 40, y + 66, x + 63, y + 66), fill=color, width=3)
    else:  # durability
        draw.arc((x + 22, y + 19, x + 82, y + 80), 10, 340, fill=color, width=3)
        draw.line((x + 30, y + 78, x + 79, y + 28), fill=color, width=3)
        draw.line((x + 45, y + 63, x + 44, y + 43), fill=color, width=3)


def draw_features(image: Image.Image, data: dict, color: str) -> None:
    paste_garment(image, color, (675, 310, 690, 990))
    draw = ImageDraw.Draw(image)
    features = [
        (data["composition"], "Мягкий, дышащий\nи приятный к телу."),
        ("ПРЯМОЙ КРОЙ", "Свободный крой для\nкомфорта и свободы\nдвижений."),
        (data["printing"], "Яркие цвета, чёткие детали\nи высокая стойкость."),
        ("ПРОЧНОСТЬ И КОМФОРТ", "Ткань сохраняет форму и цвет\nдаже после множества стирок."),
    ]
    for i, (heading, text) in enumerate(features):
        y = 355 + i * 265
        feature_icon(draw, 60, y, i, ACCENT)
        draw.text((190, y + 4), heading, font=font(36 if i < 3 else 31, True), fill=ACCENT)
        draw.multiline_text((190, y + 64), text, font=font(30), fill=INK, spacing=10)


def draw_size_chart(image: Image.Image, data: dict, color: str) -> None:
    draw = ImageDraw.Draw(image)
    draw.text((65, 304), "Все измерения указаны в сантиметрах.", font=font(30), fill=INK)
    columns = [75, 250, 395, 540]
    y = 422
    for heading, x in zip(["РАЗМЕР", "A", "B", "C"], columns, strict=False):
        draw.text((x, y), heading, font=font(27 if x == 75 else 36, True), fill=ACCENT)
    for label, x in zip(["ДЛИНА", "ШИРИНА", "РУКАВ"], columns[1:], strict=False):
        draw.text((x - 12, y + 51), label, font=font(23), fill=INK)
    y += 105
    rows = data["measurements"]
    for i, row in enumerate(rows):
        if i % 2 == 0:
            draw.rounded_rectangle((60, y - 6, 650, y + 66), radius=9, fill=ROW_FILL)
        for value, x in zip(row, columns, strict=False):
            draw.text((x, y + 7), str(value), font=font(33, True), fill=INK)
        y += 77
    # Continuous grid across the header and all measurement rows.
    table_top, table_header = 407, 527
    table_bottom = table_header + 77 * len(rows)
    for x in (60, 220, 365, 510, 650):
        draw.line((x, table_top, x, table_bottom), fill=GRID, width=2)
    for line_y in [table_top, table_header] + [table_header + 77 * i for i in range(1, len(rows) + 1)]:
        draw.line((60, line_y, 650, line_y), fill=GRID, width=2)

    x0, y0, width, height = paste_garment(image, color, (665, 430, 515, 750))
    draw = ImageDraw.Draw(image)
    marks = "white" if color == "black" else INK
    for start, end in [((0.60, 0.13), (0.60, 0.95)), ((0.20, 0.43), (0.81, 0.43)), ((0.74, 0.07), (0.93, 0.27))]:
        measure_arrow(
            draw, (x0 + start[0] * width, y0 + start[1] * height), (x0 + end[0] * width, y0 + end[1] * height), marks
        )
    for label, rx, ry in [("A", 0.63, 0.70), ("B", 0.42, 0.45), ("C", 0.80, 0.30)]:
        draw.text((x0 + rx * width, y0 + ry * height), label, font=font(28, True), fill=marks)
    for i, (letter, text) in enumerate([("A", "длина изделия"), ("B", "ширина изделия"), ("C", "длина рукава")]):
        line_y = 1170 + i * 55
        draw.text((690, line_y), letter, font=font(30, True), fill=ACCENT)
        draw.text((728, line_y), text, font=font(28), fill=INK)


def build_info_slide(index: int, color: str, config: dict) -> bytes:
    """index 4: product features, index 5: size chart."""
    data = config["information"]
    color = data.get("garment_color", color)
    image = Image.new("RGBA", (1200, 1600), BACKGROUND)
    draw = ImageDraw.Draw(image)
    title = "ХАРАКТЕРИСТИКИ\nТОВАРА" if index == 4 else "РАЗМЕРНАЯ\nСЕТКА"
    draw.multiline_text((60, 60), title, font=font(78, True), fill=INK, spacing=0)
    draw.line((65, 267, 205, 267), fill=ACCENT, width=5)
    if index == 4:
        draw_features(image, data, color)
    else:
        draw_size_chart(image, data, color)
    draw = ImageDraw.Draw(image)
    draw.line((65, 1425, 1135, 1425), fill=RULE, width=2)
    if index == 5:
        draw.text((65, 1460), f"Допустимое отклонение ± {data['tolerance_cm']} см", font=font(28), fill=INK)
        draw.text((735, 1460), "100% хлопок • DTF", font=font(28), fill=ACCENT)
    else:
        draw.text((65, 1460), "100% ХЛОПОК   /   ПРЯМОЙ КРОЙ   /   DTF-ПЕЧАТЬ", font=font(28, True), fill=ACCENT)
    return png(image.convert("RGB"))


def information_signature(config: dict) -> str:
    payload = {"information": config["information"], "version": INFORMATION_VERSION}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def check_information(config: dict) -> None:
    try:
        manifest = json.loads((INFORMATION_DIR / "manifest.json").read_text(encoding="utf-8"))
        if manifest.get("source") != "user" and manifest["signature"] != information_signature(config):
            raise ValueError("Information configuration changed")
        for color in config["colors"]:
            for name in SLIDE_FILES.values():
                with Image.open(INFORMATION_DIR / color / name) as image:
                    image.verify()
    except (OSError, KeyError, ValueError) as exc:
        raise RetryLater(
            "Подготовьте общие слайды: python -m printflow.scripts.generate_wb_information. " + str(exc),
            delay_sec=300,
        ) from exc


def info_slide(index: int, color: str, config: dict) -> bytes:
    check_information({**config, "colors": [color]})
    return (INFORMATION_DIR / color / SLIDE_FILES[index]).read_bytes()

"""Оформление слайдов: палитра, шрифты, холст с примитивами (плашки, иконки, стрелки)."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from printflow.services.gallery.canvas import TextCanvas

FONTS_DIR = Path(__file__).resolve().parents[2] / "assets" / "fonts"

# Палитра всех слайдов
CREAM = (245, 238, 228)
INK = (43, 33, 26)
MUTED = (120, 104, 90)
ACCENT = (196, 134, 52)
DARK = (74, 52, 38)
WHITE = (255, 255, 255)

# Шрифт — Montserrat (в Docker из fonts-montserrat), локально Segoe UI;
# свои можно положить в shopper/assets/fonts/{Regular,SemiBold,Bold,Black}.ttf.
_FONT_DIRS = [FONTS_DIR, Path("/usr/share/fonts"), Path("C:/Windows/Fonts")]
_FONT_FILES = {
    "regular": ["Regular.ttf", "Montserrat-Medium.*", "segoeui.ttf", "DejaVuSans.ttf"],
    "semibold": ["SemiBold.ttf", "Montserrat-SemiBold.*", "seguisb.ttf", "DejaVuSans-Bold.ttf"],
    "bold": ["Bold.ttf", "Montserrat-Bold.*", "segoeuib.ttf", "DejaVuSans-Bold.ttf"],
    "black": ["Black.ttf", "Montserrat-ExtraBold.*", "seguibl.ttf", "DejaVuSans-Bold.ttf"],
}


@lru_cache(maxsize=8)
def _font_path(weight: str) -> str:
    for name in _FONT_FILES[weight]:
        for base in _FONT_DIRS:
            if base.is_dir():
                found = next(iter(sorted(base.rglob(name))), None)
                if found:
                    return str(found)
    raise RuntimeError("Не найден шрифт с кириллицей: положите TTF в shopper/assets/fonts/")


@lru_cache(maxsize=256)
def font(size: float, weight: str = "regular") -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(_font_path(weight), max(8, int(size)))


class Canvas(TextCanvas):
    font = staticmethod(font)
    ink = INK
    text_spacing = 1.12


    def wrap(self, text: str, f, max_w: float) -> list[str]:
        lines: list[str] = []
        for para in text.split("\n"):
            cur = ""
            for word in para.split():
                probe = f"{cur} {word}".strip()
                if cur and self.text_w(probe, f) > max_w:
                    lines.append(cur)
                    cur = word
                else:
                    cur = probe
            lines.append(cur)
        return lines



    def pill(self, x: float, y: float, text: str, f, *, fill=WHITE, color=INK, anchor: str = "l") -> tuple[float, float]:
        """Плашка-таблетка. anchor: l — x левый край, m — x центр. Возвращает (w, h)."""
        w = self.text_w(text, f) + f.size * 1.8
        h = f.size * 2.1
        if anchor == "m":
            x -= w / 2
        self.draw.rounded_rectangle([x, y, x + w, y + h], radius=h / 2, fill=fill)
        self.draw.text((x + w / 2, y + h / 2), text, font=f, fill=color, anchor="mm")
        return w, h

    def pills_row(self, cx: float, y: float, items: list[str], f, **kw) -> float:
        """Ряд плашек по центру cx; возвращает y снизу."""
        gap = self.u * 16
        widths = [self.text_w(t, f) + f.size * 1.8 for t in items]
        x = cx - (sum(widths) + gap * (len(items) - 1)) / 2
        h = 0.0
        for text, w in zip(items, widths):
            _, h = self.pill(x, y, text, f, **kw)
            x += w + gap
        return y + h

    def icon(self, kind: str, cx: float, cy: float, r: float) -> None:
        """Круглая иконка: белый круг, линия акцентным цветом."""
        self.draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=WHITE)
        lw = max(2, int(r * 0.09))
        d, s, col = self.draw, r * 0.5, ACCENT
        if kind == "leaf":  # лист по диагонали: линза из двух дуг, прожилка и черенок
            axis, normal = np.array([1.0, -1.0]) / np.sqrt(2), np.array([1.0, 1.0]) / np.sqrt(2)
            ts = np.linspace(-1, 1, 24)
            side = [np.array([cx, cy]) + axis * t * s * 1.05 + normal * (1 - t * t) * s * 0.5 for t in ts]
            other = [np.array([cx, cy]) + axis * t * s * 1.05 - normal * (1 - t * t) * s * 0.5 for t in ts[::-1]]
            d.line([tuple(p) for p in side + other + side[:1]], fill=col, width=lw, joint="curve")
            d.line([(cx - axis[0] * s * 1.45, cy - axis[1] * s * 1.45), (cx + axis[0] * s * 0.8, cy + axis[1] * s * 0.8)],
                   fill=col, width=lw)
        elif kind == "brush":
            d.ellipse([cx - s, cy - s * 0.85, cx + s, cy + s * 0.85], outline=col, width=lw)
            for dx, dy in ((-0.45, -0.3), (0.05, -0.5), (0.5, -0.15)):
                d.ellipse([cx + dx * s - lw, cy + dy * s - lw, cx + dx * s + lw, cy + dy * s + lw], fill=col)
            d.ellipse([cx - s * 0.1, cy + s * 0.15, cx + s * 0.45, cy + s * 0.6], outline=col, width=lw)
        elif kind == "ruler":
            d.rounded_rectangle([cx - s * 1.1, cy - s * 0.4, cx + s * 1.1, cy + s * 0.4], radius=lw, outline=col, width=lw)
            for i in range(1, 6):
                x = cx - s * 1.1 + i * s * 2.2 / 6
                d.line([(x, cy - s * 0.4), (x, cy - s * (0.05 if i % 2 else -0.1))], fill=col, width=lw)
        elif kind == "bag":
            d.rounded_rectangle([cx - s * 0.8, cy - s * 0.3, cx + s * 0.8, cy + s * 0.95], radius=lw, outline=col, width=lw)
            d.arc([cx - s * 0.45, cy - s * 0.95, cx + s * 0.45, cy + s * 0.35], 180, 360, fill=col, width=lw)
        else:  # check
            d.line([(cx - s * 0.6, cy), (cx - s * 0.15, cy + s * 0.45), (cx + s * 0.65, cy - s * 0.45)],
                   fill=col, width=lw, joint="curve")

    def arrow(self, p0, p1, width: float, color=INK):
        self.draw.line([p0, p1], fill=color, width=int(width))
        v = np.array(p1, float) - np.array(p0, float)
        v /= np.linalg.norm(v) or 1.0
        n = np.array([-v[1], v[0]])
        head = width * 5
        for tip, d in ((p1, v), (p0, -v)):
            t = np.array(tip, float)
            self.draw.polygon([tuple(t), tuple(t - d * head + n * head * 0.5), tuple(t - d * head - n * head * 0.5)],
                              fill=color)

    def vertical_label(self, text: str, f, x: float, cy: float, color=INK) -> None:
        tw = int(self.text_w(text, f)) + 8
        tmp = Image.new("RGBA", (tw, int(f.size * 1.4)), (0, 0, 0, 0))
        ImageDraw.Draw(tmp).text((tw / 2, tmp.height / 2), text, font=f, fill=color, anchor="mm")
        tmp = tmp.rotate(90, expand=True)
        self.img.alpha_composite(tmp, (int(x), int(cy - tmp.height / 2)))



def care_icon(c: Canvas, kind: str, cx: float, cy: float, s: float):
    lw = max(2, int(s * 0.08))
    d = c.draw
    if kind == "wash30":
        d.polygon([(cx - s * 0.62, cy - s * 0.3), (cx + s * 0.62, cy - s * 0.3),
                   (cx + s * 0.48, cy + s * 0.45), (cx - s * 0.48, cy + s * 0.45)], outline=INK, width=lw)
        d.line([(cx - s * 0.62, cy - s * 0.3), (cx - s * 0.3, cy - s * 0.46), (cx, cy - s * 0.3),
                (cx + s * 0.3, cy - s * 0.46), (cx + s * 0.62, cy - s * 0.3)], fill=INK, width=lw)
        d.text((cx, cy + s * 0.1), "30", font=font(s * 0.42, "bold"), fill=INK, anchor="mm")
        return
    if kind == "no_bleach":
        d.polygon([(cx, cy - s * 0.5), (cx + s * 0.58, cy + s * 0.45), (cx - s * 0.58, cy + s * 0.45)],
                  outline=INK, width=lw)
    elif kind == "no_tumble":
        d.rectangle([cx - s * 0.5, cy - s * 0.5, cx + s * 0.5, cy + s * 0.5], outline=INK, width=lw)
        d.ellipse([cx - s * 0.34, cy - s * 0.34, cx + s * 0.34, cy + s * 0.34], outline=INK, width=lw)
    elif kind == "iron_low":
        d.polygon([(cx - s * 0.6, cy + s * 0.35), (cx + s * 0.6, cy + s * 0.35), (cx + s * 0.45, cy - s * 0.2),
                   (cx - s * 0.2, cy - s * 0.2)], outline=INK, width=lw)
        d.line([(cx - s * 0.05, cy - s * 0.2), (cx - s * 0.05, cy - s * 0.42), (cx + s * 0.5, cy - s * 0.42)],
               fill=INK, width=lw)
        d.ellipse([cx - s * 0.07, cy + s * 0.02, cx + s * 0.07, cy + s * 0.16], fill=INK)
        return
    elif kind == "no_dryclean":
        d.ellipse([cx - s * 0.5, cy - s * 0.5, cx + s * 0.5, cy + s * 0.5], outline=INK, width=lw)
    else:
        d.ellipse([cx - s * 0.2, cy - s * 0.2, cx + s * 0.2, cy + s * 0.2], fill=INK)
        return
    k = s * 0.62
    d.line([(cx - k, cy - k), (cx + k, cy + k)], fill=ACCENT, width=lw)
    d.line([(cx - k, cy + k), (cx + k, cy - k)], fill=ACCENT, width=lw)

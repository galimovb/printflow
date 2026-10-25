"""Оформление слайдов ковриков: холст с примитивами (плашки, иконки), шрифты из assets/fonts."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from printflow.services.gallery.canvas import TextCanvas


INK = (24, 22, 46)          # заголовки
MUTED = (96, 94, 122)       # подписи
ACCENT = (110, 84, 255)     # фиолетовый: иконки, плашки, полоса под заголовком
LIME = (214, 255, 92)       # акцентная плашка на тёмном
CARD = (27, 25, 52)         # тёмные карточки
WHITE = (255, 255, 255)
PAPER = (244, 243, 249)     # фон слайдов без сцены

# Стиль карточки (как в референсе: тёмные панели, двухцветные заголовки, плитки с иконками)
DARK = (22, 24, 31)         # графит: панели, плитки
BLUE = (59, 91, 255)        # ультрамарин: акцент
SOFT = (236, 238, 245)      # светлые плитки
INK2 = (22, 24, 31)

FONTS_DIR = Path(__file__).resolve().parents[2] / "assets" / "fonts"
_WEIGHTS = {"regular": 500, "semibold": 600, "bold": 700, "black": 900}


@lru_cache(maxsize=256)
def font(size: float, weight: str = "regular") -> ImageFont.FreeTypeFont:
    """Montserrat коврика (assets/fonts, переменная толщина): regular | semibold | bold | black."""
    f = ImageFont.truetype(str(FONTS_DIR / "Montserrat[wght].ttf"), max(8, int(size)))
    f.set_variation_by_axes([_WEIGHTS[weight]])
    return f


@lru_cache(maxsize=256)
def cond(size: float, weight: str = "bold") -> ImageFont.FreeTypeFont:
    """Узкий гротеск для заголовков и подписей: Oswald (mousepad/assets/fonts), иначе Bahnschrift Condensed
    (Windows, для локального превью), иначе DejaVu Sans Condensed."""
    size = max(8, int(size))
    wght = {"regular": 400, "medium": 500, "semibold": 600, "bold": 700}[weight]
    for path in sorted(FONTS_DIR.glob("Oswald*.ttf")):
        f = ImageFont.truetype(str(path), size)
        try:
            f.set_variation_by_axes([wght])
        except (OSError, ValueError):
            pass
        return f
    win = Path("C:/Windows/Fonts/bahnschrift.ttf")
    if win.is_file():
        f = ImageFont.truetype(str(win), size)
        f.set_variation_by_axes([min(wght, 700), 75])
        return f
    for base in (Path("/usr/share/fonts"),):
        found = next(iter(sorted(base.rglob("DejaVuSansCondensed-Bold.ttf"))), None) if base.is_dir() else None
        if found:
            return ImageFont.truetype(str(found), size)
    return font(size, "black")


__all__ = ["ACCENT", "BLUE", "CARD", "DARK", "INK", "LIME", "MUTED", "PAPER", "SOFT", "WHITE", "Canvas", "cond", "font"]


class Canvas(TextCanvas):
    font = staticmethod(font)
    ink = INK
    text_spacing = 1.08

    # ───────── текст ─────────




    def title(self, x: float, y: float, text: str, max_size: float, max_w: float, *, fill=INK,
              anchor: str = "la", bar: bool = True) -> float:
        """Крупный заголовок + короткая фиолетовая полоса под ним; возвращает y под полосой."""
        f = self.fit(text, max_size, max_w)
        y = self.text((x, y), text, f, fill=fill, anchor=anchor, spacing=1.0)
        if bar:
            bw, bh = self.u * 110, self.u * 12
            bx = x - bw / 2 if anchor.startswith("m") else x
            y += f.size * 0.34  # ниже хвостов букв (Д, Щ, Ц)
            self.draw.rounded_rectangle([bx, y, bx + bw, y + bh], radius=bh / 2, fill=ACCENT)
            y += bh
        return y

    # ───────── плашки и карточки ─────────

    def pill(self, x: float, y: float, text: str, f, *, fill=ACCENT, color=WHITE, anchor: str = "l",
             icon: str | None = None) -> tuple[float, float]:
        pad = f.size * 0.95
        icon_w = f.size * 1.35 if icon else 0.0
        w = self.text_w(text, f) + 2 * pad + icon_w
        h = f.size * 2.2
        if anchor == "m":
            x -= w / 2
        self.draw.rounded_rectangle([x, y, x + w, y + h], radius=h * 0.32, fill=fill)
        if icon:
            self.icon(icon, x + pad + f.size * 0.45, y + h / 2, f.size * 0.55, color=color, ring=False)
        self.draw.text((x + pad + icon_w, y + h / 2), text, font=f, fill=color, anchor="lm")
        return w, h

    def pills_row(self, cx: float, y: float, items: list[str], f, **kw) -> float:
        gap = self.u * 18
        widths = [self.text_w(t, f) + 2 * f.size * 0.95 for t in items]
        x = cx - (sum(widths) + gap * (len(items) - 1)) / 2
        h = 0.0
        for text, w in zip(items, widths):
            _, h = self.pill(x, y, text, f, **kw)
            x += w + gap
        return y + h

    def card(self, box: list[float], fill=CARD, radius: float | None = None) -> None:
        self.draw.rounded_rectangle(box, radius=radius or self.u * 34, fill=fill)

    # ───────── иконки (линия; ring — в круге) ─────────

    def icon(self, kind: str, cx: float, cy: float, r: float, *, color=ACCENT, ring: bool = True,
             ring_fill=WHITE) -> None:
        d = self.draw
        if ring:
            d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=ring_fill)
            s = r * 0.52
        else:
            s = r
        lw = max(2, int(s * 0.17))
        if kind == "size":  # стрелки в углы
            for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
                tip = (cx + sx * s, cy + sy * s)
                d.line([(cx + sx * s * 0.25, cy + sy * s * 0.25), tip], fill=color, width=lw)
                d.line([tip, (tip[0] - sx * s * 0.5, tip[1])], fill=color, width=lw)
                d.line([tip, (tip[0], tip[1] - sy * s * 0.5)], fill=color, width=lw)
        elif kind == "layers":
            for k in (-0.45, 0.0, 0.45):
                y = cy + k * s
                d.polygon([(cx - s, y), (cx, y - s * 0.38), (cx + s, y), (cx, y + s * 0.38)], outline=color,
                          width=max(2, lw - 1))
        elif kind == "monitor":
            d.rounded_rectangle([cx - s, cy - s * 0.75, cx + s, cy + s * 0.45], radius=lw, outline=color, width=lw)
            d.line([(cx, cy + s * 0.45), (cx, cy + s * 0.8)], fill=color, width=lw)
            d.line([(cx - s * 0.45, cy + s * 0.85), (cx + s * 0.45, cy + s * 0.85)], fill=color, width=lw)
        elif kind == "book":
            d.line([(cx, cy - s * 0.55), (cx, cy + s * 0.75)], fill=color, width=lw)
            d.polygon([(cx, cy - s * 0.55), (cx - s, cy - s * 0.75), (cx - s, cy + s * 0.55), (cx, cy + s * 0.75)],
                      outline=color, width=lw)
            d.polygon([(cx, cy - s * 0.55), (cx + s, cy - s * 0.75), (cx + s, cy + s * 0.55), (cx, cy + s * 0.75)],
                      outline=color, width=lw)
        elif kind == "gift":
            d.rectangle([cx - s * 0.85, cy - s * 0.2, cx + s * 0.85, cy + s * 0.85], outline=color, width=lw)
            d.rectangle([cx - s, cy - s * 0.55, cx + s, cy - s * 0.2], outline=color, width=lw)
            d.line([(cx, cy - s * 0.55), (cx, cy + s * 0.85)], fill=color, width=lw)
            d.arc([cx - s * 0.6, cy - s * 1.0, cx, cy - s * 0.45], 180, 360, fill=color, width=lw)
            d.arc([cx, cy - s * 1.0, cx + s * 0.6, cy - s * 0.45], 180, 360, fill=color, width=lw)
        elif kind == "shield":
            d.polygon([(cx, cy - s), (cx + s * 0.85, cy - s * 0.6), (cx + s * 0.7, cy + s * 0.4), (cx, cy + s),
                       (cx - s * 0.7, cy + s * 0.4), (cx - s * 0.85, cy - s * 0.6)], outline=color, width=lw)
            d.line([(cx - s * 0.35, cy), (cx - s * 0.05, cy + s * 0.3), (cx + s * 0.4, cy - s * 0.3)],
                   fill=color, width=lw)
        elif kind == "hand":  # ладонь: четыре пальца и большой
            for i, k in enumerate((-0.55, -0.18, 0.18, 0.55)):
                top = cy - s * (0.75 if i in (1, 2) else 0.6)
                d.line([(cx + k * s, cy), (cx + k * s, top)], fill=color, width=lw)
            d.rounded_rectangle([cx - s * 0.7, cy - s * 0.1, cx + s * 0.7, cy + s * 0.9], radius=s * 0.35,
                                outline=color, width=lw)
            d.line([(cx - s * 0.7, cy + s * 0.25), (cx - s * 1.0, cy - s * 0.15)], fill=color, width=lw)
        elif kind == "cursor":
            d.polygon([(cx - s * 0.55, cy - s), (cx + s * 0.6, cy + s * 0.15), (cx + s * 0.05, cy + s * 0.25),
                       (cx - s * 0.2, cy + s * 0.85)], outline=color, width=lw)
        elif kind == "grip":  # сетка рельефа
            for k in np.linspace(-0.8, 0.8, 4):
                d.line([(cx - s * 0.8, cy + k * s), (cx + s * 0.8, cy + k * s)], fill=color, width=max(2, lw - 1))
                d.line([(cx + k * s, cy - s * 0.8), (cx + k * s, cy + s * 0.8)], fill=color, width=max(2, lw - 1))
        elif kind == "target":  # прицел
            d.ellipse([cx - s * 0.8, cy - s * 0.8, cx + s * 0.8, cy + s * 0.8], outline=color, width=lw)
            d.ellipse([cx - s * 0.25, cy - s * 0.25, cx + s * 0.25, cy + s * 0.25], fill=color)
            for dx, dy in ((0, -1), (0, 1), (-1, 0), (1, 0)):
                d.line([(cx + dx * s * 0.8, cy + dy * s * 0.8), (cx + dx * s * 1.1, cy + dy * s * 1.1)], fill=color,
                       width=lw)
        elif kind == "waves":  # плавный ход
            for k in (-0.35, 0.35):
                pts = [(cx + x * s, cy + k * s + 0.28 * s * np.sin(x * np.pi * 1.5)) for x in np.linspace(-1, 1, 24)]
                d.line(pts, fill=color, width=lw, joint="curve")
        elif kind == "mouse":
            d.rounded_rectangle([cx - s * 0.55, cy - s * 0.95, cx + s * 0.55, cy + s * 0.95], radius=s * 0.55,
                                outline=color, width=lw)
            d.line([(cx, cy - s * 0.95), (cx, cy - s * 0.3)], fill=color, width=lw)
        elif kind == "palette":
            d.ellipse([cx - s, cy - s * 0.85, cx + s, cy + s * 0.85], outline=color, width=lw)
            for dx, dy in ((-0.45, -0.3), (0.05, -0.5), (0.5, -0.15)):
                d.ellipse([cx + dx * s - lw, cy + dy * s - lw, cx + dx * s + lw, cy + dy * s + lw], fill=color)
            d.ellipse([cx - s * 0.1, cy + s * 0.15, cx + s * 0.4, cy + s * 0.6], outline=color, width=lw)
        elif kind == "sparkle":  # чёткие детали
            d.polygon([(cx, cy - s), (cx + s * 0.22, cy - s * 0.22), (cx + s, cy), (cx + s * 0.22, cy + s * 0.22),
                       (cx, cy + s), (cx - s * 0.22, cy + s * 0.22), (cx - s, cy), (cx - s * 0.22, cy - s * 0.22)],
                      outline=color, width=lw)
        elif kind == "roll":  # свёрнутый коврик
            d.ellipse([cx - s, cy - s * 0.55, cx - s * 0.1, cy + s * 0.55], outline=color, width=lw)
            d.line([(cx - s * 0.55, cy - s * 0.55), (cx + s, cy - s * 0.55)], fill=color, width=lw)
            d.line([(cx - s * 0.55, cy + s * 0.55), (cx + s, cy + s * 0.55)], fill=color, width=lw)
            d.line([(cx + s, cy - s * 0.55), (cx + s, cy + s * 0.55)], fill=color, width=lw)
        else:  # check
            d.line([(cx - s * 0.6, cy), (cx - s * 0.15, cy + s * 0.45), (cx + s * 0.65, cy - s * 0.45)],
                   fill=color, width=lw, joint="curve")


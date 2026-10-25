"""Слайды ковриков в стиле «пастельной инфографики»: персиковый фон с пятнами (из каркаса), жирный заголовок
в две строки, терракотовая плашка с иконкой, кремовый бейдж-пузырь, рукописная заметка с сердечком,
нарисованные стрелки, бейдж в нижнем углу, котик-маскот и слоган внизу.

Тексты — product.json → texts.<слайд>:
  title: [жирная строка, обычная строка]   pill: [иконка, текст]
  bubble: [крупно, мелко]   note: "рукописный\\nтекст"   badge: [иконка, мелко, крупно]   mascot: true|false
Общий слоган — texts.footer. Положение элементов можно сдвинуть: texts.<слайд>.at.<элемент> = [x, y] в u
(1/1000 ширины кадра; высота кадра 3:4 ≈ 1333u).
"""
from __future__ import annotations

import math
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from printflow.products.mousepad.infrastructure.gallery.theme import Canvas

FONTS = Path(__file__).resolve().parents[2] / "assets" / "fonts"
MASCOT = Path(__file__).resolve().parents[2] / "assets" / "mascot.png"

INK = (33, 26, 24)
TERRA = (201, 112, 92)
TERRA_DARK = (176, 88, 70)
CREAM = (255, 246, 240)

DEFAULT_AT = {
    "title": (60, 50), "pill": (60, 0), "bubble": (960, 215), "note": (50, 470), "badge": (40, 1105),
}


@lru_cache(maxsize=128)
def mont(size: float, weight: int = 800) -> ImageFont.FreeTypeFont:
    f = ImageFont.truetype(str(FONTS / "Montserrat[wght].ttf"), max(8, int(size)))
    f.set_variation_by_axes([weight])
    return f


@lru_cache(maxsize=32)
def hand(size: float, weight: int = 600) -> ImageFont.FreeTypeFont:
    f = ImageFont.truetype(str(FONTS / "Caveat[wght].ttf"), max(8, int(size)))
    f.set_variation_by_axes([weight])
    return f


@lru_cache(maxsize=1)
def _mascot() -> Image.Image | None:
    return Image.open(MASCOT).convert("RGBA") if MASCOT.is_file() else None


class Slide(Canvas):
    def at(self, t: dict, name: str) -> tuple[float | None, float]:
        """Позиция элемента в px; x = None — прижать к правому полю (в product.json: "right")."""
        x, y = (t.get("at") or {}).get(name, DEFAULT_AT[name])
        return (None if x == "right" else self.u * x), self.u * y

    def heading(self, x: float, y: float, lines: list[str], max_w: float) -> float:
        """Строка 1 — Montserrat Black, строка 2 — Medium, обе капсом; возвращает y под заголовком."""
        size1, size2 = self.u * 138, self.u * 100
        while size1 > 30 and self.text_w(lines[0].upper(), mont(size1, 900)) > max_w:
            size1 *= 0.96
        if len(lines) > 1:
            while size2 > 24 and self.text_w(lines[1].upper(), mont(size2, 500)) > max_w:
                size2 *= 0.96
        self.draw.text((x, y), lines[0].upper(), font=mont(size1, 900), fill=INK)
        y += size1 * 1.0
        if len(lines) > 1:
            self.draw.text((x, y), lines[1].upper(), font=mont(size2, 500), fill=INK)
            y += size2 * 1.05
        return y

    def pill(self, x: float, y: float, icon: str, text: str) -> float:  # type: ignore[override]
        f = mont(self.u * 31, 600)
        h = self.u * 84
        w = self.u * 150 + self.text_w(text.upper(), f)
        self.draw.rounded_rectangle([x, y, x + w, y + h], radius=h / 2, fill=TERRA)
        self.icon(icon, x + self.u * 62, y + h / 2, self.u * 24, color=CREAM, ring=False)
        self.draw.text((x + self.u * 112, y + h / 2), text.upper(), font=f, fill=CREAM, anchor="lm")
        return y + h

    def bubble(self, right: float, y: float, big: str, small: str) -> tuple[float, float, float, float]:
        """Кремовый бейдж-пузырь, правым краем к right: крупно цифры, ниже мелко; возвращает его рамку."""
        size = self.u * 78  # крупная строка подбирается так, чтобы пузырь не заходил на заголовок
        while size > self.u * 40 and self.text_w(big, mont(size, 800)) > self.u * 250:
            size *= 0.95
        fb, fs = mont(size, 800), mont(self.u * 40, 700)
        w = max(self.text_w(big, fb), self.text_w(small, fs)) + self.u * 100
        x = right - w
        h = fb.size * 1.05 + fs.size * 1.1 + self.u * 70
        self.draw.rounded_rectangle([x, y, x + w, y + h], radius=h * 0.45, fill=CREAM)
        tail = [(x + w * 0.22, y + h - self.u * 8), (x + w * 0.12, y + h + self.u * 46), (x + w * 0.40, y + h - self.u * 8)]
        self.draw.polygon(tail, fill=CREAM)
        self.draw.text((x + w / 2, y + self.u * 36), big, font=fb, fill=INK, anchor="mt")
        self.draw.text((x + w / 2, y + self.u * 36 + fb.size * 1.05), small, font=fs, fill=INK, anchor="mt")
        return x, y, x + w, y + h

    def badge(self, x: float | None, y: float, icon: str, small: str, big: str) -> tuple[float, float, float, float]:
        fs, fb = mont(self.u * 32, 500), mont(self.u * 52, 800)
        w = self.u * 150 + max(self.text_w(small, fs), self.text_w(big.upper(), fb)) + self.u * 50
        h = self.u * 140
        if x is None:
            x = self.W - self.u * 40 - w
        self.draw.rounded_rectangle([x, y, x + w, y + h], radius=self.u * 56, fill=CREAM)
        self.icon(icon, x + self.u * 78, y + h / 2, self.u * 34, color=INK, ring=False)
        self.draw.text((x + self.u * 140, y + h * 0.36), small, font=fs, fill=INK, anchor="lm")
        self.draw.text((x + self.u * 140, y + h * 0.68), big.upper(), font=fb, fill=INK, anchor="lm")
        return x, y, x + w, y + h

    def note(self, x: float, y: float, text: str, angle: float = 8) -> None:
        """Рукописная заметка под наклоном, сердечко и три штриха. Одна строка — сердечко справа от текста
        (заметка низкая, помещается в узкую полосу), несколько — под текстом."""
        f = hand(self.u * 62, 600)
        lines = text.split("\n")
        one_line = len(lines) == 1
        text_w = max(self.text_w(line, f) for line in lines)
        w = int(text_w + self.u * (110 if one_line else 140))
        h = int(f.size * 1.0 * len(lines) + self.u * (30 if one_line else 120))
        layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        ty = self.u * 10
        for line in lines:
            d.text((self.u * 20, ty), line, font=f, fill=INK)
            ty += f.size * 1.0
        if one_line:
            self._heart(d, self.u * 20 + text_w + self.u * 45, self.u * 10 + f.size * 0.55, self.u * 22)
        else:
            self._heart(d, self.u * 40, ty + self.u * 40, self.u * 22)
        rotated = layer.rotate(angle, expand=True, resample=Image.Resampling.BICUBIC)
        self.img.alpha_composite(rotated, (int(x), int(y)))
        cx, cy = x + rotated.width * 0.92, y + self.u * 10
        for k in (-0.9, -0.35, 0.2):  # штрихи «сияния»
            a = math.pi * k
            self.draw.line([(cx + math.cos(a) * self.u * 26, cy + math.sin(a) * self.u * 26),
                            (cx + math.cos(a) * self.u * 52, cy + math.sin(a) * self.u * 52)], fill=TERRA,
                           width=max(3, int(self.u * 5)))

    @staticmethod
    def _heart(d: ImageDraw.ImageDraw, cx: float, cy: float, r: float) -> None:
        pts = []
        for i in range(60):
            t = 2 * math.pi * i / 60
            hx = 16 * math.sin(t) ** 3
            hy = 13 * math.cos(t) - 5 * math.cos(2 * t) - 2 * math.cos(3 * t) - math.cos(4 * t)
            pts.append((cx + hx * r / 16, cy - hy * r / 16))
        d.line(pts + pts[:1], fill=INK, width=max(3, int(r * 0.18)), joint="curve")

    def arrow(self, p0: tuple[float, float], p1: tuple[float, float], bend: float = 0.3, color=TERRA_DARK) -> None:
        """Нарисованная от руки дуга со стрелкой на конце p1."""
        (x0, y0), (x1, y1) = p0, p1
        mx, my = (x0 + x1) / 2, (y0 + y1) / 2
        nx, ny = -(y1 - y0), x1 - x0
        cx, cy = mx + nx * bend, my + ny * bend
        pts = [((1 - s) ** 2 * x0 + 2 * (1 - s) * s * cx + s * s * x1,
                (1 - s) ** 2 * y0 + 2 * (1 - s) * s * cy + s * s * y1) for s in [i / 40 for i in range(41)]]
        lw = max(3, int(self.u * 6))
        self.draw.line(pts, fill=color, width=lw, joint="curve")
        (ax, ay), (bx, by) = pts[-4], pts[-1]
        ang = math.atan2(by - ay, bx - ax)
        for side in (-1, 1):
            a = ang + math.pi + side * 0.55
            self.draw.line([(bx, by), (bx + math.cos(a) * self.u * 36, by + math.sin(a) * self.u * 36)], fill=color,
                           width=lw)

    def mascot(self, side: str = "right") -> None:
        """Котик выглядывает из нижнего угла (над слоганом): side — right | left."""
        img = _mascot()
        if img is None:
            return
        w = int(self.W * 0.27)
        m = img.resize((w, int(img.height * w / img.width)), Image.Resampling.LANCZOS)
        x = self.u * 30 if side == "left" else self.W - w - self.u * 30
        self.img.alpha_composite(m, (int(x), int(self.H - m.height - self.u * 78)))

    def footer(self, text: str) -> None:
        self.draw.text((self.W / 2, self.H - self.u * 40), text, font=mont(self.u * 34, 500), fill=INK, anchor="mb")


def slide(img: Image.Image, t: dict, footer: str = "") -> Image.Image:
    c = Slide(img)
    u = c.u
    x, y = c.at(t, "title")
    y = c.heading(x, y, t["title"], u * (540 if t.get("bubble") else 760))
    if t.get("pill"):
        px, _ = c.at(t, "pill")
        y = c.pill(px, y + u * 18, *t["pill"])
    if t.get("bubble"):
        bx, by = c.at(t, "bubble")
        box = c.bubble(bx, by, *t["bubble"])
        c.arrow((box[0] + (box[2] - box[0]) * 0.75, box[3] + u * 30), (box[0] + (box[2] - box[0]) * 0.35, box[3] + u * 170),
                bend=-0.35)
    if t.get("note"):
        # по умолчанию — одной строкой сразу под плашкой, выше коврика (каркасы оставляют сверху пустую полосу);
        # сдвинуть можно через texts.<слайд>.at.note
        nx, ny = c.at(t, "note") if "note" in (t.get("at") or {}) else (u * 60, y + u * 14)
        c.note(nx, ny, " ".join(t["note"].split()), float(t.get("note_angle", 3)))
    if t.get("badge"):
        gx, gy = c.at(t, "badge")
        box = c.badge(gx, gy, *t["badge"])
        if gx is None:  # бейдж справа — стрелка вверх-влево, к коврику
            c.arrow((box[2] - u * 140, box[1] - u * 20), (box[2] - u * 230, box[1] - u * 150), bend=-0.3)
        else:
            c.arrow((box[0] + u * 140, box[1] - u * 20), (box[0] + u * 230, box[1] - u * 150), bend=0.3)
    if t.get("mascot", True):  # по умолчанию на каждом слайде; "left" — в левый угол, false — без котика
        c.mascot("left" if t.get("mascot") == "left" else "right")
    if footer:
        c.footer(footer)
    return c.result()


SLIDE_LAYOUTS = {name: slide for name in ("hero", "office", "glide", "print", "protect", "base", "compact")}

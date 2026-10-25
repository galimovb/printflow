"""Раскладки слайдов: каждая рассчитана на свободное место своего каркаса (см. scripts/generate_blanks.py)."""
from __future__ import annotations

from PIL import Image

from printflow.products.shopper.infrastructure.gallery.theme import ACCENT, CREAM, DARK, INK, MUTED, WHITE, Canvas, care_icon, font


def slide_hero(img: Image.Image, t: dict) -> Image.Image:
    """Сумка справа на крючке, слева пустая стена: тег, крупный заголовок, 3 преимущества."""
    c = Canvas(img)
    x, max_w = c.u * 70, c.W * 0.42
    y = c.H * 0.055
    _, h = c.pill(x, y, t["tag"].upper(), font(c.u * 34, "bold"), fill=ACCENT, color=WHITE)
    f_title = c.fit(t["title"].upper(), c.u * 125, max_w)
    y = c.text((x, y + h + c.u * 26), t["title"].upper(), f_title, spacing=1.0)
    y += c.u * 50
    r = c.u * 54
    tx = x + 2 * r + c.u * 24
    text_w = c.W * 0.47 - tx  # правее начинается сумка
    f_b = c.fit("\n".join(b for _, b, _ in t["features"]), c.u * 42, text_w, "bold")
    f_r = c.fit("\n".join(s for _, _, s in t["features"]), c.u * 32, text_w, "regular")
    for kind, bold, regular in t["features"]:
        c.icon(kind, x + r, y + r, r)
        c.draw.text((tx, y + r - c.u * 4), bold, font=f_b, fill=INK, anchor="ls")
        c.draw.text((tx, y + r + c.u * 6), regular, font=f_r, fill=MUTED, anchor="lt")
        y += 2 * r + c.u * 34
    return c.result()


def slide_specs(img: Image.Image, t: dict, bag_box: list) -> Image.Image:
    """Сумка в верхней части кадра: стрелки размеров, под ней заголовок и плашки."""
    c = Canvas(img)
    lw = c.u * 2.6
    f_dim = font(c.u * 34, "bold")
    x0, y0, x1, y1 = bag_box
    ya = y1 + c.u * 40
    c.arrow((x0, ya), (x1, ya), lw)
    c.draw.text(((x0 + x1) / 2, ya + c.u * 18), f"{t['width_cm']} см", font=f_dim, fill=INK, anchor="mt")
    xa = x1 + c.u * 45
    c.arrow((xa, y0), (xa, y1), lw)
    c.vertical_label(f"{t['height_cm']} см", f_dim, xa + c.u * 16, (y0 + y1) / 2)
    f_t = c.fit(t["title"], c.u * 82, c.W * 0.86)
    ty = ya + c.u * 120
    c.draw.text((c.W / 2, ty), t["title"], font=f_t, fill=INK, anchor="mt")
    c.pills_row(c.W / 2, ty + f_t.size * 1.45, t["chips"], font(c.u * 36, "semibold"))
    return c.result()


def slide_title_top(img: Image.Image, t: dict) -> Image.Image:
    """Пустая полоса сверху: заголовок по центру и плашки."""
    c = Canvas(img)
    f = c.fit(t["title"], c.u * 84, c.W * 0.88)
    y = c.text((c.W / 2, c.H * 0.045), t["title"], f, anchor="ma", spacing=1.05)
    if t.get("chips"):
        c.pills_row(c.W / 2, y + c.u * 22, t["chips"], font(c.u * 36, "semibold"))
    return c.result()


def slide_title_left(img: Image.Image, t: dict) -> Image.Image:
    """Пустой угол слева сверху: крупный заголовок и пункты с галочками."""
    c = Canvas(img)
    x, max_w = c.u * 70, c.W * 0.36  # правее — ручки на спинке стула
    f = c.fit(t["title"], c.u * 110, max_w)
    y = c.text((x, c.H * 0.05), t["title"], f, spacing=1.0) + c.u * 30
    f_b = c.fit("\n".join(t["bullets"]), c.u * 50, max_w - c.u * 84, "semibold")
    for line in t["bullets"]:
        c.icon("check", x + c.u * 32, y + f_b.size * 0.62, c.u * 32)
        c.draw.text((x + c.u * 84, y), line, font=f_b, fill=INK)
        y += f_b.size * 1.55
    return c.result()


def slide_title_bottom(img: Image.Image, t: dict) -> Image.Image:
    """Пустая полоса снизу: акцентное слово + продолжение, две строки по центру."""
    c = Canvas(img)
    lines = [t["accent"] + " " + t["title"].split("\n")[0], *t["title"].split("\n")[1:]]
    f = c.fit("\n".join(lines), c.u * 80, c.W * 0.88, "bold")
    f_acc = font(f.size, "black")
    y = c.H * 0.955 - f.size * 1.1 * len(lines)
    for i, line in enumerate(lines):
        if i == 0:  # первое слово — акцентом
            rest = line[len(t["accent"]):]
            total = c.text_w(t["accent"], f_acc) + c.text_w(rest, f)
            x = (c.W - total) / 2
            c.draw.text((x, y), t["accent"], font=f_acc, fill=ACCENT)
            c.draw.text((x + c.text_w(t["accent"], f_acc), y), rest, font=f, fill=INK)
        else:
            c.draw.text((c.W / 2, y), line, font=f, fill=INK, anchor="ma")
        y += f.size * 1.1
    return c.result()


def slide_model(img: Image.Image, t: dict) -> Image.Image:
    c = Canvas(img)
    f = font(c.u * 40, "semibold")
    c.pill(c.W / 2, c.H - c.u * 70 - f.size * 2.1, t["caption"], f, fill=DARK, color=WHITE, anchor="m")
    return c.result()


def slide_care(size: tuple[int, int], t: dict) -> Image.Image:
    c = Canvas(Image.new("RGB", size, CREAM))
    mx = c.u * 80
    f_t = c.fit(t["title"], c.u * 84, c.W - 2 * mx)
    c.draw.text((mx, c.H * 0.07), t["title"], font=f_t, fill=INK)
    f_s = font(c.u * 32)
    c.draw.text((mx, c.H * 0.07 + f_t.size * 1.3), t["subtitle"], font=f_s, fill=MUTED)
    y = c.H * 0.22
    box = c.u * 130
    f_r = font(c.u * 34, "semibold")
    step = (c.H * 0.86 - y) / max(1, len(t["rows"]))
    for icon, text in t["rows"]:
        c.draw.rounded_rectangle([mx, y, mx + box, y + box], radius=c.u * 30, fill=WHITE)
        care_icon(c, icon, mx + box / 2, y + box / 2, box * 0.5)
        tx = mx + box + c.u * 44
        lines = c.wrap(text, f_r, c.W - tx - mx)
        c.text((tx, y + box / 2 - len(lines) * f_r.size * 1.2 / 2), "\n".join(lines), f_r, spacing=1.2)
        y += step
    c.pill(c.W / 2, c.H * 0.9, t["footer"], font(c.u * 28, "semibold"), fill=WHITE, color=MUTED, anchor="m")
    return c.result()

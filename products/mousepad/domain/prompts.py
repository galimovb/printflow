"""Промпты принта коврика. Принт — вся верхняя поверхность коврика (сублимация по ткани), поэтому
GPT сразу рисует плоский прямоугольник от края до края: без мокапа, без хромакея и без вырезания фона."""
from __future__ import annotations

from printflow.services.printing.prompts import name_prompt, theme_prompt as build_theme_prompt


def _surface_rule(size_cm: tuple[float, float], margin_cm: float) -> str:
    width, height = size_cm
    return (
        f"The image IS the printed top surface of a {width:g} x {height:g} cm landscape mouse pad, seen flat and "
        "front-facing as if scanned. Fill the ENTIRE canvas edge to edge with the design, including its own "
        "background color, texture or pattern: no mockup, no pad photo, no desk, no shadow, no frame, no border, "
        "no white margins, no transparent areas. "
        f"The pad corners are rounded and the edges are stitched: keep faces, text and key details at least "
        f"{margin_cm:g} cm inside every edge; only background may run to the edges."
    )


SUBLIMATION_RULE = (
    "Printed by dye sublimation on soft fabric: rich saturated colors, smooth gradients allowed, crisp clean "
    "outlines, no tiny hairline details that would blur on fabric weave."
)

SKIN_RULE = (
    "Faces, hands and skin keep smooth continuous shading; never posterize them into blotches."
)


THEME_TEXT_RULE = (
    "If the theme gives an exact headline, render it verbatim in its own language and alphabet (Cyrillic stays "
    "Cyrillic), with the given line breaks, large, bold, perfectly spelled and readable at a glance, at the top with "
    "a generous margin from every edge; it is the ONLY text in the image. If no headline is given, the image has no "
    "text at all: no words, letters, numbers, captions, signs, labels or calligraphy anywhere."
)

NO_PAD_RULE = "Never draw the pad itself: no stitching, no rounded corners, no edge or outline around the canvas."


def theme_prompt(theme: dict, direction: str, drawn: list[str], size_cm: tuple[float, float],
                 margin_cm: float) -> str:
    return build_theme_prompt(
        theme, direction, drawn, product="mouse pad", composed_for="a small mouse pad",
        print_rules=f"{SUBLIMATION_RULE} {_surface_rule(size_cm, margin_cm)} {NO_PAD_RULE}",
    )


def preview_prompt(theme: str, size_cm: tuple[float, float], margin_cm: float) -> str:
    """Новый принт по свободной теме (поле theme задачи)."""
    return (
        f"Create an original, finished, print-ready mouse pad artwork. Theme: {theme.strip()}. "
        "Carefully composed for a small landscape pad: one clear focal subject, an idea readable in two seconds, "
        "confident clean outlines, a tasteful harmonious palette, no clutter. "
        f"{_surface_rule(size_cm, margin_cm)} {NO_PAD_RULE} {SUBLIMATION_RULE} {THEME_TEXT_RULE} {SKIN_RULE} "
        "No mockup, no product photo, no badges, dimensions, logos or watermark."
    )


def reference_prompt(note: str, size_cm: tuple[float, float], margin_cm: float) -> str:
    """Фото коврика с маркетплейса → тот же рисунок поверхности 1:1, плоский и прямоугольный."""
    note_part = f"Additional note: {note.strip()}. " if note.strip() else ""
    return (
        "The reference is a marketplace product photo of a mouse pad that already has a printed design. "
        "Reproduce ONLY the artwork printed on the pad surface and reproduce it EXACTLY: the same illustration, "
        "characters, background color and texture, typography (keep the original language, spelling and letter "
        "shapes, including censored words as printed), colors, proportions and layout. "
        "Undo the perspective: output it flat, upright and rectangular, as if the pad surface were scanned. "
        "Where the mouse, a hand, a keyboard or glare hides part of the surface, continue the background and "
        "the design consistently. IGNORE everything not printed on the pad: the desk, mouse, keyboard, hands, "
        "the pad's edge and rubber base, shadows, and the marketplace overlays around the pad (titles like "
        "\"mouse pad\", size and thickness badges, icons, captions, prices, watermarks). "
        f"{note_part}{_surface_rule(size_cm, margin_cm)} {SKIN_RULE}"
    )


def hires_prompt(size: str, size_cm: tuple[float, float], margin_cm: float) -> str:
    """Перерисовка превью для печати."""
    return (
        "Recreate this mouse pad surface artwork at higher resolution for dye sublimation printing. "
        "The input is already the flat full-surface artwork, not a photo. Keep the exact same design, "
        "composition, colors, text and proportions. "
        f"Output image must be exactly {size} pixels. "
        "Redraw every outline smooth and continuous at the output resolution: no pixel staircase, no blocky "
        "edges on letters or shapes. Print-ready. "
        f"{_surface_rule(size_cm, margin_cm)} {SKIN_RULE}"
    )


NAME_PROMPT = name_prompt("на коврике для мыши", "Коврик для мыши")

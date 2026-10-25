"""Промпты термонаклейки: отдельная картинка на хромакее, маленький физический размер."""
from __future__ import annotations

from printflow.services.printing.prompts import name_prompt

RULE = """Create only a flat isolated heat-transfer artwork for clothes, not a product photo.
No bag, shirt, mockup, packaging, dimensions, frame or advertising text.
Keep the entire silhouette and fine details inside the image with a clear margin.
Use a solid #90EE90 chromakey background, never include that color inside the design.
The intended physical print size is {w} x {h} cm: favor a clear readable silhouette.
Do not claim actual embroidery, gemstones, glitter or raised material; any such texture is a printed illusion.
"""

NAME_PROMPT = name_prompt("на термонаклейке для одежды", "Термонаклейка")


def rule(area_cm: tuple[float, float]) -> str:
    return RULE.format(w=area_cm[0], h=area_cm[1])


def subject_prompt(theme: dict, drawn: list[str]) -> str:
    seen = "; ".join(drawn) if drawn else "пока ничего"
    return (
        f"Придумай один новый сюжет маленькой термонаклейки на тему «{theme['name']}». "
        f"Направления: {theme['known']}. Уже было: {seen}. "
        "Один узнаваемый объект с выразительной деталью, читаемый на размере 6–10 см. "
        "Без фона, брендов и повторения прежних сюжетов. Ответ только на английском, 6–12 слов."
    )


def preview_prompt(theme: str, area_cm: tuple[float, float]) -> str:
    return rule(area_cm) + "\nOriginal design brief: " + theme


def theme_prompt(theme: dict, subject: str, area_cm: tuple[float, float]) -> str:
    return preview_prompt(f"{theme['name']}: {subject}. Style: {theme.get('style', '')}", area_cm)


def reference_prompt(note: str, area_cm: tuple[float, float]) -> str:
    return (rule(area_cm) + "\nExtract and faithfully reconstruct ONLY the printed design in the reference. "
            "Preserve its composition, colors and text. " + note)


def hires_prompt(area_cm: tuple[float, float]) -> str:
    return (rule(area_cm) + "\nReproduce the attached artwork faithfully in high resolution for printing. "
            "Keep all colors, lettering and composition. Sharpen fine edges without adding new content.")

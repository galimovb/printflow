"""Промпты принтов шоппера. Общие правила печати (DTF, хромакей, без кириллицы, без обрезки) — из ядра."""
from __future__ import annotations

from server.print_generation import print_change_strength_rule
from server.print_raster import PRINT_CHROMAKEY_HEX
from printflow.services.printing.prompts import name_prompt
from server.prompts import (
    PRESERVE_REFERENCE_TEXT_LANGUAGE_RULE,
    DETAIL_BALANCE_RULE,
    DTF_PRINT_RULE,
    NO_RUSSIAN_TEXT_RULE,
    PRINT_CHROMAKEY_BACKGROUND_RULE,
    PRINT_NO_CROP_RULE,
)


def _area_rule(area_cm: tuple[int, int]) -> str:
    width, height = area_cm
    return (
        f"The print goes on the flat front panel of a cotton tote bag; the print area is at most "
        f"{width} x {height} cm. Do not force a fixed aspect; match the artwork proportions."
    )


SKIN_RULE = (
    "Faces, hands and skin are part of the print: keep them as opaque continuous ink with smooth shading; "
    "never posterize them into blotches, punch holes or replace them with the background or bag fabric."
)

CONTRAST_RULE = (
    "The same print is used on a milky off-white bag and on a black bag, so it MUST read on both: "
    "use saturated mid-tone and bright colors, and give dark or very light elements a contrasting keyline. "
    "No large areas of pure white or pure black ink."
)


def subject_prompt(theme: dict, drawn: list[str]) -> str:
    """Текстовой модели: один новый сюжет принта. Модель картинок не умеет «не рисуй X» — список уже
    нарисованного она повторяет, поэтому новизну решает текстовая модель. Коротко: длинные правила путают."""
    seen = "; ".join(drawn) if drawn else "пока ничего"
    return (
        f"Придумай сюжет принта для сумки-шоппера на тему «{theme['name']}». Уже было: {seen}.\n"
        "Нужно: один узнаваемый объект этой темы с одной выразительной деталью; не повторяй ни объект, ни предмет "
        "рядом из того, что уже было. Правдоподобно, без химер и абсурда; животные как настоящие — без одежды и "
        "человеческих занятий. Стильно и сдержанно: то, что взрослый спокойно носит каждый день. Без фона и брендов.\n"
        "Ответ: только сюжет на английском, 6–12 слов."
    )


def theme_prompt(theme: dict, subject: str, area_cm: tuple[int, int]) -> str:
    """Принт по тематике: сюжет придумала текстовая модель. Коротко: длинные правила путают модель картинок."""
    width, height = area_cm
    caption = ("Optional short Russian caption on top only if it adds wit; otherwise no text."
               if theme.get("captions") else "No text.")
    return (
        f"Tote bag print. Theme: «{theme['name']}». Subject: {subject}. "
        "Only the subject, no background, empty canvas around it. "
        "Style: tasteful, understated fine-art illustration — realistic and painterly, easy to wear every day with "
        "casual clothes; not cartoonish, cute or kitschy. "
        f"{caption} No brands, logos, smoking, alcohol or religious symbols. "
        "DTF print: clean opaque edges, no glow or splashes; reads on both cream and black bags. "
        f"Up to {width} x {height} cm, whole artwork centered and uncropped on a flat solid "
        f"{PRINT_CHROMAKEY_HEX} background."
    )


NAME_PROMPT = name_prompt("на сумке-шоппере", "Сумка-шоппер")


def preview_prompt(theme: str, area_cm: tuple[int, int]) -> str:
    return (
        f"Create a tote bag print design for DTF transfer. Print theme: {theme.strip()}. "
        f"{DTF_PRINT_RULE} {DETAIL_BALANCE_RULE} {NO_RUSSIAN_TEXT_RULE} "
        f"{CONTRAST_RULE} {_area_rule(area_cm)} "
        "Output ONE flat isolated print graphic. "
        f"{PRINT_CHROMAKEY_BACKGROUND_RULE} "
        "No bag, no mockup, no person. Artwork centered in the frame."
    )


def reference_prompt(theme: str, area_cm: tuple[int, int]) -> str:
    """Фото товара (своего, с другого кабинета) → тот же принт 1:1, плоский, без сумки и фона."""
    theme_part = f"Additional note: {theme.strip()}. " if theme.strip() else ""
    return (
        "The reference is a marketplace product photo of a tote bag that already has a print. "
        "Extract ONLY the print artwork printed on the bag fabric and reproduce it EXACTLY: "
        "the same illustration, characters, typography, colors, proportions and layout. "
        f"{print_change_strength_rule('original')} "
        f"{PRESERVE_REFERENCE_TEXT_LANGUAGE_RULE} "
        "IGNORE everything that is not the print: the bag fabric, handles, folds, shadows, perspective, "
        "the photo background, people, props, marketplace overlays, badges, captions, prices and watermarks. "
        "Straighten the print: front-facing, flat, upright, as if scanned. "
        f"{theme_part}{PRINT_NO_CROP_RULE} {SKIN_RULE} "
        "Output ONE flat isolated print graphic. "
        f"{PRINT_CHROMAKEY_BACKGROUND_RULE} "
        "No bag, no mockup, no person, no photo background. Artwork centered in the frame."
    )


def hires_prompt(size: str, area_cm: tuple[int, int]) -> str:
    return (
        "Recreate this tote bag print graphic at higher resolution for DTF transfer. "
        "Input is already a flat isolated print — not a photo of a bag. "
        "Keep the exact same design, composition, colors, and proportions. "
        f"{PRINT_NO_CROP_RULE} "
        f"Output image must be exactly {size} pixels; fit the FULL artwork without cropping. "
        f"{PRINT_CHROMAKEY_BACKGROUND_RULE} {SKIN_RULE} "
        "Redraw every outline smooth and continuous at the output resolution: no pixel staircase, "
        "no blocky edges on letters or shapes; logo and text fills flat and opaque. Print-ready. "
        f"{_area_rule(area_cm)}"
    )

"""Общие правила идеи, разнообразия и описания принта для всех товаров."""
from __future__ import annotations

THEME_IDEA_RULE = (
    "Before drawing, think of several ideas and pick the most interesting one. Skip the first, most obvious cliché "
    "of this theme and its usual default composition, time of day and color scheme. The chosen idea is unexpected "
    "yet instantly clear: an interesting subject, story, situation, angle or moment. One clear focal "
    "subject, everything in the picture serves the idea. Do not add animals or characters that are not part of "
    "this theme or its directions."
)

THEME_CAPTION_RULE = (
    "Add ONE short Russian caption at the top (with a generous margin) only if it makes the idea sharper; otherwise "
    "no text at all. If you add it, it must be a complete thought with a twist that the picture pays off, make sense "
    "to anyone who sees just this picture and caption, and sound like natural spoken Russian a person would actually "
    "say about their own day. Do not describe what is drawn, no slogans, no motivational or poetic phrases, no "
    "invented words, no wordplay that needs explaining. Max 6 words, perfect spelling and grammar, no English, "
    "no quotes. No other text anywhere."
)
NO_TEXT_RULE = "No text at all: no words, letters, numbers, captions, signs or labels anywhere."
ORIGINAL_RULE = "Original: no brands, logos, famous characters or celebrities; no smoking, alcohol or religious symbols."


def theme_style(composed_for: str) -> str:
    """Единый стиль принтов по тематикам (утверждён на коврике); composed_for — «a small mouse pad», «a tote bag»."""
    return (
        "Stylish editorial illustration, confident clean outlines, subtle paper grain, tasteful limited palette of "
        f"3–4 harmonious colors, carefully composed for {composed_for}, one clear focal subject, generous safe margins."
    )


def theme_prompt(theme: dict, direction: str, drawn: list[str], *, product: str, composed_for: str,
                 print_rules: str, style: str | None = None) -> str:
    """Принт по тематике — одинаково для всех товаров: идею придумывает GPT в направлении тематики.
    product — изделие в промпте («mouse pad»), print_rules — правила печати изделия,
    style — свой стиль товара вместо единого theme_style (коврик — единый)."""
    avoid = f"Already drawn in this collection — do something clearly different: {'; '.join(drawn)}. " if drawn else ""
    return (
        f"Create an original, finished {product} print for the theme «{theme['name']}». "
        f"Buyers in this theme like: {theme['known']}. Direction for this print: {direction}. "
        f"{avoid}{THEME_IDEA_RULE} "
        f"{style or theme_style(composed_for)} {THEME_CAPTION_RULE if theme.get('captions') else NO_TEXT_RULE} "
        f"{ORIGINAL_RULE} "
        f"{print_rules}"
    )


def name_prompt(on_product: str, card_name: str) -> str:
    """Описание рисунка для названия карточки; on_product — «на коврике для мыши», «на сумке-шоппере»."""
    return (
        f"Это рисунок {on_product}. Назови, что на нём изображено, для названия товара «{card_name} с принтом …»: "
        "2–4 слова в именительном падеже, со строчной буквы. Примеры: «пастельные котики», «японская волна», "
        "«инь-ян в огне», «надпись про кофе». Нельзя: бренды, логотипы, имена персонажей и людей, названия фильмов, "
        "игр, аниме и мультфильмов — описывай словами, что изображено. Ответь только этой фразой, без кавычек и точки."
    )

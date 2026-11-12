"""template_mockup requests about the ready mockup photos: which ones go into the card and how the print is drawn
on them at its real size."""

FRAME_PLAN = (
    "These are ready photos of people in a BLANK T-shirt, PHOTO_INDEX=N above each; a print will go on the chest "
    "of the chosen ones. Return JSON:\n"
    '- photos: for every photo {{"index":N,"view":"front|back|side|closeup","chest_clear":bool}}. front: the '
    "shirt front faces the camera; back: the person's back faces the camera; side: turned so far that a chest "
    "print would be mostly hidden; closeup: the shirt front fills most of the frame. chest_clear: no hand, arm, "
    "hair, bag, phone or cup covers the chest.\n"
    "- order: {count} different photos in card order: first the best front photo with chest_clear and the whole "
    "look visible, then front or closeup photos with chest_clear, a closeup last; at most one back photo, never "
    "first; no side photos and no covered chest. No two chosen photos have a similar background, place, pose or "
    "framing. The print: {print_summary}.\n"
    "- reason: one short sentence in Russian on the order."
)


def frame_plan_prompt(count: int, print_summary: str) -> str:
    return FRAME_PLAN.format(count=count, print_summary=print_summary.strip()[:300] or "-")


INK = (
    "The ink is opaque and exactly as saturated as in main-product.png, the same colors, black and white: the fabric's "
    "shadows may darken it slightly, but it never fades, washes out or turns gray."
)


CELLS = ("top-left", "top-right", "bottom-left", "bottom-right")


def frame_check_prompt(print_colors: list[str], frame_colors: list[str]) -> str:
    """Collages are drawn on low: every drawn frame is compared with the print file of its shirt color, so a melted
    head or a solid shape turned into an outline (6416 on low) never reaches the card."""
    files = "; ".join(
        f"IMAGE {i + 1} is the print file for the {c.upper()} T-shirt, shown on that fabric"
        for i, c in enumerate(print_colors)
    )
    first = len(print_colors) + 1
    frames = "; ".join(
        f"IMAGE {first + i} is photo {i + 1}, a person in the {c.upper()} T-shirt" for i, c in enumerate(frame_colors)
    )
    schema = ", ".join(f'"{i + 1}":{{"ok":bool,"reason":"..."}}' for i in range(len(frame_colors)))
    return (
        f"{files}. {frames}. For each photo compare the print on the shirt with the print file of that shirt color, "
        "part by part, wherever the print is visible. Not ok: any part missing, extra, merged or melted (a head or "
        "face turned into a blob, a hand, a tool or a line gone), letters missing, misspelled or garbled, other ink "
        "colors, a solid shape drawn as an outline or an outline filled in, the print smeared, doubled or cut off "
        "on the visible part. Fine: the print bending with the body and its folds, parts hidden behind arms, "
        "hands, hair or a bag, the part turned away from the camera, the fabric's light and shadow on the ink. "
        f"reason: one short sentence in Russian on what is wrong, empty when ok. Return JSON {{{schema}}}."
    )


def frame_collage_prompt(colors: list[str]) -> str:
    """Model frames as one 2x2 collage request; `colors` is the shirt color of each cell, row by row. With two colors a
    row is one person and pose in both colors side by side, so the print comes out the same on both shirts: white vs
    black width differed by 1.6% on average (max 5.5%) against 2.3% for separate frames and 3.8% for one collage per
    color, at $0.100 for 8 frames instead of $0.208 (4 prints, 2026-11-09).
    The ink sentence: without it the pink of a print came out at 76% of the file's saturation on average, with it
    89%."""
    shirts = sorted(set(colors), key=colors.index)
    layout = ", ".join(f"{cell} in a blank {color.upper()} T-shirt" for cell, color in zip(CELLS, colors))
    files = "; ".join(f"main-product-{c}.png is the {c.upper()} T-shirt laid flat with its print" for c in shirts)
    put = " and ".join(
        f"the {c.upper()} T-shirt from main-product-{c}.png on the people in {c.upper()} shirts" for c in shirts
    )
    pairs = len(shirts) > 1 and colors[0] != colors[1]
    rows = " Each row is one person and pose shown twice." if pairs else ""
    same = "In each row the print has exactly the same size, position and bend on the two shirts. " if pairs else ""
    return (
        f"template.png is a 2x2 collage of four separate photos: {layout}.{rows} {files}. "
        f"Put {put}, in place of the blank ones: the print keeps exactly its size and position on the shirt, the "
        "same share of the shirt width and the same distance below the collar as in the flat shirt, and bends with "
        "the body, its turn and folds; on a turned view only the part facing the camera shows. "
        f"{same}Anything in front of the chest (arms, hands, hair, a bag, a phone) stays in front. Keep the collage "
        "exactly: the same four photos in the same cells, edge to edge, each person, pose, cut and folds of the "
        "shirt, background, light and framing identical. The ink is opaque and exactly as saturated as in the flat "
        "shirt, the same colors, black and white: the fabric's shadows may darken it slightly, but it never fades, "
        "washes out or turns gray."
    )

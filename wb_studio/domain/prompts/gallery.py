"""Redraw algorithms' requests about the seller gallery and its print: analysis, extraction, recoloring, checks."""

PRINT_BACKGROUND = (
    "Background: flat #90EE90 everywhere outside the artwork, no shadow or gradient; white, gray and black ink "
    "stays neutral, with no green tint. "
)

GALLERY_ANALYSIS = (
    "These are all photos of one Wildberries T-shirt listing, PHOTO_INDEX=N above each. Only the print on the "
    "front of the torso counts; prints on sleeves, shoulders or the back are ignored. Return JSON:\n"
    '- photos: for EVERY photo {{"label":"PHOTO_INDEX=N","index":N,"role":"front|back|detail|infographic|other",'
    '"same_print":bool,"whole_print":bool,"normal_light":bool,"adult":bool}}. front: a real person wears the '
    "shirt facing the camera (seller text or badges over the photo do not matter); back: the person's back; "
    "infographic: a designed slide such as a size chart, a feature list or cut-out products on a graphic "
    "background. same_print: this shirt carries the listing's main front print. whole_print: every letter, line "
    "and edge of that print is inside the photo, none cut off by the photo border, a fold, an arm, a hanger, a "
    "banner or another shirt. normal_light: false for glow-in-the-dark or UV demos.\n"
    "- selected: up to 4 front photos with same_print, normal_light and adult, in clearly different poses (body "
    "angle, framing, arms, sitting, walking); at most one plain frontal standing shot. Fewer is fine.\n"
    "- scene_order: catalog, interior, outdoor and closeup, ordered by how much each adds to the selected poses, "
    "most first.\n"
    "- shirt_color: white|black, the seller's shirt in the front photos; any other color becomes the one the ink "
    "stands out on: light ink black, dark ink white.\n"
    "- print_source: index of the photo the print file is made from. It must have whole_print: a close-up that "
    "cuts off even one letter is never the source. Among those: a shirt of shirt_color (a seller showing both "
    "colors prints different ink on each, so never the other color or a photo with both), straight and upright, "
    "then the largest and sharpest. A flat lay or a child model is fine; a back, collage or infographic never.\n"
    '- recolor: {{"white":"...","black":"..."}}, one action per shirt color so the print of print_source keeps '
    "its look and meaning on that shirt: none | outlines | lettering | lettering_and_outlines | invert_flat | "
    "tone. Vanishing ink lies on bare fabric and is close to the shirt color: on black, black and very dark "
    "colors (dark purple, brown, red, navy); on white, white and very pale colors (pale yellow, light gray, "
    "pastels). Ink on another colored area of the print never vanishes (black text on a pink label, black "
    "outlines inside a colored drawing), and white or black gaps between colors (flag stripes, highlights) "
    "simply show the fabric. First picture the print exactly as it is on each shirt color: if it looks right "
    "there, with nothing important lost, that color is none, whichever color the seller's shirt was; a change "
    "is only for what would really vanish. outlines: thin vanishing contour lines; lettering: vanishing letters "
    "and numbers; lettering_and_outlines: both. invert_flat: a flat one-color logo, silhouette or lettering with no "
    "shading, "
    "all in vanishing ink; it takes the contrast ink. tone: a photo, portrait, halftone, engraving or shaded "
    "drawing whose vanishing ink carries the picture; it is made again for that fabric, never as a negative. "
    "tone turns vanishing ink into bare fabric, so when the vanishing part is mostly lettering and the picture "
    "stays visible, choose lettering. Colored drawings, faces, plates, badges, multi-color logos and flags are "
    "never inverted. Pick the smallest action. "
    "Examples: a flag skull with a thin black outline is none for white and outlines for black; a black halftone "
    "portrait is tone for black; a white one-color skull logo is invert_flat for white; a colored character with "
    "a black slogan and a black name above a red car are lettering for black; a navy plate with a white crown is "
    "none for black; thin dark purple line art is outlines for black.\n"
    "- front_print (bool): the front carries a print; a tiny neck logo alone does not count.\n"
    '- theme_match (bool), theme_reason (Russian): the artwork itself fits the theme "{theme}", whatever the '
    "title says.\n"
    "- print_count (int), single_print (bool), print_reason (Russian): separate prints on the front. Elements "
    "close together are one print (a caption right above or below a drawing); elements with wide plain fabric "
    "between them are separate (chest text plus a design near the hem).\n"
    "- print_width: width of the widest front print as a share of the front width between the side seams, 0..1, "
    "measured, not rounded down.\n"
    "- reaches_edges (bool): a front print touches a side seam, an armhole, the collar or the bottom hem.\n"
    "- small_print (bool): the main print is a small mark, not a chest print: a pocket-size logo or text on one "
    "side of the chest, a small logo or caption under the collar, a patch, or anything narrower than about a "
    "quarter of the front width.\n"
    "- kids_print (bool): the print is meant for a child: a child's age (1 годик, мне 5 лет), a child speaking "
    "about a parent (жду папу, папина дочка), baby or school-kid phrases; also when the seller shows it only on "
    "children.\n"
    "- audience: female|male|unisex, who would wear the print of print_source, decided by the print alone, never "
    "by the seller's models, other designs or the words мужская, женская, унисекс in the title. A first-person "
    "phrase is worn by its speaker and the person it names is the other one: I love my girlfriend, люблю свою "
    "жену are male; I love my boyfriend, люблю мужа are female. Otherwise words naming the wearer decide "
    "(сестра, мама, жена, дочь, королева, feminine endings are female; брат, папа, муж, сын, король are male), "
    "then the style: fashion houses, pearls, flowers, hearts, princesses, pink glamour, unicorns and cute kawaii "
    "characters are female; strength sports, military, cars and menacing beasts (angry pitbulls and other snarling "
    "dogs, gorillas, wolves, bears, roaring lions and tigers, skulls, barbed wire and chains) are male. A cute "
    "drawing of the same animal stays as cute (female or unisex). A cute drawing with a rude slogan "
    "follows the drawing. When in doubt, unisex.\n"
    '- title: Russian, starts with "Футболка с принтом", max 60 characters: the words about the print '
    '(phrases, names, characters) from the seller title "{source_title}", without brand, article number, price, '
    "shop text, size, fabric, fit or color; without such words, name the print from the photos. Movies, series, "
    "games, characters, bands and celebrities are named normally (Футболка с принтом Бэтмен). Only a "
    "world-famous fashion or sports brand, its logo or monogram (Nike, Adidas, Gucci, Supreme) is titled just "
    '"Футболка с принтом".\n'
    "- description: Russian, max 400 characters, only what the print shows; no invented materials, brands or "
    "licenses.\n"
    "When the theme or the front print is uncertain, answer false."
)


def gallery_analysis_prompt(theme: str, source_title: str = "") -> str:
    return GALLERY_ANALYSIS.format(theme=theme, source_title=source_title.strip()[:300] or "-")


def with_feedback(prompt: str, feedback: str) -> str:
    return prompt + (" A previous attempt was rejected: " + feedback if feedback else "")


def extract_print_prompt(expected_print: str = "", feedback: str = "") -> str:
    """Seller photo -> flat print file in its original colors."""
    subject = f" ({expected_print})" if expected_print else ""
    prompt = (
        f"The photo shows a T-shirt with a print{subject}. Make a flat print file of ONLY the main front print: "
        "every element, letter (same language, never translated), proportion and color copied 1:1, upright and "
        "front-on, in its own aspect ratio. Leave out the person, the shirt, folds, light, background, sleeve "
        "prints and seller text, stickers or watermarks; add, remove or restyle nothing. Faces and skin stay "
        "smooth continuous ink. Openings where the shirt shows through (the eye sockets of a skull, the inside "
        "of O, A or B, gaps between shapes) are background, never white or black ink, even when they match the "
        "shirt; stripes, stars, highlights and fills drawn in the print stay ink. "
        + PRINT_BACKGROUND
        + "Crop close around the artwork."
    )
    return with_feedback(prompt, feedback)


VANISHING_INK = {
    "white": ("white or very pale", "black, or for a pale color a deep shade of the same hue"),
    "black": ("black or very dark", "white, or for a dark color a light tint of the same hue"),
}

# The gallery analysis only picks one of these, so the same print always gets the same instruction.
# Only invert_flat recolors a whole shape (flat one-color logos); a photo or portrait is redrawn by tone, never
# inverted, because a negative breaks it.
RECOLOR_ACTIONS = {
    "outlines": "turn only the thin {ink} outlines and contour lines that touch the bare fabric into {visible}; "
    "fills, shading, faces, eyes and lettering stay as they are",
    "lettering": "turn only the {ink} letters and numbers that touch the bare fabric into {visible}, same font "
    "and shape; drawings, faces and outlines stay as they are",
    "lettering_and_outlines": "turn the {ink} letters, numbers and thin outlines that touch the bare fabric into "
    "{visible}, same shape; fills, shading, faces and eyes stay as they are",
    "invert_flat": "this is a flat one-color logo, silhouette or lettering: turn all of its {ink} ink into solid "
    "{visible} of exactly the same shape; openings and gaps stay empty canvas",
    "tone": "the same picture made for a {shirt} shirt so it looks the same there, NOT a negative: {tone}; "
    "faces, features and the halftone pattern keep their shape, colored parts keep their colors, every word of "
    "the lettering stays complete and readable on {shirt} fabric, and nothing is added",
}
# Which parts of the picture carry ink on each shirt: the picture keeps its light and dark, the fabric fills in.
TONE = {
    "black": "what looks light in the original (skin, highlights, white areas) becomes white ink and what looks "
    "dark (hair, shadows, black clothes) becomes empty canvas where the black fabric shows",
    "white": "what looks dark in the original (hair, shadows, black areas) becomes black ink and what looks "
    "light (skin, highlights) becomes empty canvas where the white fabric shows",
}


def recolor_change(color: str, action: str) -> str:
    ink, visible = VANISHING_INK[color]
    return RECOLOR_ACTIONS[action].format(ink=ink, visible=visible, shirt=color.upper(), tone=TONE[color])


def tone_print_prompt(color: str, expected_print: str = "", feedback: str = "") -> str:
    """Seller photo -> the print made directly for a shirt of `color`; for pictures a recolor would turn negative."""
    subject = f" ({expected_print})" if expected_print else ""
    visible = "white or light" if color == "black" else "black or dark"
    prompt = (
        f"The photo shows a T-shirt with a print{subject}. Make a flat print file of ONLY the main front print for "
        f"a {color.upper()} T-shirt, so that on {color} fabric it looks like the same picture, never a negative: "
        f"{TONE[color]}. Faces, features, shading and the halftone pattern keep their shape; colored parts keep "
        f"their colors; every word stays complete, in the same language, and lettering that would vanish on {color} "
        f"fabric becomes {visible}. Same composition and aspect ratio, upright and front-on. Leave out the person, "
        "the shirt, folds, light, background and seller text, stickers or watermarks; add nothing. "
        + PRINT_BACKGROUND
        + "Crop close around the artwork."
    )
    return with_feedback(prompt, feedback)


def recolor_print_prompt(color: str, action: str, feedback: str = "", ratio: float | None = None) -> str:
    """Clean print file -> the same drawing with only the fixed change of the chosen action."""
    shape = f" (width:height = {ratio:.2f})" if ratio else ""
    prompt = (
        f"artwork.png is a T-shirt print centered on a #90EE90 canvas. Make its version for a {color.upper()} "
        f"shirt with exactly this change and nothing else: {recolor_change(color, action)}. Every other color, "
        "line, letter and proportion stays exactly as it is; white, gray and black stay neutral, with no green "
        f"tint. The artwork keeps the same rectangle on the canvas{shape}, nothing extended or cropped, the margins "
        "flat #90EE90."
    )
    return with_feedback(prompt, feedback)


def recolor_need_prompt(colors: list[str]) -> str:
    """The extracted file as it will really be printed on each fabric: a change is needed only for what is lost there.
    The seller photo cannot tell a printed black panel from black fabric (5929: white lettering on a black strip was
    sent to recolor in 4 runs of 5 and every redraw was rejected)."""
    listing = "; ".join(f"IMAGE {i + 1} is a print file printed exactly as it is on a {c.upper()} shirt"
                        for i, c in enumerate(colors))  # fmt: skip
    schema = ", ".join(f'"{c}":{{"lost":bool,"reason":"..."}}' for c in colors)
    return (
        f"{listing}. For each, decide whether anything important of the design is lost because it blends into the "
        "fabric: letters, numbers, outlines, faces or the picture itself. Ink on a printed background, panel or "
        "frame of the print's own stays visible, and small dark or light details inside a picture that still reads "
        f"are not lost. Return JSON {{{schema}}}."
    )


def verify_prints_prompt(keys: list[str], expected_print: str = "", changes: dict | None = None) -> str:
    """'base' is the extraction in original colors, color keys are its versions with the requested change."""

    def describe(key: str) -> str:
        if key == "base":
            return "the print file extracted from it, in the original ink colors, shown on gray"
        action = (changes or {}).get(key)
        change = recolor_change(key, action) if action in RECOLOR_ACTIONS else "vanishing ink made visible"
        return (
            f"its version for a {key.upper()} shirt, shown on that fabric as printed, with only this change: {change}"
        )

    listing = "; ".join(f"IMAGE {i + 2} is {describe(key)}" for i, key in enumerate(keys))
    schema = ", ".join(f'"{key}":{{"text":"...","accepted":bool,"reason":"..."}}' for key in keys)
    expected = f"Expected print: {expected_print}. " if expected_print else ""
    return (
        f"IMAGE 1 is a seller photo of a T-shirt. {listing}. For each print file decide whether it is the same "
        "design as the main print on the shirt in IMAGE 1. First copy every word of the file into text letter by "
        "letter exactly as drawn, without correcting it to a real word, then compare that copy letter by letter "
        "with the shirt; a letter IMAGE 1 does not show (cut off by its edge) is a reject. "
        "Reject: a different or incomplete design; missing, extra or duplicated elements; changed, misspelled or "
        "garbled lettering; seller graphics, people, background or a block of the seller's fabric included; in "
        "the extracted file an ink turned into another color (green to black, colors to gray or white); in a "
        "shirt-color version any change beyond the requested one or one that alters the look or meaning (a "
        "negative photo or portrait, an inverted plate, badge or multi-color logo, recolored flags, changed "
        "faces, filled outlines, unreadable lettering). "
        "Allowed: brighter and cleaner colors, removed fabric and light, straightened perspective, cleaner edges "
        "and exactly the requested change. "
        f"{expected}Return JSON {{{schema}}}."
    )

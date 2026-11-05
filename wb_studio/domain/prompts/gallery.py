"""Redraw algorithms' requests about the seller gallery and its print: analysis, extraction, recoloring, checks."""

PRINT_BACKGROUND = (
    "Background: solid flat #90EE90 everywhere outside the artwork, no shadow or gradient; white, gray and black "
    "areas of the artwork stay neutral, with no green tint from the background. "
)

GALLERY_ANALYSIS = (
    "These are all photos of one Wildberries T-shirt listing; PHOTO_INDEX=N is written above each. Return JSON:\n"
    '- photos: for EVERY photo {{"label":"PHOTO_INDEX=N","index":N,"role":"front|back|detail|infographic|other",'
    '"same_print":bool,"whole_print":bool,"normal_light":bool,"adult":bool}}. whole_print: every letter, line '
    "and edge of the main print is inside this photo; false when the photo border, a fold, an arm, a hanger, a "
    "seller banner or another shirt cuts off even one letter or corner. front: a real adult wears the shirt and the camera "
    "sees the chest with the whole print; seller text or badges over a real photo do not change that. back: the "
    "camera sees the person's back. infographic: a designed slide such as a size chart, a feature list or cut-out "
    "products on a graphic background. same_print: the main front design of the listing is on this shirt. "
    "normal_light: false for glow-in-the-dark or UV demos.\n"
    "- selected: up to 4 front photos with same_print, normal_light and adult, each in a clearly different pose "
    "(body angle, framing, arms, sitting, walking); at most one plain frontal standing shot and never two "
    "near-identical shots. Fewer is fine.\n"
    "- scene_order: catalog, interior, outdoor and closeup, ordered by how much each adds to the selected poses, "
    "most first.\n"
    "- shirt_color: white|black, the seller's shirt in the front photos. White and black shirts keep their color. "
    "Any other color (pink, gray, beige, colored) becomes the one the print ink stands out on: light or white ink "
    "is black, dark ink is white. Never a color on which the ink would vanish.\n"
    "- print_source: index of the photo the print is redrawn from; whatever it does not show gets invented. "
    "First rule, above size: the WHOLE print is inside the photo, every letter, word, line and edge visible, "
    "nothing cut by the photo border, a fold, an arm, a hanger or a banner. A close-up that crops even one "
    "letter is never the source. Among complete prints pick the one straight and upright, not rotated or seen "
    "at an angle, then the largest and sharpest, on a shirt of shirt_color. If unsure, take the main photo 0 "
    "when its print is complete. A seller who "
    "shows both colors prints different ink on each: check the shirt color in that very photo and never take "
    "the print from a shirt of the other color or from a photo showing both colors. Prefer selected photos, else "
    "a flat lay, a close-up showing the whole print or a child model; never a back, collage or infographic "
    "photo.\n"
    '- recolor: {{"white":"...","black":"..."}}, for each shirt color one action for the print of print_source: '
    "none | outlines | lettering | lettering_and_outlines | invert_flat | tone. The print must keep its look and "
    "meaning on both shirts, and the printed file is what the buyer gets: ink matching the shirt is invisible. "
    "Vanishing ink touches the bare fabric "
    "and is close to the shirt color: on a black shirt black, near-black and very dark colors (dark purple, dark "
    "brown, dark red, dark navy); on a white shirt white and very pale colors (pale yellow, light gray, pastels). "
    "Ink lying on another colored area of the print is not vanishing: black text on a pink label, a black "
    "silhouette on a red circle or a flag, black outlines inside a colored drawing. outlines: thin contour lines "
    "on the fabric; lettering: letters and numbers on the fabric; lettering_and_outlines: both. invert_flat: a "
    "flat one-color logo, silhouette or lettering without shading, drawn entirely in vanishing ink (a white "
    "Misfits skull on a white shirt, a black silhouette on a black shirt); its ink becomes the contrast color, "
    "the way such logos are printed on the other shirt color. tone: a photo, portrait, halftone, engraving or "
    "shaded drawing whose dark or light ink carries the picture and would vanish (a black Tyler Durden portrait "
    "or gray engraved angels on a black shirt); it is made again for that fabric so it looks the same as the "
    "original, never as a negative, colored parts and lettering kept. Colored drawings, a character's "
    "eyes and face, plates, boxes, badges, multi-color logos and flags are never inverted. Pick the smallest "
    "action; none when nothing that carries the design would vanish. White or black fills between other colors "
    "(flag stripes, highlights, gaps) simply show the fabric and never need an action. Examples: a "
    "red-white-blue flag skull with a thin black outline is none for white and outlines for black; a black "
    "halftone portrait is tone for black; a white Misfits skull is invert_flat for white; a cute colored "
    "character with a black slogan is lettering for black; a navy plate with a white crown is none for black; "
    "thin dark purple line art is outlines for black. The color the print was made for is almost always none.\n"
    "Only the front of the torso counts below; prints on sleeves, shoulders or the back are ignored.\n"
    "- front_print (bool): the front carries a print; a tiny neck logo alone does not count.\n"
    '- theme_match (bool), theme_reason (Russian): the artwork itself fits the theme "{theme}", whatever the '
    "listing title says.\n"
    "- print_count (int), single_print (bool), print_reason (Russian): separate prints on the front. Elements "
    "close together are ONE print, e.g. a caption right above or below a drawing. Elements in different zones "
    "with wide plain fabric between them are separate, e.g. chest text plus a design near the hem.\n"
    "- print_width: width of the widest front print as a share of the front width between the side seams, 0..1, "
    "measured, not rounded down.\n"
    "- reaches_edges (bool): a front print touches a side seam, an armhole, the collar or the bottom hem.\n"
    "- small_print (bool): the main front print is a small mark instead of a chest print: a pocket-size logo or "
    "text on the left or right chest, a small logo or caption right under the collar, a patch or badge; also any "
    "print narrower than about a quarter of the front width.\n"
    "- kids_print (bool): the print is meant for a child, not an adult: a child's age (1 годик, мне 5 лет, "
    "birthday numbers for kids), a child speaking about a parent (жду папу, мамин сыночек, папина дочка), "
    "baby or school-kid phrases; true also when the seller shows it only on children.\n"
    "- audience: female|male|unisex, the person who would wear the print of print_source. Other designs in the "
    "gallery (a paired couple shirt, a different slogan), the gender of the seller's models and the words "
    "мужская, женская, унисекс in the seller title do not count; only the print itself decides. "
    "First understand what the print means and "
    "who says it. A first-person phrase (I, my, я, мой, моя) is worn by its speaker, and the person it names "
    "is the other one: I love my girlfriend, I love hot moms, люблю свою жену, моя девушка лучше всех are male; "
    "I love my boyfriend, I love hot dads, люблю мужа, мой парень are female. This decides over the words "
    "below. Otherwise the print names its wearer: words for a woman (сестра, мама, жена, дочь, бабушка, "
    "подруга, тётя, девушка, королева, feminine word endings) are female, for a man (брат, папа, муж, сын, "
    "дедушка, друг, дядя, парень, король) male. Then the style of the print: women's fashion houses and feminine "
    "motifs (Chanel, Dior, crowns with pearls, flowers, hearts, princesses, ballet, pink glamour, unicorns, "
    "rainbows, pastel and cute kawaii characters) are female; strength sports, military, cars and other clearly "
    "masculine motifs are male. A cute drawing with a rude or ironic slogan follows the drawing. When in doubt, "
    "unisex.\n"
    '- title: Russian, starts with "Футболка с принтом", max 60 characters: the seller title "{source_title}" '
    "keeping only its words about the print (phrases, names, characters), without brand, article number, price, "
    "shop text, sizes, fabric, fit or color. If it has none, name the print from the photos. A print of a brand, "
    "its logo or monogram, or a licensed character or franchise (Dior, Barbie, Spider-Man, South Park) is titled "
    'just "Футболка с принтом".\n'
    "- description: Russian, max 400 characters, only what is visible in the print; no invented materials, brands "
    "or licenses.\n"
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
        f"The photo shows a T-shirt with a printed design{subject}, worn or laid flat. Recreate ONLY the main "
        "design on the front of the shirt as a flat print file: every element, letter (same language, never "
        "translate), proportion and color copied 1:1, upright and front-on even if the shirt is tilted or "
        "wrinkled, in its original aspect ratio. Leave out the person, the shirt, folds, lighting, background, "
        "prints on the sleeves and any seller text, stickers or watermarks. Do not add, remove or restyle "
        "anything; only clean the edges. Human faces and skin stay smooth continuous ink, no posterization or holes. "
        "Openings in the design where the bare shirt shows through, such as the eye sockets and nose of a skull, "
        "the inside of letters like O, A or B and gaps between separate shapes, are #90EE90 background too, "
        "never filled with white or black ink, even when they match the shirt color. Stripes, stars, highlights "
        "and fills that are part of the drawing stay ink. " + PRINT_BACKGROUND + "Crop close around the artwork."
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
        f"The photo shows a T-shirt with a printed design{subject}. Recreate ONLY the main design on the front as a "
        f"flat print file for a {color.upper()} T-shirt, so that printed on {color} fabric it looks like the same "
        f"picture, never a negative: {TONE[color]}. Faces, features, shading and the halftone pattern keep their "
        "shape; colored parts keep their colors; every letter and word stays complete, in the same language, and "
        f"lettering that would vanish on {color} fabric becomes {visible}. Same composition, proportions and aspect "
        "ratio, upright and front-on. Leave out the person, the shirt, folds, lighting, background and any seller "
        "text, stickers or watermarks; nothing is added. " + PRINT_BACKGROUND + "Crop close around the artwork."
    )
    return with_feedback(prompt, feedback)


def recolor_print_prompt(color: str, action: str, feedback: str = "", ratio: float | None = None) -> str:
    """Clean print file -> the same drawing with only the fixed change of the chosen action."""
    shape = f" (width:height = {ratio:.2f})" if ratio else ""
    prompt = (
        f"artwork.png is a finished T-shirt print centered on a #90EE90 canvas. Make its version for a "
        f"{color.upper()} shirt with exactly this change and nothing else: {recolor_change(color, action)}. "
        "The print keeps its meaning and look: every other color, line, letter and proportion stays exactly as it "
        "is; skin and faces stay natural; white, gray and black areas stay neutral, with no green tint from the "
        f"canvas. The artwork keeps the same rectangle on the canvas{shape}: same position, width and height, "
        "nothing extended or cropped, the #90EE90 margins empty and flat."
    )
    return with_feedback(prompt, feedback)


def verify_prints_prompt(keys: list[str], expected_print: str = "", changes: dict | None = None) -> str:
    """'base' is the extraction in original colors, color keys are its versions with the requested change."""

    def describe(key: str) -> str:
        if key == "base":
            return "the print file extracted from it, in the original ink colors"
        action = (changes or {}).get(key)
        change = recolor_change(key, action) if action in RECOLOR_ACTIONS else "vanishing ink made visible"
        return f"a version for a {key.upper()} shirt that should differ only by this change: {change}"

    listing = "; ".join(f"IMAGE {i + 2} is {describe(key)}" for i, key in enumerate(keys))
    listing += (
        ". The extracted file is shown on gray; each shirt-color version is shown on its own shirt color exactly "
        "as it will be printed, so judge it by how it looks on that fabric"
    )
    schema = ", ".join(f'"{key}":{{"text":"...","accepted":bool,"reason":"..."}}' for key in keys)
    expected = f"Expected print: {expected_print}. " if expected_print else ""
    return (
        f"IMAGE 1 is a seller photo of a T-shirt. {listing}. For each print file decide whether it is the same "
        "design as the main print on the shirt in IMAGE 1. First copy into text every word of that print file "
        "exactly as drawn, letter by letter, including doubled, missing or extra letters and punctuation, "
        "without correcting it to a real word; then compare that copy letter by letter with the words on the "
        "shirt in IMAGE 1. A print cut off by the edge of IMAGE 1 is no proof for the hidden letters: any letter "
        "the photo does not show is a reject. "
        "Reject only for: a different or incomplete design, missing or extra elements, changed, misspelled or "
        "garbled lettering, a duplicated design, seller graphics, people or background included, the seller's "
        "shirt fabric kept as a block or patch around the design, or, in the extracted file, an ink turned into "
        "another color (green turned black, "
        "colors turned gray or white). Allowed: brighter or cleaner versions of the same colors, removed fabric "
        "and lighting, straightened perspective, cleaner edges, a gray preview background, and in a shirt-color "
        "version exactly its requested change. Also reject a shirt-color version whose change goes further or "
        "alters what the print means or how it looks: a negative portrait or photo, an inverted plate, badge or "
        "multi-color logo, recolored flags or symbols, changed eyes or faces of a character, filled shapes that "
        "were outlines, unreadable lettering, a look clearly unlike the seller's print. A flat one-color logo in "
        "the contrast color is fine when that is the requested change. "
        f"{expected}Return JSON {{{schema}}}."
    )

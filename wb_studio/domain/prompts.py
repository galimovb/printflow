"""Prompt text for every paid request, grouped by algorithm.

Builders return plain strings; the generator only attaches images and calls the API.
"""

PRINT_BACKGROUND = "Background: solid flat #90EE90 everywhere outside the artwork, no shadow or gradient. "

# --- source_redraw -----------------------------------------------------------

GALLERY_ANALYSIS = (
    "These are all photos of one Wildberries T-shirt listing; PHOTO_INDEX=N is written above each. "
    "Decide whether its print can be reused and return JSON:\n"
    '- photos: for EVERY photo {{"label":"PHOTO_INDEX=N","index":N,'
    '"role":"front|back|detail|infographic|other",'
    '"same_print":bool,"normal_light":bool,"adult":bool}}. front = a real adult wearing the shirt, '
    "front view, main print fully visible. Posters or collages with cut-out people, headlines, arrows "
    "or size labels are infographic, even if people wear the shirt. Glow-in-the-dark or UV demos have "
    "normal_light=false. same_print compares with the main front design of the listing.\n"
    "- selected: up to 4 indices of eligible photos (front, same_print, normal_light, adult), best first. "
    "Fewer than 4 is fine.\n"
    "- print_source: integer index of the eligible photo where the main print is largest, sharpest "
    "and complete.\n"
    "- theme_match (bool) and theme_reason (Russian): does the artwork itself fit the theme "
    '"{theme}"? Judge the drawing, not the listing title.\n'
    "- main_print_side: front|back|both|unknown. A tiny neck or back logo does not count.\n"
    "- print_count (int), single_print (bool), print_reason (Russian): separate prints on the garment. "
    "A caption counts as part of an illustration only when it touches it inside one compact block. "
    "Elements in different zones of the shirt separated by plain fabric are separate prints: chest text "
    "plus a design near the hem is 2; a small chest logo plus a large design is 2.\n"
    "- print_width: width of the widest print as a share of the shirt front width between the side "
    "seams, 0..1. Measure the real extent, do not round down.\n"
    "- reaches_edges (bool): any print touches or crosses a side seam, a sleeve, the collar or the "
    "bottom hem.\n"
    "- audience: female|male|unisex. female if the shirt is a women's cut or shown only on women; "
    "male if a men's cut or shown only on men; otherwise unisex.\n"
    '- title: Russian, starts with "Футболка с принтом", max 60 characters, names the print.\n'
    "- description: Russian, max 400 characters, only what is visible in the print; no invented "
    "materials, brands or licenses.\n"
    "If the theme or the print side is uncertain, set theme_match=false or main_print_side=unknown."
)


def gallery_analysis_prompt(theme: str) -> str:
    return GALLERY_ANALYSIS.format(theme=theme)


def with_feedback(prompt: str, feedback: str) -> str:
    return prompt + (" A previous attempt was rejected: " + feedback if feedback else "")


def extract_print_prompt(expected_print: str = "", feedback: str = "") -> str:
    """Seller photo -> flat print file in its original colors."""
    subject = f" ({expected_print})" if expected_print else ""
    prompt = (
        f"The photo shows a person wearing a T-shirt with a printed design{subject}. "
        "Recreate ONLY that printed design as a flat print file in its original colors. "
        "Ignore the person, the shirt, folds, lighting, background and any seller text, stickers or "
        "watermarks outside the print. Show it front-on and upright even if the shirt is tilted or "
        "wrinkled; keep its original aspect ratio. Copy it 1:1: every element, letter (same language, "
        "never translate), proportion and color. Do not add, remove or restyle anything; only clean up "
        "edges. Faces and skin stay smooth continuous ink, no posterization or holes. "
        + PRINT_BACKGROUND
        + "Crop close around the artwork. No shirt, mockup or person."
    )
    return with_feedback(prompt, feedback)


VANISHING_INK = {
    "white": (
        "white or very pale",
        "darken it just enough to stay visible, or give it a thin dark outline",
    ),
    "black": (
        "black or very dark",
        "lighten it just enough to stay visible, or give it a thin light outline",
    ),
}


def recolor_print_prompt(color: str, feedback: str = "") -> str:
    """Clean print file -> the same drawing with only vanishing ink adjusted."""
    ink, fix = VANISHING_INK[color]
    prompt = (
        "artwork.png is a finished T-shirt print on a #90EE90 background. Make its version for a "
        f"{color.upper()} shirt. Keep the drawing identical: every line, shape, letter, proportion, "
        f"composition and saturated color stays exactly as it is. Change ONLY {ink} ink, which would "
        f"vanish on {color} fabric: {fix}. Skin and faces stay natural. Same size and framing. "
        "Background: solid flat #90EE90 everywhere outside the artwork."
    )
    return with_feedback(prompt, feedback)


def verify_prints_prompt(keys: list[str], expected_print: str = "") -> str:
    """'base' is the extraction in original colors, color keys are its contrast versions."""

    def describe(key: str) -> str:
        if key == "base":
            return "the print file extracted from it in original colors"
        return (
            f"a version for a {key.upper()} shirt, where only ink that would vanish on that fabric "
            "may be darkened or lightened; its drawing must be identical"
        )

    listing = "; ".join(f"IMAGE {i + 2} is {describe(key)}" for i, key in enumerate(keys))
    schema = ", ".join(f'"{key}":{{"accepted":bool,"reason":"..."}}' for key in keys)
    expected = f"Expected print: {expected_print}. " if expected_print else ""
    return (
        f"IMAGE 1 is a seller photo of a T-shirt. {listing}. For each print file decide whether it is "
        "the same design as the main print on the shirt in IMAGE 1. Reject only for: a different or "
        "incomplete design, missing or extra elements, changed or garbled lettering, a duplicated design, "
        "or seller graphics, people or background included. Allowed: removed fabric and lighting, "
        "straightened perspective, cleaner edges, gray preview background, and in color versions "
        f"pale or dark ink adjusted for contrast. {expected}Return JSON {{{schema}}}."
    )


LIVE_SCENES = (
    "MAIN CATALOG VIEW: near-frontal torso, head to hips, uncluttered neutral setting, "
    "soft daylight, full shirt and complete print in focus. Product dominates the frame.",
    "EVERYDAY INTERIOR VIEW: head to knees in a believable minimal interior with window light. "
    "Relaxed posture; use subtle surroundings to support the shirt, without a prescribed pose.",
    "OUTDOOR LIFESTYLE VIEW: head to knees in a quiet urban location, natural daylight. "
    "A slight body angle is allowed while the entire front print remains readable.",
    "PRINT AND FIT VIEW: closer framing from shoulders to below the hem, near-frontal chest, "
    "soft side light revealing cotton texture, seams and realistic ink. Keep the complete print "
    "and shirt hem inside the frame; the face may be outside the crop.",
)

POSE_SCENE = (
    "Repeat the pose, body angle, camera distance and framing of pose-reference.png. "
    "Take NOTHING else from it: not the person, face, T-shirt, print, colors, props or background; "
    "use a new clean setting that suits the pose."
)

PERSONS = {
    "female": "a young woman aged 18–25; face, hair and look are your choice",
    "male": "a young man aged 18–25; face, hair and look are your choice",
    "unisex": "an adult aged 18–25 of any gender; face, hair and look are your choice",
}


def live_photo_prompt(color: str, index: int, audience: str = "unisex", pose: bool = False) -> str:
    """Model photo from the calibrated shirt reference and the clean print file.

    pose: a seller photo is attached only as a pose and framing reference.
    """
    pose_note = (
        "pose-reference.png is another product photo used ONLY for pose and framing; ignore its shirt "
        "and print completely. "
        if pose
        else ""
    )
    return (
        "Photorealistic marketplace photo of a person wearing the T-shirt from main-product.png. "
        "main-product.png shows the shirt with the print at its exact size and position. "
        "artwork.png is the exact print. "
        + pose_note
        + f"SHIRT: solid {color.upper()} regular-fit cotton crewneck, short sleeves, not oversized. "
        "PRINT: place artwork.png on the chest exactly once, at the size and position from main-product.png. "
        "Keep every element, letter, proportion and ink color unchanged; do not redraw, enlarge, crop "
        "or duplicate it. The ink follows fabric folds with matte cotton texture, not a glossy sticker. "
        f"PERSON: {PERSONS.get(audience, PERSONS['unisex'])}. Jeans or trousers, shirt untucked. "
        "The same person may appear in other frames. "
        f"SCENE: {POSE_SCENE if pose else LIVE_SCENES[index]} "
        "Hands, hair and props stay off the print; no strong torso twist, colored light or deep chest folds. "
        "Natural anatomy and skin. No added text, badges, borders, collage or watermarks. "
        "One vertical 3:4 photo."
    )


# --- standard ----------------------------------------------------------------


def standard_extract_prompt(theme: str) -> str:
    return (
        "Extract ONLY the printed artwork from the reference T-shirt, reconstructing the complete design "
        "front-on. Keep the source artwork, lettering and colors accurate. Remove the person, garment, "
        "fabric folds, shadows, background and marketplace labels. One cohesive standalone print, no "
        "garment or mockup, on uniform chromakey #90EE90, no green in the design. Do not add or invent "
        "new design elements. Topic context: " + theme
    )


def describe_prompt(theme: str) -> str:
    return (
        "Return JSON with Russian title (max 60 characters) and description (max 1500). "
        "The input is artwork to be printed, not a photograph of the product. Describe the full artwork "
        "composition. People, clothing, textures and objects depicted INSIDE the artwork are elements of "
        "the illustration, never features of the physical T-shirt being sold. Do not claim patterned "
        "sleeves or all-over printing. Describe only the actual T-shirt print visible. Do not invent "
        "material composition, licenses, measurements or manufacturing facts. Title begins Футболка с "
        "принтом. Search theme context: " + theme
    )


STANDARD_SCENES = {
    1: (
        "Atmospheric editorial lifestyle photograph of a freely chosen adult fashion model aged 18–25 "
        "lounging naturally in a chair in a cozy creative interior, warm wood or textured walls, window "
        "light, a small unbranded retro radio or books at the edge. Head to knees or full-body "
        "composition, wide-leg baggy jeans clearly visible, relaxed youthful pose, shirt front open to "
        "camera, arms resting beside the design. Palette and understated props complement the supplied "
        "artwork. Not a generic mirror selfie."
    ),
    2: (
        "Dynamic cinematic streetwear photograph of another freely chosen adult fashion model aged 18–25 "
        "at an evening urban street or neon-lit skate/cafe frontage, soft colored lights and pavement "
        "reflections, head to knees. Expressive natural pose, one arm may be raised away from the chest, "
        "wide-leg baggy denim trousers, fully dressed, shirt hem down. Main print remains readable and "
        "unobstructed. Different person and location from the interior photograph. Balanced lighting so "
        "the print colors stay accurate."
    ),
}

# Shared two-image contract: IMAGE 1 is the finished shirt, IMAGE 2 the isolated print.
PRODUCT_SHOOT = (
    " Continue the same product shoot. "
    "IMAGE 1 (main-product.png) is the full t-shirt with its finished print. "
    "IMAGE 2 (artwork.png) is the isolated print graphic. "
    "Keep the same print 1:1. Preserve its size and placement relative to the shirt, "
    "original proportions, colors, text and illustration. "
    "Change only the scene, person and camera framing. Do not redraw the illustration "
    "from another viewpoint, widen, shorten, rotate or independently rescale it. "
    "The print follows the shirt surface and torso angle, never the image canvas. "
    "Artwork perspective inside the illustration stays unchanged; only the garment surface bends. "
    "IMAGE 1 is the authority for the product; an optional white-shirt scene controls only "
    "the person and location, never the artwork or print dimensions."
)


def standard_model_prompt(color: str, index: int) -> str:
    """Frames 2 and 3: lifestyle shots wearing the shirt from the straight reference."""
    return (
        STANDARD_SCENES[index]
        + f" The product is a {color} full-length regular-fit straight-cut cotton crewneck T-shirt. "
        "Natural standard regular fit, shoulder seams at the shoulder points and comfortable ease through "
        "the torso. On adult women the same full-length regular-cut shirt may drape slightly closer, "
        "without stretching. No oversized or boxy silhouette, dropped shoulders, extra-wide sleeves, "
        "elbow-length sleeves or exaggerated garment volume. Normal everyday T-shirt proportions. "
        "Wear the same finished printed shirt from IMAGE 1: preserve its complete illustration, colors, "
        "lettering and aspect ratio, no redesign, extra objects or repeated elements. Scene 4 may crop "
        "the design naturally with the camera. All human models are adults aged 18–25, distinctly "
        "youthful faces. Fashionable wide-leg baggy jeans or loose full-length denim trousers, skate "
        "sneakers, understated accessories. Shirt untucked and hem fully covers stomach and waistband. "
        "No cropped or lifted shirt, exposed midriff, underwear, swimwear, bare legs or sexualized pose. "
        "No slim-fit jeans or older-looking models. Choose different adult people freely for different "
        "model scenes; no recurring cast or prescribed facial features. Natural fabric texture and "
        "subtle drape, print unobstructed by hands, phone or hair. No added captions, badges, "
        "watermarks, typography or reserved header space. Vertical 3:4 photograph, 1200x1600. "
        "If same-scene-white-shirt.png is present, keep precisely that scene and adult identity, "
        "change only shirt color; artwork.png remains the print reference." + PRODUCT_SHOOT
    )


def outfit_flatlay_prompt(color: str) -> str:
    """Frame 4: flat lay of the shirt from the hero photo with jeans and sneakers."""
    return (
        f"Premium editorial outfit flat-lay photograph, overhead view: the same {color} printed "
        "regular-fit cotton T-shirt with natural shoulder seams and standard mid-upper-arm sleeves, "
        "laid neatly and fully visible as the central hero product, paired with "
        "wide-leg blue jeans folded alongside and unbranded skate sneakers at the edge. "
        "Warm gray concrete or textured studio floor, soft natural side lighting, stylish youth streetwear. "
        "Keep props outside the shirt front, the entire artwork readable, no objects on the print. "
        "Show neckline, sleeves and hem clearly. Preserve exactly the garment and physical print scale "
        "from main-product.png; do not enlarge artwork to fill the torso. Real cotton texture and seams. "
        "No people, captions, badges, watermarks, extra brand logos or feature claims. Vertical 3:4 "
        "photograph." + PRODUCT_SHOOT
    )

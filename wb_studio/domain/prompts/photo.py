"""Model photos of the redraw algorithms: scenes, poses, looks, backgrounds and the frame prompt."""

import random

LIVE_SCENES = (
    "CATALOG: head to hips, plain light neutral studio backdrop, soft daylight, the shirt and the whole print in "
    "focus.",
    "INTERIOR: {setting}, natural window light.",
    "OUTDOOR: {setting}, natural daylight.",
    "CLOSE-UP: from the shoulders to just below the hem, a softly blurred background of {setting}, soft side light showing "
    "the cotton texture and the ink; the face may be outside the crop.",
)
SCENE_KEYS = ("catalog", "interior", "outdoor", "closeup")  # names of LIVE_SCENES for the gallery analysis

# Frames without a seller pose combine one value of each list; a card never repeats a value, so its frames
# differ in body angle, framing and action at once.
BODY_ANGLES = (
    "body turned three-quarters to the left",
    "body turned three-quarters to the right",
    "facing the camera while in motion",
    "body at a slight angle",
)
FRAMINGS = ("full-length shot", "framed from head to knees", "waist-up shot")
ACTIONS = (
    "walking",
    "sitting on a stool or a ledge",
    "leaning a shoulder against a wall",
    "holding a coffee cup at hip level",
    "thumbs hooked in the jeans pockets",
    "adjusting a sleeve",
    "one hand on the hip",
    "looking away from the camera",
)


def body_pose(seed: int, index: int, scene: int) -> str:
    """The catalog scene stays frontal; other frames take distinct values from lists shuffled per card."""
    if scene == 0:
        return "standing upright, arms relaxed"
    shuffle = random.Random(seed)
    angles, framings, actions = (shuffle.sample(values, len(values)) for values in (BODY_ANGLES, FRAMINGS, ACTIONS))
    framing = "" if scene == 3 else f", {framings[index % len(framings)]}"  # the close-up sets its own framing
    return f"{angles[index % len(angles)]}, {actions[index % len(actions)]}{framing}"


# A look per frame, picked by the vendor number and the frame: every frame shows a different person.
AGES = ("in their early 20s", "in their mid 20s", "around 30", "in their mid 30s", "around 40", "in their mid 40s")
HAIR_COLORS = ("dark brown", "black", "light brown", "blond", "red", "ash blond", "chestnut")
HAIRSTYLES = {
    "female": ("long wavy", "shoulder-length bob", "ponytail", "short pixie", "messy bun", "long straight", "curly"),
    "male": ("short crew cut", "tousled medium-length", "buzz cut", "curly", "slicked-back", "undercut"),
    "unisex": ("short", "shoulder-length", "curly", "tied-back", "tousled"),
}
BUILDS = ("slim", "fit", "athletic")
DETAILS = {
    "female": ("freckles", "glasses", "small earrings", "a wristwatch", "no accessories"),
    "male": ("light stubble", "a short beard", "glasses", "a wristwatch", "clean-shaven"),
    "unisex": ("freckles", "glasses", "a wristwatch", "no accessories"),
}


def look(audience: str, seed: int, index: int = 0) -> str:
    """Age, hair, build and one detail; each frame of a card gets its own person."""
    kind = audience if audience in ("female", "male") else "unisex"
    pick = random.Random(seed * 7 + 1 + index * 1009)
    return (
        f"{pick.choice(AGES)}, {pick.choice(HAIR_COLORS)} {pick.choice(HAIRSTYLES[kind])} hair, "
        f"{pick.choice(BUILDS)} build, {pick.choice(DETAILS[kind])}"
    )


# Backgrounds of frames 2-4 and posed frames; picked by the vendor number, so neighbours differ.
SETTINGS = (
    "a bright Scandinavian living room with a sofa and plants",
    "a small home kitchen with morning light",
    "a loft with a brick wall and large windows",
    "a cozy bedroom with soft textiles",
    "a home office with bookshelves",
    "a cafe interior with wooden tables",
    "a quiet city street with old facades",
    "a green park alley with trees",
    "a waterfront promenade",
    "a modern courtyard with concrete and greenery",
    "a rooftop terrace above the city",
    "a sunny residential street with small houses",
)


INDOOR, OUTDOOR = SETTINGS[:6], SETTINGS[6:]


def setting(seed: int, index: int, scene: int | None = None) -> str:
    """Frames of one card get different backgrounds; the interior and outdoor scenes take matching places."""
    pool = INDOOR if scene == 1 else OUTDOOR if scene == 2 else SETTINGS
    return pool[(seed * 5 + index * 4) % len(pool)]


POSE_SCENE = (
    "Repeat the pose, camera distance and framing of pose-reference.png, with the whole print visible. "
    "Nothing else comes from it (person, clothes, print, colors, props, background); the setting is "
    "{setting}."
)

MODEL = (
    "an attractive, well-groomed fashion model with a symmetrical face, clear skin and a relaxed confident "
    "expression, as in a clothing brand catalogue"
)
PERSONS = {
    "female": f"a woman aged 18–45, {MODEL}",
    "male": f"a man aged 18–45, {MODEL}",
    "unisex": f"an adult aged 18–45 of any gender, {MODEL}",
}


PERSON_REFERENCE = (
    "PERSON: exactly the person from person-reference.png: the same face, hair, skin tone, age and build. "
    "Nothing else comes from it (clothes, pose, background, light). "
)


def print_placement(geometry: dict | None, reference: str | None = "main-product.png") -> str:
    """Exact print size in words: the model drifts from the reference image alone.

    reference: the attached shirt photo that shows the same size; None when no such image is sent.
    """
    if not geometry:
        return f"at the size and position from {reference}" if reference else "centered on the chest"
    body_width = geometry["body_cm"][0]
    same = f", exactly as in {reference}" if reference else ""
    return (
        f"centered on the chest, {geometry['width_cm']:.0f} cm wide ({geometry['width_cm'] / body_width:.0%} of "
        f"the shirt front width between the side seams) and {geometry['height_cm']:.0f} cm tall, top edge "
        f"{geometry['top_cm']} cm below the collar seam{same}. Never shrink it to a "
        "pocket or chest logo, never stretch it across the torso, never move it off-center"
    )


def live_photo_prompt(
    color: str,
    index: int,
    audience: str = "unisex",
    pose: bool = False,
    geometry: dict | None = None,
    seed: int = 0,
    scene: int | None = None,
    person: bool = False,
) -> str:
    """Model photo from the calibrated shirt reference and the clean print file.

    pose: a blurred seller photo is attached only as a pose and framing reference.
    geometry: print size from the straight reference, repeated in words.
    seed: the vendor number; it picks the look, pose and backgrounds, so neighbouring cards look different.
    scene: fixed scene of a frame without a seller pose (index of LIVE_SCENES); defaults to the frame index.
    person: a ready model photo is attached as person-reference.png and replaces the drawn look.
    """
    scene_index = index if scene is None else scene
    template = POSE_SCENE if pose else LIVE_SCENES[scene_index]
    scene_text = template.format(setting=setting(seed, index, None if pose else scene_index))
    body = "" if pose else f"POSE: {body_pose(seed, index, scene_index)}. "
    pose_note = (
        "pose-reference.png is a deliberately blurred photo used ONLY for body pose and camera framing; "
        "it says nothing about the shirt, the print or its position. "
        if pose
        else ""
    )
    people = (
        PERSON_REFERENCE
        if person
        else f"PERSON: {PERSONS.get(audience, PERSONS['unisex'])}. Looks: {look(audience, seed, index)}. "
    )
    return (
        "Photorealistic marketplace photo of a person wearing the T-shirt from main-product.png, which shows the "
        "shirt with the print at its exact size and position; artwork.png is the exact print. "
        + pose_note
        + f"SHIRT: solid {color.upper()} regular-fit cotton crewneck, short sleeves, not oversized. "
        f"PRINT: place artwork.png exactly once, {print_placement(geometry)}. Every element, letter, proportion "
        "and ink color stays unchanged; the ink follows the fabric folds with a matte cotton texture. "
        + people
        + "Jeans or trousers, shirt untucked. "
        f"SCENE: {scene_text} "
        + body
        + "The whole print on the chest is visible to the camera; the body may turn up to three-quarters and "
        "the head may look anywhere. "
        + "Hands, hair and props stay off the print. Natural light, anatomy and skin; no added text, badges, "
        "borders or collage. One vertical 3:4 photo."
    )

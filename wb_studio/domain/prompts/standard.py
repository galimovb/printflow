"""Prompts of the standard algorithm."""


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
    "Change only the scene and camera framing. Do not redraw the illustration "
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
        "lettering and aspect ratio, no redesign, extra objects or repeated elements. All human models are adults aged 18–25, distinctly "
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

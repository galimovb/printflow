"""Studio-wide constants and naming rules."""

PRODUCT = "tee_wb"
ALGORITHMS = ("standard", "source_redraw")
# Generation order: white first, so black scenes can repeat the white ones.
COLORS = ("white", "black")


# WB "Пол" accepts one value; unisex shirts leave it empty so the card is shown to everyone.
WB_GENDER = {"female": "Женский", "male": "Мужской"}

# Same shape as the main ozon-tee articles (TEE-<9 digits>-<3 digits><W|B>). The middle segment
# 100 is reserved for the studio: no existing article in the WB account uses it, so codes never clash.
VENDOR_PREFIX = "TEE"
STUDIO_SEGMENT = "100"


def vendor_codes(design_number: int, colors: list[str]) -> dict[str, str]:
    """TEE-<design>-100<W|B>; also the file name of the printable PNG."""
    return {
        color: f"{VENDOR_PREFIX}-{design_number:09d}-{STUDIO_SEGMENT}" + ("W" if color == "white" else "B")
        for color in colors
    }

"""Studio-wide constants and naming rules."""

PRODUCT = "tee_wb"
ALGORITHMS = ("standard", "source_redraw")
# Generation order: white first, so black scenes can repeat the white ones.
COLORS = ("white", "black")


# WB "Пол" accepts one value; unisex shirts leave it empty so the card is shown to everyone.
WB_GENDER = {"female": "Женский", "male": "Мужской"}

# Main ozon-tee articles are TEE-<9 digits>-...; a 6-digit design number keeps studio codes disjoint.
VENDOR_PREFIX = "TEE"


def group_number(merge_group: str | None) -> int:
    """PFWG-<campaign>-<n> -> n; a card outside a merge group is group 1."""
    tail = (merge_group or "").rsplit("-", 1)[-1]
    return int(tail) if tail.isdigit() else 1


def vendor_codes(design_number: int, colors: list[str], group: int = 1) -> dict[str, str]:
    """TEE-<design>-<group>-<W|B>; also the file name of the printable PNG."""
    return {
        color: f"{VENDOR_PREFIX}-{design_number:06d}-{group:03d}-" + ("W" if color == "white" else "B")
        for color in colors
    }

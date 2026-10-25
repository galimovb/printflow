"""Studio-wide constants and naming rules."""

PRODUCT = "tee_wb"
ALGORITHMS = ("standard", "source_redraw")
# Generation order: white first, so black scenes can repeat the white ones.
COLORS = ("white", "black")


def vendor_codes(design_number: int, colors: list[str]) -> dict[str, str]:
    """WB vendor code per color; also the file name of the printable PNG."""
    return {color: f"PFW-{design_number:06d}-" + ("W" if color == "white" else "B") for color in colors}

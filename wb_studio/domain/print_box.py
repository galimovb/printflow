"""The print's real size on the 54 cm wide oversize front: the straight reference lays it at this size."""

PRINT_WIDTH_CM = 30.0
MAX_PRINT_HEIGHT_CM = 39.0


def print_size_cm(aspect: float) -> tuple[float, float]:
    """(width, height) of a print of width/height `aspect`: 30 cm wide, at most 39 cm tall."""
    width, height = PRINT_WIDTH_CM, PRINT_WIDTH_CM / aspect
    if height > MAX_PRINT_HEIGHT_CM:
        width, height = MAX_PRINT_HEIGHT_CM * aspect, MAX_PRINT_HEIGHT_CM
    return width, height

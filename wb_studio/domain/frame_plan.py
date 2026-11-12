"""Frame plan of a template_mockup card: which ready photos go into the card, in what order, which get the print.

The model sees random candidate photos and answers per photo (view, open chest) plus an order; the code only
trusts what the answer proves: the first frame shows the front with an open chest, a back photo is kept as it
is (no print, at most one, never first), side photos and covered chests are never used.
"""

DRAWN_VIEWS = ("front", "closeup")


def choose_frames(data: dict, count: int, total: int) -> list[dict] | None:
    """[{index, draw}] for the card, or None when the answer cannot give a valid card (the caller falls back)."""
    views: dict[int, tuple[str | None, bool]] = {}
    for photo in data.get("photos") or []:
        if isinstance(photo, dict) and type(photo.get("index")) is int and 0 <= photo["index"] < total:
            views[photo["index"]] = (photo.get("view"), photo.get("chest_clear") is True)

    def drawable(index: int) -> bool:
        view, clear = views.get(index, (None, False))
        return view in DRAWN_VIEWS and clear

    order = [i for i in dict.fromkeys(data.get("order") or []) if type(i) is int and 0 <= i < total]
    chosen: list[dict] = []
    back_used = False
    for index in order:
        if len(chosen) == count:
            break
        if drawable(index):
            chosen.append({"index": index, "draw": True})
        elif views.get(index, (None,))[0] == "back" and chosen and not back_used:
            chosen.append({"index": index, "draw": False})
            back_used = True
    # Photos the model judged usable but left out of the order fill the gaps, in their own order.
    for index in sorted(views):
        if len(chosen) == count:
            break
        if drawable(index) and all(c["index"] != index for c in chosen):
            chosen.append({"index": index, "draw": True})
    if len(chosen) < count or not chosen[0]["draw"]:
        return None
    return chosen

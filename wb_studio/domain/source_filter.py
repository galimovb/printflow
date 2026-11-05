"""Filter sources; plan missing new views without replacing a source product."""


def photo_shows_print(photo: dict) -> bool:
    """The main front design is visible whole in normal light, whoever or whatever wears it.

    A cropped print is redrawn with invented letters («ЧЧИТЕЛЬ» from a hanger photo cutting off «У»). A seller
    banner around a real shirt photo counts as infographic, yet it is often the only whole view (5219).
    """
    return (
        photo.get("same_print") is True
        and photo.get("whole_print") is True
        and photo.get("normal_light") is True
        and photo.get("role") in ("front", "detail", "other", "infographic")
    )


def assess(data, count, max_print_width=0.9):
    reasons = []
    width = data.get("print_width")
    if type(width) not in (int, float) or not 0 < width <= 1:
        reasons.append("Не определена ширина принта")
    elif width >= max_print_width:  # the model tends to round down, so the limit itself rejects
        reasons.append("Принт раздут почти на всю ширину футболки")
    if data.get("small_print") is not False:
        reasons.append("Мелкий принт: логотип у ворота, на месте кармана или нашивка")
    if data.get("kids_print") is True:  # our models are adults, a child's print on them breaks its meaning
        reasons.append("Детский принт: на взрослой модели теряет смысл")
    if data.get("reaches_edges") is not False:
        reasons.append("Принт доходит до швов, рукава, ворота или низа футболки")
    if data.get("theme_match") is not True:
        reasons.append("Принт не соответствует теме или соответствие не подтверждено")
    if data.get("front_print") is not True:
        reasons.append("На лицевой стороне нет принта или он не подтверждён")
    if data.get("single_print") is not True or type(data.get("print_count")) is not int or data.get("print_count") != 1:
        reasons.append("На лицевой стороне несколько отдельных принтов далеко друг от друга")
    photos = data.get("photos", [])
    indexed = {}
    for photo in photos if isinstance(photos, list) else []:
        if not isinstance(photo, dict):
            continue
        index = photo.get("index")
        if type(index) is int and 0 <= index < count and index not in indexed:
            indexed[index] = photo
    if len(indexed) != count:
        reasons.append("Не все исходные фото классифицированы")
    eligible = []
    rejected = []
    for i in range(count):
        p = indexed.get(i, {})
        why = []
        if p.get("role") != "front":
            why.append("не передний ракурс на человеке")
        if p.get("same_print") is not True:
            why.append("нет того же основного принта")
        if p.get("normal_light") is not True:
            why.append("изменён цвет освещением или демонстрацией свечения")
        if p.get("adult") is not True:
            why.append("не подтверждена взрослая модель")
        if why:
            rejected.append({"index": i, "reasons": why})
        else:
            eligible.append(i)
    proposed = data.get("selected", [])
    selected = []
    for index in proposed if isinstance(proposed, list) else []:
        if type(index) is int and index in eligible and index not in selected:
            selected.append(index)
    selected = (selected + [i for i in eligible if i not in selected])[:4]
    # Eligible photos only supply poses; frames without one use the fixed scenes.
    original_selected = selected.copy()
    # The print may come from any photo that shows it whole: a child model, a flat lay, a close-up.
    showing = [i for i in range(count) if photo_shows_print(indexed.get(i, {}))]
    source = data.get("print_source")
    picked = [source] if type(source) is int else []
    # Only a photo with the whole print: the model's pick on an adult front, a selected front, the model's pick
    # anywhere else, the main photo, then any whole view.
    order = [i for i in (*[p for p in picked if p in eligible], *selected, *picked, 0, *showing) if i in showing]
    source = order[0] if order else None
    if source is None:
        reasons.append("Принт целиком не виден ни на одном фото")
    extra = list(range(len(selected), 4))
    selected.extend([source] * (4 - len(selected)))
    return {
        "accepted": not reasons,
        "reasons": reasons,
        "eligible": eligible,
        "print_source": source,
        "selected": selected,
        "original_selected": original_selected,
        "generated_extra_frames": extra,
        "rejected_photos": rejected,
        "single_print": data.get("single_print"),
        "print_count": data.get("print_count"),
        "print_width": width,
        "small_print": data.get("small_print"),
        "kids_print": data.get("kids_print"),
        "audience": data.get("audience"),
        "print_reason": data.get("print_reason", ""),
        "theme_match": data.get("theme_match"),
        "theme_reason": data.get("theme_reason", ""),
        "front_print": data.get("front_print"),
    }

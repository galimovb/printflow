"""Filter sources; plan missing new views without replacing a source product."""


def photo_shows_print(photo: dict) -> bool:
    """The main front design is visible in normal light, whoever or whatever wears it."""
    return (
        photo.get("same_print") is True
        and photo.get("normal_light") is True
        and photo.get("role") in ("front", "detail", "other")
    )


def assess(data, count, max_print_width=0.9):
    reasons = []
    width = data.get("print_width")
    if type(width) not in (int, float) or not 0 < width <= 1:
        reasons.append("Не определена ширина принта")
    elif width >= max_print_width:  # the model tends to round down, so the limit itself rejects
        reasons.append("Принт раздут почти на всю ширину футболки")
    if data.get("reaches_edges") is not False:
        reasons.append("Принт доходит до швов, рукава, ворота или низа футболки")
    if data.get("theme_match") is not True:
        reasons.append("Принт не соответствует теме или соответствие не подтверждено")
    if data.get("main_print_side") != "front":
        reasons.append("Основной принт не подтверждён только на передней стороне футболки")
    if data.get("single_print") is not True or type(data.get("print_count")) is not int or data.get("print_count") != 1:
        reasons.append("Не подтверждён один принт: отдельные верхний и нижний рисунки не допускаются")
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
    if type(source) is not int or source not in eligible:
        if selected:
            source = selected[0]
        elif source not in showing:
            source = showing[0] if showing else None
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
        "audience": data.get("audience"),
        "print_reason": data.get("print_reason", ""),
        "theme_match": data.get("theme_match"),
        "theme_reason": data.get("theme_reason", ""),
        "main_print_side": data.get("main_print_side"),
    }

"""WB content API request bodies for new cards: pure functions of a draft and its barcodes."""

import copy
import re
import unicodedata

from printflow.domain.errors import PermanentError
from printflow.wb_studio.domain.models import WB_GENDER


def validate(config):
    missing = []
    if not config.get("subject_id"):
        missing.append("subject_id")
    if not config.get("price") or config["price"] <= 0:
        missing.append("price")
    if not config.get("sizes"):
        missing.append("sizes")
    if not config.get("characteristics"):
        missing.append("characteristics")
    for key in ("length", "width", "height", "weightBrutto"):
        if not config.get("dimensions", {}).get(key) or config["dimensions"][key] <= 0:
            missing.append("dimensions." + key)
    if missing:
        raise PermanentError("WB: заполните wb_studio/config/config.json: " + ", ".join(missing))


def clean_text(value: str) -> str:
    """WB rejects the whole upload for a symbol such as ♥ or an emoji copied from a print's slogan."""
    kept = "".join(
        ch for ch in value
        if unicodedata.category(ch) not in ("So", "Cs", "Co") and ch not in "\u200d\ufe0e\ufe0f"
    )  # fmt: skip
    return re.sub(r"[ \t]{2,}", " ", kept).strip()


def build_payload(draft, barcodes):
    config = draft["config"]
    validate(config)
    if len(barcodes) != len(draft["images"]) * len(config["sizes"]):
        raise PermanentError("WB returned an unexpected barcode count")
    variants = []
    offset = 0
    for color in draft["images"]:
        entries = []
        for size in config["sizes"]:
            entries.append({**size, "price": config["price"], "skus": [barcodes[offset]]})
            offset += 1
        characteristics = copy.deepcopy(config["characteristics"])
        # Color ID comes from the configured subject dictionary, not an assumed constant.
        if config.get("color_attribute_id"):
            characteristics = [x for x in characteristics if int(x["id"]) != int(config["color_attribute_id"])]
            characteristics.append(
                {"id": config["color_attribute_id"], "value": ["белый" if color == "white" else "черный"]}
            )
        gender = WB_GENDER.get((draft.get("analysis") or {}).get("audience"))
        if config.get("gender_attribute_id") and gender:
            characteristics = [x for x in characteristics if int(x["id"]) != int(config["gender_attribute_id"])]
            characteristics.append({"id": config["gender_attribute_id"], "value": [gender]})
        variants.append(
            {
                "vendorCode": draft["vendor_codes"][color],
                "title": clean_text(draft["text"]["title"]),
                "description": clean_text(draft["text"]["description"]),
                "brand": config.get("brand", ""),
                "dimensions": config["dimensions"],
                "characteristics": characteristics,
                "sizes": entries,
                "kizMarked": bool(config.get("kiz_marked", False)),
            }
        )
    if offset != len(barcodes):
        raise ValueError("WB barcode count mismatch")
    return [{"subjectID": config["subject_id"], "variants": variants}]


def validate_group(drafts):
    if not drafts:
        raise PermanentError("WB: пустая группа публикации")
    variants = sum(len(d["images"]) for d in drafts)
    if variants > 30:
        raise PermanentError("WB: не более 30 цветовых вариантов в группе")
    base = drafts[0]["config"]
    vendors = []
    for draft in drafts:
        validate(draft["config"])
        if any(draft["config"].get(k) != base.get(k) for k in ("subject_id", "brand", "sizes", "price")):
            raise PermanentError("WB: предмет, бренд, размеры и цена должны совпадать внутри группы")
        for color in draft["images"]:
            vendors.append(draft["vendor_codes"][color])
    if len(vendors) != len(set(vendors)):
        raise PermanentError("WB: повтор артикула внутри группы")


def build_group_payload(drafts, barcodes):
    validate_group(drafts)
    expected = sum(len(d["images"]) * len(d["config"]["sizes"]) for d in drafts)
    if len(barcodes) != expected:
        raise PermanentError("WB returned an unexpected group barcode count")
    variants = []
    offset = 0
    for draft in drafts:
        count = len(draft["images"]) * len(draft["config"]["sizes"])
        variants.extend(build_payload(draft, barcodes[offset : offset + count])[0]["variants"])
        offset += count
    return [{"subjectID": drafts[0]["config"]["subject_id"], "variants": variants}]

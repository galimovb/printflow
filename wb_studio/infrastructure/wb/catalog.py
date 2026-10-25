"""WB image URL mapping reused from parser/prog/parser/run_wb.py."""

_BASKET_VOL_UPPER = (
    (143, "01"),
    (287, "02"),
    (431, "03"),
    (719, "04"),
    (1007, "05"),
    (1061, "06"),
    (1115, "07"),
    (1169, "08"),
    (1313, "09"),
    (1601, "10"),
    (1655, "11"),
    (1919, "12"),
    (2045, "13"),
    (2189, "14"),
    (2405, "15"),
    (2621, "16"),
    (2837, "17"),
    (3053, "18"),
    (3269, "19"),
    (3485, "20"),
    (3701, "21"),
    (3917, "22"),
    (4133, "23"),
    (4349, "24"),
    (4565, "25"),
    (4877, "26"),
    (5189, "27"),
    (5501, "28"),
    (5813, "29"),
    (6125, "30"),
    (6437, "31"),
    (6749, "32"),
    (7061, "33"),
    (7373, "34"),
    (7685, "35"),
    (7997, "36"),
    (8309, "37"),
    (8741, "38"),
    (9173, "39"),
    (9605, "40"),
    (10373, "41"),
    (11141, "42"),
    (11909, "43"),
    (12677, "44"),
    (13445, "45"),
    (14213, "46"),
)


def basket_host_for_nm(nm_id: int) -> str:
    vol = nm_id // 100_000
    basket = "47"
    for upper, code in _BASKET_VOL_UPPER:
        if vol <= upper:
            basket = code
            break
    return f"basket-{basket}.wbbasket.ru"


def wb_image_url(nm_id: int, pic_index: int = 1, size: str = "big") -> str:
    """Собирает CDN-URL фото по nm_id (как volHostV2 на сайте)."""
    vol = nm_id // 100_000
    part = nm_id // 1_000
    host = basket_host_for_nm(nm_id)
    return f"https://{host}/vol{vol}/part{part}/{nm_id}" f"/images/{size}/{pic_index}.webp"


def catalog_cards(payload):
    """Both seller and search catalog envelopes, in the server-provided order."""
    if not isinstance(payload, dict):
        return []
    products = payload.get("products")
    if not isinstance(products, list):
        for key in ("data", "result"):
            value = payload.get(key)
            if isinstance(value, dict) and isinstance(value.get("products"), list):
                products = value["products"]
                break
    if not isinstance(products, list):
        return []
    result = []
    for item in products:
        if not isinstance(item, dict):
            continue
        sku = str(item.get("id") or "")
        if not sku.isdigit():
            continue
        if int(item.get("subjectId") or 0) != 192 and "футболк" not in str(item.get("name", "")).lower():
            continue
        result.append(
            {
                "url": f"https://www.wildberries.ru/catalog/{sku}/detail.aspx",
                "title": str(item.get("name") or ""),
                "image": wb_image_url(int(sku)),
                "sku": sku,
                "seller_id": str(item.get("supplierId") or ""),
            }
        )
    return result

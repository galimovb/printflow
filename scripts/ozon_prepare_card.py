#!/usr/bin/env python3
"""Подготовить карточку товара по данным Ozon API (только чтение из Ozon), записать в products/<товар>/config/product.json.

    python -m printflow.scripts.ozon_prepare_card --product shopper
    python -m printflow.scripts.ozon_prepare_card --product mousepad --no-write   # только отчёт
    python -m printflow.scripts.ozon_prepare_card --product shopper --category 17028741 --type 93228

Что делает:
  1. /v1/description-category/tree — ищет тип товара (у товара: ozon_type_name, или --type-name).
  2. /v1/description-category/attribute — все характеристики этого типа.
  3. /v1/description-category/attribute/values(/search) — dictionary_value_id для значений
     из product.json → ozon.wishes и для цветов (colors.*.ozon_names).
  4. Пишет в product.json: ozon.category_id, ozon.type_id, ozon.attributes, colors.*.ozon_value.
  5. Печатает, какие обязательные характеристики ещё не заполнены.
"""
from __future__ import annotations

import argparse
import sys
from typing import Any

import httpx

from printflow.config import OzonSettings
from printflow.scripts._cli import add_product_arg, target, utf8_console
from printflow.services.ozon.attributes import ATTR_COLOR, ATTR_TYPE, SET_BY_CODE


def norm(text: Any) -> str:
    return str(text).lower().replace("ё", "е").strip()


class Ozon:
    def __init__(self, settings: OzonSettings, env_hint: str) -> None:
        if not settings.configured:
            sys.exit(f"Задайте ключи Ozon: {env_hint}")
        headers = {"Client-Id": settings.client_id, "Api-Key": settings.api_key}
        self.http = httpx.Client(base_url=settings.api_url, headers=headers, timeout=settings.timeout_sec)

    def post(self, path: str, body: dict) -> dict:
        resp = self.http.post(path, json=body)
        if resp.status_code >= 400:
            sys.exit(f"Ozon {path}: HTTP {resp.status_code} {resp.text[:500]}")
        return resp.json()


def walk_types(nodes: list[dict], path: list[str], cat_id: int | None, out: list[dict]) -> None:
    for node in nodes:
        cid = node.get("description_category_id") or cat_id
        name = node.get("category_name") or node.get("type_name") or ""
        if node.get("type_id"):
            out.append({"category_id": cid, "type_id": node["type_id"], "type_name": node.get("type_name", ""),
                        "path": " / ".join(p for p in path if p), "disabled": bool(node.get("disabled"))})
        walk_types(node.get("children") or [], [*path, name], cid, out)


def find_type(api: Ozon, type_name: str) -> tuple[int, int, str]:
    tree = api.post("/v1/description-category/tree", {"language": "DEFAULT"}).get("result") or []
    types: list[dict] = []
    walk_types(tree, [], None, types)
    exact = [t for t in types if norm(t["type_name"]) == norm(type_name) and not t["disabled"]]
    if not exact:
        for t in [t for t in types if norm(type_name)[:5] in norm(t["type_name"])][:30]:
            print(f"  --category {t['category_id']} --type {t['type_id']}  {t['path']} / {t['type_name']}")
        sys.exit(f"Тип «{type_name}» не найден. Похожие — выше; перезапустите с --category и --type")
    if len(exact) > 1:
        print(f"Найдено несколько типов «{type_name}», беру первый (проверьте!):")
        for t in exact:
            print(f"  --category {t['category_id']} --type {t['type_id']}  {t['path']}")
    t = exact[0]
    return int(t["category_id"]), int(t["type_id"]), f"{t['path']} / {t['type_name']}"


def dict_value(api: Ozon, cat: int, typ: int, attr_id: int, wanted: str) -> dict | None:
    """dictionary_value_id для значения: сначала поиск, потом полный перебор справочника."""
    target = norm(wanted)
    candidates: list[dict] = []
    if len(target) >= 2:
        body = {"attribute_id": attr_id, "description_category_id": cat, "type_id": typ,
                "value": wanted, "limit": 100}
        candidates = api.post("/v1/description-category/attribute/values/search", body).get("result") or []
    if not any(norm(c["value"]) == target for c in candidates):
        last_id = 0
        for _ in range(20):  # до 40 000 значений
            body = {"attribute_id": attr_id, "description_category_id": cat, "type_id": typ,
                    "language": "DEFAULT", "limit": 2000, "last_id": last_id}
            page = api.post("/v1/description-category/attribute/values", body)
            rows = page.get("result") or []
            candidates += rows
            if any(norm(r["value"]) == target for r in rows) or not page.get("has_next") or not rows:
                break
            last_id = rows[-1]["id"]
    exact = [c for c in candidates if norm(c["value"]) == target]
    loose = [c for c in candidates if target in norm(c["value"])]
    hit = (exact or loose or [None])[0]
    return {"dictionary_value_id": hit["id"], "value": hit["value"]} if hit else None


def main() -> int:
    utf8_console()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_product_arg(parser)
    parser.add_argument("--type-name", default=None, help="тип товара в дереве Ozon (по умолчанию — у товара)")
    parser.add_argument("--category", type=int, help="description_category_id (если знаете)")
    parser.add_argument("--type", dest="type_id", type=int, help="type_id (если знаете)")
    parser.add_argument("--no-write", action="store_true", help="ничего не записывать, только отчёт")
    args = parser.parse_args()

    t = target(args.product)
    api = Ozon(t.settings.ozon, f"{t.product.env_prefix}_OZON_CLIENT_ID / _API_KEY в printflow/.env")
    product = t.product.config
    if t.product.name == "thermo":
        from printflow.domain.models import CardSpec
        product = t.product.for_spec(CardSpec()).config
    if args.category and args.type_id:
        cat, typ, where = args.category, args.type_id, "(задано вручную)"
    else:
        cat, typ, where = find_type(api, args.type_name or t.product.ozon_type_name)
    print(f"Категория: {cat}, тип: {typ}  {where}")

    attrs = api.post("/v1/description-category/attribute",
                     {"description_category_id": cat, "type_id": typ, "language": "DEFAULT"}).get("result") or []
    print(f"Характеристик: {len(attrs)}, обязательных: {sum(1 for a in attrs if a.get('is_required'))}")

    wishes = {norm(k): (v if isinstance(v, list) else [v]) for k, v in product["ozon"]["wishes"].items()}
    resolved: list[dict] = []
    problems: list[str] = []
    for attr in attrs:
        aid = int(attr["id"])
        wanted = wishes.get(norm(attr["name"]))
        if aid in SET_BY_CODE or aid == ATTR_TYPE or not wanted:
            continue
        values: list[dict] = []
        for value in wanted:
            if not attr.get("dictionary_id"):
                values.append({"value": str(value)})
            elif hit := dict_value(api, cat, typ, aid, str(value)):
                values.append(hit)
            else:
                problems.append(f"«{attr['name']}»: в справочнике нет «{value}»")
        if not attr.get("is_collection"):
            values = values[:1]
        if values:
            resolved.append({"complex_id": 0, "id": aid, "values": values})
            print(f"  + {aid:>6} {attr['name']}: {', '.join(v['value'] for v in values)}")

    color_values: dict[str, list[dict]] = {}
    if any(int(a["id"]) == ATTR_COLOR for a in attrs):
        for color, spec in product["colors"].items():
            for name in spec["ozon_names"]:
                if hit := dict_value(api, cat, typ, ATTR_COLOR, name):
                    color_values[color] = [hit]
                    print(f"  + цвет {color}: {hit['value']} ({hit['dictionary_value_id']})")
                    break
            else:
                problems.append(f"цвет {color}: не нашёл ни одно из {spec['ozon_names']}")

    done = {a["id"] for a in resolved} | SET_BY_CODE | {ATTR_TYPE}
    missing = [a for a in attrs if a.get("is_required") and int(a["id"]) not in done]

    if not args.no_write:
        product["ozon"].update(category_id=cat, type_id=typ, attributes=resolved)
        if t.product.name == 'thermo':
            from printflow.products.thermo.domain.assortment import sizes
            product['ozon']['prepared_assortment_count'] = len(sizes(product))
        for color, value in color_values.items():
            product["colors"][color]["ozon_value"] = value
        if t.product.name == 'thermo':
            import copy
            root = copy.deepcopy(t.product.config)
            mode = product['assortment']['mode']
            root.setdefault('offers', {}).setdefault(mode, {})['ozon'] = copy.deepcopy(product['ozon'])
            root['colors'] = copy.deepcopy(product['colors'])
            t.product.save_config(root)
        else:
            t.product.save_config(product)
        print("\nЗаписано в product.json")

    if problems:
        print("\nНе удалось подобрать:")
        for p in problems:
            print(f"  ! {p}")
    if missing:
        print("\nОбязательные характеристики без значения — добавьте в product.json → ozon.wishes и перезапустите:")
        for a in missing:
            kind = "справочник" if a.get("dictionary_id") else a.get("type", "")
            print(f"  * {a['id']:>6} {a['name']} ({kind})")
    else:
        print("\nВсе обязательные характеристики заполнены.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

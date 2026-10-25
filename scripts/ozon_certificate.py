#!/usr/bin/env python3
"""Привязать к сертификату качества уже выложенные товары (артикулы с префиксом товара: BAG-, MSE-).

    python -m printflow.scripts.ozon_certificate --product shopper                 # сертификат из SHOPPER_OZON_CERTIFICATE_ID
    python -m printflow.scripts.ozon_certificate --product shopper --certificate-id 123
    python -m printflow.scripts.ozon_certificate --product mousepad --dry-run      # только показать

Новые товары привязываются сами после выкладки (шаг certificate в задаче карточки).
Сертификат должен быть загружен в кабинет товара.
"""
from __future__ import annotations

import argparse
import asyncio
import sys

from printflow.scripts._cli import Target, add_product_arg, target, utf8_console
from printflow.services.ozon.certificates import CertificateBinder
from printflow.services.ozon.client import OzonClient


async def product_ids(client: OzonClient, prefix: str) -> list[tuple[str, int]]:
    """(артикул, product_id) всех видимых товаров кабинета с префиксом."""
    found: list[tuple[str, int]] = []
    last_id = ""
    while True:
        result = (await client.post("/v3/product/list", {
            "filter": {"visibility": "ALL"}, "last_id": last_id, "limit": 1000,
        }))["result"]
        found += [(i["offer_id"], i["product_id"]) for i in result["items"] if i["offer_id"].startswith(prefix)]
        last_id = result.get("last_id") or ""
        if not result["items"] or not last_id:
            return found


async def run(t: Target, certificate_id: int, dry_run: bool) -> int:
    client = OzonClient(t.settings.ozon)
    products = await product_ids(client, t.product.article_prefix)
    print(f"Товаров «{t.product.title}» в кабинете: {len(products)}")
    if dry_run:
        for offer, pid in products[:20]:
            print(f"  {offer}  product_id={pid}")
        return 0
    bound = await CertificateBinder(client, certificate_id).bind(pid for _, pid in products)
    print(f"Привязано к сертификату {certificate_id}: {bound}")
    return 0


def main() -> int:
    utf8_console()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_product_arg(parser)
    parser.add_argument("--certificate-id", type=int, default=None, help="по умолчанию <ТОВАР>_OZON_CERTIFICATE_ID")
    parser.add_argument("--dry-run", action="store_true", help="только показать товары, ничего не привязывать")
    args = parser.parse_args()
    t = target(args.product)
    certificate_id = args.certificate_id or t.settings.ozon.certificate_id
    if not certificate_id and not args.dry_run:
        sys.exit(f"Укажите {t.product.env_prefix}_OZON_CERTIFICATE_ID в printflow/.env или --certificate-id")
    return asyncio.run(run(t, certificate_id, args.dry_run))  # type: ignore[arg-type]


if __name__ == "__main__":
    sys.exit(main())

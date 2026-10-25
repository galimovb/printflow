#!/usr/bin/env python3
"""Создать бакеты товара в S3 (тот же аккаунт, что у футболок) с публичным чтением.

    python -m printflow.scripts.create_buckets --product mousepad --dry-run   # только показать, каких нет
    python -m printflow.scripts.create_buckets --product mousepad             # создать недостающие

Бакеты — products/<товар>/config/product.json → buckets. Ссылки на фото уходят в Ozon напрямую, поэтому
бакеты открыты на чтение.
"""
from __future__ import annotations

import argparse
import json
import sys

import boto3

from printflow.scripts._cli import add_product_arg, target, utf8_console


def public_read_policy(bucket: str) -> str:
    return json.dumps({
        "Version": "2012-10-17",
        "Statement": [{"Effect": "Allow", "Principal": "*", "Action": ["s3:GetObject"],
                       "Resource": [f"arn:aws:s3:::{bucket}/*"]}],
    })


def main() -> int:
    utf8_console()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_product_arg(parser)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    t = target(args.product)
    s3 = t.app.s3
    if not s3.access_key or not s3.secret_key:
        sys.exit("Не заданы S3_ACCESS_KEY / S3_SECRET_KEY")
    client = boto3.client("s3", endpoint_url=s3.endpoint or None, region_name=s3.region,
                          aws_access_key_id=s3.access_key, aws_secret_access_key=s3.secret_key)
    existing = {b["Name"] for b in client.list_buckets().get("Buckets", [])}
    for bucket in t.product.buckets.values():
        if bucket in existing:
            print(f"  = {bucket}: уже есть")
            continue
        if args.dry_run:
            print(f"  - {bucket}: нет (создать без --dry-run)")
            continue
        client.create_bucket(Bucket=bucket)
        client.put_bucket_policy(Bucket=bucket, Policy=public_read_policy(bucket))
        print(f"  + {bucket}: создан, публичное чтение")
    return 0


if __name__ == "__main__":
    sys.exit(main())

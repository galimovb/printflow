"""S3: тот же аккаунт, что у футболок; бакеты шопперов — из product.json. Ссылки — прямые публичные."""
from __future__ import annotations

import asyncio

import boto3

from printflow.config import S3Settings
from printflow.domain.errors import ShopperError


class Storage:
    def __init__(self, settings: S3Settings) -> None:
        if not settings.access_key or not settings.secret_key:
            raise ShopperError("Не заданы S3_ACCESS_KEY / S3_SECRET_KEY")
        self.public_base = settings.public_base
        self.client = boto3.client(
            "s3",
            endpoint_url=settings.endpoint or None,
            region_name=settings.region,
            aws_access_key_id=settings.access_key,
            aws_secret_access_key=settings.secret_key,
        )

    def url(self, bucket: str, key: str) -> str:
        """Прямая публичная ссылка (бакеты с public-read)."""
        return f"{self.public_base}/{bucket}/{key}"

    async def put(self, bucket: str, key: str, data: bytes, content_type: str) -> str:
        await asyncio.to_thread(self.client.put_object, Bucket=bucket, Key=key, Body=data, ContentType=content_type)
        return self.url(bucket, key)

    async def get(self, bucket: str, key: str) -> bytes:
        response = await asyncio.to_thread(self.client.get_object, Bucket=bucket, Key=key)
        return await asyncio.to_thread(response["Body"].read)

    def key_of(self, url: str, bucket: str) -> str | None:
        """Ключ объекта по прямой ссылке этого бакета (url()) — или None, если ссылка чужая."""
        prefix = f"{self.public_base}/{bucket}/"
        return url[len(prefix):] if url.startswith(prefix) else None

    async def delete(self, bucket: str, keys: list[str]) -> int:
        """Удаляет объекты пачками по 1000 (лимит S3 DeleteObjects); возвращает число удалённых."""
        deleted = 0
        for start in range(0, len(keys), 1000):
            chunk = [{"Key": k} for k in keys[start:start + 1000]]
            response = await asyncio.to_thread(self.client.delete_objects, Bucket=bucket,
                                               Delete={"Objects": chunk, "Quiet": True})
            if errors := response.get("Errors"):
                raise ShopperError(f"S3 не удалил {len(errors)} объектов в {bucket}: {errors[0]}")
            deleted += len(chunk)
        return deleted

    async def exists(self, bucket: str, key: str) -> bool:
        try:
            await asyncio.to_thread(self.client.head_object, Bucket=bucket, Key=key)
        except self.client.exceptions.ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in ("404", "NoSuchKey", "NotFound"):
                return False
            raise
        return True

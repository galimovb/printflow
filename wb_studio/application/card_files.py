"""Storage layout of one WB card job and resumable progress helpers."""

import asyncio
import io
from collections.abc import Awaitable, Callable, Iterable

from PIL import Image, ImageOps

Save = Callable[[str, dict], None]

GALLERY_SIZE = (1200, 1600)
MIN_PHOTO_SIDE = 700


def to_png(raw: bytes) -> bytes:
    """WB serves WEBP/JPEG; store sources as PNG so every reader decodes them the same way."""
    out = io.BytesIO()
    Image.open(io.BytesIO(raw)).convert("RGB").save(out, format="PNG")
    return out.getvalue()


async def gather_all(coroutines: Iterable[Awaitable]) -> list:
    """Run siblings to completion before re-raising, so progress of the others is saved."""
    outcomes = await asyncio.gather(*coroutines, return_exceptions=True)
    for outcome in outcomes:
        if isinstance(outcome, BaseException):
            raise outcome
    return outcomes


class CardFiles:
    """Keys under printflow-wb/<job id>/ in the prints and mockups buckets."""

    def __init__(self, storage, buckets: dict, job_id: str, result: dict, save: Save):
        self.storage = storage
        self.buckets = buckets
        self.prefix = f"printflow-wb/{job_id}"
        self.result = result
        self.save = save

    async def get(self, bucket: str, name: str) -> bytes:
        return await self.storage.get(self.buckets[bucket], f"{self.prefix}/{name}")

    async def put(self, bucket: str, name: str, data: bytes, content_type: str = "image/png") -> str:
        return await self.storage.put(self.buckets[bucket], f"{self.prefix}/{name}", data, content_type)

    async def put_shared(self, bucket: str, key: str, data: bytes) -> str:
        """Outside the job folder, e.g. printable files named by WB vendor code."""
        return await self.storage.put(self.buckets[bucket], key, data, "image/png")

    async def source_photo(self, index: int) -> bytes:
        return await self.get("mockups", f"sources/{index + 1:02}.png")

    async def store_frame(self, color: str, index: int, raw: bytes) -> None:
        """Archive the raw PNG and publish a 3:4 JPEG; the public list never has holes."""
        image = Image.open(io.BytesIO(raw)).convert("RGB")
        if min(image.size) < MIN_PHOTO_SIDE:
            raise RuntimeError("Generated gallery image is too small")
        name = f"{color}/{index + 1:02}"
        await self.put("mockups", f"{name}.png", raw)
        out = io.BytesIO()
        ImageOps.fit(image, GALLERY_SIZE).save(out, format="JPEG", quality=95)
        slots = self.result.setdefault("photo_checkpoints", {}).setdefault(color, {})
        slots[str(index)] = await self.put("mockups", f"{name}.jpg", out.getvalue(), "image/jpeg")
        ordered = []
        while str(len(ordered)) in slots:
            ordered.append(slots[str(len(ordered))])
        self.result.setdefault("images", {})[color] = ordered
        self.save(f"photo:{color}:{index + 1}", self.result)

    def has_frame(self, color: str, index: int) -> bool:
        return str(index) in self.result.get("photo_checkpoints", {}).get(color, {})

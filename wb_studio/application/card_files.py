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
    """Keys under printflow-wb/<job id>/ in the prints, mockups and temporary buckets.

    temporary holds working files (seller photos, print candidates, references); they are
    deleted once the card is finished or permanently rejected.
    """

    def __init__(self, storage, buckets: dict, job_id: str, result: dict, save: Save):
        self.storage = storage
        self.buckets = buckets
        self.prefix = f"printflow-wb/{job_id}"
        self.result = result
        self.persist = save
        self.last_stage = "started"

    def save(self, stage: str, result: dict) -> None:
        self.last_stage = stage
        self.persist(stage, result)

    async def get(self, bucket: str, name: str) -> bytes:
        return await self.storage.get(self.buckets[bucket], f"{self.prefix}/{name}")

    async def put(self, bucket: str, name: str, data: bytes, content_type: str = "image/png") -> str:
        key = f"{self.prefix}/{name}"
        if bucket == "temporary":
            temporary = self.result.setdefault("temporary_files", [])
            if key not in temporary:
                temporary.append(key)
        return await self.storage.put(self.buckets[bucket], key, data, content_type)

    async def remove_temporary(self) -> int:
        """Delete all working files of this card; the stored result keeps only final assets."""
        keys = self.result.get("temporary_files", [])
        if keys:
            await self.storage.delete(self.buckets["temporary"], keys)
        self.result["temporary_files"] = []
        self.result["temporary_removed"] = True
        return len(keys)

    async def put_shared(self, bucket: str, key: str, data: bytes) -> str:
        """Outside the job folder, e.g. printable files named by WB vendor code."""
        return await self.storage.put(self.buckets[bucket], key, data, "image/png")

    async def source_photo(self, index: int) -> bytes:
        return await self.get("temporary", f"sources/{index + 1:02}.png")

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

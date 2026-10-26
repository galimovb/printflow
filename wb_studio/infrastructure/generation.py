"""Paid OpenAI requests. Run only from an explicitly enqueued studio job."""

import base64
import io
import json
import re

from openai import AsyncOpenAI
from PIL import Image, ImageDraw, ImageFont

from printflow.domain.errors import PermanentError
from printflow.services.printing.chromakey import finalize_print
from printflow.wb_studio.domain import prompts
from printflow.wb_studio.domain.source_filter import assess

from .errors import generation_errors

REASONING_MODELS = ("gpt-5", "gpt-6", "o1", "o3", "o4")


def data_url(raw: bytes, mime: str = "image/jpeg") -> str:
    return f"data:{mime};base64," + base64.b64encode(raw).decode()


def jpeg(image: Image.Image, quality: int = 90) -> bytes:
    out = io.BytesIO()
    image.convert("RGB").save(out, format="JPEG", quality=quality)
    return out.getvalue()


def png(image: Image.Image) -> bytes:
    out = io.BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


def label_font(size: int) -> ImageFont.ImageFont:
    for name in ("C:/Windows/Fonts/arial.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def numbered_photo(raw: bytes, index: int) -> bytes:
    """Gallery photo with a visible PHOTO_INDEX header, so answers cite the right photo."""
    image = Image.open(io.BytesIO(raw)).convert("RGB")
    image.thumbnail((900, 900))
    numbered = Image.new("RGB", (image.width, image.height + 65), "white")
    numbered.paste(image, (0, 65))
    ImageDraw.Draw(numbered).text((10, 10), f"PHOTO_INDEX={index}", font=label_font(34), fill="black")
    return jpeg(numbered, quality=85)


def on_gray(raw: bytes) -> bytes:
    """Transparent prints on neutral gray, so the judge never mistakes background for ink."""
    image = Image.open(io.BytesIO(raw)).convert("RGBA")
    image.thumbnail((1024, 1024))
    background = Image.new("RGBA", image.size, "#bbbbbb")
    background.alpha_composite(image)
    return jpeg(background)


def on_chromakey(raw: bytes) -> bytes:
    image = Image.open(io.BytesIO(raw)).convert("RGBA")
    keyed = Image.new("RGBA", image.size, "#90EE90")
    keyed.alpha_composite(image)
    return png(keyed.convert("RGB"))


def photo_index(value) -> int | None:
    """The model sometimes echoes the photo object or its label instead of the index."""
    if isinstance(value, dict):
        value = value.get("index", value.get("label"))
    if isinstance(value, str):
        match = re.fullmatch(r"(?:PHOTO_INDEX=)?(\d+)", value.strip())
        return int(match[1]) if match else None
    return value if type(value) is int else None


class Generator:
    def __init__(self, env: dict, config: dict):
        self.config = config
        self.key = env.get("OPENAI_API_KEY", "")
        self.base = env.get("OPENAI_BASE_URL") or None

    def client(self) -> AsyncOpenAI:
        if not self.key:
            raise PermanentError("OPENAI_API_KEY is not configured")
        return AsyncOpenAI(api_key=self.key, base_url=self.base, timeout=300)

    # --- transport ------------------------------------------------------------

    @generation_errors
    async def edit(self, files: list[tuple], prompt: str, *, request_timeout: float | None = None) -> bytes:
        client = self.client()
        if request_timeout is not None:
            client = client.with_options(timeout=request_timeout, max_retries=0)
        async with client:
            response = await client.images.edit(
                model=self.config["image_model"],
                image=files,
                prompt=prompt,
                size=self.config["image_size"],
                quality=self.config["image_quality"],
            )
        if not response.data or not response.data[0].b64_json:
            raise RuntimeError("Image generation returned no image")
        return base64.b64decode(response.data[0].b64_json)

    @generation_errors
    async def chat_json(self, content: list[dict], *, model: str, retries: bool = True) -> dict:
        client = self.client()
        if not retries:
            client = client.with_options(max_retries=0)
        async with client:
            # Reasoning models reject a fixed temperature; the rest answer deterministically with 0.
            options = {} if model.startswith(REASONING_MODELS) else {"temperature": 0}
            response = await client.chat.completions.create(
                model=model,
                response_format={"type": "json_object"},
                messages=[{"role": "user", "content": content}],
                **options,
            )
        return json.loads(response.choices[0].message.content)

    async def judge(self, prompt: str, images: list[bytes]) -> dict:
        content = [{"type": "text", "text": prompt}]
        content += [
            {"type": "image_url", "image_url": {"url": data_url(on_gray(raw)), "detail": "high"}} for raw in images
        ]
        model = self.config.get("vision_model", self.config["name_model"])
        return await self.chat_json(content, model=model)

    def listing_text(self, title: str, description: str, limit: int) -> dict:
        """Model text plus the fixed product facts from config, within WB limits."""
        facts = self.config.get("description_product_facts", "").strip()
        description = description[: max(0, limit - len(facts) - 2)] if facts else description[:limit]
        if facts:
            description = description.rstrip() + "\n\n" + facts
        return {"title": title[:60], "description": description[:1500]}

    # --- source_redraw ----------------------------------------------------------

    async def analyze_gallery(self, photos: list[bytes], theme: str) -> dict:
        content = [{"type": "text", "text": prompts.gallery_analysis_prompt(theme)}]
        for index, raw in enumerate(photos):
            content += [
                {"type": "text", "text": f"PHOTO INDEX {index}"},
                {"type": "image_url", "image_url": {"url": data_url(numbered_photo(raw, index))}},
            ]
        data = await self.chat_json(
            content, model=self.config.get("analysis_model", self.config["name_model"]), retries=False
        )
        roles = data.get("photos")
        if not isinstance(roles, list):
            raise RuntimeError("Missing gallery photo classifications")
        for item in roles:
            if isinstance(item, dict):
                label = re.fullmatch(r"PHOTO_INDEX=(\d+)", str(item.get("label", "")).strip())
                if label:
                    item["index"] = int(label[1])
        if not isinstance(data.get("title"), str) or not isinstance(data.get("description"), str):
            raise RuntimeError("Invalid combined listing text")
        data["print_source"] = photo_index(data.get("print_source"))
        assessment = assess(data, len(photos), self.config.get("max_print_width", 0.9))
        audience = data.get("audience") if data.get("audience") in ("female", "male") else "unisex"
        return {
            "selected": assessment["selected"],
            "print_source": assessment["print_source"],
            "photos": roles,
            "accepted": assessment["accepted"],
            "filter": assessment,
            "audience": audience,
            "text": self.listing_text(data["title"], data["description"][:400], 1500),
        }

    async def extract_print(self, source: bytes, expected_print: str = "", feedback: str = "") -> bytes:
        prompt = prompts.extract_print_prompt(expected_print, feedback)
        return finalize_print(await self.edit([("source-photo.png", source, "image/png")], prompt))

    async def recolor_print(self, art: bytes, color: str, feedback: str = "") -> bytes:
        prompt = prompts.recolor_print_prompt(color, feedback)
        return finalize_print(await self.edit([("artwork.png", on_chromakey(art), "image/png")], prompt))

    async def verify_prints(self, source: bytes, prints: dict[str, bytes], expected_print: str = "") -> dict:
        keys = list(prints)
        data = await self.judge(prompts.verify_prints_prompt(keys, expected_print), [source, *prints.values()])
        for key in keys:
            if not isinstance(data.get(key), dict) or type(data[key].get("accepted")) is not bool:
                raise RuntimeError("Missing automatic print verification")
        return {key: data[key] for key in keys}

    async def live_photo(
        self, product: bytes, art: bytes, color: str, index: int, audience: str = "unisex", pose: bytes | None = None
    ) -> bytes:
        files = [("main-product.png", product, "image/png"), ("artwork.png", art, "image/png")]
        if pose:
            files.append(("pose-reference.png", pose, "image/png"))
        return await self.edit(files, prompts.live_photo_prompt(color, index, audience, bool(pose)))

    # --- standard -------------------------------------------------------------

    async def extract(self, reference: bytes, theme: str) -> bytes:
        image = Image.open(io.BytesIO(reference)).convert("RGB")
        image.thumbnail((1536, 1536))
        result = await self.edit([("source.png", png(image), "image/png")], prompts.standard_extract_prompt(theme))
        return finalize_print(result)

    async def describe(self, art: bytes, theme: str) -> dict:
        image = Image.open(io.BytesIO(art)).convert("RGBA")
        image.thumbnail((700, 700))
        background = Image.new("RGBA", image.size, "white")
        background.alpha_composite(image)
        content = [
            {"type": "text", "text": prompts.describe_prompt(theme)},
            {"type": "image_url", "image_url": {"url": data_url(jpeg(background, 75)), "detail": "high"}},
        ]
        result = await self.chat_json(content, model=self.config["name_model"])
        if not isinstance(result.get("title"), str) or not isinstance(result.get("description"), str):
            raise RuntimeError("Invalid generated listing text")
        return self.listing_text(result["title"], result["description"], 1500)

    async def adapt_print(self, art: bytes, color: str) -> bytes:
        from server.prompts import products_import_extract_print_prompt

        if color not in ("white", "black"):
            raise ValueError("Unsupported garment color")
        prompt = products_import_extract_print_prompt(shirt_color=color)
        return finalize_print(await self.edit([("original-artwork.png", art, "image/png")], prompt))

    async def standard_photo(
        self, art: bytes, product: bytes, color: str, index: int, white_scene: bytes | None = None
    ) -> bytes:
        """Frames 2-3 are lifestyle shots, frame 4 a flat lay; product is the finished shirt."""
        prompt = prompts.outfit_flatlay_prompt(color) if index == 3 else prompts.standard_model_prompt(color, index)
        files = [("main-product.png", product, "image/png"), ("artwork.png", art, "image/png")]
        if white_scene:
            files.append(("same-scene-white-shirt.png", white_scene, "image/png"))
        return await self.edit(files, prompt, request_timeout=180)

"""Paid OpenAI requests. Run only from an explicitly enqueued studio job."""

import base64
import io
import json
import re

from openai import AsyncOpenAI
from PIL import Image

from printflow.domain.errors import PermanentError
from printflow.services.printing.chromakey import finalize_print
from printflow.wb_studio.domain import prompts
from printflow.wb_studio.domain.print_tone import despill
from printflow.wb_studio.domain.source_filter import assess

from . import usage
from .errors import generation_errors
from .images import blurred, data_url, jpeg, numbered_photo, on_canvas, on_gray, png, shrunk

REASONING_MODELS = ("gpt-5", "gpt-6", "o1", "o3", "o4")


def clean_print(raw: bytes) -> bytes:
    """Cut-out print: chroma key to transparency, then the green cast of the key removed from edges and shadows."""
    return despill(finalize_print(raw))


def photo_index(value) -> int | None:
    """The model sometimes echoes the photo object or its label instead of the index."""
    if isinstance(value, dict):
        value = value.get("index", value.get("label"))
    if isinstance(value, str):
        match = re.fullmatch(r"(?:PHOTO_INDEX=)?(\d+)", value.strip())
        return int(match[1]) if match else None
    return value if type(value) is int else None



def flag(env_value: str | None, default: bool) -> bool:
    """An env switch ("1", "true", "yes" or "0", "false", "no") over the config default."""
    if env_value is None or env_value.strip() == "":
        return bool(default)
    return env_value.strip().lower() in ("1", "true", "yes")

class Generator:
    def __init__(self, env: dict, config: dict):
        self.config = config
        # Env values override the config frozen in a job, so they also reach cards already queued.
        self.image_quality = env.get("PRINTFLOW_WB_IMAGE_QUALITY") or config["image_quality"]
        self.photo_quality = env.get("PRINTFLOW_WB_PHOTO_QUALITY") or config.get("photo_quality") or self.image_quality
        # template_mockup collages: medium. On low a collage costs $0.037 against $0.050, but the print came out
        # spoiled (6416: a melted gnome head) and a low extraction outlined white ink in black in 3 runs of 5, so no
        # flat ink was left to invert (2026-11-10).
        self.template_quality = (
            env.get("PRINTFLOW_WB_TEMPLATE_QUALITY") or config.get("template_quality") or self.image_quality
        )
        self.extract_quality = (
            env.get("PRINTFLOW_WB_EXTRACT_QUALITY") or config.get("extract_quality") or self.image_quality
        )
        # check_frames after every collage: its verdicts are stored in the card (frame_checks, frame_problems).
        # Off: two more vision requests a card, $0.023 or 14% of a card (2026-11-10, 144 cards).
        # frame_redraw: a spoiled collage is redrawn once and a second spoiled one fails the card; off.
        self.frame_check = flag(env.get("PRINTFLOW_WB_FRAME_CHECK"), config.get("frame_check", False))
        self.frame_redraw = flag(env.get("PRINTFLOW_WB_FRAME_REDRAW"), config.get("frame_redraw", False))
        self.reasoning_effort = env.get("PRINTFLOW_WB_REASONING_EFFORT") or config.get("reasoning_effort")
        # Longest side of the reference images sent with each model photo.
        self.photo_input_side = int(env.get("PRINTFLOW_WB_PHOTO_INPUT_SIDE") or config.get("photo_input_side", 768))
        # template_mockup frames: input images are about 65% of a frame's price at full size (2026-11-09); the model
        # only needs the pose, the shirt and where the print sits, the output keeps the template's own size.
        # template_mockup frames may use another image model than extraction and recolor (gpt-image-2.6 on low drew
        # sharper prints than 2.5 on medium, 2026-11-09).
        self.frame_model = env.get("PRINTFLOW_WB_FRAME_MODEL") or config.get("frame_model") or config.get("image_model")
        self.frame_input_side = int(env.get("PRINTFLOW_WB_FRAME_INPUT_SIDE") or config.get("frame_input_side", 768))
        # The 2x2 frame collage: each cell comes out at the template's 1024x1536.
        self.collage_size = env.get("PRINTFLOW_WB_COLLAGE_SIZE") or config.get("collage_size", "2048x3072")
        # One model for gallery analysis and print checks; the env value also reaches cards already queued.
        self.analysis_model = env.get("PRINTFLOW_WB_ANALYSIS_MODEL") or config.get(
            "analysis_model", config["name_model"]
        )
        self.vision_model = env.get("PRINTFLOW_WB_ANALYSIS_MODEL") or config.get("vision_model", config["name_model"])
        self.key = env.get("OPENAI_API_KEY", "")
        self.base = env.get("OPENAI_BASE_URL") or None

    def client(self) -> AsyncOpenAI:
        if not self.key:
            raise PermanentError("OPENAI_API_KEY is not configured")
        return AsyncOpenAI(api_key=self.key, base_url=self.base, timeout=300)

    # --- transport ------------------------------------------------------------

    @generation_errors
    async def edit(
        self,
        files: list[tuple],
        prompt: str,
        *,
        request_timeout: float | None = None,
        quality: str | None = None,
        size: str | None = None,
        purpose: str = "",
        model: str | None = None,
    ) -> bytes:
        model = model or self.config["image_model"]
        client = self.client()
        if request_timeout is not None:
            client = client.with_options(timeout=request_timeout, max_retries=0)
        async with client:
            response = await client.images.edit(
                model=model,
                image=files,
                prompt=prompt,
                size=size or self.config["image_size"],
                quality=quality or self.image_quality,
            )
        usage.record("image", purpose, model, getattr(response, "usage", None),
                     quality=quality or self.image_quality, size=size or self.config["image_size"])  # fmt: skip
        if not response.data or not response.data[0].b64_json:
            raise RuntimeError("Image generation returned no image")
        return base64.b64decode(response.data[0].b64_json)

    @generation_errors
    async def chat_json(self, content: list[dict], *, model: str, retries: bool = True, purpose: str = "") -> dict:
        client = self.client()
        if not retries:
            client = client.with_options(max_retries=0)
        async with client:
            # Reasoning models reject a fixed temperature; the rest answer deterministically with 0.
            options = {} if model.startswith(REASONING_MODELS) else {"temperature": 0}
            if model.startswith(REASONING_MODELS) and self.reasoning_effort:
                options["reasoning_effort"] = self.reasoning_effort
            response = await client.chat.completions.create(
                model=model,
                response_format={"type": "json_object"},
                messages=[{"role": "user", "content": content}],
                **options,
            )
        usage.record(
            "chat", purpose, model, getattr(response, "usage", None), reasoning_effort=options.get("reasoning_effort")
        )
        return json.loads(response.choices[0].message.content)

    async def judge(self, prompt: str, images: list[bytes], fabrics: list[str] | None = None) -> dict:
        """fabrics: per image the background it is shown on; gray by default."""
        fabrics = fabrics or ["#bbbbbb"] * len(images)
        content = [{"type": "text", "text": prompt}]
        # High detail: at low (about 512 px) single letters blur, the judge read words by meaning and passed
        # «ЧЧИТЕЛЬ» for «УЧИТЕЛЬ» (5219, 2026-11-05).
        content += [
            {"type": "image_url", "image_url": {"url": data_url(on_gray(raw, fabric)), "detail": "high"}}
            for raw, fabric in zip(images, fabrics, strict=True)
        ]
        model = self.vision_model
        return await self.chat_json(content, model=model, purpose="verify")

    def listing_text(self, title: str, description: str, limit: int) -> dict:
        """Model text plus the fixed product facts from config, within WB limits."""
        facts = self.config.get("description_product_facts", "").strip()
        description = description[: max(0, limit - len(facts) - 2)] if facts else description[:limit]
        if facts:
            description = description.rstrip() + "\n\n" + facts
        return {"title": title[:60], "description": description[:1500]}

    # --- source_redraw ----------------------------------------------------------

    async def plan_frames(self, photos: list[bytes], count: int, print_summary: str) -> dict:
        """template_mockup: which of the candidate photos go into the card and in what order (raw answer)."""
        content = [{"type": "text", "text": prompts.frame_plan_prompt(count, print_summary)}]
        for index, raw in enumerate(photos):
            content.append(
                {"type": "image_url", "image_url": {"url": data_url(numbered_photo(raw, index)), "detail": "low"}}
            )
        return await self.chat_json(content, model=self.analysis_model, purpose="frame_plan")

    async def analyze_gallery(self, photos: list[bytes], theme: str, source_title: str = "") -> dict:
        content = [{"type": "text", "text": prompts.gallery_analysis_prompt(theme, source_title)}]
        for index, raw in enumerate(photos):
            content += [
                {"type": "text", "text": f"PHOTO INDEX {index}"},
                {"type": "image_url", "image_url": {"url": data_url(numbered_photo(raw, index)), "detail": "low"}},
            ]
        data = await self.chat_json(content, model=self.analysis_model, retries=False, purpose="analysis")
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
        shirt_color = data.get("shirt_color") if data.get("shirt_color") in ("white", "black") else "white"
        recolor = data.get("recolor") if isinstance(data.get("recolor"), dict) else {}
        order = [s for s in data.get("scene_order") or [] if s in prompts.SCENE_KEYS]
        scene_order = list(dict.fromkeys(order + list(prompts.SCENE_KEYS)))
        return {
            "selected": assessment["selected"],
            "print_source": assessment["print_source"],
            "photos": roles,
            "accepted": assessment["accepted"],
            "filter": assessment,
            "audience": audience,
            "shirt_color": shirt_color,
            # Per shirt color one fixed recolor action; "none" puts the print onto that fabric as it is.
            "recolor": {
                color: recolor.get(color) if recolor.get(color) in prompts.RECOLOR_ACTIONS else "none"
                for color in ("white", "black")
            },
            "scene_order": scene_order,
            "text": self.listing_text(data["title"], data["description"][:400], 1500),
        }

    async def extract_print(self, source: bytes, expected_print: str = "", feedback: str = "") -> bytes:
        prompt = prompts.extract_print_prompt(expected_print, feedback)
        files = [("source-photo.png", source, "image/png")]
        return clean_print(await self.edit(files, prompt, quality=self.extract_quality, purpose="extract"))

    async def recolor_print(self, art: bytes, color: str, action: str, feedback: str = "") -> bytes:
        image = Image.open(io.BytesIO(art))
        box = image.getchannel("A").getbbox() if image.mode == "RGBA" else None
        width, height = (box[2] - box[0], box[3] - box[1]) if box else image.size
        prompt = prompts.recolor_print_prompt(color, action, feedback, width / height)
        out_width, out_height = (int(x) for x in self.config["image_size"].split("x"))
        files = [("artwork.png", on_canvas(art, out_width / out_height), "image/png")]
        return clean_print(await self.edit(files, prompt, purpose="recolor"))

    async def tone_print(self, source: bytes, color: str, expected_print: str = "", feedback: str = "") -> bytes:
        """tone: a picture is cut out of the seller photo again, made for this shirt color directly."""
        prompt = prompts.tone_print_prompt(color, expected_print, feedback)
        files = [("source-photo.png", source, "image/png")]
        return clean_print(await self.edit(files, prompt, quality=self.extract_quality, purpose="tone"))

    async def recolor_needed(self, art: bytes, colors: list[str]) -> dict[str, bool]:
        """Per color: is anything of the extracted file lost on that fabric when printed as it is."""
        data = await self.judge(prompts.recolor_need_prompt(colors), [art] * len(colors), list(colors))
        answers = {c: data.get(c) for c in colors}
        return {c: a["lost"] for c, a in answers.items() if isinstance(a, dict) and type(a.get("lost")) is bool}

    async def verify_prints(
        self, source: bytes, prints: dict[str, bytes], expected_print: str = "", changes: dict | None = None
    ) -> dict:
        keys = list(prints)
        prompt = prompts.verify_prints_prompt(keys, expected_print, changes)
        # A color version is judged on its own fabric: that is how it is printed and what the buyer sees.
        fabrics = ["#bbbbbb", *("#bbbbbb" if key == "base" else key for key in keys)]
        data = await self.judge(prompt, [source, *prints.values()], fabrics)
        for key in keys:
            if not isinstance(data.get(key), dict) or type(data[key].get("accepted")) is not bool:
                raise RuntimeError("Missing automatic print verification")
        return {key: data[key] for key in keys}

    async def live_photo(
        self,
        product: bytes,
        art: bytes,
        color: str,
        index: int,
        audience: str = "unisex",
        pose: bytes | None = None,
        geometry: dict | None = None,
        seed: int = 0,
        scene: int | None = None,
        person: bytes | None = None,
    ) -> bytes:
        side = self.photo_input_side
        files = [
            ("main-product.png", shrunk(product, side), "image/png"),
            ("artwork.png", shrunk(art, side), "image/png"),
        ]
        if pose:
            files.append(("pose-reference.png", blurred(pose, side * 2 // 3), "image/png"))
        if person:
            files.append(("person-reference.png", shrunk(person, side), "image/png"))
        prompt = prompts.live_photo_prompt(color, index, audience, bool(pose), geometry, seed, scene, bool(person))
        return await self.edit(files, prompt, quality=self.photo_quality, purpose="live_photo")

    async def frame_collage(self, collage: bytes, products: dict[str, bytes], colors: list[str]) -> bytes:
        """template_mockup: four template photos as a 2x2 collage (`colors`: the shirt color of each cell, row by row),
        every person dressed in the straight reference shirt of that color (`products`, the print laid by code at
        30 cm). One request for four frames; each cell comes out at the template's 1024x1536.

        No separate print file: with it the model scaled the print from that big image (about 70% of the shirt width
        instead of 56%); from the flat shirt alone it came out near 60% with the same letters (2026-11-07)."""
        files = [("template.png", collage, "image/png")]
        for color in sorted(set(colors), key=colors.index):
            files.append((f"main-product-{color}.png", shrunk(products[color], self.frame_input_side), "image/png"))
        return await self.edit(
            files,
            prompts.frame_collage_prompt(colors),
            quality=self.template_quality,
            size=self.collage_size,
            purpose="frame",
            model=self.frame_model,
        )

    async def check_frames(self, prints: dict[str, bytes], frames: list[tuple[str, bytes]]) -> list[dict]:
        """template_mockup: per drawn frame (shirt color, image), is its print the same as the print file of that
        color everywhere it shows. One request for the frames of a collage."""
        colors = sorted({color for color, _ in frames}, key=[color for color, _ in frames].index)
        prompt = prompts.frame_check_prompt(colors, [color for color, _ in frames])
        images = [prints[color] for color in colors] + [raw for _, raw in frames]
        data = await self.judge(prompt, images, [*colors, *["#bbbbbb"] * len(frames)])
        verdicts = [data.get(str(i + 1)) for i in range(len(frames))]
        if not all(isinstance(v, dict) and type(v.get("ok")) is bool for v in verdicts):
            raise RuntimeError("Missing automatic frame check")
        return [{"ok": v["ok"], "reason": str(v.get("reason") or "")} for v in verdicts]

    # --- standard -------------------------------------------------------------

    async def extract(self, reference: bytes, theme: str) -> bytes:
        image = Image.open(io.BytesIO(reference)).convert("RGB")
        image.thumbnail((1536, 1536))
        result = await self.edit(
            [("source.png", png(image), "image/png")], prompts.standard_extract_prompt(theme), purpose="extract"
        )
        return clean_print(result)

    async def describe(self, art: bytes, theme: str) -> dict:
        image = Image.open(io.BytesIO(art)).convert("RGBA")
        image.thumbnail((700, 700))
        background = Image.new("RGBA", image.size, "white")
        background.alpha_composite(image)
        content = [
            {"type": "text", "text": prompts.describe_prompt(theme)},
            {"type": "image_url", "image_url": {"url": data_url(jpeg(background, 75)), "detail": "low"}},
        ]
        result = await self.chat_json(content, model=self.config["name_model"], purpose="describe")
        if not isinstance(result.get("title"), str) or not isinstance(result.get("description"), str):
            raise RuntimeError("Invalid generated listing text")
        return self.listing_text(result["title"], result["description"], 1500)

    async def adapt_print(self, art: bytes, color: str) -> bytes:
        from server.prompts import products_import_extract_print_prompt

        if color not in ("white", "black"):
            raise ValueError("Unsupported garment color")
        prompt = products_import_extract_print_prompt(shirt_color=color)
        return clean_print(await self.edit([("original-artwork.png", art, "image/png")], prompt, purpose="adapt"))

    async def standard_photo(
        self, art: bytes, product: bytes, color: str, index: int, white_scene: bytes | None = None
    ) -> bytes:
        """Frames 2-3 are lifestyle shots, frame 4 a flat lay; product is the finished shirt."""
        prompt = prompts.outfit_flatlay_prompt(color) if index == 3 else prompts.standard_model_prompt(color, index)
        files = [("main-product.png", product, "image/png"), ("artwork.png", art, "image/png")]
        if white_scene:
            files.append(("same-scene-white-shirt.png", white_scene, "image/png"))
        return await self.edit(files, prompt, request_timeout=180, quality=self.photo_quality, purpose="standard_photo")

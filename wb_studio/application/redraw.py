"""source_redraw: reuse a seller's print and redraw the seller's photos with our shirt.

1. Download up to 20 gallery photos.
2. One request analyses the gallery: theme, single front print, width, audience,
   up to four model photos, listing text. Rejected products stop here.
3. The print is extracted once. A color version redraws that clean file only when
   its ink would vanish on the fabric. One shared check, one retry per file.
4. Four model photos per color, all in parallel. A frame with its own seller photo
   copies that pose; the rest use fixed scenes. Frames 5-6 are prebuilt slides.
"""

from printflow.domain.errors import PermanentError
from printflow.wb_studio.domain.print_contrast import vanishing_ink
from printflow.wb_studio.infrastructure.rendering.info_slides import info_slide
from printflow.wb_studio.infrastructure.rendering.straight_reference import prepare_straight_reference

from .card_files import CardFiles, gather_all, to_png

MAX_GALLERY_PHOTOS = 20
MODEL_FRAMES = 4
MAX_PRINT_ATTEMPTS = 2


class RedrawPipeline:
    def __init__(self, studio, job, generator, files: CardFiles):
        self.studio = studio
        self.job = job
        self.config = job.payload["config"]
        self.generator = generator
        self.files = files
        self.result = files.result

    async def run(self) -> None:
        await self.download_gallery()
        analysis = await self.analyze()
        text = self.result["text"]
        expected = f"{text['title']}. {text['description']}"
        source = await self.files.source_photo(analysis["print_source"])
        await self.extract_prints(source, expected)
        if not self.result.get("print"):
            first = await self.files.get("prints", f"prints/{self.config['colors'][0]}.png")
            self.result["print"] = await self.files.put("prints", "print.png", first)
            self.files.save("print_ready", self.result)
        await self.studio.save_article_prints(self.job, self.result, self.files)
        await self.gallery(analysis)

    async def download_gallery(self) -> None:
        urls = self.job.payload["source"].get("images", [])[:MAX_GALLERY_PHOTOS]
        if not urls:
            raise PermanentError("Нет исходных фото карточки")
        archived = self.result.setdefault("source_photos", {})

        async def download(index: int, url: str) -> None:
            if str(index) in archived:
                return
            raw = to_png(await self.studio.fetch_photo(url))
            archived[str(index)] = await self.files.put("temporary", f"sources/{index + 1:02}.png", raw)
            self.files.save(f"source_saved:{index + 1}", self.result)

        await gather_all(download(i, url) for i, url in enumerate(urls))
        self.result.setdefault("source", archived["0"])

    async def analyze(self) -> dict:
        if not self.result.get("analysis"):
            photos = [await self.files.source_photo(i) for i in range(len(self.result["source_photos"]))]
            async with self.studio.photo_slots:
                analysis = await self.generator.analyze_gallery(photos, self.job.payload["theme"])
            self.result["analysis"] = analysis
            self.result["text"] = analysis["text"]
            self.files.save("gallery_analyzed", self.result)
        analysis = self.result["analysis"]
        if analysis.get("accepted") is not True:
            verdict = analysis.get("filter") or {"accepted": False, "reasons": ["Нет результата фильтра"]}
            self.result["source_filter"] = verdict
            self.files.save("source_rejected", self.result)
            raise PermanentError("Исходная карточка отклонена фильтром: " + "; ".join(verdict.get("reasons", [])))
        return analysis

    async def extract_prints(self, source: bytes, expected: str) -> None:
        """Candidates live under candidates/<key>.png; accepted ones become prints/<color>.png."""
        colors = self.config["colors"]
        result = self.result
        variants = result.setdefault("print_variants", {})
        checks = result.setdefault("print_checks", {})
        candidates = result.setdefault("print_candidates", {})
        attempts = result.setdefault("print_attempts", {})

        async def put_candidate(key: str, raw: bytes) -> None:
            candidates[key] = await self.files.put("temporary", f"candidates/{key}.png", raw)

        async def candidate(key: str) -> bytes:
            return await self.files.get("temporary", f"candidates/{key}.png")

        while not all(color in variants for color in colors):
            for key, check in checks.items():
                if check.get("accepted") is False and attempts.get(key, 0) >= MAX_PRINT_ATTEMPTS:
                    raise PermanentError(
                        "Извлечённый принт не прошёл автоматическую проверку: " + str(check.get("reason", ""))
                    )
            if "base" not in candidates or checks.get("base", {}).get("accepted") is False:
                feedback = str(checks.pop("base", {}).get("reason", ""))
                async with self.studio.photo_slots:
                    raw = await self.generator.extract_print(source, expected, feedback)
                attempts["base"] = attempts.get("base", 0) + 1
                await put_candidate("base", raw)
                # Color versions derive from the base, so a new base invalidates them.
                for color in colors:
                    candidates.pop(color, None)
                    checks.pop(color, None)
                    attempts.pop(color, None)
                self.files.save("print_extracted", result)
            base = await candidate("base")

            async def recolor(color: str, base: bytes) -> None:
                pending = color in candidates and checks.get(color, {}).get("accepted") is not False
                if color in variants or pending or not vanishing_ink(base, color):
                    return
                feedback = str(checks.pop(color, {}).get("reason", ""))
                async with self.studio.photo_slots:
                    raw = await self.generator.recolor_print(base, color, feedback)
                attempts[color] = attempts.get(color, 0) + 1
                await put_candidate(color, raw)
                self.files.save(f"print_recolored:{color}", result)

            await gather_all(recolor(color, base) for color in colors)
            unchecked = {} if checks.get("base", {}).get("accepted") is True else {"base": base}
            for color in colors:
                if color in candidates and color not in checks:
                    unchecked[color] = await candidate(color)
            if unchecked:
                async with self.studio.photo_slots:
                    checks.update(await self.generator.verify_prints(source, unchecked, expected))
            if checks.get("base", {}).get("accepted") is True:
                for color in colors:
                    if color in variants:
                        continue
                    if color not in candidates:
                        raw = base
                    elif checks.get(color, {}).get("accepted") is True:
                        raw = await candidate(color)
                    else:
                        continue
                    variants[color] = await self.files.put("prints", f"prints/{color}.png", raw)
            self.files.save("print_checked", result)

    async def gallery(self, analysis: dict) -> None:
        """All frames of both colors at once; no automatic photo check, the card goes to manual review."""
        colors = self.config["colors"]
        audience = analysis.get("audience", "unisex")
        own = analysis.get("filter", {}).get("original_selected", [])[:MODEL_FRAMES]
        poses = [await self.files.source_photo(i) for i in own]
        arts = {color: await self.files.get("prints", f"prints/{color}.png") for color in colors}
        references = {color: prepare_straight_reference(arts[color], color, self.config) for color in colors}

        async def frame(color: str, index: int) -> None:
            if self.files.has_frame(color, index):
                return
            if index >= MODEL_FRAMES:
                await self.files.store_frame(color, index, info_slide(index, color, self.config))
                return
            pose = poses[index] if index < len(poses) else None
            product, geometry = references[color]
            async with self.studio.photo_slots:
                raw = await self.studio.with_photo_timeout(
                    self.generator.live_photo(product, arts[color], color, index, audience, pose, geometry)
                )
            await self.files.store_frame(color, index, raw)

        await gather_all(frame(color, i) for color in colors for i in range(self.config["photos_per_color"]))

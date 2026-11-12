"""source_redraw: reuse a seller's print and redraw the seller's photos with our shirt.

1. Download up to 20 gallery photos.
2. One request analyses the gallery: theme, single front print, width, audience,
   up to four model photos, listing text. Rejected products stop here.
3. The print is extracted once. A color version comes only when the gallery analysis picks a recolor
   action for that fabric: lettering and outlines are redrawn on the clean file, a flat logo takes the
   contrast ink by pixels, a picture with shading is cut out of the seller photo again for that fabric.
   One shared check, one retry per file.
4. Four model photos, all in parallel, only in the seller's shirt color. A frame with its own
   seller photo copies that pose; the rest use fixed scenes. Frames 5-6 are prebuilt slides.
"""

from printflow.domain.errors import PermanentError
from printflow.wb_studio.domain.print_tone import MIN_VANISHING_PIXELS, invert_flat, one_color_ink, vanishing_ink
from printflow.wb_studio.domain.prompts import SCENE_KEYS
from printflow.wb_studio.infrastructure.rendering.info_slides import info_slide
from printflow.wb_studio.infrastructure.rendering.straight_reference import prepare_straight_reference

from .card_files import CardFiles, gather_all, to_png

MAX_GALLERY_PHOTOS = 20
MODEL_FRAMES = 4
MAX_PRINT_ATTEMPTS = 2


class RedrawPipeline:
    def __init__(self, cards, job, generator, files: CardFiles):
        self.cards = cards
        self.job = job
        self.config = dict(job.payload["config"])
        self.generator = generator
        self.files = files
        self.result = files.result

    async def run(self) -> None:
        await self.download_gallery()
        analysis = await self.analyze()
        self.use_source_color(analysis)
        text = self.result["text"]
        expected = f"{text['title']}. {text['description']}"
        # A resumed card with its prints done never touches the seller photos: they may be gone already.
        if not all(color in self.result.get("print_variants", {}) for color in self.config["colors"]):
            source = await self.files.source_photo(analysis["print_source"])
            await self.extract_prints(source, expected)
        if not self.result.get("print"):
            first = await self.files.get("prints", f"prints/{self.config['colors'][0]}.png")
            self.result["print"] = await self.files.put("prints", "print.png", first)
            self.files.save("print_ready", self.result)
        await self.cards.save_article_prints(self.job, self.result, self.files)
        await self.gallery(analysis)

    async def download_gallery(self) -> None:
        urls = self.job.payload["source"].get("images", [])[:MAX_GALLERY_PHOTOS]
        if not urls:
            raise PermanentError("Нет исходных фото карточки")
        archived = self.result.setdefault("source_photos", {})

        async def download(index: int, url: str) -> None:
            if str(index) in archived:
                return
            raw = to_png(await self.cards.fetch_photo(url))
            archived[str(index)] = await self.files.put("temporary", f"sources/{index + 1:02}.png", raw)
            self.files.save(f"source_saved:{index + 1}", self.result)

        await gather_all(download(i, url) for i, url in enumerate(urls))
        self.result.setdefault("source", archived["0"])

    async def analyze(self) -> dict:
        if not self.result.get("analysis"):
            photos = [await self.files.source_photo(i) for i in range(len(self.result["source_photos"]))]
            async with self.cards.photo_slots:
                title = self.job.payload["source"].get("title", "")
                analysis = await self.generator.analyze_gallery(photos, self.job.payload["theme"], title)
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

    def use_source_color(self, analysis: dict) -> None:
        """One card per print: the seller's shirt color, so the print is shown on the fabric it was made for."""
        color = analysis.get("shirt_color")
        if color in self.config["colors"]:
            self.config["colors"] = [color]
        self.result["colors"] = self.config["colors"]

    async def extract_prints(self, source: bytes, expected: str) -> None:
        """Candidates live under candidates/<key>.png; accepted ones become prints/<color>.png."""
        colors = self.config["colors"]
        result = self.result
        variants = result.setdefault("print_variants", {})
        checks = result.setdefault("print_checks", {})
        candidates = result.setdefault("print_candidates", {})
        attempts = result.setdefault("print_attempts", {})
        # The gallery analysis picks one fixed recolor action per color, so the print keeps its meaning.
        changes = (result.get("analysis") or {}).get("recolor") or {}

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
                async with self.cards.photo_slots:
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
            await self.review_recolor(base, changes)

            async def recolor(color: str, base: bytes) -> None:
                if changes.get(color) != "invert_flat" and one_color_ink(base) == ("dark" if color == "black" else "light"):
                    # One flat ink that vanishes on this fabric: flipping it keeps every shape, free and exact.
                    # The analysis sometimes asked for a redraw (unreadable dark blots, 5259) or for nothing.
                    changes[color] = "invert_flat"
                pending = color in candidates and checks.get(color, {}).get("accepted") is not False
                if changes.get(color, "none") == "none" or color in variants or pending:
                    return
                feedback = str(checks.pop(color, {}).get("reason", ""))
                action = changes[color]
                if action == "invert_flat":
                    raw = invert_flat(base, color)  # a flat logo only changes its ink: exact and free
                else:
                    async with self.cards.photo_slots:
                        if action == "tone":  # a recolor turns a picture negative: cut it out for this fabric
                            raw = await self.generator.tone_print(source, color, expected, feedback)
                        else:
                            raw = await self.generator.recolor_print(base, color, action, feedback)
                attempts[color] = attempts.get(color, 0) + 1
                await put_candidate(color, raw)
                self.files.save(f"print_recolored:{color}", result)

            await gather_all(recolor(color, base) for color in colors)
            unchecked = {} if checks.get("base", {}).get("accepted") is True else {"base": base}
            for color in colors:
                if color in candidates and color not in checks:
                    unchecked[color] = await candidate(color)
            if unchecked:
                async with self.cards.photo_slots:
                    checks.update(await self.generator.verify_prints(source, unchecked, expected, changes))
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

    async def review_recolor(self, base: bytes, changes: dict) -> None:
        """The analysis picks recolor actions from the seller photo; the extracted file decides whether they are needed
        (once per extracted base). Code first: letters or lines of the fabric's own color lying on bare fabric vanish,
        so that color is recolored whatever the analysis or the model says (5929: the model judged white letters on a
        white shirt fine). Otherwise the model looks at the file on the fabric and may cancel a needless recolor."""
        result = self.result
        key = str(result.get("print_attempts", {}).get("base", 0))
        if result.get("recolor_reviewed") == key:
            return
        review = result.setdefault("recolor_review", {})
        asked = []
        for color in self.config["colors"]:
            action = changes.get(color, "none")
            pixels = vanishing_ink(base, color)
            if pixels >= MIN_VANISHING_PIXELS:
                if action == "none":
                    changes[color] = "lettering_and_outlines"
                review[color] = {"asked": action, "vanishing_pixels": pixels, "kept": changes[color]}
            elif action != "none":
                asked.append(color)
        if asked:
            async with self.cards.photo_slots:
                lost = await self.generator.recolor_needed(base, asked)
            for color in asked:
                review[color] = {"asked": changes[color], "lost": lost.get(color)}
                if lost.get(color) is False:
                    changes[color] = "none"
        result["recolor_reviewed"] = key
        self.files.save("recolor_reviewed", result)

    async def gallery(self, analysis: dict) -> None:
        """All frames of both colors at once; no automatic photo check, the card goes to manual review."""
        colors = self.config["colors"]
        audience = analysis.get("audience", "unisex")
        own = analysis.get("filter", {}).get("original_selected", [])[:MODEL_FRAMES]
        # Seller poses are read only for frames still to draw; finished frames never need the seller photos.
        missing = [i for i in range(len(own)) if not all(self.files.has_frame(c, i) for c in colors)]
        poses = [await self.files.source_photo(own[i]) if i in missing else b"" for i in range(len(own))]
        arts = {color: await self.files.get("prints", f"prints/{color}.png") for color in colors}
        references = {color: prepare_straight_reference(arts[color], color, self.config) for color in colors}

        async def frame(color: str, index: int) -> None:
            if self.files.has_frame(color, index):
                return
            if index >= MODEL_FRAMES:
                await self.files.store_frame(color, index, info_slide(index, color, self.config))
                return
            pose = poses[index] if index < len(poses) else None
            # Frames without a seller pose take the fixed scenes the analysis ranked most complementary;
            # the first frame is the main WB photo, so without a seller pose it is always the catalog shot.
            order = list(analysis.get("scene_order") or SCENE_KEYS)
            if not poses:
                order = ["catalog"] + [key for key in order if key != "catalog"]
            scene = None if pose else SCENE_KEYS.index(order[(index - len(poses)) % len(order)])
            product, geometry = references[color]
            person = self.person(index, audience)
            async with self.cards.photo_slots:
                raw = await self.cards.with_photo_timeout(
                    self.generator.live_photo(
                        product,
                        arts[color],
                        color,
                        index,
                        person.gender if person else audience,
                        pose,
                        geometry,
                        self.job.design_number or 0,
                        scene,
                        person=person.photo if person else None,
                    )
                )
            await self.files.store_frame(color, index, raw)

        await gather_all(frame(color, i) for color in colors for i in range(self.config["photos_per_color"]))

    def person(self, index: int, audience: str):
        """The person of a model frame is drawn from the prompt; model_reference hands over a ready model."""
        return None

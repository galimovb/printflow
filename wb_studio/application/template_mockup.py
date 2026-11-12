"""template_mockup: source_redraw whose model frames come from ready mockup photos instead of generation.

After the gallery analysis (the audience is known) the card looks at 8 random candidate photos of that set, each
from another series (another person and place) and, while slot types last, another slot (pose and framing). One
more request orders 4 of them for the card and marks the back view, which is used as it is (the print is front
only). The code accepts only a plan whose first frame shows an open chest; otherwise, or with
PRINTFLOW_WB_TEMPLATE_MIX=0, the card keeps one series: frames 01, 03, 04 (back) and 05. Frames 5-6 are the
prebuilt slides. Both colors come from one extracted print, recolored only where the analysis asks for it; the
white and black photos of a series and slot show the same pose, so both colors get the same frames. Frames come from
2x2 collage requests: each row is one pose in white and in black, so the print matches on both shirts; a card takes two
such requests instead of eight single frames. Every drawn frame is checked against its print file by the vision model
(frame_check) and a spoiled print is marked in frame_problems; with frame_redraw on (off for now) that collage is
redrawn once and a second spoiled one fails the card.

The print's size comes from the straight reference, as in the other algorithms: a flat shirt with the print laid by
code at 30 cm (main-product.png). The photo model gets the clean photo, that reference and the print file, and draws
the print on the photo at the same share of the shirt, behind whatever covers the chest.
"""

from printflow.domain.errors import PermanentError
from printflow.wb_studio.domain.frame_plan import choose_frames
from printflow.wb_studio.infrastructure.images import collage, collage_cells
from printflow.wb_studio.infrastructure.rendering.info_slides import info_slide
from printflow.wb_studio.infrastructure.rendering.straight_reference import prepare_straight_reference
from printflow.wb_studio.infrastructure.template_library import TemplateShot

from .card_files import gather_all
from .redraw import MODEL_FRAMES, RedrawPipeline

TEMPLATE_SLOTS = (1, 3, 4, 5)
BACK_SLOT = 4
FRAME_CANDIDATES = 8
# A collage whose print is spoiled on any drawn frame is drawn once more; a second spoiled one stops the card.
MAX_COLLAGE_ATTEMPTS = 2


class TemplatePipeline(RedrawPipeline):
    def use_source_color(self, analysis: dict) -> None:
        """Both colors from one extracted print: every series has black and white frames anyway."""
        self.result["colors"] = self.config["colors"]

    async def plan_frames(self, analysis: dict, seed: str) -> list[dict]:
        """Mixed frames: random candidates from different series and slots, the model orders them and marks the
        back; an answer that cannot make a valid card gives [] and the card keeps one series."""
        if self.cards.env.get("PRINTFLOW_WB_TEMPLATE_MIX", "1").lower() in ("0", "false", "no"):
            return []
        shots = self.cards.templates.candidates(analysis.get("audience", "unisex"), seed, FRAME_CANDIDATES)
        # White is enough: the black photo of the same series and slot has the same person, pose and place.
        photos = [await self.cards.templates.shot(shot, "white") for shot in shots]
        summary = (self.result.get("text") or {}).get("title", "")
        async with self.cards.photo_slots:
            answer = await self.generator.plan_frames(photos, MODEL_FRAMES, summary)
        chosen = choose_frames(answer, MODEL_FRAMES, len(shots))
        self.result["frame_plan_reason"] = str(answer.get("reason", ""))[:300]
        if not chosen:
            return []
        return [{"gender": shots[c["index"]].gender, "series": shots[c["index"]].series,
                 "slot": shots[c["index"]].slot, "draw": c["draw"]} for c in chosen]  # fmt: skip

    async def gallery(self, analysis: dict) -> None:
        colors = self.config["colors"]
        # The source link joins the vendor number: local runs number every card 1.
        seed = f"{self.job.design_number or 0}:{self.job.payload['source'].get('url', '')}"
        if "template_frames" not in self.result:
            self.result["template_frames"] = await self.plan_frames(analysis, seed)
            self.files.save("frames_planned", self.result)
        plan = self.result["template_frames"]
        series = self.cards.templates.pick(analysis.get("audience", "unisex"), seed)
        if plan:
            series = type(series)(plan[0]["gender"], plan[0]["series"])  # the hero's series, for reports
        self.result["template_series"] = {"gender": series.gender, "number": series.number}
        arts = {color: await self.files.get("prints", f"prints/{color}.png") for color in colors}
        references = {color: prepare_straight_reference(arts[color], color, self.config) for color in colors}

        async def template_for(color: str, index: int) -> tuple[bytes, bool]:
            if plan:
                shot = plan[index]
                shot = TemplateShot(shot["gender"], shot["series"], shot["slot"])
                return await self.cards.templates.shot(shot, color), plan[index]["draw"]
            slot = TEMPLATE_SLOTS[index]
            return await self.cards.templates.photo(series, color, slot), slot != BACK_SLOT

        async def slides() -> None:
            for index in range(MODEL_FRAMES, self.config["photos_per_color"]):
                for color in colors:
                    if not self.files.has_frame(color, index):
                        await self.files.store_frame(color, index, info_slide(index, color, self.config))

        async def model_frames(cells: list[tuple[int, str]]) -> None:
            """Four model frames (`cells`: frame index and shirt color, row by row) from one 2x2 collage request. With
            two colors a row is one pose in both colors side by side, so the print matches on both shirts. A back view
            goes into the collage only to keep the layout and is stored as the clean template."""
            missing = [cell for cell in cells if not self.files.has_frame(cell[1], cell[0])]
            if not missing:
                return
            shots = [await template_for(color, index) for index, color in cells]
            products = {color: references[color][0] for _, color in cells}
            key = "+".join(f"{index}{color}" for index, color in cells)
            attempts = self.result.setdefault("frame_attempts", {})
            checks = self.result.setdefault("frame_checks", {})
            while True:
                request = self.generator.frame_collage(
                    collage([photo for photo, _ in shots]), products, [color for _, color in cells]
                )
                async with self.cards.photo_slots:
                    raw = await self.cards.with_photo_timeout(request)
                attempts[key] = attempts.get(key, 0) + 1
                pieces = collage_cells(raw)
                # Only the frames that go into the card with the print are checked; back views stay templates.
                drawn = [(cell, piece) for cell, piece, (_, draw) in zip(cells, pieces, shots, strict=True)
                         if draw and cell in missing]  # fmt: skip
                frames = [(cell[1], piece) for cell, piece in drawn]
                checking = bool(frames) and getattr(self.generator, "frame_check", False)
                verdicts = await self.generator.check_frames(arts, frames) if checking else []
                bad = [(cell, v["reason"]) for (cell, _), v in zip(drawn, verdicts) if not v["ok"]]
                if checking:
                    checks[key] = [
                        {"frame": cell[0] + 1, "color": cell[1], **v} for (cell, _), v in zip(drawn, verdicts)
                    ]
                problems = self.result.setdefault("frame_problems", {})
                problems.pop(key, None)
                if bad:
                    problems[key] = [{"frame": cell[0] + 1, "color": cell[1], "reason": reason} for cell, reason in bad]
                # Without frame_redraw a spoiled print is only marked for the review.
                if not bad or not getattr(self.generator, "frame_redraw", False):
                    break
                if attempts[key] >= MAX_COLLAGE_ATTEMPTS:
                    raise PermanentError(
                        "Принт испорчен на кадрах после повтора коллажа: "
                        + "; ".join(f"кадр {cell[0] + 1} ({cell[1]}): {reason}" for cell, reason in bad)
                    )
                self.files.save("frames_rejected", self.result)
            for cell, piece, (photo, draw) in zip(cells, pieces, shots, strict=True):
                if cell in missing:
                    await self.files.store_frame(cell[1], cell[0], piece if draw else photo)

        cells = [(index, color) for index in range(MODEL_FRAMES) for color in colors]
        await gather_all([slides(), *(model_frames(cells[i : i + 4]) for i in range(0, len(cells), 4))])

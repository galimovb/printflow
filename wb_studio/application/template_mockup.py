"""template_mockup: source_redraw whose model frames come from ready mockup series instead of generation.

The print audience picks the set (women, men; unisex takes either), the vendor number picks one series,
so all four frames show the same person in the same place. Frames 1-4 of the card are template frames
01, 03, 04 and 05: the print goes onto the front ones, the back view stays as it is because the print
is front-only. Frames 5-6 are the prebuilt slides. Unlike source_redraw the card keeps both colors: one
extracted print goes onto the black and the white frames of the same series, recolored only where the
gallery analysis asks for it.
"""

from printflow.wb_studio.infrastructure.rendering.info_slides import info_slide
from printflow.wb_studio.infrastructure.rendering.straight_reference import prepare_straight_reference

from .card_files import gather_all
from .redraw import MODEL_FRAMES, RedrawPipeline

TEMPLATE_SLOTS = (1, 3, 4, 5)
BACK_SLOT = 4


class TemplatePipeline(RedrawPipeline):
    def use_source_color(self, analysis: dict) -> None:
        """Both colors from one extracted print: every series has black and white frames anyway."""
        self.result["colors"] = self.config["colors"]

    async def gallery(self, analysis: dict) -> None:
        colors = self.config["colors"]
        # The source link joins the vendor number: local runs number every card 1.
        seed = f"{self.job.design_number or 0}:{self.job.payload['source'].get('url', '')}"
        series = self.cards.templates.pick(analysis.get("audience", "unisex"), seed)
        self.result["template_series"] = {"gender": series.gender, "number": series.number}
        arts = {color: await self.files.get("prints", f"prints/{color}.png") for color in colors}

        async def frame(color: str, index: int) -> None:
            if self.files.has_frame(color, index):
                return
            if index >= MODEL_FRAMES:
                await self.files.store_frame(color, index, info_slide(index, color, self.config))
                return
            slot = TEMPLATE_SLOTS[index]
            template = await self.cards.templates.photo(series, color, slot)
            if slot == BACK_SLOT:
                await self.files.store_frame(color, index, template)
                return
            _, geometry = prepare_straight_reference(arts[color], color, self.config)
            async with self.cards.photo_slots:
                raw = await self.cards.with_photo_timeout(
                    self.generator.template_photo(template, arts[color], color, geometry)
                )
            await self.files.store_frame(color, index, raw)

        await gather_all(frame(color, i) for color in colors for i in range(self.config["photos_per_color"]))

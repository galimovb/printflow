"""standard: extract the print from the main seller photo and shoot a new gallery.

Frame 1 is a calibrated local hero (no API), frames 2-3 lifestyle shots wearing the
straight reference shirt, frame 4 an outfit flat lay of the hero shirt, frames 5-6
prebuilt slides. Black frames repeat the white scene of the same index.
"""

import asyncio

from printflow.wb_studio.infrastructure.rendering.hero import prepare_hero
from printflow.wb_studio.infrastructure.rendering.info_slides import info_slide
from printflow.wb_studio.infrastructure.rendering.straight_reference import prepare_straight_reference

from .card_files import CardFiles, gather_all, to_png

HERO, FLATLAY, MODEL_FRAMES = 0, 3, 4


class StandardPipeline:
    def __init__(self, studio, job, generator, files: CardFiles):
        self.studio = studio
        self.job = job
        self.config = job.payload["config"]
        self.generator = generator
        self.files = files
        self.result = files.result

    async def run(self) -> None:
        art = await self.extract()
        if not self.result.get("text"):
            self.result["text"] = await self.generator.describe(art, self.job.payload["theme"])
            self.files.save("text_ready", self.result)
        await self.adapt(art)
        await self.studio.save_article_prints(self.job, self.result, self.files)
        await self.gallery()

    async def extract(self) -> bytes:
        if not self.result.get("source"):
            raw = to_png(await self.studio.fetch_photo(self.job.payload["source"]["image"]))
            self.result["source"] = await self.files.put("temporary", "source.png", raw)
            self.files.save("source_saved", self.result)
        if not self.result.get("print"):
            source = await self.files.get("temporary", "source.png")
            art = await self.generator.extract(source, self.job.payload["theme"])
            self.result["print"] = await self.files.put("prints", "print.png", art)
            self.files.save("print_ready", self.result)
        return await self.files.get("prints", "print.png")

    async def adapt(self, art: bytes) -> None:
        variants = self.result.setdefault("print_variants", {})

        async def adapt(color: str) -> None:
            if color in variants:
                return
            async with self.studio.photo_slots:
                adapted = await self.generator.adapt_print(art, color)
            variants[color] = await self.files.put("prints", f"prints/{color}.png", adapted)
            self.files.save(f"print_ready:{color}", self.result)

        await gather_all(adapt(color) for color in self.config["colors"])

    async def gallery(self) -> None:
        colors = self.config["colors"]
        limit = int(self.studio.env.get("PRINTFLOW_WB_REQUESTS_PER_PRINT", "4"))
        card_slots = asyncio.Semaphore(max(1, min(4, limit)))
        arts = {color: await self.files.get("prints", f"prints/{color}.png") for color in colors}
        products = await self.straight_references(arts)
        tasks: dict[tuple[str, int], asyncio.Task] = {}

        async def frame(color: str, index: int) -> None:
            if self.files.has_frame(color, index):
                return
            if index == HERO:
                raw = await self.hero(arts[color], color)
            elif index < MODEL_FRAMES:
                # Follow-ups need the hero shirt; black repeats the white scene of the same frame.
                await tasks[color, HERO]
                white_scene = None
                if color != "white" and "white" in colors:
                    await tasks["white", index]
                    white_scene = await self.files.get("mockups", f"white/{index + 1:02}.png")
                product = await self.files.get("mockups", f"{color}/01.png") if index == FLATLAY else products[color]
                async with card_slots, self.studio.photo_slots:
                    raw = await self.studio.with_photo_timeout(
                        self.generator.standard_photo(arts[color], product, color, index, white_scene)
                    )
            else:
                raw = info_slide(index, color, self.config)
            await self.files.store_frame(color, index, raw)

        for color in colors:
            for index in range(self.config["photos_per_color"]):
                tasks[color, index] = asyncio.create_task(frame(color, index))
        await gather_all(tasks.values())

    async def straight_references(self, arts: dict[str, bytes]) -> dict[str, bytes]:
        references = self.result.setdefault("product_references", {})
        products = {}
        for color, art in arts.items():
            name = f"templates/{color}/product-reference.png"
            if color in references:
                products[color] = await self.files.get("temporary", name)
                continue
            data, geometry = await asyncio.to_thread(prepare_straight_reference, art, color, self.config)
            geometry["url"] = await self.files.put("temporary", name, data)
            references[color] = geometry
            self.files.save(f"product_reference:{color}", self.result)
            products[color] = data
        return products

    async def hero(self, art: bytes, color: str) -> bytes:
        prepared, geometry = await asyncio.to_thread(prepare_hero, art, color, self.config)
        geometry["preview"] = await self.files.put("temporary", f"{color}/01-placed.png", prepared)
        self.result.setdefault("hero_placement", {})[color] = geometry
        self.files.save(f"hero_placed:{color}", self.result)
        return prepared

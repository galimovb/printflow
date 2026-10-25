"""Сценарий «пришёл заказ → принт для печати»: превью из bag-prints перерисовывается в высоком
качестве в bag-high-resolution-prints. Если файл уже есть — не генерируем (как у футболок)."""
from __future__ import annotations

from typing import Any

from printflow.domain.models import Job, SaveProgress
from printflow.domain.ports import HiresGenerator, Storage


class HiresService:
    def __init__(self, product: dict[str, Any], storage: Storage, generator: HiresGenerator) -> None:
        self.buckets = product["buckets"]
        self.product = product
        self.storage = storage
        self.generator = generator

    async def run(self, job: Job, save: SaveProgress) -> dict[str, Any]:
        article = job.payload["article"]
        key = f"{article}.png"
        if await self.storage.exists(self.buckets["hires"], key) and not job.payload.get('product_config'):
            return {"article": article, "hires": self.storage.url(self.buckets["hires"], key), "existing": True}
        save("hires", {"article": article})
        import copy
        generator = copy.copy(self.generator)
        config = job.payload.get('product_config')
        if config and hasattr(generator, 'area'):
            generator.area = tuple(config['generation']['print_area_cm'])
        existing = await self.storage.exists(self.buckets['hires'], key)
        preview = b'' if existing else await self.storage.get(self.buckets['prints'], key)
        png = await self.storage.get(self.buckets['hires'], key) if existing else await generator.hires_print(preview)
        url = self.storage.url(self.buckets['hires'], key) if existing else await self.storage.put(self.buckets['hires'], key, png, 'image/png')
        result = {"article": article, "hires": url, "existing": existing}
        if config:
            from printflow.products.thermo.domain.assortment import sizes
            from PIL import Image, ImageOps
            import io, json
            source = Image.open(io.BytesIO(png)).convert('RGBA')
            result['print_files'] = []
            for item in sizes(config):
                dimensions = tuple(round(v/2.54*300) for v in item['size_cm'])
                file_key = f"{article}/300dpi/{item['key']}.png"
                if not await self.storage.exists(self.buckets['hires'], file_key):
                    canvas = Image.new('RGBA', dimensions)
                    art = ImageOps.contain(source, dimensions, Image.Resampling.LANCZOS)
                    canvas.alpha_composite(art, ((canvas.width-art.width)//2, (canvas.height-art.height)//2))
                    buffer=io.BytesIO();canvas.save(buffer,format='PNG',dpi=(300,300))
                    await self.storage.put(self.buckets['hires'],file_key,buffer.getvalue(),'image/png')
                result['print_files'].append({'key':item['key'],'size_cm':item['size_cm'],'dpi':300,
                    'pixels':list(dimensions),'url':self.storage.url(self.buckets['hires'],file_key)})
            manifest=json.dumps({'article':article,'assortment':config['assortment']['mode'],'files':result['print_files']},ensure_ascii=False).encode()
            result['print_manifest']=await self.storage.put(self.buckets['hires'],f'{article}/print-manifest.json',manifest,'application/json')
        return result

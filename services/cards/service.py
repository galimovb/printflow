"""Сценарий «новый дизайн → карточка Ozon» — один для всех товаров (products/):

  1. print   — принт: по теме, по тематике (themes.json, идею придумывает GPT) или копия с фото товара
               → <бакет prints>/{article}.png;
  2. gallery — принт на каркасы, по каждому варианту товара (цвет шоппера, один у коврика)
               → <бакет mockups>/{article}/{вариант}/;
  3. ozon    — карточка: товары вариантов, объединение по группе. Ошибка Ozon не повторяется сразу:
               задача ждёт сброса лимитов (03:00, OzonRetryPolicy);
  4. certificate — отдельная задача привязки к сертификату качества (если задан <ТОВАР>_OZON_CERTIFICATE_ID).

Чем товары отличаются (генератор принта, галерея, варианты, тело импорта), решает Product. Каждый шаг
сохраняет результат в задачу, поэтому повтор продолжает с места падения и не делает готовое заново.
"""
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, Callable

from printflow.domain.errors import PermanentError, ShopperError
from printflow.domain.models import CardSpec, Job, SaveProgress, design_article, design_merge_group
from printflow.services.ozon.client import OzonError
from printflow.services.ozon.retry import OzonRetryPolicy
from printflow.domain.ports import CardPublisher, Gallery, ImageFetcher, PrintGenerator, Storage

if TYPE_CHECKING:
    from printflow.products.base import Product


class CardService:
    def __init__(
        self,
        product: Product,
        storage: Storage,
        generator: PrintGenerator,
        gallery: Gallery,
        publisher: Callable[[], CardPublisher],
        fetcher: ImageFetcher,
        merge_designs: int = 1,
        enqueue_certificate: Callable[[str, list[int]], Any] | None = None,
        ozon_retry: OzonRetryPolicy | None = None,
        drawn_titles: Callable[[str], list[str]] | None = None,
    ) -> None:
        self.product = product
        self.buckets = product.buckets
        self.storage = storage
        self.generator = generator
        self.gallery = gallery
        self.publisher = publisher  # фабрика: без ключей Ozon сервис работает для dry_run
        self.fetcher = fetcher
        self.merge_designs = merge_designs  # мест в группе — для «Названия цвета»
        self.enqueue_certificate = enqueue_certificate  # None — сертификат не задан
        self.ozon_retry = ozon_retry  # None — ошибки Ozon повторяются как обычные
        self.drawn_titles = drawn_titles or (lambda theme_key: [])  # уже нарисованное в тематике

    async def run(self, job: Job, save: SaveProgress) -> dict[str, Any]:
        spec = CardSpec.from_payload(job.payload)
        if hasattr(self.product, 'for_spec'):
            import copy
            snapshot = job.result.get('product_config') or spec.product_config
            bound = self.product.for_spec(spec, snapshot)
            if not getattr(self, '_bound', False):
                service = copy.copy(self)
                service._bound = True
                service.product = bound
                service.gallery = bound.gallery()
                service.generator = copy.copy(self.generator)
                if hasattr(service.generator, 'area'):
                    service.generator.area = tuple(bound.config['generation']['print_area_cm'])
                job.result = {**job.result, 'product_config': copy.deepcopy(bound.config)}
                save('configured', job.result)
                return await service.run(job, save)
        if spec.upload_to_ozon and not spec.dry_run:
            self.product.validate_publication()
        result = dict(job.result)
        article = result.setdefault("article", design_article(self.product.article_prefix, job))

        png = await self._print(article, job, spec, result, save)
        if hasattr(self.product, 'resolve_print'):
            import copy
            config = self.product.resolve_print(png)
            self.gallery = self.product.gallery()
            result['product_config'] = copy.deepcopy(config)
            result['print_dimensions'] = copy.deepcopy(config.get('resolved_print'))
            save('dimensions_done', result)
        if (self.product.names_designs or spec.theme_key) and not result.get("design_name"):
            # описание рисунка: готовое из задачи (идеи) или вторым запросом по принту
            result["design_name"] = spec.design_name or await self.generator.name_print(png)
            save("named", result)
        await self._gallery(article, png, spec, result, save)
        if spec.upload_to_ozon and not result.get("ozon"):
            await self._publish(article, job, spec, result, save)
        self._schedule_certificate(article, result, save)
        return result

    def _job_publisher(self):
        publisher = self.publisher()
        if hasattr(self.product, 'for_spec') and hasattr(publisher, 'ozon'):
            import copy
            publisher = copy.copy(publisher)
            publisher.ozon = self.product.config['ozon']
        return publisher

    def _schedule_certificate(self, article: str, result: dict[str, Any], save: SaveProgress) -> None:
        """После выкладки — задача привязки к сертификату (одна на артикул, повтор её не дублирует)."""
        ozon = result.get("ozon") or {}
        if self.enqueue_certificate is None or ozon.get("dry_run") or not ozon.get("product_ids"):
            return
        if result.get("certificate_job"):
            return
        job, _ = self.enqueue_certificate(article, ozon["product_ids"])
        result["certificate_job"] = job.id
        save("certificate_queued", result)

    async def _print(self, article: str, job: Job, spec: CardSpec, result: dict[str, Any],
                     save: SaveProgress) -> bytes:
        key = f"{article}.png"
        if not result.get("print"):
            save("print", result)
            if spec.reference_url:
                png = await self.generator.copy_from_photo(await self.fetcher.download(spec.reference_url), spec.theme)
            elif spec.theme_key:
                png = await self._theme_print(spec.theme_key, job.number if spec.theme_step is None
                                              else spec.theme_step, result, save)
            else:
                png = await self.generator.preview_print(spec.theme)
            result["print"] = await self.storage.put(self.buckets["prints"], key, png, "image/png")
            save("print_done", result)
            return png
        return await self.storage.get(self.buckets["prints"], key)

    async def _theme_print(self, theme_key: str, step: int, result: dict[str, Any], save: SaveProgress) -> bytes:
        """Тематика из themes.json. Если генератор сам придумывает сюжет (pick_subject) — сюжет сохраняется
        в задаче (result.subject): по нему следующие принты тематики видят уже нарисованное. Иначе —
        направление по кругу (по номеру принта в тематике) и список уже нарисованного."""
        theme = self.product.themes.get(theme_key)
        if theme is None:
            raise PermanentError(f"Нет тематики {theme_key!r} в products/{self.product.name}/themes.json")
        if hasattr(self.generator, "pick_subject"):
            if not result.get("subject"):
                result["subject"] = await self.generator.pick_subject(theme, self.drawn_titles(theme_key))
                save("subject", result)
            return await self.generator.subject_print(theme, result["subject"])
        direction = self.product.theme_direction(theme, step)
        return await self.generator.theme_print(theme, direction, self.drawn_titles(theme_key))

    async def _gallery(self, article: str, png: bytes, spec: CardSpec, result: dict[str, Any],
                       save: SaveProgress) -> None:
        images: dict[str, list[str]] = result.setdefault("images", {})
        main = f"_{self.product.main_slide}"
        for variant in self.product.variants(spec):
            if images.get(variant):
                continue
            save(f"gallery:{variant}", result)
            slides = await asyncio.to_thread(self.gallery.render, png, variant)
            if not any(name.endswith(main) for name, _ in slides):
                raise ShopperError(f"{variant}: нет главного фото ({self.product.main_slide}) — проверьте каркасы "
                                   f"в products/{self.product.name}/assets/templates")
            urls = [
                await self.storage.put(self.buckets["mockups"], f"{article}/{variant}/{name}.jpg", data, "image/jpeg")
                for name, data in slides
            ]
            await self.fetcher.ensure_public(urls[0])
            images[variant] = urls
            save("gallery_done", result)

    async def _publish(self, article: str, job: Job, spec: CardSpec, result: dict[str, Any],
                       save: SaveProgress) -> None:
        save("ozon", result)
        group = design_merge_group(self.product.article_prefix, job, self.merge_designs)
        result["merge_group"] = group.key
        images = {variant: result["images"][variant] for variant in self.product.variants(spec)}
        items = self.product.build_items(article, images, spec.product_name, group, result.get("design_name"))
        if spec.dry_run:
            result["ozon"] = {"dry_run": True, "offers": [item["offer_id"] for item in items]}
        else:
            try:
                result["ozon"] = await self._job_publisher().publish(items)
            except OzonError as exc:
                if self.ozon_retry is None:
                    raise
                error = self.ozon_retry.on_error(exc, result)
                save("ozon_wait", result)
                raise error from exc
        save("ozon_done", result)

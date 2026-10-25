"""Composition root: единственное место, где создаются и связываются зависимости.

AppContainer — одно приложение: общая база задач, S3, список товаров (SM_PRODUCTS).
ProductContainer — всё для одного товара: его настройки (<ТОВАР>_*), генератор принта, галерея, кабинет Ozon,
очередь (свой пул воркеров) и обработчик заказов. Тяжёлые зависимости (S3, OpenAI, Ozon) создаются лениво —
API и тесты поднимаются без ключей.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import cached_property

from printflow.config import AppSettings, ProductSettings, load_app_settings, load_product_settings
from printflow.domain.models import JobKind
from printflow.products import get_product
from printflow.products.base import Product
from printflow.repositories.jobs import JobRepository
from printflow.services.cards.service import CardService
from printflow.services.certificates.service import CertificateService
from printflow.services.hires.service import HiresService
from printflow.services.jobs.service import JobService
from printflow.services.orders.watcher import OrderWatcher
from printflow.services.ozon.client import OzonClient
from printflow.services.ozon.publisher import OzonPublisher
from printflow.services.ozon.retry import OzonRetryPolicy
from printflow.services.storage.http import ImageFetcher
from printflow.services.storage.s3 import Storage
from printflow.workers.queue import QueueWorker


@dataclass
class AppContainer:
    settings: AppSettings = field(default_factory=load_app_settings)
    product_settings: dict[str, ProductSettings] = field(default_factory=dict)  # пусто — из env

    @cached_property
    def wb_studio(self):
        from printflow.wb_studio.application.studio import Studio
        from printflow.config import read_env
        return Studio(self.job_repository,self.storage,read_env())

    @cached_property
    def wb_worker(self):
        from printflow.config import read_env
        from printflow.wb_studio.application.worker import worker
        return worker(self.wb_studio,read_env())

    @cached_property
    def job_repository(self) -> JobRepository:
        return JobRepository(self.settings.jobs_db, timeout_sec=self.settings.db_timeout_sec)

    @cached_property
    def storage(self) -> Storage:
        return Storage(self.settings.s3)

    @cached_property
    def products(self) -> dict[str, ProductContainer]:
        out = {}
        for name in self.settings.products:
            product = get_product(name)
            settings = self.product_settings.get(name) or load_product_settings(product.env_prefix)
            out[name] = ProductContainer(self, product, settings)
        return out


@dataclass
class ProductContainer:
    app: AppContainer
    product: Product
    settings: ProductSettings

    @property
    def name(self) -> str:
        return self.product.name

    @property
    def job_repository(self) -> JobRepository:
        return self.app.job_repository

    @cached_property
    def jobs(self) -> JobService:
        return JobService(self.job_repository, product=self.name, merge_designs=self.settings.ozon.merge_designs,
                          prepare_spec=getattr(self.product, "prepare_spec", None))

    # ───────── внешние системы ─────────

    @cached_property
    def fetcher(self) -> ImageFetcher:
        return ImageFetcher(self.settings.http)

    @cached_property
    def generator(self):
        return self.product.generator(self.settings.openai)

    @cached_property
    def ozon_client(self) -> OzonClient:
        return OzonClient(self.settings.ozon)

    def ozon_publisher(self) -> OzonPublisher:
        return OzonPublisher(self.ozon_client, self.product.config, self.settings.ozon)

    # ───────── сценарии ─────────

    @cached_property
    def cards(self) -> CardService:
        return CardService(
            self.product,
            self.app.storage,
            self.generator,
            self.product.gallery(),
            publisher=self.ozon_publisher,
            fetcher=self.fetcher,
            merge_designs=self.settings.ozon.merge_designs,
            enqueue_certificate=self._enqueue_certificate if self.settings.ozon.certificate_id else None,
            ozon_retry=OzonRetryPolicy(self.settings.ozon),
            drawn_titles=self._drawn_titles,
        )

    def _drawn_titles(self, theme_key: str) -> list[str]:
        limit = int(self.product.config["generation"]["theme_drawn_limit"])
        # товар, который сам придумывает сюжет (pick_subject), сравнивает новые сюжеты с прежними сюжетами
        field = "subject" if self.product.picks_subjects else "design_name"
        return self.job_repository.drawn_titles(self.name, theme_key, limit, field)

    def _enqueue_certificate(self, article: str, product_ids: list[int]):
        return self.jobs.enqueue_certificate(article, product_ids, self.settings.ozon.certificate_id)  # type: ignore[arg-type]

    @cached_property
    def certificates(self) -> CertificateService:
        return CertificateService(lambda: self.ozon_client, self.settings.ozon)

    @cached_property
    def hires(self) -> HiresService:
        return HiresService(self.product.config, self.app.storage, self.generator)

    @cached_property
    def queue_worker(self) -> QueueWorker:
        handlers = {JobKind.CARD: self.cards.run, JobKind.HIRES: self.hires.run,
                    JobKind.CERTIFICATE: self.certificates.run}
        return QueueWorker(self.job_repository, handlers, self.settings.queue, product=self.name)

    @cached_property
    def order_watcher(self) -> OrderWatcher | None:
        if not self.settings.ozon.configured:
            return None
        return OrderWatcher(self.ozon_client, self.jobs, self.product.article_prefix, self.settings.orders)

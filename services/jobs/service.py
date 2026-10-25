"""Сценарии работы с очередью: поставить карточку или hi-res, получить, повторить. Используют
контроллеры API и обработчик заказов — правила идемпотентности живут здесь, а не в роутах."""
from __future__ import annotations

from printflow.domain.errors import InvalidJobState, JobNotFound
from printflow.domain.models import CardSpec, Job, JobKind, JobStatus, certificate_external_id, hires_external_id
from printflow.repositories.jobs import JobRepository


class JobService:
    def __init__(self, repository: JobRepository, *, product: str, merge_designs: int = 1, prepare_spec=None) -> None:
        self.prepare_spec = prepare_spec
        self.repository = repository
        self.product = product              # все задачи этого сервиса — одного товара
        self.merge_designs = merge_designs  # сколько дизайнов в одной карточке Ozon

    def enqueue_card(self, spec: CardSpec, *, external_id: str | None = None) -> tuple[Job, bool]:
        """Карточка получает сквозной номер дизайна (артикул BAG-001001) и место в группе объединения
        (если merge_designs > 1) — по группе Ozon собирает одну карточку.
        Повтор с тем же external_id возвращает существующую задачу (created=False)."""
        return self.enqueue_cards([(spec, external_id)])[0]

    def enqueue_cards(self, cards: list[tuple[CardSpec, str | None]]) -> list[tuple[Job, bool]]:
        """Пачка карточек одной транзакцией: номера и места в группах — по порядку пачки."""
        if self.prepare_spec:
            cards = [(self.prepare_spec(spec), key) for spec, key in cards]
        elif any(spec.assortment for spec, _ in cards):
            raise ValueError("Комплектация поддерживается только термонаклейками")
        group_size = self.merge_designs if self.merge_designs > 1 else None
        return self.repository.create_many([(spec.to_payload(), external_id) for spec, external_id in cards],
                                           product=self.product, numbered=True, group_size=group_size)

    def enqueue_hires(self, article: str) -> tuple[Job, bool]:
        """Одна задача на артикул — повторные заказы того же дизайна принт заново не рисуют."""
        payload = {"kind": JobKind.HIRES.value, "article": article}
        original = self.repository.find_card_article(self.product, article) if self.product == "thermo" else None
        if original:
            config = original.result.get("product_config") or original.payload.get("product_config")
            if config:
                payload["product_config"] = config
        return self.repository.create(payload, product=self.product,
                                      external_id=hires_external_id(article))

    def enqueue_certificate(self, article: str, product_ids: list[int], certificate_id: int) -> tuple[Job, bool]:
        """Привязка товаров дизайна к сертификату — одна задача на артикул."""
        payload = {"kind": JobKind.CERTIFICATE.value, "article": article,
                   "product_ids": product_ids, "certificate_id": certificate_id}
        return self.repository.create(payload, product=self.product, external_id=certificate_external_id(article))

    def get(self, job_id: str) -> Job:
        if (job := self.repository.get(job_id)) is None or job.product != self.product:
            raise JobNotFound("Задача не найдена")
        return job

    def list(self, *, status: JobStatus | None = None, limit: int = 50) -> list[Job]:
        return self.repository.list(product=self.product, status=status, limit=limit)

    def retry(self, job_id: str) -> Job:
        """Ручной повтор упавшей задачи: продолжит с места падения, попытки считаются заново."""
        job = self.get(job_id)
        if job.status != JobStatus.FAILED:
            raise InvalidJobState(f"Повторить можно только failed, сейчас {job.status.value}")
        return self.repository.reset_failed(job_id)  # type: ignore[return-value]

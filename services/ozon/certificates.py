"""Сертификат качества (декларация и т.п.) на товары: привязка по product_id к сертификату кабинета.

Сертификат загружается в кабинет один раз (ЛК или /v2/product/certificate/create), его id — в
SHOPPER_OZON_CERTIFICATE_ID. Сертификат должен быть в том же кабинете, что и товары, иначе Ozon
отвечает «компания не соответствует компании сертификата».
"""
from __future__ import annotations

from typing import Iterable

from printflow.domain.ports import JsonApiClient

BIND_BATCH = 100


class CertificateBinder:
    def __init__(self, client: JsonApiClient, certificate_id: int) -> None:
        self.client = client
        self.certificate_id = certificate_id

    async def bind(self, product_ids: Iterable[int]) -> int:
        """Привязывает товары к сертификату (повторная привязка того же товара безвредна); возвращает сколько."""
        ids = [int(pid) for pid in product_ids if pid]
        for start in range(0, len(ids), BIND_BATCH):
            await self.client.post(
                "/v1/product/certificate/bind",
                {"certificate_id": self.certificate_id, "product_id": ids[start:start + BIND_BATCH]},
            )
        return len(ids)

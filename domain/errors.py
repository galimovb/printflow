"""Ошибки домена. Воркер очереди решает по типу ошибки, повторять задачу или нет."""
from __future__ import annotations


class ShopperError(Exception):
    """Ожидаемая ошибка задачи: текст показывается в job.error."""


class PermanentError(ShopperError):
    """Повтор не поможет (запрос отклонён фильтром OpenAI, неверные данные) — задача сразу failed."""


class RetryLater(ShopperError):
    """Задача ещё не может выполниться (например, ждём модерацию Ozon) — отложить, не тратя попытку."""

    def __init__(self, reason: str, delay_sec: float) -> None:
        super().__init__(reason)
        self.delay_sec = delay_sec


class JobNotFound(ShopperError):
    pass


class InvalidJobState(ShopperError):
    pass

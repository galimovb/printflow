"""Зависимости контроллеров: проверка токена товара. Контроллеры строятся на товар (router(pc)), поэтому
нужный ProductContainer у них уже есть — без поиска по запросу."""
from __future__ import annotations

import hmac
from typing import TYPE_CHECKING, Callable

from fastapi import Header, HTTPException, status

if TYPE_CHECKING:
    from printflow.container import ProductContainer


def token_checker(pc: ProductContainer) -> Callable[..., None]:
    """`Authorization: Bearer <ТОВАР_API_TOKEN>` или `X-API-Key: <токен>` — у каждого товара свой токен."""

    def require_token(authorization: str | None = Header(default=None), x_api_key: str | None = Header(default=None)) -> None:
        expected = pc.settings.api.token
        token = x_api_key or ""
        if authorization and authorization.lower().startswith("bearer "):
            token = authorization[7:]
        if not expected or not hmac.compare_digest(token.strip(), expected):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Неверный или отсутствующий токен")

    return require_token

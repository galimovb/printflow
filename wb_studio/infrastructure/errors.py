"""Safe, persistent diagnostics for studio failures."""

from functools import wraps

from openai import APIConnectionError, APIError, APIStatusError, APITimeoutError

from printflow.domain.errors import PermanentError


def generation_errors(function):
    @wraps(function)
    async def wrapped(*args, **kwargs):
        try:
            return await function(*args, **kwargs)
        except APIError as exc:
            body = exc.body if isinstance(exc.body, dict) else {}
            error = body.get("error", body)
            if not isinstance(error, dict):
                error = {}
            code = error.get("code") or getattr(exc, "code", None)
            request_id = getattr(exc, "request_id", None)
            suffix = f" Request ID: {request_id}" if request_id else ""
            if code == "moderation_blocked":
                raise PermanentError(
                    "Генератор отклонил изображение: moderation_blocked. Автоматический повтор отключён." + suffix
                ) from exc
            if isinstance(exc, APIStatusError):
                status = exc.status_code
                message = f"Ошибка API генерации: HTTP {status}" + (f" ({code})" if code else "") + "." + suffix
                if status in (400, 401, 403, 404, 422):
                    raise PermanentError(message) from exc
                raise RuntimeError(message + " Повторите запуск позже; готовые шаги сохранены.") from exc
            if isinstance(exc, APIConnectionError | APITimeoutError):
                raise RuntimeError(
                    "Нет ответа от API генерации: сеть или таймаут. Повторите запуск позже; готовые шаги сохранены."
                    + suffix
                ) from exc
            raise RuntimeError("Ошибка API генерации." + suffix) from exc

    return wrapped


def failure(exc, stage):
    return {
        "type": type(exc).__name__,
        "message": str(exc)[:2000],
        "stage": stage,
        "retryable": not isinstance(exc, PermanentError),
    }

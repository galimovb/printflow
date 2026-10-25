"""Конфигурация: окружение приложения и товаров. Описание каждого товара — products/<товар>/config/product.json.

Приложение одно (один процесс, один Docker, одна база задач), товаров несколько:
  • SM_*         — приложение: адрес и порт API, папка данных (база jobs.db), ожидание блокировки SQLite,
                   какие товары запускать (SM_PRODUCTS);
  • <ТОВАР>_*    — свои у каждого товара: SHOPPER_*, MOUSEPAD_* — токен API, кабинет Ozon, очередь, заказы;
  • OPENAI_*, S3_* — общие (из .env футболок; OPENAI_TEXT_MODEL и OPENAI_NAME_* — из printflow/.env).

Порядок источников (правый перекрывает левый): .env футболок → printflow/.env → переменные
окружения. Читаются только перечисленные здесь ключи, поэтому футболочные настройки сюда не попадают.

Значений по умолчанию в коде нет: каждый ключ обязателен, без него приложение не стартует и называет все
недостающие ключи разом. Пустое значение допустимо только там, где оно означает «выключено»
(<ТОВАР>_OZON_CLIENT_ID / _API_KEY — только dry_run, <ТОВАР>_OZON_CERTIFICATE_ID — не привязывать).
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import time
from pathlib import Path
from typing import Any

from dotenv import dotenv_values

PACKAGE_DIR = Path(__file__).resolve().parent
ROOT = PACKAGE_DIR.parent


@dataclass(frozen=True)
class ApiSettings:
    token: str            # <ТОВАР>_API_TOKEN — у каждого товара свой токен


@dataclass(frozen=True)
class OzonSettings:
    client_id: str        # <ТОВАР>_OZON_CLIENT_ID — у каждого товара свой кабинет; пусто — только dry_run
    api_key: str          # <ТОВАР>_OZON_API_KEY
    api_url: str          # <ТОВАР>_OZON_API_URL
    timeout_sec: float    # <ТОВАР>_OZON_TIMEOUT_SEC
    import_poll_sec: float  # <ТОВАР>_OZON_IMPORT_POLL_SEC — пауза между проверками результата импорта
    import_poll_attempts: int  # <ТОВАР>_OZON_IMPORT_POLL_ATTEMPTS
    merge_designs: int    # <ТОВАР>_OZON_MERGE_DESIGNS — дизайнов в одной карточке
    certificate_id: int | None  # <ТОВАР>_OZON_CERTIFICATE_ID — сертификат качества; пусто — не привязывать
    certificate_wait_sec: tuple[float, ...]  # <ТОВАР>_OZON_CERTIFICATE_WAIT_SEC — паузы между проверками SKU
    # перед привязкой: 1-я, 2-я, …; последняя повторяется
    certificate_max_wait_hours: float  # <ТОВАР>_OZON_CERTIFICATE_MAX_WAIT_HOURS — сколько ждать SKU максимум
    retry_at: time        # <ТОВАР>_OZON_RETRY_AT — после ошибки Ozon повтор в это время (сброс лимитов)
    retry_utc_offset: float  # <ТОВАР>_OZON_RETRY_UTC_OFFSET — часовой пояс для RETRY_AT (3 = МСК)
    retry_nights: int     # <ТОВАР>_OZON_RETRY_NIGHTS — сколько ночей повторять, потом failed
    rate_limit_wait_sec: float  # <ТОВАР>_OZON_RATE_LIMIT_WAIT_SEC — повтор после лимита «в секунду»
    env_prefix: str       # чей кабинет (SHOPPER, MOUSEPAD) — для понятных сообщений об ошибках

    @property
    def configured(self) -> bool:
        return bool(self.client_id and self.api_key)


@dataclass(frozen=True)
class NamingSettings:
    """Второй запрос — описание рисунка для названия карточки (у товаров с names_designs)."""

    model: str            # OPENAI_TEXT_MODEL
    image_side: int       # OPENAI_NAME_IMAGE_SIDE — принт уменьшается до этой стороны
    jpeg_quality: int     # OPENAI_NAME_JPEG_QUALITY — сжатие уменьшенного принта
    detail: str           # OPENAI_NAME_DETAIL — low / high / auto (low — дешевле всего)
    temperature: float    # OPENAI_NAME_TEMPERATURE
    max_tokens: int       # OPENAI_NAME_MAX_TOKENS
    max_chars: int        # OPENAI_NAME_MAX_CHARS — ответ длиннее отбрасывается, задача повторяется


@dataclass(frozen=True)
class OpenAISettings:
    api_key: str          # OPENAI_API_KEY (общий с футболками)
    base_url: str         # OPENAI_BASE_URL
    image_model: str      # <ТОВАР>_IMAGE_MODEL — модель картинок товара (принты, шаблоны)
    timeout_sec: float    # <ТОВАР>_OPENAI_TIMEOUT_SEC
    reference_max_side: int  # <ТОВАР>_REFERENCE_MAX_SIDE — фото товара уменьшается до этой стороны
    naming: NamingSettings


@dataclass(frozen=True)
class S3Settings:
    endpoint: str         # S3_ENDPOINT_URL (общий с футболками)
    region: str           # S3_REGION
    access_key: str       # S3_ACCESS_KEY
    secret_key: str       # S3_SECRET_KEY
    public_base: str      # S3_PUBLIC_BASE_URL


@dataclass(frozen=True)
class QueueSettings:
    workers: int          # <ТОВАР>_WORKERS — задач товара одновременно
    max_attempts: int     # <ТОВАР>_MAX_ATTEMPTS
    retry_delays_sec: tuple[float, ...]  # <ТОВАР>_RETRY_DELAYS_SEC — паузы перед повторами, через запятую
    poll_sec: float       # <ТОВАР>_QUEUE_POLL_SEC — как часто искать новые задачи
    error_pause_sec: float  # <ТОВАР>_QUEUE_ERROR_PAUSE_SEC — пауза после сбоя базы, потом очередь продолжает
    first_article_number: int  # <ТОВАР>_FIRST_ARTICLE_NUMBER — с какого номера дизайна начинать


@dataclass(frozen=True)
class OrdersSettings:
    interval_min: int     # <ТОВАР>_ORDERS_INTERVAL_MIN — опрос заказов кабинета
    fbs_statuses: tuple[str, ...]  # <ТОВАР>_ORDERS_FBS_STATUSES — через запятую
    lookback_days: int    # <ТОВАР>_ORDERS_LOOKBACK_DAYS
    cutoff_future_days: int  # <ТОВАР>_ORDERS_CUTOFF_FUTURE_DAYS
    page_size: int        # <ТОВАР>_ORDERS_PAGE_SIZE


@dataclass(frozen=True)
class HttpSettings:
    timeout_sec: float    # <ТОВАР>_HTTP_TIMEOUT_SEC — скачивание фото, проверка публичности ссылок


@dataclass(frozen=True)
class ProductSettings:
    """Настройки одного товара (ключи <ТОВАР>_*)."""

    api: ApiSettings
    ozon: OzonSettings
    openai: OpenAISettings
    queue: QueueSettings
    orders: OrdersSettings
    http: HttpSettings


def product_data_dir(data_root: Path, product: str) -> Path:
    """The only product-data layout rule, also valid for a Docker-mounted SM_DATA_DIR."""
    if not re.fullmatch(r'[a-z][a-z0-9_]*', product):
        raise ValueError(f'Invalid product data namespace: {product!r}')
    return Path(data_root) / product


@dataclass(frozen=True)
class AppSettings:
    """Настройки приложения (ключи SM_*, общий S3)."""

    host: str             # SM_HOST
    port: int             # SM_PORT
    data_dir: Path        # SM_DATA_DIR — база задач всех товаров (относительный путь — от printflow/)
    db_timeout_sec: float  # SM_DB_TIMEOUT_SEC — ожидание блокировки SQLite
    products: tuple[str, ...]  # SM_PRODUCTS — какие товары запускать, через запятую
    s3: S3Settings

    def product_data_dir(self, product: str) -> Path:
        return product_data_dir(self.data_dir, product)

    @property
    def jobs_db(self) -> Path:
        return self.data_dir / "jobs.db"

    @property
    def api_url(self) -> str:
        host = "127.0.0.1" if self.host in ("0.0.0.0", "") else self.host
        return f"http://{host}:{self.port}"


class MissingSettings(RuntimeError):
    """В окружении нет обязательных ключей."""


def read_env() -> dict[str, str]:
    """Пустые значения сохраняются: «ключ есть, но пуст» (выключено) отличается от «ключа нет»."""
    merged: dict[str, Any] = {**dotenv_values(ROOT / ".env"), **dotenv_values(PACKAGE_DIR / ".env"), **os.environ}
    return {k: str(v).strip() for k, v in merged.items() if v is not None}


class _Env:
    """Чтение обязательных ключей: недостающие копятся и сообщаются одной ошибкой (check())."""

    def __init__(self, env: dict[str, str] | None) -> None:
        self.env = env if env is not None else read_env()
        self.missing: list[str] = []

    def text(self, key: str, *, allow_empty: bool = False) -> str:
        value = self.env.get(key)
        if value is None or (value == "" and not allow_empty):
            self.missing.append(key)
            return ""
        return value

    def num(self, key: str, cast: type = float) -> Any:
        value = self.text(key)
        return cast(value) if value else cast(0)

    def items(self, key: str) -> tuple[str, ...]:
        return tuple(part.strip() for part in self.text(key).split(",") if part.strip())

    def floats(self, key: str) -> tuple[float, ...]:
        return tuple(float(v) for v in self.items(key))

    def check(self) -> None:
        if self.missing:
            raise MissingSettings("Не заданы ключи окружения (printflow/.env или .env футболок): "
                                  + ", ".join(self.missing))


def load_app_settings(env: dict[str, str] | None = None) -> AppSettings:
    e = _Env(env)
    data_dir = Path(e.text("SM_DATA_DIR"))
    settings = AppSettings(
        host=e.text("SM_HOST"),
        port=e.num("SM_PORT", int),
        data_dir=data_dir if data_dir.is_absolute() else PACKAGE_DIR / data_dir,
        db_timeout_sec=e.num("SM_DB_TIMEOUT_SEC"),
        products=e.items("SM_PRODUCTS"),
        s3=S3Settings(
            endpoint=e.text("S3_ENDPOINT_URL"),
            region=e.text("S3_REGION"),
            access_key=e.text("S3_ACCESS_KEY"),
            secret_key=e.text("S3_SECRET_KEY"),
            public_base=e.text("S3_PUBLIC_BASE_URL").rstrip("/"),
        ),
    )
    e.check()
    return settings


def load_product_settings(prefix: str, env: dict[str, str] | None = None) -> ProductSettings:
    """Настройки товара: свои ключи — <prefix>_* (SHOPPER_WORKERS, MOUSEPAD_OZON_CLIENT_ID…), общие — OPENAI_*."""
    e = _Env(env)
    p = prefix
    certificate = e.text(f"{p}_OZON_CERTIFICATE_ID", allow_empty=True)
    retry_at = e.text(f"{p}_OZON_RETRY_AT")
    settings = ProductSettings(
        api=ApiSettings(token=e.text(f"{p}_API_TOKEN")),
        ozon=OzonSettings(
            client_id=e.text(f"{p}_OZON_CLIENT_ID", allow_empty=True),
            api_key=e.text(f"{p}_OZON_API_KEY", allow_empty=True),
            api_url=e.text(f"{p}_OZON_API_URL").rstrip("/"),
            timeout_sec=e.num(f"{p}_OZON_TIMEOUT_SEC"),
            import_poll_sec=e.num(f"{p}_OZON_IMPORT_POLL_SEC"),
            import_poll_attempts=e.num(f"{p}_OZON_IMPORT_POLL_ATTEMPTS", int),
            merge_designs=max(1, e.num(f"{p}_OZON_MERGE_DESIGNS", int)),
            certificate_id=int(certificate) if certificate else None,
            certificate_wait_sec=e.floats(f"{p}_OZON_CERTIFICATE_WAIT_SEC"),
            certificate_max_wait_hours=e.num(f"{p}_OZON_CERTIFICATE_MAX_WAIT_HOURS"),
            retry_at=time.fromisoformat(retry_at) if retry_at else time(),
            retry_utc_offset=e.num(f"{p}_OZON_RETRY_UTC_OFFSET"),
            retry_nights=max(1, e.num(f"{p}_OZON_RETRY_NIGHTS", int)),
            rate_limit_wait_sec=e.num(f"{p}_OZON_RATE_LIMIT_WAIT_SEC"),
            env_prefix=p,
        ),
        openai=OpenAISettings(
            api_key=e.text("OPENAI_API_KEY"),
            base_url=e.text("OPENAI_BASE_URL"),
            image_model=e.text(f"{p}_IMAGE_MODEL"),
            timeout_sec=e.num(f"{p}_OPENAI_TIMEOUT_SEC"),
            reference_max_side=e.num(f"{p}_REFERENCE_MAX_SIDE", int),
            naming=NamingSettings(
                model=e.text("OPENAI_TEXT_MODEL"),
                image_side=e.num("OPENAI_NAME_IMAGE_SIDE", int),
                jpeg_quality=e.num("OPENAI_NAME_JPEG_QUALITY", int),
                detail=e.text("OPENAI_NAME_DETAIL"),
                temperature=e.num("OPENAI_NAME_TEMPERATURE"),
                max_tokens=e.num("OPENAI_NAME_MAX_TOKENS", int),
                max_chars=e.num("OPENAI_NAME_MAX_CHARS", int),
            ),
        ),
        queue=QueueSettings(
            workers=max(1, e.num(f"{p}_WORKERS", int)),
            max_attempts=max(1, e.num(f"{p}_MAX_ATTEMPTS", int)),
            retry_delays_sec=e.floats(f"{p}_RETRY_DELAYS_SEC"),
            poll_sec=e.num(f"{p}_QUEUE_POLL_SEC"),
            error_pause_sec=e.num(f"{p}_QUEUE_ERROR_PAUSE_SEC"),
            first_article_number=max(1, e.num(f"{p}_FIRST_ARTICLE_NUMBER", int)),
        ),
        orders=OrdersSettings(
            interval_min=max(1, e.num(f"{p}_ORDERS_INTERVAL_MIN", int)),
            fbs_statuses=e.items(f"{p}_ORDERS_FBS_STATUSES"),
            lookback_days=e.num(f"{p}_ORDERS_LOOKBACK_DAYS", int),
            cutoff_future_days=e.num(f"{p}_ORDERS_CUTOFF_FUTURE_DAYS", int),
            page_size=e.num(f"{p}_ORDERS_PAGE_SIZE", int),
        ),
        http=HttpSettings(timeout_sec=e.num(f"{p}_HTTP_TIMEOUT_SEC")),
    )
    e.check()
    return settings

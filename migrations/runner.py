"""Миграции схемы SQLite: файлы NNNN_*.sql применяются по порядку, версия — PRAGMA user_version.

Запускаются отдельно от приложения (сервис migrate в docker-compose, локально —
python -m printflow.migrations). Приложение только проверяет, что схема актуальна.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).resolve().parent


class SchemaOutdated(RuntimeError):
    pass


def migration_files() -> list[Path]:
    return sorted(MIGRATIONS_DIR.glob("[0-9][0-9][0-9][0-9]_*.sql"))


def latest_version() -> int:
    return len(migration_files())


def current_version(db: sqlite3.Connection) -> int:
    version = db.execute("PRAGMA user_version").fetchone()[0]
    has_jobs = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='jobs'").fetchone()
    if version == 0 and has_jobs:
        return 1  # база создана до появления миграций — схема 0001 уже есть
    return version


def migrate(path: Path) -> list[str]:
    """Применяет недостающие миграции; возвращает имена применённых."""
    path.parent.mkdir(parents=True, exist_ok=True)
    applied: list[str] = []
    db = sqlite3.connect(path, isolation_level=None)
    try:
        version = current_version(db)
        for number, sql_file in enumerate(migration_files()[version:], start=version + 1):
            # одна транзакция на миграцию: либо применена целиком вместе с версией, либо не применена
            sql = sql_file.read_text(encoding="utf-8")
            db.executescript(f"BEGIN;\n{sql}\nPRAGMA user_version = {number};\nCOMMIT;")
            applied.append(sql_file.name)
    finally:
        db.close()
    return applied


def design_counter(product: str) -> str:
    """Счётчик сквозных номеров дизайнов товара: design:shopper, design:mousepad."""
    return f"design:{product}"


def reserve_numbers(path: Path, product: str, first_number: int) -> int:
    """Номера дизайнов товара (артикулы BAG-NNNNNN, MSE-NNNNNN) не ниже first_number — чтобы не совпасть с уже
    выложенными в Ozon артикулами. Счётчик только растёт; возвращает номер следующего дизайна."""
    name = design_counter(product)
    db = sqlite3.connect(path, isolation_level=None)
    try:
        db.execute("BEGIN")
        db.execute("INSERT OR IGNORE INTO counters (name, value) VALUES (?, 0)", (name,))
        db.execute("UPDATE counters SET value = max(value, ?) WHERE name = ?", (int(first_number) - 1, name))
        db.execute("COMMIT")
        return db.execute("SELECT value FROM counters WHERE name = ?", (name,)).fetchone()[0] + 1
    finally:
        db.close()


def ensure_current(path: Path) -> None:
    """Для приложения: схема должна быть актуальной, иначе — понятная ошибка вместо падения на SQL."""
    if not path.exists():
        raise SchemaOutdated(f"Нет базы {path}: выполните миграции (python -m printflow.migrations)")
    db = sqlite3.connect(path)
    try:
        version = current_version(db)
    finally:
        db.close()
    if version < latest_version():
        raise SchemaOutdated(
            f"Схема {path} версии {version}, нужна {latest_version()}: выполните миграции (python -m printflow.migrations)"
        )

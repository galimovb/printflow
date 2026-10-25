"""Миграции общей базы задач: python -m printflow.migrations (в Docker — сервис migrate).
Заодно выставляет стартовые номера дизайнов каждого товара (<ТОВАР>_FIRST_ARTICLE_NUMBER)."""
from __future__ import annotations

import sys

from printflow.config import load_app_settings, load_product_settings
from printflow.migrations.runner import latest_version, migrate, reserve_numbers
from printflow.products import get_product
from printflow.scripts.migrate_product_data import migrate as migrate_data


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except AttributeError:
        pass
    settings = load_app_settings()
    moved = migrate_data(settings.data_dir, apply=True)
    print(f"Данные товаров: перенесено {len(moved)} файлов")
    path = settings.jobs_db
    applied = migrate(path)
    print(f"{path}: применено {len(applied)} ({', '.join(applied) or 'схема актуальна'}), версия {latest_version()}")
    for name in settings.products:
        product = get_product(name)
        first = load_product_settings(product.env_prefix).queue.first_article_number
        print(f"  {name}: следующий номер дизайна {reserve_numbers(path, name, first)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

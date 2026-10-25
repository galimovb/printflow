# PrintFlow

Приложение переименовано из shopper_mousepad. Новый режим футболок WB: `/studio/wb`.
Инструкция: [WB Studio](wb_studio/README.md). Старые Python-команды поддерживаются.

# printflow — товары с принтом для Ozon

Одно приложение (один процесс, один Docker, одна база задач) для нескольких товаров:

| Товар | Префикс | Что это |
|---|---|---|
| `thermo` | `TRM-` | термонаклейки 6,5×9,5 см, один товар на дизайн, 6 слайдов; [настройка](products/thermo/README.md) |
| `shopper` | `BAG-` | шоппер 38×42 см, принт DTF, два цвета сумки — товар на каждый цвет |
| `mousepad` | `MSE-` | коврик для мыши 22×18 см, 3 мм, принт во весь коврик — один товар на дизайн |

Конвейер у всех товаров один: **принт → галерея → карточка Ozon → сертификат**, заказ → hi-res для печати.

## Устройство

```
printflow/
  config.py, container.py, __main__.py   приложение: настройки SM_* и <ТОВАР>_*, сборка зависимостей
  domain/, repositories/, migrations/    задачи, одна база на все товары (у задачи — товар)
  workers/                               очередь: у каждого товара свой пул воркеров
  services/                              общее: сценарий карточки, Ozon, сертификаты, заказы, hi-res, S3
  api/                                   REST: /api/v1/<товар>/…, у каждого товара свой токен
  products/
    base.py                              интерфейс товара (Product)
    shopper/, mousepad/, thermo/         товары, раскладка у всех одинаковая (см. ниже)
  scripts/                               общие скрипты с --product
```

Товар отвечает только за то, чем отличается (`products/base.py`). Раскладка у всех товаров одна:

```text
products/<товар>/
  product.py                          Product — фасад товара, связывает части ниже
  config/product.json                 артикулы, бакеты, генерация, галерея, тексты, карточка Ozon
  config/themes.json                  тематики: key, name, known, captions, style — у всех товаров одинаково
  domain/prompts.py                   промпты и правила принта
  infrastructure/print_generator.py   генерация принта (OpenAI Images)
  infrastructure/ozon_listing.py      тело импорта Ozon
  infrastructure/gallery/             фото карточки из принта и каркасов
  assets/                             каркасы (assets/templates), шрифты, картинки
  scripts/                            каркасы и превью галереи
```

Товары не импортируют друг друга: общее — в `services/` (принт на хромакее —
`services/printing/chromakey.py`, «один дизайн — один товар» на Ozon — `services/ozon/listing.py`).

- `config/product.json` — описание товара и карточки;
- `generator()` — генерация принта;
- `gallery()` — фото карточки;
- `variants()` — варианты дизайна;
- `build_items()` — тело импорта Ozon.

Новый товар — подкласс `Product` в `products/<имя>/product.py` и строка в `products/__init__.py`.

Рабочие файлы каждого товара лежат в одной папке, определяемой через
`AppSettings.product_data_dir(name)` относительно `SM_DATA_DIR`:

```text
data/
  jobs.db                 общая очередь
  backups/                резервные копии общей базы
  migrations/             журналы переноса файлов
  shopper/
    reports/
  mousepad/
    reports/
  thermo/
    reports/
```

Справочники и настройки товара находятся в `products/<товар>`, рабочие данные —
в `data/<товар>`. `outputs/` используется только для явно заказанных экспортов.
Отчёт об источниках — в `data/<товар>/reports/sources.csv`. В Docker всё сохраняется в том же постоянном
томе `SM_DATA_DIR=/data`; дополнительных томов для каждого товара не требуется.

Старые пути переносит стандартная команда миграций при запуске Docker.
Отдельно: `python -m printflow.scripts.migrate_product_data` показывает план,
`--apply` выполняет перенос. Существующие файлы не перезаписываются, перед переносом
проверяются все конфликты, содержимое сверяется по SHA-256. Повторный запуск безопасен.

**База** — один файл `data/jobs.db`.
- У каждой задачи и группы объединения есть поле «товар» (миграция `0005`).
- Номера дизайнов считаются по товарам: `design:shopper`, `design:mousepad`.
- Воркер берёт только задачи своего товара.

## Запуск

```bash
cd printflow
docker compose up -d --build                     # migrate → app, API на 127.0.0.1:8090
docker compose exec -T app python -m printflow.scripts.progress
```

**Настройки** — `printflow/.env`:
- `SM_*` — приложение: порт, `SM_PRODUCTS` — какие товары запускать;
- `SHOPPER_*` и `MOUSEPAD_*` — свои у каждого товара: токен API, кабинет Ozon, сертификат, очередь, заказы;
- общие ключи S3 и OpenAI берутся из `.env` футболок.

## Скрипты

| Задача | Команда |
|---|---|
| Прогресс | `python -m printflow.scripts.progress [--product mousepad]` |
| Постановка из XLSX парсера | `python -m printflow.scripts.from_xlsx --product mousepad файл.xlsx --limit 9999` |
| Принты по тематикам (GPT придумывает сам) | `python -m printflow.scripts.themes --product mousepad --all --count 100` |
| Шопперы по выбранным тематикам | `python -m printflow.scripts.themes --product shopper --theme cats space --count 10 --dry-run` |
| Перезапуск упавших (кроме фильтра OpenAI) | `python -m printflow.scripts.retry_failed [--product shopper] [--dry-run]` |
| Характеристики Ozon по справочникам | `python -m printflow.scripts.ozon_prepare_card --product mousepad` |
| Привязать выложенные к сертификату | `python -m printflow.scripts.ozon_certificate --product shopper` |
| Бакеты S3 товара | `python -m printflow.scripts.create_buckets --product mousepad` |
| Шаблоны галереи шоппера | `python -m printflow.products.shopper.scripts.generate_blanks` |
| Превью галереи шоппера | `python -m printflow.products.shopper.scripts.preview_gallery --print принт.png` |
| Шаблоны галереи коврика | `python -m printflow.products.mousepad.scripts.generate_blanks` |
| Превью коврика из таблицы | `python -m printflow.products.mousepad.scripts.preview_gallery --xlsx файл.xlsx --row 3` |

В контейнере эти скрипты запускаются так: `docker compose exec -T app python -m …`.

Тематики каждого товара — `products/<товар>/config/themes.json`. `--count` — число дизайнов на каждую
тематику; у шоппера каждый дизайн даёт два цветовых варианта. `--dry-run` генерирует принты и
галереи (с запросами в OpenAI), но не публикует их на Ozon. Для публикации уберите этот флаг.
После обновления кода пересоберите сервис: `docker compose up -d --build`.

Коврики и шопперы используют общий генератор изображений, описание рисунка и правила разнообразия.
Товар задаёт промпт печати и обработку результата: коврик заполняется от края до края, шоппер получает
изолированный DTF-принт на прозрачном фоне, подходящий для обеих сумок. У тематических шопперов
сохраняется `design_name` для истории коллекции; название карточки шоппера остаётся из его шаблона.
Промпт учитывает последние описания рисунков этой темы и товара; это снижает повторы, но не является
проверкой визуального совпадения. Подписи ковриков — русские, шопперов — английские по правилам DTF-промпта.

Контракты зависимостей сценариев находятся в `domain/ports.py` (`Protocol`): генератор,
галерея, хранилище, загрузчик изображений, публикация карточек и JSON API-клиент.
`ImagePrintGenerator` содержит общие генерацию, редактирование, hi-res и описание рисунка;
реализации товаров задают промпты и обработку изображений через абстрактные методы.
`JpegGalleryRenderer` экспортирует слайды одинаково для обоих товаров, сохраняя их порядок
и правила нумерации; композиция остаётся у товара. Сценарий hi-res зависит только от
контракта `HiresGenerator`, без импорта генератора конкретного товара.

`TextCanvas` содержит общие операции текста и холста, а `services/gallery/geometry.py` —
матрицу перспективы. Товарные темы сохраняют свои шрифты, палитры, интервалы и иконки.

Тесты: `python -m unittest discover -s printflow/tests -p "test_*.py"`.

## API

У каждого товара свой префикс `/api/v1/<товар>`:
- `POST /jobs` и `POST /jobs/batch` — поставить карточки в очередь;
- `GET /jobs/{id}`, `GET /jobs?status=…` — задача и список;
- `POST /jobs/{id}/retry` — повторить задачу;
- `POST /prints/{article}/hires` — hi-res принта для печати;
- `GET /health` — проверка сервиса.

Общий `GET /api/v1/health` показывает очередь всех товаров.

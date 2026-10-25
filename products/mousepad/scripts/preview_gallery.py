#!/usr/bin/env python3
"""Превью галереи коврика и проверка каркасов (локально, без S3 и Ozon).

    python -m printflow.products.mousepad.scripts.preview_gallery --print path/to/print.png   # → printflow/data/mousepad/preview/
    python -m printflow.products.mousepad.scripts.preview_gallery --photo photo.webp          # принт с фото через OpenAI (1 запрос) → превью
    python -m printflow.products.mousepad.scripts.preview_gallery --xlsx products-mousepad_….xlsx --row 3   # фото из строки таблицы парсера
    python -m printflow.products.mousepad.scripts.preview_gallery --check                     # сетка и углы на каждом каркасе

Папка превью очищается перед каждым запуском.
"""
from __future__ import annotations

import argparse
import asyncio
import shutil
import sys
from pathlib import Path

from PIL import Image, ImageDraw

from printflow.config import PACKAGE_DIR, load_product_settings, load_app_settings
from printflow.products.mousepad.product import Mousepad

PRODUCT = Mousepad()
TEMPLATES_DIR = PRODUCT.templates_dir
from printflow.products.mousepad.infrastructure.gallery.geometry import analyse_template, place_on_surface, template_path
from printflow.products.mousepad.infrastructure.gallery.renderer import SLIDES, PadGalleryRenderer
from printflow.products.mousepad.infrastructure.gallery.theme import font



def test_pattern(size_cm: tuple[float, float]) -> Image.Image:
    w, h = int(700 * size_cm[0] / size_cm[1]), 700
    img = Image.new("RGB", (w, h), (250, 250, 250))
    d = ImageDraw.Draw(img)
    for i in range(1, 11):
        d.line([(w * i / 11, 0), (w * i / 11, h)], fill=(220, 40, 40), width=3)
        d.line([(0, h * i / 9), (w, h * i / 9)], fill=(220, 40, 40), width=3)
    d.rectangle([0, 0, w - 1, h - 1], outline=(30, 30, 200), width=14)
    d.text((w / 2, h / 2), "TOP", font=font(h * 0.2, "black"), fill=(30, 30, 200), anchor="mm")
    return img


def run_check(product: dict, out_dir: Path) -> None:
    """Тестовая сетка на поверхности (синяя рамка = края коврика, TOP = верх) и найденные углы (зелёный контур)."""
    dst = out_dir / "_check"
    dst.mkdir(parents=True, exist_ok=True)
    pattern = test_pattern(tuple(product["size_cm"]))
    for slide in SLIDES:
        path = template_path(slide, TEMPLATES_DIR)
        scene = product["gallery"]["scenes"].get(slide, {})
        if not path.is_file():
            print(f"  {slide}: нет каркаса")
            continue
        if not scene.get("print", True):
            print(f"  {slide}: без принта")
            continue
        alpha, quad = analyse_template(path)
        quad = scene.get("quad") or quad
        if quad is None:
            print(f"  {slide}: ! зелёная поверхность не найдена")
            continue
        img = place_on_surface(Image.open(path), pattern, quad, alpha, 0)
        ImageDraw.Draw(img).polygon([tuple(p) for p in quad], outline=(0, 200, 120), width=4)
        img.save(dst / f"{slide}.jpg", quality=88)
        print(f"  {slide}: углы {[tuple(map(int, p)) for p in quad]}")
    print(f"Проверка: {dst}")


def photo_from_xlsx(path: Path, row: int) -> bytes:
    """Главное фото товара из строки таблицы парсера (как берёт from_xlsx)."""
    import httpx

    from printflow.scripts.from_xlsx import read_rows

    rows = [r for r in read_rows(path) if r.get("Фото")]
    if not 1 <= row <= len(rows):
        sys.exit(f"В таблице {len(rows)} строк с фото, а запрошена {row}")
    print(f"  строка {row}: {rows[row - 1].get('Название', '')[:80]}")
    response = httpx.get(rows[row - 1]["Фото"], timeout=60, follow_redirects=True)
    response.raise_for_status()
    return response.content


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except AttributeError:
        pass
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--print", dest="print_path", type=Path, help="PNG принта (вся поверхность коврика)")
    parser.add_argument("--photo", type=Path, help="фото коврика: принт снимается через OpenAI, как в очереди")
    parser.add_argument("--xlsx", type=Path, help="таблица парсера: фото берётся из колонки «Фото»")
    parser.add_argument("--row", type=int, default=1, help="номер товара в таблице (1 — первый), по умолчанию 1")
    parser.add_argument("--check", action="store_true", help="тестовая сетка на всех каркасах")
    args = parser.parse_args()
    out_dir = load_app_settings().product_data_dir(PRODUCT.name) / "preview"

    product = PRODUCT.config
    shutil.rmtree(out_dir, ignore_errors=True)
    out_dir.mkdir(parents=True)
    if args.check:
        run_check(product, out_dir)
        return 0
    if args.photo or args.xlsx:
        from printflow.products.mousepad.infrastructure.print_generator import PadPrintGenerator

        photo = args.photo.read_bytes() if args.photo else photo_from_xlsx(args.xlsx, args.row)
        (out_dir / "photo.jpg").write_bytes(photo)
        generator = PadPrintGenerator(load_product_settings(PRODUCT.env_prefix).openai, product)
        print_png = asyncio.run(generator.copy_from_photo(photo))
        (out_dir / "print.png").write_bytes(print_png)
        print("  + photo.jpg (исходное фото), print.png (принт с фото)")
    elif args.print_path:
        print_png = args.print_path.read_bytes()
    else:
        parser.error("нужен --print, --photo, --xlsx или --check")
    for name, data in PadGalleryRenderer(product, TEMPLATES_DIR).render(print_png):
        (out_dir / f"{name}.jpg").write_bytes(data)
        print(f"  + {name}.jpg")
    print(f"Готово: {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Превью галереи и проверка разметки каркасов (локально, без S3 и Ozon).

    python -m printflow.products.shopper.scripts.preview_gallery --print path/to/print.png   # → printflow/data/shopper/preview/{white,black}/
    python -m printflow.products.shopper.scripts.preview_gallery --check                     # → printflow/data/shopper/preview/_check/

Папка превью очищается перед каждым запуском.
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

from printflow.config import PACKAGE_DIR, load_product_settings, load_app_settings
from printflow.products.shopper.product import Shopper

PRODUCT = Shopper()
TEMPLATES_DIR = PRODUCT.templates_dir
from printflow.products.shopper.infrastructure.gallery.geometry import place_print, scene_geometry, template_path
from printflow.products.shopper.infrastructure.gallery.renderer import GalleryRenderer
from printflow.products.shopper.infrastructure.gallery.theme import font



def test_pattern(aspect: float) -> Image.Image:
    w, h = int(700 * aspect), 700
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, w - 1, h - 1], outline=(220, 40, 40, 255), width=8)
    for i in range(1, 6):
        d.line([(w * i / 6, 0), (w * i / 6, h)], fill=(220, 40, 40, 160), width=3)
        d.line([(0, h * i / 6), (w, h * i / 6)], fill=(220, 40, 40, 160), width=3)
    d.text((w / 2, h / 2), "ZONE", font=font(h * 0.16, "black"), fill=(220, 40, 40, 255), anchor="mm")
    return img


def run_check(product: dict[str, Any], templates_dir: Path, out_dir: Path) -> None:
    """Сетка в зоне печати (красная) и контур корпуса (зелёный) — проверить определение глазами."""
    cfg = product["gallery"]
    print_cm = tuple(product["generation"]["print_area_cm"])
    dst = out_dir / "_check"
    dst.mkdir(parents=True, exist_ok=True)
    pattern = test_pattern(print_cm[0] / print_cm[1])
    for scene in cfg["scenes"]:
        body, zone = scene_geometry(scene, cfg, print_cm, templates_dir)
        for color in cfg["shade"]:
            path = template_path(scene, color, templates_dir)
            if not path.is_file() or zone is None:
                print(f"  {scene}/{color}: нет каркаса или корпус не найден")
                continue
            img = place_print(Image.open(path).convert("RGB"), pattern, zone, print_cm[0] / print_cm[1], 0)
            ImageDraw.Draw(img).polygon(body, outline=(0, 200, 120), width=5)
            img.save(dst / f"{scene}_{color}.jpg", quality=88)
            print(f"  {scene}/{color}: корпус {[tuple(map(int, p)) for p in body]}")
    print(f"Проверка: {dst}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--print", dest="print_path", type=Path, help="PNG принта")
    parser.add_argument("--check", action="store_true", help="наложить тестовую сетку на все каркасы")
    args = parser.parse_args()
    out_dir = load_app_settings().product_data_dir(PRODUCT.name) / "preview"

    product = PRODUCT.config
    shutil.rmtree(out_dir, ignore_errors=True)
    if args.check:
        run_check(product, TEMPLATES_DIR, out_dir)
        return 0
    if not args.print_path:
        parser.error("нужен --print (или --check)")
    renderer = GalleryRenderer(product, TEMPLATES_DIR)
    for color in product["colors"]:
        dst = out_dir / color
        dst.mkdir(parents=True)
        for name, data in renderer.render(args.print_path.read_bytes(), color):
            (dst / f"{name}.jpg").write_bytes(data)
            print(f"  + {color}/{name}.jpg")
    print(f"Готово: {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

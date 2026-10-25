#!/usr/bin/env python3
"""Генерация каркасов для шопперов через OpenAI Images, строго по очереди.

Каркас — фото ПУСТОЙ сумки (без принта). Принт накладывается потом кодом
(shopper/services/gallery), поэтому каркас делается один раз на все карточки.

Шаги:
  white, black           — packshot для главного фото (принт кладётся алгоритмом, как у футболок)
  <scene>_white          — сцена с белой сумкой (images.generate)
  <scene>_black          — та же сцена с чёрной сумкой (images.edit по <scene>_white, геометрия 1:1)
Сцены: hero, front, lifestyle, closeup, flatlay, model.

Ключ OpenAI — как у всего shopper (shopper/settings.py).

    python -m printflow.products.shopper.scripts.generate_blanks                      # всё (14 запросов), папка очищается
    python -m printflow.products.shopper.scripts.generate_blanks --only hero_white hero_black --quality medium

Результат — сразу в printflow/products/shopper/assets/templates/<шаг>.png. Полный прогон очищает папку,
--only перезаписывает только свои файлы. Зоны печати — product.json → gallery.scenes.
"""
from __future__ import annotations

import argparse
import base64
import shutil
import sys
import time
from pathlib import Path

from openai import BadRequestError, OpenAI

from printflow.config import PACKAGE_DIR, load_product_settings
from printflow.products.shopper.product import Shopper

PRODUCT = Shopper()
TEMPLATES_DIR = PRODUCT.templates_dir

STYLE = (
    "Minimal Scandinavian aesthetic: warm off-white and sand tones (#F3EFE9, #E7DFD4), "
    "light oak wood, soft natural daylight from the left, gentle soft shadows, calm clean "
    "composition with generous negative space. Photorealistic e-commerce lifestyle photography. "
    "No text, no letters, no logos, no brand marks, no watermarks anywhere in the image."
)
BAG = (
    "a plain blank MILKY OFF-WHITE (warm ecru-white, about #F1ECE2) cotton twill tote bag (shopper), about 38 x 42 cm, with two 60 cm "
    "fabric handles. The FRONT PANEL of the bag is completely empty — no print, no logo, "
    "no label — smooth and evenly lit, with no folds or wrinkles in its central area, and it "
    "is NOT covered by handles, hands, hair or any objects"
)
PACKSHOT = (
    "Product photo of a plain blank MILKY OFF-WHITE (warm ecru-white, about #F1ECE2) cotton canvas tote bag (shopper), front view, "
    "perfectly straight-on camera, bag lying flat and symmetric, centered in frame. "
    "Two long fabric handles fully visible above the bag, same length, naturally laid out. "
    "The front panel is completely empty: no print, no logo, no text, no label, no seams "
    "or folds or wrinkles in the central area — a smooth even fabric surface for printing. "
    "Natural cotton canvas texture, subtle and realistic. "
    "Solid uniform light-gray studio background (#E6E6E6), no gradient, no props. "
    "Soft even lighting, very soft shadow under the bag only, no harsh shadows on the fabric. "
    "Bag occupies about 70% of image height. Photorealistic e-commerce packshot."
)
SCENES: dict[str, str] = {
    "hero": (
        f"{BAG}. The bag hangs from a minimal light-oak wall hook and is placed in the RIGHT "
        "60% of the frame, front panel facing the camera squarely, perfectly frontal. The LEFT "
        "40% of the frame is an empty warm off-white plaster wall (reserved for text). A small "
        "matte ceramic vase with dried pampas grass stands on the floor in the bottom-left "
        "corner, away from the bag."
    ),
    "front": (
        f"Studio packshot of {BAG}. The bag lies perfectly flat, exact front view, centered "
        "horizontally, handles laid symmetrically above it. The whole bag including handles "
        "occupies ONLY THE UPPER 58% of the frame, with about 6% margin at the top. The LOWER "
        "36% of the frame is empty seamless warm off-white background (#F3EFE9)."
    ),
    "lifestyle": (
        f"{BAG}, standing upright on a light-oak table against a warm beige wall, filled with "
        "a hardcover book, a folded oatmeal knit sweater and a baguette sticking out of the top. "
        "The front panel faces the camera almost straight-on (at most 10 degrees of rotation) "
        "and is fully visible; the handles rise up behind the contents and do not cross the "
        "front panel. The TOP 22% of the frame is empty wall (reserved for a caption)."
    ),
    "closeup": (
        f"Close-up three-quarter view of {BAG}, hanging on the back of a light-oak chair. The "
        "front panel fills about 65% of the frame and is turned about 25 degrees to the right, "
        "cotton weave texture clearly visible, soft side light. The TOP-LEFT area of the frame "
        "is calm empty background (reserved for a caption)."
    ),
    "flatlay": (
        f"Top-down flat lay of {BAG} lying perfectly flat on warm natural linen fabric, rotated "
        "about 12 degrees clockwise. A few items are placed around its edges without touching the "
        "front panel: sunglasses, a ceramic coffee cup, a set of keys. The BOTTOM 22% of the frame "
        "is empty linen background (reserved for a caption)."
    ),
    "model": (
        f"A person wearing a plain oatmeal knit top and light-blue jeans carries {BAG} on the "
        "shoulder. Cropped from the shoulders to mid-thigh, the face is NOT visible. The bag "
        "hangs at the hip with its front panel flat and facing the camera; the arm and hand hold "
        "only the handle and do not cover the panel. Plain warm beige studio background."
    ),
}
BLACK_EDIT = (
    "Change ONLY the color of the tote bag fabric and its handles to solid deep BLACK cotton. "
    "Keep everything else exactly identical: the same bag shape, size, position, handle "
    "placement, framing, camera angle, all other objects, person, background and lighting. "
    "The front panel stays completely empty and smooth — no print, no text, no logo. "
    "Keep realistic black cotton texture with subtle highlights, not pure flat black."
)


def _build_steps() -> dict[str, dict]:
    steps: dict[str, dict] = {
        "white": {"prompt": PACKSHOT},
        "black": {"prompt": BLACK_EDIT, "base": "white"},
    }
    for scene, prompt in SCENES.items():
        steps[f"{scene}_white"] = {"prompt": f"{prompt} {STYLE}"}
        steps[f"{scene}_black"] = {"prompt": BLACK_EDIT, "base": f"{scene}_white"}
    return steps


STEPS = _build_steps()
GROUPS = {
    "all": list(STEPS),
    "packshot": ["white", "black"],
    "scenes": [s for s in STEPS if s not in ("white", "black")],
}


def _client() -> OpenAI:
    settings = load_product_settings(PRODUCT.env_prefix)
    if not settings.openai.api_key:
        sys.exit("Нет ключа: задайте OPENAI_API_KEY")
    return OpenAI(api_key=settings.openai.api_key, base_url=settings.openai.base_url,
                  timeout=settings.openai.timeout_sec)


def _save_b64(result, path: Path) -> None:
    data = result.data[0].b64_json
    if not data:
        raise RuntimeError("Ответ без b64_json")
    path.write_bytes(base64.b64decode(data))


def _with_retries(fn, what: str, attempts: int = 3):
    for i in range(1, attempts + 1):
        try:
            return fn()
        except BadRequestError:
            raise  # ошибка в запросе — повтор не поможет
        except Exception as exc:  # noqa: BLE001 — сетевые/API ошибки, повторяем
            if i == attempts:
                raise
            wait = 10 * i
            print(f"  ! {what}: {exc.__class__.__name__}: {exc} — повтор через {wait} с", flush=True)
            time.sleep(wait)


def _resolve_steps(only: list[str] | None) -> list[str]:
    if not only:
        return GROUPS["all"]
    wanted: set[str] = set()
    for name in only:
        if name in GROUPS:
            wanted.update(GROUPS[name])
        elif name in STEPS:
            wanted.add(name)
        else:
            sys.exit(f"Неизвестный шаг: {name}. Доступно: {', '.join([*GROUPS, *STEPS])}")
    return [s for s in STEPS if s in wanted]  # порядок: white-версия всегда раньше black


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--only", nargs="+", metavar="STEP", help="шаги или группы: all, packshot, scenes, hero_white, …")
    parser.add_argument("--model", default=load_product_settings(PRODUCT.env_prefix).openai.image_model)
    parser.add_argument("--size", default="1536x2048", help="WxH, по умолчанию 3:4 1536x2048")
    parser.add_argument("--quality", default="high", choices=["low", "medium", "high", "auto"])
    args = parser.parse_args()

    steps = _resolve_steps(args.only)
    client = _client()
    out_dir = TEMPLATES_DIR
    if not args.only:
        shutil.rmtree(out_dir, ignore_errors=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"Модель {args.model}, {args.size}, quality={args.quality}, шагов: {len(steps)} → {out_dir}", flush=True)

    failed: list[str] = []
    for n, step in enumerate(steps, 1):
        spec = STEPS[step]
        target = out_dir / f"{step}.png"
        print(f"[{n}/{len(steps)}] {step} …", flush=True)
        started = time.monotonic()
        base = spec.get("base")
        if base:
            base_path = out_dir / f"{base}.png"
            if not base_path.is_file():
                print(f"  пропуск: нет {base}.png — сначала сгенерируйте {base}", flush=True)
                failed.append(step)
                continue

            def call(base_path=base_path, prompt=spec["prompt"]):
                with base_path.open("rb") as image:
                    return client.images.edit(
                        model=args.model, image=image, prompt=prompt, size=args.size, quality=args.quality,
                    )
        else:
            def call(prompt=spec["prompt"]):
                return client.images.generate(
                    model=args.model, prompt=prompt, size=args.size, quality=args.quality,
                )
        try:
            _save_b64(_with_retries(call, step), target)
        except Exception as exc:  # noqa: BLE001 — один неудачный шаг не должен ронять остальные
            print(f"  ОШИБКА {step}: {exc.__class__.__name__}: {exc}", flush=True)
            failed.append(step)
            continue
        print(f"  OK {target.name} ({time.monotonic() - started:.0f} с)", flush=True)

    print(f"Готово: {out_dir}")
    if failed:
        print(f"Не получилось: {', '.join(failed)} — перезапустите с --only {' '.join(failed)}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

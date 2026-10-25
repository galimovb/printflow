#!/usr/bin/env python3
"""Генератор каркасов (шаблонов) галереи ковриков через OpenAI Images, по очереди.

Каркас — фото сцены, где ВСЯ верхняя поверхность коврика залита хромакеем #00FF00. Принт потом
кладётся кодом (mousepad/services/gallery): по зелёному находятся маска поверхности (мышь и рука
поверх вырезаются сами), 4 угла и свет. Каркас делается один раз на все карточки.

Пропорции коврика не доверяются GPT: код сам рисует план сцены — зелёный коврик ровно в пропорциях size_cm в нужной
перспективе (geometry.pad_outline, поза — SCENES[...]["pose"]), а GPT через images.edit достраивает
вокруг него фото. GPT держит форму неточно (на несколько процентов), поэтому фото затем выпрямляется:
лёгкая перспективная трансформация всего кадра делает коврик ровно в пропорциях size_cm (rectify_template). Если форма
ушла больше чем на --max-shape (8% диагонали) — сцена генерируется заново (до --attempts раз).

    python -m printflow.products.mousepad.scripts.generate_blanks --rectify-only      # выпрямить уже сгенерированные, без OpenAI

Сцены (порядок = порядок слайдов): hero, office, glide, print, protect, base, compact
(compact — свёрнутый коврик изнанкой, без принта и без плана). В каждой сцене пустая зона под текст.

    python -m printflow.products.mousepad.scripts.generate_blanks                       # все сцены, папка очищается
    python -m printflow.products.mousepad.scripts.generate_blanks --only hero glide      # перегенерировать выбранные
    python -m printflow.products.mousepad.scripts.generate_blanks --guides-only          # только планы сцен (без OpenAI) → printflow/data/mousepad/guides

Результат — products/mousepad/assets/templates/<сцена>.png. Проверить глазами: python -m printflow.products.mousepad.scripts.preview_gallery --check
"""
from __future__ import annotations

import argparse
import base64
import io
import shutil
import sys
import time
from pathlib import Path

from openai import BadRequestError, OpenAI
from PIL import Image, ImageDraw

from printflow.config import PACKAGE_DIR, load_product_settings, load_app_settings
from printflow.products.mousepad.product import Mousepad

PRODUCT = Mousepad()
TEMPLATES_DIR = PRODUCT.templates_dir
from printflow.products.mousepad.infrastructure.gallery.geometry import (
    Quad,
    align_designed,
    analyse_template,
    pad_outline,
    quad_problem,
    rectify_template,
)

BACKGROUND = (247, 210, 193)  # персиковый фон сцен (#F7D2C1) — им же залит план сцены
STYLE = (
    "Clean bright product photo on a seamless pastel peach background (#F7D2C1). Behind the objects a few "
    "large flat soft round shapes in lighter peach (#FBE2D6) and deeper peach (#F0B9A3), like a modern "
    "marketplace infographic backdrop. Soft natural contact shadows under the objects. No desk, no table "
    "edge, no wall corner. Photorealistic, soft diffused light. No text, no letters, no numbers, no logos, "
    "no watermarks anywhere in the image."
)
KEEP_PAD = (
    "The input is a layout sketch. The green rounded rectangle is the top of a thin, completely flat cloth mouse "
    "pad lying on the desk: keep its EXACT outline, position, size, proportions and perspective — do not move, "
    "resize, rotate, stretch or crop it. The pad has NO stitched edge, no binding, no border and no rim: the "
    "edges are clean cut and the top surface reaches the very edge. Keep the whole top surface one perfectly "
    "uniform solid chroma-key green (#00FF00) like a green screen: no print, no logo, no texture pattern, no "
    "gradient, no glare, only natural soft shading where objects rest on it. Replace the plain sketch "
    "background with a real scene: "
)
SCENES: dict[str, dict] = {
    # зоны под текст: сверху ~32% — заголовок; углы снизу — бейджи и маскот
    "hero": {  # главное фото: строго сверху, стороны коврика параллельны краям кадра
        "pose": {"tilt": 0, "yaw": 0, "center": (0.5, 0.6), "width": 0.74},
        "prompt": "a perfectly top-down photo, the camera looks straight down, exactly perpendicular to the pad; "
                  "the pad lies perfectly straight, its edges exactly parallel to the edges of the photo. NOTHING "
                  "lies on the pad: no mouse, no keyboard, no hands, no objects — the whole surface is fully visible. "
                  "The TOP 33% of the frame and the bottom-left and bottom-right corners stay empty peach background.",
    },
    "office": {
        "pose": {"tilt": 34, "yaw": 10, "center": (0.5, 0.62), "width": 0.8},
        "prompt": "the pad lies on the peach background; a white wireless mouse on its right part; a corner of a "
                  "white keyboard enters the frame at the far right edge beside the pad. The TOP 32% of the frame "
                  "stays empty peach background.",
    },
    "glide": {
        "pose": {"tilt": 40, "yaw": -8, "center": (0.5, 0.63), "width": 0.82},
        "prompt": "a person's right hand in a cream knit sleeve holds a white wireless mouse resting on the right "
                  "third of the pad; only the hand and wrist are visible, no face. The TOP 32% of the frame stays "
                  "empty peach background.",
    },
    "print": {
        "pose": {"tilt": 0, "yaw": -6, "center": (0.5, 0.62), "width": 0.8},
        "prompt": "a perfectly top-down photo straight down onto the pad lying on the peach background; a white "
                  "mouse sits on its lower-right corner. The TOP 30% of the frame stays empty peach background.",
    },
    "protect": {
        "pose": {"tilt": 38, "yaw": 14, "center": (0.5, 0.64), "width": 0.8},
        "prompt": "the pad lies on the peach background with a white mouse on it; a white ceramic coffee cup stands "
                  "beside the pad at the bottom-left, not touching it. The TOP 32% of the frame stays empty peach "
                  "background.",
    },
    "base": {
        "pose": {"tilt": 36, "yaw": -6, "center": (0.5, 0.64), "width": 0.8},
        "prompt": "ONLY the bottom-right corner of the pad is gently peeled up (about 12% of the pad) and curled "
                  "toward the camera, revealing the underside: black textured anti-slip rubber with a fine diamond "
                  "pattern; the rest of the pad keeps the exact sketch outline and lies flat. The TOP 32% of the "
                  "frame stays empty peach background.",
    },
    "compact": {
        "pose": None,
        "prompt": "A plain thin 22 x 18 cm mouse pad without any stitched edge, rolled into a loose tube and held "
                  "by a hand from the right side; the outer visible side is plain black textured rubber, no print, "
                  "no green color anywhere. The rolled pad is large and occupies the LOWER 60% of the frame; the "
                  "TOP 35% is empty peach background.",
    },
}


def guide_image(pose: dict, size_cm: tuple[float, float], image_size: tuple[int, int]) -> tuple[bytes, Quad]:
    """План сцены: светлый фон и зелёный коврик ровно в пропорциях size_cm в перспективе, без окантовки."""
    ss = 3  # сглаживание
    w, h = image_size
    img = Image.new("RGB", (w * ss, h * ss), BACKGROUND)
    draw = ImageDraw.Draw(img)
    quad, outline = pad_outline(size_cm, image_size, **pose)  # без окантовки: принт до самого края
    draw.polygon([(x * ss, y * ss) for x, y in outline], fill=(0, 255, 0))
    buf = io.BytesIO()
    img.resize(image_size, Image.Resampling.LANCZOS).save(buf, format="PNG")
    return buf.getvalue(), quad


def _client() -> OpenAI:
    settings = load_product_settings(PRODUCT.env_prefix)
    if not settings.openai.api_key:
        sys.exit("Нет ключа: задайте OPENAI_API_KEY")
    return OpenAI(api_key=settings.openai.api_key, base_url=settings.openai.base_url,
                  timeout=settings.openai.timeout_sec)


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


def check_template(scene: str, path: Path, designed: Quad | None) -> str:
    """Отчёт по каркасу; начинается с «!», если каркас не годится."""
    alpha, quad = analyse_template(path)
    share = float((alpha > 0.5).mean())
    if designed is None:
        return "без принта" + (f" (! зелёного {share:.0%} — лишний хромакей)" if share > 0.01 else "")
    if quad is None:
        return f"! поверхность не найдена (зелёного {share:.0%})"
    if problem := quad_problem(quad, float((alpha > 0.5).sum()), alpha.shape[::-1], designed):
        return f"! {problem}"
    return f"поверхность {share:.0%} кадра, углы {[tuple(map(int, p)) for p in quad]}"


def rectify(scene: str, size_cm: tuple[float, float], image_size: tuple[int, int], max_shape: float) -> bool:
    """Выпрямить каркас сцены: коврик ровно в пропорциях size_cm. False — форма ушла слишком далеко, нужна новая генерация."""
    path = TEMPLATES_DIR / f"{scene}.png"
    if not path.is_file():
        print(f"  {scene}: нет каркаса")
        return False
    _, found = analyse_template(path)
    if found is None:
        print(f"  {scene}: ! поверхность не найдена")
        return False
    target, residual = align_designed(found, pad_outline(size_cm, image_size, **SCENES[scene]["pose"])[0])
    if residual > max_shape:
        print(f"  {scene}: ! форма отличается на {residual:.1%} — выпрямлять не буду")
        return False
    if residual > 0.004:
        rectify_template(Image.open(path), found, target).save(path)
    print(f"  {scene}: выпрямлен (было отличие {residual:.1%})")
    return True


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except AttributeError:
        pass
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--only", nargs="+", metavar="SCENE", choices=list(SCENES), help="только эти сцены")
    parser.add_argument("--model", default=load_product_settings(PRODUCT.env_prefix).openai.image_model)
    parser.add_argument("--size", default="1536x2048", help="WxH, по умолчанию 3:4 1536x2048")
    parser.add_argument("--quality", default="high", choices=["low", "medium", "high", "auto"])
    parser.add_argument("--attempts", type=int, default=3, help="сколько раз генерировать сцену, пока форма не сойдётся")
    parser.add_argument("--guides-only", action="store_true", help="только нарисовать планы сцен, без OpenAI")
    parser.add_argument("--rectify-only", action="store_true", help="только выпрямить готовые каркасы, без OpenAI")
    parser.add_argument("--max-shape", type=float, default=0.08, help="допустимое отличие формы до выпрямления")
    args = parser.parse_args()
    guides_dir = load_app_settings().product_data_dir(PRODUCT.name) / "guides"

    scenes = args.only or list(SCENES)
    size_cm = tuple(PRODUCT.config["size_cm"])
    image_size = tuple(int(v) for v in args.size.split("x"))
    if args.guides_only:
        guides_dir.mkdir(parents=True, exist_ok=True)
        for scene in scenes:
            if SCENES[scene]["pose"]:
                (guides_dir / f"{scene}.png").write_bytes(guide_image(SCENES[scene]["pose"], size_cm, image_size)[0])
        print(f"Планы сцен: {guides_dir}")
        return 0

    if args.rectify_only:
        bad = [s for s in scenes if SCENES[s]["pose"] and not rectify(s, size_cm, image_size, args.max_shape)]
        return 1 if bad else 0

    client = _client()
    if not args.only:
        shutil.rmtree(TEMPLATES_DIR, ignore_errors=True)
    TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Модель {args.model}, {args.size}, quality={args.quality}, сцен: {len(scenes)} → {TEMPLATES_DIR}", flush=True)

    failed: list[str] = []
    for n, scene in enumerate(scenes, 1):
        spec, target = SCENES[scene], TEMPLATES_DIR / f"{scene}.png"
        guide, designed = guide_image(spec["pose"], size_cm, image_size) if spec["pose"] else (None, None)
        for attempt in range(1, args.attempts + 1):
            print(f"[{n}/{len(scenes)}] {scene}, попытка {attempt} …", flush=True)
            started = time.monotonic()

            def call(guide=guide, spec=spec):
                if guide is None:
                    return client.images.generate(model=args.model, prompt=f"{spec['prompt']} {STYLE}",
                                                  size=args.size, quality=args.quality)
                return client.images.edit(model=args.model, image=("layout.png", guide, "image/png"),
                                          prompt=f"{KEEP_PAD}{spec['prompt']} {STYLE}",
                                          size=args.size, quality=args.quality)

            try:
                data = _with_retries(call, scene).data[0].b64_json
                if not data:
                    raise RuntimeError("Ответ без b64_json")
                target.write_bytes(base64.b64decode(data))
            except Exception as exc:  # noqa: BLE001 — одна неудачная сцена не роняет остальные
                print(f"  ОШИБКА {scene}: {exc.__class__.__name__}: {exc}", flush=True)
                break
            if designed is not None:
                rectify(scene, size_cm, image_size, args.max_shape)
            report = check_template(scene, target, designed)
            print(f"  {time.monotonic() - started:.0f} с: {report}", flush=True)
            if not report.startswith("!"):
                break
        else:
            failed.append(scene)
            continue
        if not target.is_file() or check_template(scene, target, designed).startswith("!"):
            failed.append(scene)

    print(f"Готово: {TEMPLATES_DIR}")
    if failed:
        print(f"Не сошлись: {', '.join(failed)} — перезапустите с --only {' '.join(failed)}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

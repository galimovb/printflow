"""Геометрия каркасов: где на фото корпус сумки, где зона печати, как лечь принту с перспективой."""
from __future__ import annotations

from printflow.services.gallery.geometry import homography

import io
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

from printflow.products.shopper.infrastructure.gallery.theme import CREAM

CHROMA = np.array([0x90, 0xEE, 0x90], dtype=np.float32)


def load_print(path: Path | io.BytesIO) -> Image.Image:
    """RGBA-принт, обрезанный по содержимому. Фон #90EE90 без альфы вырезается."""
    img = Image.open(path).convert("RGBA")
    arr = np.asarray(img, dtype=np.float32)
    if arr[..., 3].min() > 250:  # альфы нет — пробуем хромакей
        dist = np.linalg.norm(arr[..., :3] - CHROMA, axis=-1)
        arr[..., 3] = np.clip((dist - 40.0) / 40.0, 0.0, 1.0) * 255.0
        img = Image.fromarray(arr.astype(np.uint8), "RGBA")
    bbox = img.getchannel("A").point(lambda a: 255 if a > 8 else 0).getbbox()
    return img.crop(bbox) if bbox else img




def _apply_h(h: np.ndarray, pts: list[tuple[float, float]]) -> list[tuple[float, float]]:
    out = []
    for x, y in pts:
        u, v, w = h @ np.array([x, y, 1.0])
        out.append((u / w, v / w))
    return out


def place_print(template: Image.Image, print_img: Image.Image, zone: list, aspect: float,
                shade: float = 0.5, opacity: float = 0.97) -> Image.Image:
    """Кладёт принт в зону (4 угла) с сохранением пропорций, центрируя его в зоне."""
    tpl = template.convert("RGB")
    pw, ph = print_img.size
    # зона в «плоских» координатах: ширина aspect*1000, высота 1000
    zw, zh = aspect * 1000.0, 1000.0
    s = min(zw / pw, zh / ph)
    x0, y0 = (zw - pw * s) / 2, (zh - ph * s) / 2
    placed = [(x0, y0), (x0 + pw * s, y0), (x0 + pw * s, y0 + ph * s), (x0, y0 + ph * s)]
    quad = [tuple(map(float, p)) for p in zone]
    corners_tpl = _apply_h(homography([(0, 0), (zw, 0), (zw, zh), (0, zh)], quad), placed)
    h = homography(corners_tpl, [(0, 0), (pw, 0), (pw, ph), (0, ph)])  # шаблон → принт
    coeffs = tuple((h / h[2, 2]).flatten()[:8])
    warped = print_img.transform(tpl.size, Image.Transform.PERSPECTIVE, coeffs, Image.Resampling.BICUBIC)

    w = np.asarray(warped, dtype=np.float32)
    a = w[..., 3:4] / 255.0 * opacity
    base = np.asarray(tpl, dtype=np.float32)
    if shade > 0:
        gray = np.asarray(tpl.convert("L"), dtype=np.float32)
        mask = a[..., 0] > 0.5
        med = float(np.median(gray[mask])) if mask.any() else 128.0
        k = 1.0 + shade * (gray / max(med, 1.0) - 1.0)
        lo, hi = (0.55, 1.15) if shade >= 0.5 else (0.72, 1.08)
        w[..., :3] *= np.clip(k, lo, hi)[..., None]
    out = base * (1 - a) + np.clip(w[..., :3], 0, 255) * a
    return Image.fromarray(out.astype(np.uint8), "RGB")


def warm_background(img: Image.Image, bag_mask: np.ndarray) -> Image.Image:
    """Серый студийный фон → тёплый кремовый, как на остальных слайдах; тени сохраняются."""
    arr = np.asarray(img.convert("RGB"), dtype=np.float32)
    border = np.concatenate([arr[:20].reshape(-1, 3), arr[-20:].reshape(-1, 3),
                             arr[:, :20].reshape(-1, 3), arr[:, -20:].reshape(-1, 3)])
    factor = np.array(CREAM, dtype=np.float32) / np.maximum(np.median(border, axis=0), 1.0)
    keep = ndimage.gaussian_filter(ndimage.binary_dilation(bag_mask, iterations=3).astype(np.float32), 2)[..., None]
    out = arr * keep + np.clip(arr * factor, 0, 255) * (1 - keep)
    return Image.fromarray(out.astype(np.uint8), "RGB")


def template_path(scene: str, color: str, templates_dir: Path) -> Path:
    return templates_dir / (f"{color}.png" if scene == "packshot" else f"{scene}_{color}.png")


@lru_cache(maxsize=32)
def _detect_body_cached(path: str, mtime: float) -> tuple[tuple[float, float], ...] | None:
    scale = 2
    dark = np.asarray(Image.open(path).convert("L"), dtype=np.int16)[::scale, ::scale] < 75
    body = ndimage.binary_opening(dark, structure=np.ones((61, 61)))  # срезает ручки
    labels, count = ndimage.label(body)
    if not count:
        return None
    body = labels == (np.argmax(ndimage.sum(body, labels, range(1, count + 1))) + 1)
    body = ndimage.binary_dilation(body, iterations=20) & dark  # возвращает срезанные углы
    ys, xs = np.nonzero(body)
    pts = np.stack([xs, ys], axis=1) * scale
    s, d = pts.sum(axis=1), pts[:, 0] - pts[:, 1]
    corners = (pts[s.argmin()], pts[d.argmax()], pts[s.argmax()], pts[d.argmin()])  # TL, TR, BR, BL
    return tuple((float(x), float(y)) for x, y in corners)


@lru_cache(maxsize=4)
def _bag_mask_cached(path: str, mtime: float) -> np.ndarray:
    return np.asarray(Image.open(path).convert("L")) < 90


def bag_mask(scene: str, templates_dir: Path) -> np.ndarray | None:
    """Маска сумки с ручками (по чёрному каркасу) — чтобы перекрасить фон, не задев ткань."""
    path = template_path(scene, "black", templates_dir)
    return _bag_mask_cached(str(path), path.stat().st_mtime) if path.is_file() else None


def detect_body(scene: str, templates_dir: Path) -> list[tuple[float, float]] | None:
    """4 угла корпуса сумки без ручек. Ищется по чёрному каркасу: тёмная ткань надёжно
    отделяется от фона, а белый каркас той же сцены совпадает с ним по геометрии."""
    path = template_path(scene, "black", templates_dir)
    if not path.is_file():
        return None
    found = _detect_body_cached(str(path), path.stat().st_mtime)
    return list(found) if found else None


def print_zone(body: list, cfg: dict, print_cm: tuple[float, float]) -> list[tuple[float, float]]:
    """Зона печати внутри корпуса по реальным размерам, с учётом перспективы."""
    bag_w, bag_h = cfg["bag_cm"]
    pw, ph = print_cm
    x0, y0 = (bag_w - pw) / 2 / bag_w, cfg["print_top_cm"] / bag_h
    unit = [(x0, y0), (1 - x0, y0), (1 - x0, y0 + ph / bag_h), (x0, y0 + ph / bag_h)]
    h = homography([(0, 0), (1, 0), (1, 1), (0, 1)], [tuple(map(float, p)) for p in body])
    return _apply_h(h, unit)


def scene_geometry(scene: str, cfg: dict, print_cm, templates_dir: Path):
    """(корпус, зона печати): body из product.json, если задан, иначе автоопределение."""
    body = (cfg["scenes"].get(scene) or {}).get("body") or detect_body(scene, templates_dir)
    if not body:
        return None, None
    return body, print_zone(body, cfg, print_cm)

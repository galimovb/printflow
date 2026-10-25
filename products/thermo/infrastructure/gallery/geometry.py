"""Self-contained thermo artwork loading and fabric compositing."""
import io
from pathlib import Path
import numpy as np
from PIL import Image
from printflow.services.gallery.geometry import homography

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


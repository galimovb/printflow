"""Геометрия каркасов коврика: где на фото поверхность, как лечь принту с перспективой.

Каркас — фото сцены, где верхняя поверхность коврика залита сплошным хромакеем #00FF00
(см. scripts/generate_blanks.py). Отсюда сразу:
  • маска поверхности — по зелёному, со скруглёнными углами и с вырезами там, где поверхность
    закрывают мышь или рука (их не надо размечать вручную);
  • 4 угла — прямые по краям маски, пересечённые в углах (скругление углов не сдвигает точки);
  • свет и тени — яркость зелёного канала, ими принт затеняется как настоящая ткань.
Углы можно задать и вручную: product.json → gallery.scenes.<сцена>.quad.
"""
from __future__ import annotations

from printflow.services.gallery.geometry import homography

from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage
from scipy.spatial import ConvexHull

Quad = list[tuple[float, float]]  # TL, TR, BR, BL


def green_alpha(rgb: np.ndarray) -> np.ndarray:
    """0…1: насколько пиксель — хромакей. Зелёный заметно ярче красного и синего при любом свете."""
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    dominance = g - np.maximum(r, b)
    return np.clip((dominance - 35.0) / 45.0, 0.0, 1.0) * (g > 60)


def surface_mask(alpha: np.ndarray) -> np.ndarray:
    """Самая крупная связная зелёная область без мелких бликов и крошек."""
    solid = ndimage.binary_opening(alpha > 0.5, structure=np.ones((5, 5)))
    labels, count = ndimage.label(solid)
    if not count:
        return solid
    sizes = ndimage.sum(solid, labels, range(1, count + 1))
    return labels == (int(np.argmax(sizes)) + 1)


def _fit_line(points: np.ndarray) -> tuple[np.ndarray, np.ndarray] | None:
    """Прямая (точка, направление) по точкам края; выбросы (край мыши/руки) отбрасываются."""
    for _ in range(4):
        if len(points) < 8:
            return None
        center = points.mean(axis=0)
        _, _, vt = np.linalg.svd(points - center, full_matrices=False)
        direction = vt[0]
        normal = np.array([-direction[1], direction[0]])
        residual = np.abs((points - center) @ normal)
        keep = residual <= max(1.5, 2.5 * float(np.median(residual)))
        if keep.all():
            break
        points = points[keep]
    return center, direction


def _intersect(a: tuple[np.ndarray, np.ndarray], b: tuple[np.ndarray, np.ndarray]) -> np.ndarray:
    (p, u), (q, v) = a, b
    m = np.array([u, -v]).T
    t = np.linalg.solve(m, q - p)
    return p + t[0] * u


def _cross(o: np.ndarray, a: np.ndarray, b: np.ndarray) -> float:
    return float((a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]))


def _hull_quad(points: np.ndarray) -> np.ndarray | None:
    """Четырёхугольник вокруг выпуклой оболочки: рёбра оболочки по одному «стягиваются» в точку
    пересечения соседних рёбер — каждый раз то, что добавляет меньше всего площади. Оболочка
    закрывает дыры от мыши и руки, поэтому углы находятся, даже если край частично закрыт."""
    poly = [points[i] for i in ConvexHull(points).vertices]
    while len(poly) > 4:
        n, best = len(poly), None
        for i in range(n):
            p0, p1, p2, p3 = poly[i - 1], poly[i], poly[(i + 1) % n], poly[(i + 2) % n]
            d1, d2 = p1 - p0, p3 - p2
            denom = d1[0] * d2[1] - d1[1] * d2[0]
            if abs(denom) < 1e-9:
                continue
            s = ((p2[0] - p0[0]) * d2[1] - (p2[1] - p0[1]) * d2[0]) / denom
            if s < 1.0:  # пересечение должно быть снаружи, за p1
                continue
            x = p0 + s * d1
            added = abs(_cross(p1, x, p2)) / 2
            if best is None or added < best[0]:
                best = (added, i, x)
        if best is None:
            return None
        _, i, x = best
        j = (i + 1) % n
        poly = [x if k == i else p for k, p in enumerate(poly) if k != j]
    return np.array(poly)


def _order(quad: np.ndarray) -> list[np.ndarray]:
    """TL, TR, BR, BL: по кругу (в координатах картинки — по часовой), начиная с верхнего левого."""
    center = quad.mean(axis=0)
    ring = sorted(quad, key=lambda p: np.arctan2(p[1] - center[1], p[0] - center[0]))
    start = int(np.argmin([p[0] + p[1] for p in ring]))
    return ring[start:] + ring[:start]


def fit_quad(mask: np.ndarray) -> Quad | None:
    """4 угла поверхности (TL, TR, BR, BL) с учётом перспективы."""
    edge = mask & ~ndimage.binary_erosion(mask)
    ey, ex = np.nonzero(edge)
    if len(ex) < 100 or mask.sum() < 500:
        return None
    border = np.stack([ex, ey], axis=1).astype(np.float64)
    hull = _hull_quad(border)
    if hull is None:
        return None
    init = _order(hull)
    # уточнение: прямая по каждому краю без скруглённых углов, углы — пересечения прямых
    lines = []
    for i in range(4):
        a, b = init[i], init[(i + 1) % 4]
        length = float(np.linalg.norm(b - a))
        u = (b - a) / max(length, 1e-9)
        n = np.array([-u[1], u[0]])
        rel = border - a
        t, dist = rel @ u / max(length, 1e-9), np.abs(rel @ n)
        lines.append(_fit_line(border[(t > 0.12) & (t < 0.88) & (dist < max(6.0, 0.035 * length))]))
    rough = [(float(x), float(y)) for x, y in init]
    if any(line is None for line in lines):
        return rough
    try:
        corners = [_intersect(lines[i - 1], lines[i]) for i in range(4)]
    except np.linalg.LinAlgError:
        return rough
    diag = float(np.linalg.norm(init[2] - init[0]))
    if max(float(np.linalg.norm(c - r)) for c, r in zip(corners, init)) > 0.05 * diag:
        return rough  # край почти весь закрыт — прямая ненадёжна, оставляем оболочку
    return [(float(x), float(y)) for x, y in corners]


def pad_outline(size_cm: tuple[float, float], image_size: tuple[int, int], *, tilt: float, yaw: float,
                center: tuple[float, float], width: float, radius_cm: float = 1.2,
                inset_cm: float = 0.0) -> tuple[Quad, list[tuple[float, float]]]:
    """Коврик ровно size_cm в перспективе: (4 угла без скругления, контур со скруглёнными углами).

    Прямоугольник лежит в плоскости, повёрнут на yaw (градусы, вокруг нормали) и наклонён к камере на
    tilt (0 — вид строго сверху), проецируется камерой с фокусом 1.3·ширины кадра; затем вписывается
    в кадр: center — центр (доли кадра), width — ширина проекции (доля ширины кадра).
    inset_cm — контур, сдвинутый внутрь (поверхность внутри окантовки)."""
    w, h = size_cm[0] / 2 - inset_cm, size_cm[1] / 2 - inset_cm
    r = max(radius_cm - inset_cm, 0.01)

    def rounded(n: int = 10) -> list[tuple[float, float]]:
        pts = []
        for cx, cy, start in ((w - r, -h + r, -90), (w - r, h - r, 0), (-w + r, h - r, 90), (-w + r, -h + r, 180)):
            for k in range(n + 1):
                ang = np.radians(start + 90 * k / n)
                pts.append((cx + r * np.cos(ang), cy + r * np.sin(ang)))
        return pts

    corners = [(-w, -h), (w, -h), (w, h), (-w, h)]  # TL, TR, BR, BL (y вниз — к зрителю)
    cy_, sy = np.cos(np.radians(yaw)), np.sin(np.radians(yaw))
    ct, st = np.cos(np.radians(tilt)), np.sin(np.radians(tilt))
    f = 1.3 * image_size[0]
    distance = 3.2 * size_cm[0]

    def project(points):
        out = []
        for x, y in points:
            x, y = x * cy_ - y * sy, x * sy + y * cy_
            y3, z3 = y * ct, distance - y * st  # дальний край (y<0) дальше от камеры — уже
            out.append((f * x / z3, f * y3 / z3))
        return np.array(out)

    q, outline = project(corners), project(rounded())
    scale = width * image_size[0] / (q[:, 0].max() - q[:, 0].min())
    shift = np.array([center[0] * image_size[0], center[1] * image_size[1]]) - q.mean(axis=0) * scale
    q, outline = q * scale + shift, outline * scale + shift
    return [tuple(map(float, p)) for p in q], [tuple(map(float, p)) for p in outline]


def align_designed(found: Quad, designed: Quad) -> tuple[Quad, float]:
    """Заданная форма, совмещённая с найденной (сдвиг, поворот, масштаб — без искажения), и остаток:
    насколько форма найденного коврика отличается от заданной, в долях диагонали."""
    a, b = np.array(found, dtype=np.float64), np.array(designed, dtype=np.float64)
    za = (a[:, 0] - a[:, 0].mean()) + 1j * (a[:, 1] - a[:, 1].mean())
    zb = (b[:, 0] - b[:, 0].mean()) + 1j * (b[:, 1] - b[:, 1].mean())
    s = (np.conj(zb) @ za) / (np.conj(zb) @ zb)
    z = s * zb + (a[:, 0].mean() + 1j * a[:, 1].mean())
    aligned = [(float(p.real), float(p.imag)) for p in z]
    residual = float(np.abs(za - s * zb).max() / np.linalg.norm(a[2] - a[0]))
    return aligned, residual


def rectify_template(img: Image.Image, found: Quad, target: Quad) -> Image.Image:
    """Слегка трансформирует всё фото так, чтобы коврик стал ровно target; края дотягиваются масштабом,
    чтобы не осталось пустых полос."""
    w, h = img.size
    hm = homography([tuple(map(float, p)) for p in target], [tuple(map(float, p)) for p in found])  # новое → старое
    corners = np.array([[0, 0, 1], [w, 0, 1], [w, h, 1], [0, h, 1]], dtype=np.float64)
    inv = np.linalg.inv(hm)
    mapped = np.array([(inv @ c)[:2] / (inv @ c)[2] for c in corners])  # где оказались края старого кадра
    cx, cy = w / 2, h / 2
    need = max(
        cx / max(cx - max(mapped[0, 0], mapped[3, 0], 0), 1), cx / max(min(mapped[1, 0], mapped[2, 0], w) - cx, 1),
        cy / max(cy - max(mapped[0, 1], mapped[1, 1], 0), 1), cy / max(min(mapped[2, 1], mapped[3, 1], h) - cy, 1),
    )
    zoom = np.array([[1 / need, 0, cx * (1 - 1 / need)], [0, 1 / need, cy * (1 - 1 / need)], [0, 0, 1]])
    total = hm @ zoom  # кадр → (обратный зум) → новое → старое
    coeffs = tuple((total / total[2, 2]).flatten()[:8])
    return img.convert("RGB").transform((w, h), Image.Transform.PERSPECTIVE, coeffs, Image.Resampling.BICUBIC)


def quad_deviation(found: Quad, designed: Quad) -> float:
    """Насколько найденные углы отошли от заданных — в долях диагонали коврика."""
    a, b = np.array(found), np.array(designed)
    return float(np.linalg.norm(a - b, axis=1).max() / np.linalg.norm(b[2] - b[0]))


def quad_problem(quad: Quad, mask_area: float, size: tuple[int, int], designed: Quad | None = None,
                 tolerance: float = 0.015) -> str | None:
    """Почему углы подозрительны (для проверки каркасов): за кадром, коврик вертикально, углы не сходятся."""
    q = np.array(quad, dtype=np.float64)
    w, h = size
    if (q[:, 0] < -0.02 * w).any() or (q[:, 0] > 1.02 * w).any() or (q[:, 1] < -0.02 * h).any()             or (q[:, 1] > 1.02 * h).any():
        return "угол коврика за кадром — коврик должен целиком помещаться в кадр"
    area = abs(sum(_cross(np.zeros(2), q[i], q[(i + 1) % 4]) for i in range(4))) / 2
    if mask_area / max(area, 1.0) < 0.6:
        return "поверхность сильно закрыта или углы не сходятся"
    horizontal = np.linalg.norm(q[1] - q[0]) + np.linalg.norm(q[2] - q[3])
    vertical = np.linalg.norm(q[3] - q[0]) + np.linalg.norm(q[2] - q[1])
    if vertical > horizontal * 1.05:
        return "коврик стоит вертикально — нужен горизонтальный (принт сплющится)"
    if designed is not None and (dev := align_designed(quad, designed)[1]) > tolerance:
        return f"форма коврика отличается от заданных пропорций на {dev:.1%} диагонали — пропорции исказятся"
    return None




@lru_cache(maxsize=16)
def _analyse(path: str, mtime: float) -> tuple[np.ndarray, Quad | None]:
    rgb = np.asarray(Image.open(path).convert("RGB"), dtype=np.float32)
    alpha = green_alpha(rgb)
    mask = surface_mask(alpha)
    # мягкий край: альфа хромакея, но только у основной поверхности (не у зелёных бликов вокруг)
    soft = alpha * ndimage.binary_dilation(mask, iterations=3)
    return soft.astype(np.float32), fit_quad(mask)


def analyse_template(path: Path) -> tuple[np.ndarray, Quad | None]:
    """(альфа поверхности 0…1, 4 угла) для каркаса; кэшируется до изменения файла."""
    return _analyse(str(path), path.stat().st_mtime)


def place_on_surface(template: Image.Image, print_img: Image.Image, quad: Quad, alpha: np.ndarray,
                     shade: float = 0.55) -> Image.Image:
    """Принт во весь коврик: перспектива по 4 углам, обрезка по маске, свет и тени с каркаса."""
    tpl = template.convert("RGB")
    art = print_img.convert("RGB")
    pw, ph = art.size
    h = homography([tuple(map(float, p)) for p in quad], [(0, 0), (pw, 0), (pw, ph), (0, ph)])  # каркас → принт
    coeffs = tuple((h / h[2, 2]).flatten()[:8])
    warped = np.asarray(art.transform(tpl.size, Image.Transform.PERSPECTIVE, coeffs, Image.Resampling.BICUBIC),
                        dtype=np.float32)

    base = np.asarray(tpl, dtype=np.float32).copy()
    a = alpha[..., None]
    green = base[..., 1]
    inside = alpha > 0.6
    med = float(np.median(green[inside])) if inside.any() else 200.0
    k = np.clip(1.0 + shade * (green / max(med, 1.0) - 1.0), 0.55, 1.12)[..., None]
    # зелёные отблески хромакея рядом с ковриком (край, бок мыши, рука) → нейтральный цвет
    near = ndimage.maximum_filter(alpha > 0.01, size=max(15, int(0.04 * max(alpha.shape))))
    neutral = np.maximum(base[..., 0], base[..., 2])
    base[..., 1] = np.where(near & (green > neutral), neutral, green)
    out = base * (1 - a) + np.clip(warped * k, 0, 255) * a
    return Image.fromarray(out.astype(np.uint8), "RGB")


def template_path(scene: str, templates_dir: Path) -> Path:
    return templates_dir / f"{scene}.png"

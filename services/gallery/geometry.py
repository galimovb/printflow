"""Общая математика перспективного размещения принта."""
from __future__ import annotations

from typing import Sequence

import numpy as np


def homography(src: Sequence[tuple[float, float]], dst: Sequence[tuple[float, float]]) -> np.ndarray:
    """Матрица 3×3, переводящая четыре исходные точки в четыре целевые."""
    rows, rhs = [], []
    for (x, y), (u, v) in zip(src, dst):
        rows.append([x, y, 1, 0, 0, 0, -u * x, -u * y])
        rows.append([0, 0, 0, x, y, 1, -v * x, -v * y])
        rhs += [u, v]
    h = np.linalg.solve(np.array(rows, dtype=np.float64), np.array(rhs, dtype=np.float64))
    return np.append(h, 1.0).reshape(3, 3)

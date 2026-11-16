"""Notes: local prompts on parts of the sketch (data and geometry, no Qt).

A note is a short heading in space, always vertical (Y up). By default it turns around Y with the camera; once
rotated (R) it stays fixed. With leader lines it attaches to drawn lines or points; the lines run at right angles:
first horizontally at the height of the note to above the target point, then vertically to it. Behind the heading
sits a note board with text and images (note_board.py).
"""
import math

import numpy as np
from .i18n import tr

SIZES = {"s": 0.22, "m": 0.35, "l": 0.55, "xl": 0.9}  # line height of the heading in world units
SIZE_NAMES = {"s": tr("Klein"), "m": tr("Mittel"), "l": tr("Groß"), "xl": tr("Sehr groß")}
RELINK_TOL = 0.02  # Line split/replaced: re-link when a line lies this close to the old anchor point
UP = np.array([0.0, 1.0, 0.0])


def _arclength(points):
    seg = np.linalg.norm(np.diff(points, axis=0), axis=1)
    return seg, float(seg.sum())


def curve_point(points, t):
    """Point at fraction t (0..1) of the arc length of a polyline."""
    points = np.asarray(points, float)
    seg, total = _arclength(points)
    if total <= 1e-12:
        return points[0].copy()
    target = min(max(t, 0.0), 1.0) * total
    acc = np.concatenate([[0.0], np.cumsum(seg)])
    i = int(np.clip(np.searchsorted(acc, target, side="right") - 1, 0, len(seg) - 1))
    f = (target - acc[i]) / max(seg[i], 1e-18)
    return points[i] + (points[i + 1] - points[i]) * min(max(f, 0.0), 1.0)


def curve_param(points, point):
    """(distance, fraction of arc length) of the point of the polyline nearest to point."""
    points = np.asarray(points, float)
    a, b = points[:-1], points[1:]
    ab = b - a
    ll = np.einsum("ij,ij->i", ab, ab)
    t = np.clip(np.einsum("ij,ij->i", point - a, ab) / np.maximum(ll, 1e-18), 0, 1)
    d = np.linalg.norm(a + ab * t[:, None] - point, axis=1)
    i = int(np.argmin(d))
    seg, total = _arclength(points)
    along = float(seg[:i].sum() + seg[i] * t[i])
    return float(d[i]), (along / total if total > 1e-12 else 0.0)


def relink(curves, point, tol=RELINK_TOL):
    """(line, fraction) of the nearest line within tol of point - e.g. after the line was split."""
    best = (None, 0.0, tol)
    for curve in curves:
        if len(curve.points) < 2:
            continue
        pts = curve.points
        if np.any(pts.min(axis=0) > point + tol) or np.any(pts.max(axis=0) < point - tol):
            continue
        d, t = curve_param(pts, point)
        if d <= best[2]:
            best = (curve, t, d)
    return best[0], best[1]


def right_vector(note, cam_right):
    """Horizontal reading direction of the note: with the camera (yaw None) or fixed, rotated."""
    if note.yaw is not None:
        return np.array([math.cos(note.yaw), 0.0, -math.sin(note.yaw)])
    r = np.array([cam_right[0], 0.0, cam_right[2]], float)
    n = float(np.linalg.norm(r))
    return r / n if n > 1e-6 else np.array([1.0, 0.0, 0.0])


def yaw_of(r):
    return math.atan2(-float(r[2]), float(r[0]))


def leader(start_left, start_right, anchor_point):
    """Right-angled leader line: from the nearer lower corner of the note horizontally (at its height) to above or
    below the target point, then vertically to it. -> (start, bend, target)."""
    a = np.asarray(anchor_point, float)
    flat = lambda p: np.array([p[0] - a[0], p[2] - a[2]])
    start = min((start_left, start_right), key=lambda p: float(np.linalg.norm(flat(p))))
    knee = np.array([a[0], start[1], a[2]])
    return start, knee, a

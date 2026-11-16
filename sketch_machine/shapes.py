"""Shape recognition for the pen: circle, rectangle, arc – in 2D coordinates of a plane
(x to the right, y up, as the plane appears on screen).

recognize() returns a shape as a dict or None (then a straight line is made of it as before).
adjust() fits the shape to the cursor while the key is held after recognition,
polylines() creates the lines: circle and arc one each, the rectangle four separate ones.
Ellipses are deliberately not recognized: hand-drawn circles are almost always a bit oval.
"""
import math

import numpy as np
from .i18n import tr

CLOSED_GAP = 0.2  # start and end closer than this (share of the size): closed shape
CIRCLE_TOL = 0.14  # circle: mean deviation from the radius (share of the radius)
CIRCLE_MIN_ASPECT = 0.55  # even flatter shapes do not become a circle
CORNER_DEG = 60  # if the stroke bends more sharply within CORNER_SPAN of its length, it has a corner: no circle
CORNER_SPAN = 0.06
RECT_TOL = 0.2  # rectangle: mean deviation from the outline (share of half the size)
LINE_TOL = 0.045  # open stroke with less bulge (share of the chord): straight line, no arc (finer arcs stay arcs)
ARC_TOL = 0.08  # arc: mean deviation from the circle (share of the radius)
CORNER_TOL = 0.3  # rectangle: every corner needs a stroke point this close (share of the shorter side)
SEGMENTS = 128  # points for a full circle
AXIS_SNAP_DEG = 5  # rectangle: this close to a plane axis the orientation snaps to the axis


def _dedupe(pts):
    keep = np.concatenate([[True], np.linalg.norm(np.diff(pts, axis=0), axis=1) > 1e-9])
    return pts[keep]


def recognize(pts, angles=()):
    """angles: additional orientations (radians) for rectangles, e.g. the axes of the drawing plane
    as they appear in the 2D coordinates – a rectangle on the ground is rotated in perspective."""
    pts = _dedupe(np.asarray(pts, float))
    if len(pts) < 5:
        return None
    lo, hi = pts.min(axis=0), pts.max(axis=0)
    size = float(np.linalg.norm(hi - lo))
    if size < 1e-9:
        return None
    if np.linalg.norm(pts[0] - pts[-1]) < CLOSED_GAP * size:
        return _closed(pts, angles)
    return _arc(pts)


# --- closed: circle, rectangle ---
def _rot(angle):
    return np.array([[math.cos(angle), -math.sin(angle)], [math.sin(angle), math.cos(angle)]])


def _stroke_angle(pts):
    """Dominant direction of the stroke pieces modulo 90° (for rectangles of any position)."""
    d = np.diff(pts, axis=0)
    w = np.linalg.norm(d, axis=1)
    theta = np.arctan2(d[:, 1], d[:, 0])
    return 0.25 * math.atan2(float((w * np.sin(4 * theta)).sum()), float((w * np.cos(4 * theta)).sum()))


def _closed(pts, angles=()):
    lo, hi = pts.min(axis=0), pts.max(axis=0)
    half = float((hi - lo).sum()) / 4  # mean half extent as scale
    if half < 1e-9:
        return None
    found = []
    circle = _fit_circle(pts)
    w, h = hi - lo
    turns = _turns(pts)
    if circle is not None and min(w, h) / max(w, h) > CIRCLE_MIN_ASPECT and turns.max() < CORNER_DEG:
        # ovals count as a circle, shapes with corners (e.g. triangles) do not
        c, r = circle
        err = _rms(np.linalg.norm(pts - c, axis=1) - r) / r
        if err < CIRCLE_TOL:
            found.append((err, {"kind": "circle", "center": c, "radius": r}))
    # a rectangle has four corners (at least three visible: the one at the stroke start can be split), an oval two
    if _corners(turns) >= 3:
        # orientations: screen, axes of the drawing plane, direction of the stroke itself. A plane
        # axis wins if it fits almost as well (straight edges along the grid are usually meant).
        best = None
        # screen orientation only without plane axes (otherwise the camera would determine how the rectangle lies – artist:
        # the perspective must have no influence)
        own = _stroke_angle(pts)
        near = [a for a in angles if abs((own - a + math.pi / 4) % (math.pi / 2) - math.pi / 4) < math.radians(AXIS_SNAP_DEG)]
        # if the stroke lies within AXIS_SNAP_DEG of a plane axis, the axis applies (snapped)
        cands = (near[:1] + [own]) if near else ([*angles, own] if angles else [0.0, own])
        for k, angle in enumerate(cands):
            local = pts @ _rot(-angle).T
            rect = _fit_rect(local, local.min(axis=0), local.max(axis=0))
            if rect is None:
                continue
            err = rect[0] / half * ((0.5 if k == 0 else 1.0) if near else (0.8 if k < len(angles) else 1.0))
            if best is None or err < best[0]:
                rect[1]["angle"] = angle
                best = (err, rect[1])
        if best is not None and best[0] < RECT_TOL:
            found.append(best)
    return min(found, key=lambda f: f[0])[1] if found else None


def _fit_rect(pts, lo, hi):
    """Axis-parallel rectangle (x/y = screen directions in the plane): deviation + shape."""
    w, h = hi - lo
    if min(w, h) < 1e-9:
        return None
    # balance sides instead of a bounding box: every stroke point belongs to the nearest side, the side lies at the median
    # of its points – strokes pulled past the corner otherwise made large rectangles too large (harbor test 09.11.)
    lo, hi = lo.astype(float).copy(), hi.astype(float).copy()
    for _ in range(2):
        dist = np.stack([np.abs(pts[:, 0] - lo[0]), np.abs(pts[:, 0] - hi[0]),
                         np.abs(pts[:, 1] - lo[1]), np.abs(pts[:, 1] - hi[1])], axis=1)
        side = np.argmin(dist, axis=1)
        for s_i, (axis, ref) in enumerate(((0, lo), (0, hi), (1, lo), (1, hi))):
            mine = pts[side == s_i, axis]
            if len(mine) >= 3:
                ref[axis] = float(np.median(mine))
    w, h = hi - lo
    if min(w, h) < 1e-9:
        return None
    corners = np.array([[lo[0], lo[1]], [hi[0], lo[1]], [hi[0], hi[1]], [lo[0], hi[1]]])
    for corner in corners:  # all four corners must be drawn (distinguishes it from the circle)
        if np.min(np.linalg.norm(pts - corner, axis=1)) > CORNER_TOL * min(w, h):
            return None
    outline = np.vstack([corners, corners[:1]])
    return _rms(_dist_to_polyline(pts, outline)), {"kind": "rect", "p0": lo.copy(), "p1": hi.copy()}


def _ellipse_points(c, a, b, angle, n=SEGMENTS):
    t = np.linspace(0, 2 * math.pi, n + 1)
    local = np.stack([a * np.cos(t), b * np.sin(t)], axis=1)
    rot = np.array([[math.cos(angle), -math.sin(angle)], [math.sin(angle), math.cos(angle)]])
    return np.asarray(c) + local @ rot.T


# --- open: arc ---
def _arc(pts):
    s, e = pts[0], pts[-1]
    chord = e - s
    length = float(np.linalg.norm(chord))
    if length < 1e-9:
        return None
    n = np.array([-chord[1], chord[0]]) / length
    offsets = (pts - (s + e) / 2) @ n
    if np.max(np.abs(offsets)) < LINE_TOL * length:
        return None  # almost straight: a straight line as before
    circle = _fit_circle(pts)
    if circle is None:
        return None
    c, r = circle
    if _rms(np.linalg.norm(pts - c, axis=1) - r) > ARC_TOL * r:
        return None
    side = 1.0 if offsets.mean() >= 0 else -1.0
    sagitta = (c - (s + e) / 2) @ n + side * r  # apex of the arc above the chord
    return {"kind": "arc", "start": s.copy(), "end": e.copy(), "bulge": sagitta / length}


def _fit_circle(pts):
    x, y = pts.T
    a = np.column_stack([2 * x, 2 * y, np.ones_like(x)])
    try:
        (cx, cy, k), *_ = np.linalg.lstsq(a, x * x + y * y, rcond=None)
    except np.linalg.LinAlgError:
        return None
    r2 = k + cx * cx + cy * cy
    return (np.array([cx, cy]), math.sqrt(r2)) if r2 > 0 else None


def _arc_points(s, e, bulge):
    chord = e - s
    length = float(np.linalg.norm(chord))
    h = bulge * length
    if length < 1e-12 or abs(h) < 1e-6 * length:
        return np.array([s, e])
    n = np.array([-chord[1], chord[0]]) / length
    mid = (s + e) / 2
    r = (length * length / 4 + h * h) / (2 * abs(h))
    c = mid + n * (h - math.copysign(r, h))
    peak = mid + n * h
    ang = lambda p: math.atan2(p[1] - c[1], p[0] - c[0])
    a0, a1, ap = ang(s), ang(e), ang(peak)
    ccw = (a1 - a0) % (2 * math.pi)
    sweep = ccw if (ap - a0) % (2 * math.pi) <= ccw else ccw - 2 * math.pi  # over the apex
    steps = max(8, int(math.ceil(abs(sweep) / (2 * math.pi) * SEGMENTS)))
    t = a0 + sweep * np.linspace(0, 1, steps + 1)
    pts = c + r * np.stack([np.cos(t), np.sin(t)], axis=1)
    pts[0], pts[-1] = s, e
    return pts


# --- Helpers ---
def _turns(pts, samples=100):
    """Bend in degrees along the stroke: angle between two consecutive chords over each
    CORNER_SPAN of the stroke length (sampled evenly). Chords instead of single segments: jitter does not count."""
    arc = np.concatenate([[0], np.cumsum(np.linalg.norm(np.diff(pts, axis=0), axis=1))])
    t = np.linspace(0, arc[-1], samples)
    even = np.stack([np.interp(t, arc, pts[:, i]) for i in range(2)], axis=1)
    m = max(1, int(round(CORNER_SPAN * samples)))
    if len(even) <= 2 * m:
        return np.zeros(1)
    d1, d2 = even[m:-m] - even[:-2 * m], even[2 * m:] - even[m:-m]
    cos = np.einsum("ij,ij->i", d1, d2) / np.maximum(np.linalg.norm(d1, axis=1) * np.linalg.norm(d2, axis=1), 1e-18)
    return np.degrees(np.arccos(np.clip(cos, -1, 1)))


def _corners(turns):
    """Number of corners: contiguous places with a bend above CORNER_DEG."""
    sharp = np.concatenate([[False], turns >= CORNER_DEG, [False]])
    return int(np.count_nonzero(sharp[1:] & ~sharp[:-1]))


def _rms(values):
    return float(np.sqrt(np.mean(np.square(values))))


def _dist_to_polyline(pts, line):
    a, b = line[:-1], line[1:]
    ab = b - a
    t = np.clip(np.einsum("pij,ij->pi", pts[:, None, :] - a[None], ab) / np.maximum((ab * ab).sum(1), 1e-18), 0, 1)
    closest = a[None] + t[..., None] * ab[None]
    return np.min(np.linalg.norm(pts[:, None, :] - closest, axis=2), axis=1)


# --- after recognition: readjust with the cursor ---
def prepare(shape, cursor):
    """Remembers how the cursor lay relative to the shape at recognition (reference for readjusting)."""
    shape = dict(shape)
    if shape["kind"] == "rect":
        cursor = np.asarray(cursor, float) @ _rot(-shape.get("angle", 0.0)).T  # into the position of the rectangle
        corners = np.array([shape["p0"], [shape["p1"][0], shape["p0"][1]], shape["p1"], [shape["p0"][0], shape["p1"][1]]])
        k = int(np.argmin(np.linalg.norm(corners - cursor, axis=1)))
        shape["fixed"] = corners[(k + 2) % 4].copy()  # opposite corner stays put
    return shape


def adjust(shape, cursor, square=False, snap_deg=None):
    """Fit shape to the cursor. square: rectangle -> square. snap_deg: snap the arc end."""
    shape = dict(shape)
    kind = shape["kind"]
    if kind == "circle":
        shape["radius"] = max(float(np.linalg.norm(cursor - shape["center"])), 1e-9)
    elif kind == "rect":
        d = np.asarray(cursor, float) @ _rot(-shape.get("angle", 0.0)).T - shape["fixed"]
        if square:
            side = max(abs(d[0]), abs(d[1]))
            d = np.array([math.copysign(side, d[0]), math.copysign(side, d[1])])
        p, q = shape["fixed"], shape["fixed"] + d
        shape["p0"], shape["p1"] = np.minimum(p, q), np.maximum(p, q)
    elif kind == "arc":
        end = np.asarray(cursor, float)
        if snap_deg:
            v = end - shape["start"]
            length, step = float(np.linalg.norm(v)), math.radians(snap_deg)
            angle = round(math.atan2(v[0], v[1]) / step) * step  # 0° = up
            end = shape["start"] + length * np.array([math.sin(angle), math.cos(angle)])
        shape["end"] = end
    return shape


def polylines(shape):
    kind = shape["kind"]
    if kind == "circle":
        return [_ellipse_points(shape["center"], shape["radius"], shape["radius"], 0.0)]
    if kind == "rect":
        (x0, y0), (x1, y1) = shape["p0"], shape["p1"]
        c = np.array([[x0, y0], [x1, y0], [x1, y1], [x0, y1]]) @ _rot(shape.get("angle", 0.0)).T
        return [np.array([c[i], c[(i + 1) % 4]]) for i in range(4)]
    return [_arc_points(shape["start"], shape["end"], shape["bulge"])]


NAMES = {"circle": tr("Kreis"), "rect": tr("Rechteck"), "arc": tr("Bogen")}

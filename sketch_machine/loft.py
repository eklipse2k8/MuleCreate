"""Loft ("Skin" in Houdini): a curved drawing surface through several cross-sections.

The cross-sections are lines (or chains of lines) or outlines of drawing surfaces. They are
  1. put into an order (chain of the center points, starting at one end),
  2. resampled evenly and aligned with each other (same running direction, seam at the
     right place - otherwise the surface twists),
  3. connected across by smooth curves (blended circular arcs through the corresponding
     points of all cross-sections - points on a circle give exactly the circle). Two cross-sections
     give a straight connection, from three on the surface swings.
The result is a fine triangle net - for drawing on, equivalent to a NURBS surface,
for export it stays described by its cross-sections.
"""
import numpy as np

from .extrude import CORNER_DEG, is_closed

CLOSED_SAMPLES = 64  # points per closed cross-section
OPEN_SAMPLES = 48  # points per open cross-section
SPAN_SAMPLES = 12  # intermediate rows per section between two cross-sections


def order(sections):
    """Order of the cross-sections: start at one end of the chain (the center point that lies farthest
    from the others), then always go to the nearest one not yet used. Returns indices."""
    cents = np.array([np.asarray(s, float).mean(axis=0) for s in sections])
    if len(cents) < 3:
        return list(range(len(cents)))
    dist = np.linalg.norm(cents[:, None] - cents[None], axis=2)
    start = int(np.argmax(dist.sum(axis=1)))
    out, free = [start], set(range(len(cents))) - {start}
    while free:
        nxt = min(free, key=lambda j: dist[out[-1], j])
        out.append(nxt)
        free.remove(nxt)
    return out


def _resample(points, n, closed):
    return resample_at(points, n, closed)[0]


def resample_at(points, n, closed=False):
    """Resample evenly by arc length (corners stay sharp) -> (points, arc length per new point)."""
    pts = np.asarray(points, float)
    if closed:
        pts = np.vstack([pts, pts[:1]]) if np.linalg.norm(pts[0] - pts[-1]) > 1e-12 else pts
    arc = np.concatenate([[0], np.cumsum(np.linalg.norm(np.diff(pts, axis=0), axis=1))])
    if arc[-1] <= 0:
        return np.repeat(pts[:1], n, axis=0), np.zeros(n)
    t = np.linspace(0, arc[-1], n + 1 if closed else n)
    # keep real corners (kink from CORNER_DEG) sharp: the nearest sample point snaps onto the corner
    if len(pts) > 2:
        a, b = pts[1:-1] - pts[:-2], pts[2:] - pts[1:-1]
        cos = np.einsum("ij,ij->i", a, b) / np.maximum(np.linalg.norm(a, axis=1) * np.linalg.norm(b, axis=1), 1e-18)
        corners = arc[1:-1][cos < np.cos(np.radians(CORNER_DEG))]
        if closed and len(pts) > 3:  # seam: kink between the last and first piece
            a0, b0 = pts[-1] - pts[-2], pts[1] - pts[0]
            if a0 @ b0 / max(np.linalg.norm(a0) * np.linalg.norm(b0), 1e-18) < np.cos(np.radians(CORNER_DEG)):
                corners = np.append(corners, 0.0)
        for c in corners:
            k = int(np.argmin(np.abs(t - c)))
            if 0 < k < len(t) - 1 or (closed and k == 0):
                t[k] = c
    out = np.stack([np.interp(t, arc, pts[:, i]) for i in range(3)], axis=1)
    return (out[:-1], t[:-1]) if closed else (out, t)


def _normal(loop):
    """Surface normal of a closed run (Newell) - direction = winding sense."""
    a, b = loop, np.roll(loop, -1, axis=0)
    n = np.array([np.sum((a[:, 1] - b[:, 1]) * (a[:, 2] + b[:, 2])),
                  np.sum((a[:, 2] - b[:, 2]) * (a[:, 0] + b[:, 0])),
                  np.sum((a[:, 0] - b[:, 0]) * (a[:, 1] + b[:, 1]))])
    return n / max(np.linalg.norm(n), 1e-12)


def prepare(sections):
    """Cross-sections (in the desired order) -> (aligned cross-sections (K, M, 3), closed?)."""
    secs = [np.asarray(s, float) for s in sections if len(s) >= 2]
    closed = all(is_closed(s) for s in secs)
    n = CLOSED_SAMPLES if closed else OPEN_SAMPLES
    secs = [_resample(s[:-1] if closed and np.linalg.norm(s[0] - s[-1]) < 1e-9 else s, n, closed) for s in secs]
    cents = np.array([s.mean(axis=0) for s in secs])
    out = []
    for k, s in enumerate(secs):
        if closed:
            # same winding sense relative to the running direction of the surface
            tangent = cents[min(k + 1, len(secs) - 1)] - cents[max(k - 1, 0)]
            if np.linalg.norm(tangent) > 1e-9 and _normal(s) @ tangent < 0:
                s = s[::-1]
            if out:  # place the seam so that the points correspond best to the previous cross-section
                prev = out[-1]
                a = (prev - prev.mean(axis=0)) / max(np.linalg.norm(prev - prev.mean(axis=0), axis=1).mean(), 1e-12)
                b = (s - s.mean(axis=0)) / max(np.linalg.norm(s - s.mean(axis=0), axis=1).mean(), 1e-12)
                costs = [np.sum((a - np.roll(b, -shift, axis=0)) ** 2) for shift in range(len(b))]
                s = np.roll(s, -int(np.argmin(costs)), axis=0)
        elif out:
            prev = out[-1]
            same = np.linalg.norm(prev[0] - s[0]) + np.linalg.norm(prev[-1] - s[-1])
            flipped = np.linalg.norm(prev[0] - s[-1]) + np.linalg.norm(prev[-1] - s[0])
            if flipped < same:
                s = s[::-1]
        out.append(s)
    return np.array(out), closed


def _catmull_rom(points, samples, hard=None):
    """Smooth curves through point rows: points (K, M, 3) -> (R, M, 3), R = (K-1)*samples + 1 (see interp_rows)."""
    return interp_rows(points, np.arange(len(points)) * samples, hard)


def interp_rows(points, at, hard=None):
    """Smooth curves through point rows (one per column): point row k lies on grid row at[k] (ascending,
    at[0] = 0), each section has its own row count. -> (at[-1] + 1, M, 3)
    Circular arcs blended: the section p1 -> p2 passes from the arc through p0, p1, p2 into the arc through p1, p2, p3.
    If the points lie on a circle, the curve is exactly that circle (four circles give a round ring, three
    cross-sections a semicircle), if they lie on a straight line, exactly the line. At the end only the one arc counts; two
    rows: straight. Ring (first = last row, from four): all the way around, without a seam.
    hard (K, M): hardness per row and column (0 ... 1) - at a hard row only the own arc counts on each side
    (kink), in between it blends."""
    points = np.asarray(points, float)
    at = [int(x) for x in at]
    k = len(points)
    if all(b - a == 1 for a, b in zip(at, at[1:])):
        return points.copy()  # every grid row is a point row (curve surface: span 1) - the curves go exactly through
    if k == 2:
        t = np.linspace(0, 1, at[1] - at[0] + 1)[:, None, None]
        return points[0] * (1 - t) + points[1] * t
    ring = k >= 4 and np.allclose(points[0], points[-1])
    ext = np.concatenate([points[-2:-1], points, points[1:2]]) if ring else None
    rows = []
    for i in range(1, k):
        j = i - 1  # section from row j to j + 1
        p1, p2 = points[j], points[j + 1]
        p0 = ext[j] if ring else (points[j - 1] if j > 0 else None)
        p3 = ext[j + 3] if ring else (points[j + 2] if j + 2 < k else None)
        n = at[i] - at[i - 1]
        ss = np.linspace(0, 1, n + 1)[:-1] if i < k - 1 else np.linspace(0, 1, n + 1)
        w = ss[:, None, None]
        line = p1[None] * (1 - w) + p2[None] * w
        A0 = _arc_span(p0, p1, p2, ss, 1) if p0 is not None else None  # arc through p0, p1, p2: piece p1 -> p2
        B0 = _arc_span(p1, p2, p3, ss, 0) if p3 is not None else None  # arc through p1, p2, p3: piece p1 -> p2
        A = A0 if A0 is not None else (B0 if B0 is not None else line)
        B = B0 if B0 is not None else A
        if hard is not None and not ring:
            # at a hard row only what lies on this side counts: the arc reaching across it is
            # replaced by the arc without it - if a third point is missing there, the straight line
            hs = np.asarray(hard[j], float)[None, :, None] if j > 0 else 0.0
            he = np.asarray(hard[j + 1], float)[None, :, None] if j + 1 < k - 1 else 0.0
            fwd = (B0 if B0 is not None else line) * (1 - he) + line * he  # forward, without p0
            back = (A0 if A0 is not None else line) * (1 - hs) + line * hs  # backward, without p3
            A, B = A * (1 - hs) + fwd * hs, B * (1 - he) + back * he
        rows.extend(A * (1 - w) + B * w)
    return np.array(rows)


def _arc_span(a, b, c, ss, which):
    """Circular arc through a, b, c (per column, (M, 3)); the piece a -> b (which 0) or b -> c (which 1) at the
    fractions ss (even in angle). Almost on a straight line: the parabola through the three (centripetal) - it passes
    continuously into the line. -> (len(ss), M, 3)"""
    u, v = b - a, c - b
    nrm = np.cross(u, v)
    lu, lv = np.linalg.norm(u, axis=1), np.linalg.norm(v, axis=1)
    sin = np.linalg.norm(nrm, axis=1) / np.maximum(lu * lv, 1e-30)
    ss = np.asarray(ss, float)[:, None, None]
    # parabola (centripetal) as a fallback and for almost straight places
    ta, tb = np.maximum(lu, 1e-12) ** 0.5, np.maximum(lv, 1e-12) ** 0.5
    t0, t1, t2 = np.zeros_like(ta), ta, ta + tb
    lo_, hi_ = (t0, t1) if which == 0 else (t1, t2)
    t = lo_[None, :, None] + (hi_ - lo_)[None, :, None] * ss
    L0 = (t - t1[None, :, None]) * (t - t2[None, :, None]) / ((t0 - t1) * (t0 - t2))[None, :, None]
    L1 = (t - t0[None, :, None]) * (t - t2[None, :, None]) / ((t1 - t0) * (t1 - t2))[None, :, None]
    L2 = (t - t0[None, :, None]) * (t - t1[None, :, None]) / ((t2 - t0) * (t2 - t1))[None, :, None]
    para = L0 * a[None] + L1 * b[None] + L2 * c[None]
    ok = sin > 1e-4
    if not ok.any():
        return para
    # circle: center in the plane of the three points
    n_ = nrm / np.maximum(np.linalg.norm(nrm, axis=1), 1e-30)[:, None]
    w_ = c - a
    denom = 2 * np.maximum(np.einsum("ij,ij->i", nrm, nrm), 1e-30)[:, None]
    center = a + np.cross(np.einsum("ij,ij->i", u, u)[:, None] * w_ - np.einsum("ij,ij->i", w_, w_)[:, None] * u,
                          nrm) / denom
    start, end = (a, b) if which == 0 else (b, c)
    r0, r1 = start - center, end - center
    ang = np.arctan2(np.einsum("ij,ij->i", n_, np.cross(r0, r1)), np.einsum("ij,ij->i", r0, r1))
    ang = np.where(ang < 0, ang + 2 * np.pi, ang)
    th = ang[None, :, None] * ss
    perp = np.cross(n_, r0)
    circ = center[None] + np.cos(th) * r0[None] + np.sin(th) * perp[None]
    # smooth transition to the parabola near the line (no jump at the threshold)
    f = np.clip((sin - 1e-4) / 1e-3, 0, 1)[None, :, None]
    return circ * f + para * (1 - f)


def gordon(u_curves, rows, v_curves, cols, cross, hard_u=None, hard_v=None):
    """Gordon surface (curve net in both directions, basis of "Network Surface"): loft through the u curves plus
    loft through the v curves minus the surface through their intersection points - it passes exactly through all curves. Without inner
    curves it is the Coons surface of the boundary.
    u_curves (K, m, 3): curves across (row rows[k]; boundary at bottom/top included), sampled so that the intersection points
    with the v curves lie on the columns cols; v_curves (L, r, 3) correspondingly lengthwise (column cols[l]); cross (K, L, 3)
    the intersection points. hard_u (K, m) / hard_v (L, r): hardness along the curves (the surface kinks there). -> (r, m, 3)"""
    u_curves, v_curves, cross = (np.asarray(x, float) for x in (u_curves, v_curves, cross))
    pu = interp_rows(u_curves, rows, hard_u)  # (r, m)
    pv = np.swapaxes(interp_rows(v_curves, cols, hard_v), 0, 1)  # (r, m)
    t = interp_rows(cross, rows, None if hard_u is None else np.asarray(hard_u)[:, cols])  # (r, L)
    puv = np.swapaxes(interp_rows(np.swapaxes(t, 0, 1), cols, hard_v), 0, 1)  # (r, m)
    return pu + pv - puv


def grid(sections, samples=SPAN_SAMPLES, hard=None):
    """Point grid of the surface (R, M, 3): rows across the cross-sections, columns = longitudinal lines. hard: see
    _catmull_rom (hard cross-sections kink the surface)."""
    return _catmull_rom(np.asarray(sections, float), samples, hard)


def rail_columns(sections, closed, direction, view):
    """Columns where real longitudinal lines arise: open the two side edges; closed by the
    extrusion rule (corners, about every 90°, circle: four, two of them on the silhouette)."""
    secs = np.asarray(sections, float)
    m = secs.shape[1]
    if not closed:
        return [0, m - 1]
    from .extrude import rail_points
    first = np.vstack([secs[0], secs[0][:1]])
    cols = []
    for p in rail_points(first, direction, view):
        c = int(np.argmin(np.linalg.norm(secs[0] - p, axis=1)))
        if c not in cols:
            cols.append(c)
    return sorted(cols)


def build(sections, closed, samples=SPAN_SAMPLES, g=None):
    """Aligned cross-sections (K, M, 3) -> (vertices, triangles, uv) of the loft surface. g: finished grid (R, M, 3)
    instead of computing it from the cross-sections (net surface: moved)."""
    grid = _catmull_rom(np.asarray(sections, float), samples) if g is None else np.asarray(g, float)  # (R, M, 3)
    r, m = grid.shape[:2]
    verts = grid.reshape(-1, 3)
    cols = m if closed else m - 1
    i = np.arange(cols)
    j = (i + 1) % m
    tris = []
    for row in range(r - 1):
        a, b = row * m, (row + 1) * m
        tris += [np.stack([a + i, a + j, b + j], 1), np.stack([a + i, b + j, b + i], 1)]
    uv = np.zeros((len(verts), 2))
    return verts, np.concatenate(tris).astype(np.int32), uv


def _cr_axis(g, n, periodic):
    """Resample the grid smoothly along axis 0 (Catmull-Rom, even in index) to n rows."""
    r = len(g)
    if r < 2 or n == r:
        return g
    t = np.linspace(0, r if periodic else r - 1, n, endpoint=not periodic)
    i = np.floor(t).astype(int)
    f = (t - i)[:, None, None]
    if periodic:
        idx = lambda k: np.mod(k, r)
    else:
        i = np.minimum(i, r - 2)
        f = (t - i)[:, None, None]
        idx = lambda k: np.clip(k, 0, r - 1)
    p0, p1, p2, p3 = g[idx(i - 1)], g[idx(i)], g[idx(i + 1)], g[idx(i + 2)]
    f2, f3 = f * f, f * f * f
    return 0.5 * (2 * p1 + (p2 - p0) * f + (2 * p0 - 5 * p1 + 4 * p2 - p3) * f2 + (3 * p1 - p0 - 3 * p2 + p3) * f3)


def resample_grid(g, factor, closed, breaks_r=(), breaks_c=(), ring=False):
    """Resample a point grid (R, M, 3) smoothly with factor-times the density (rows and columns) - for a finer
    or coarser net with the same shape. Closed: the columns run all the way around. breaks_r/breaks_c: rows or
    columns where the surface kinks (hard net lines) - sampled separately there, the crease stays.
    ring: the rows also run all the way around (last row = first), without a seam."""
    g = np.asarray(g, float)
    if ring and len(g) >= 4:
        g = _resample_axis(g[:-1], factor, True, ())
        g = np.concatenate([g, g[:1]])
    else:
        g = _resample_axis(g, factor, False, breaks_r)
    return np.swapaxes(_resample_axis(np.swapaxes(g, 0, 1), factor, closed, breaks_c), 0, 1)


def _resample_axis(g, factor, periodic, breaks):
    r = len(g)
    cuts = sorted({int(b) for b in breaks if 0 < int(b) < r - 1}) if not periodic else []
    if not cuts:
        n = max(3 if periodic else 2, int(round((r if periodic else r - 1) * factor)) + (0 if periodic else 1))
        return _cr_axis(g, n, periodic)
    out, bounds = [], [0] + cuts + [r - 1]
    for a, b in zip(bounds[:-1], bounds[1:]):
        part = _cr_axis(g[a:b + 1], max(2, int(round((b - a) * factor)) + 1), False)
        out.append(part if b == r - 1 else part[:-1])
    return np.concatenate(out)


# --- Displayed net by curvature: as fine as the shape needs, not as fine as the computation grid ---
# A flat surface needs two triangles, no matter how large; a tight rounding needs many, no matter how small. Measured
# on the shape itself - not on the size and not on the spacing of the points of its lines (that only says how it was drawn).
ADAPT_TOL = 0.001  # the coarser net may deviate from the shape by at most this much (fraction of the surface size)
ADAPT_ANGLE = 10.0  # ... and kink at most this much between two pieces (degrees): below that the light stays smooth
ADAPT_MAX = 4.0  # never finer than this many times the computation grid (even with the slider turned up)
_LADDER = (2, 3, 4, 5, 6, 8, 10, 12, 16, 20, 24, 32, 40, 48, 64, 80, 96, 128, 160, 192, 256)


def _max_turn(c, periodic):
    """Largest kink (degrees) between consecutive pieces along axis 0, over all columns."""
    d = np.diff(np.concatenate([c, c[:1]]) if periodic else c, axis=0)
    n = np.linalg.norm(d, axis=2)
    a, b = (d, np.roll(d, -1, axis=0)) if periodic else (d[:-1], d[1:])
    na, nb = (n, np.roll(n, -1, axis=0)) if periodic else (n[:-1], n[1:])
    if not len(a):
        return 0.0
    ok = (na > 1e-12) & (nb > 1e-12)
    cos = np.einsum("rmk,rmk->rm", a, b) / np.maximum(na * nb, 1e-30)
    ang = np.degrees(np.arccos(np.clip(cos, -1.0, 1.0)))
    return float(ang[ok].max()) if ok.any() else 0.0


def _rows_needed(g, periodic, tol, angle=ADAPT_ANGLE):
    """Smallest number of rows (from a ladder) with which the resampled grid along axis 0 deviates from g by at most tol
    and kinks at most angle degrees between two pieces - g's own kinks (a corner in the shape)
    do not count against it. At most the row count of g."""
    r = len(g)
    lo = 3 if periodic else 2
    if r <= lo:
        return r
    limit = max(angle, 1.2 * _max_turn(g, periodic))
    k = np.arange(r, dtype=float)
    for n in _LADDER:
        if n < lo:
            continue
        if n >= r:
            break
        c = _cr_axis(g, n, periodic)
        if periodic:
            t = k * n / r
            i = np.floor(t).astype(int) % n
            j = (i + 1) % n
        else:
            t = k * (n - 1) / (r - 1)
            i = np.minimum(np.floor(t).astype(int), n - 2)
            j = i + 1
        f = (t - np.floor(t) if periodic else t - i)[:, None, None]
        dev = float(np.linalg.norm(c[i] * (1 - f) + c[j] * f - g, axis=2).max())
        if dev <= tol and _max_turn(c, periodic) <= limit:
            return n
    return r


def _axis_plan(g, tol, scale, periodic, breaks):
    """Division along axis 0 by curvature: [(from, to, rows)] - separated at the rows breaks (the surface kinks
    there, the crease stays). scale: slider - this much finer (> 1) or coarser (< 1) than necessary."""
    r = len(g)

    def count(part, per):
        need = _rows_needed(part, per, tol)
        steps = (need if per else need - 1) * scale
        most = (len(part) if per else len(part) - 1) * ADAPT_MAX
        return max(3 if per else 2, int(round(min(max(steps, 1.0), most))) + (0 if per else 1))

    cuts = sorted({int(b) for b in breaks if 0 < int(b) < r - 1}) if not periodic else []
    bounds = [0] + cuts + [r - 1]
    if not cuts:
        return [(0, r - 1, count(g, periodic))]
    return [(a, b, count(g[a:b + 1], False)) for a, b in zip(bounds[:-1], bounds[1:])]


def _apply_plan(g, plan, periodic):
    if len(plan) == 1:
        return _cr_axis(g, plan[0][2], periodic)
    out = []
    for a, b, n in plan:
        part = _cr_axis(g[a:b + 1], n, False)
        out.append(part if b == len(g) - 1 else part[:-1])
    return np.concatenate(out)


# The division depends only on the shape, not on the position: if a surface is moved as a whole or scaled evenly,
# the same division still holds. Remembered per shape (fingerprint that does not change in the process; when rotated the
# size on which the tolerance hangs changes - then it is searched anew) -
# after releasing a drag, every surface moved along otherwise searched its division anew (harbor 11.11.: 94 surfaces of an
# object, 0.15 s per release and per undo for this alone).
_PLANS = {}


def _shape_print(g, flat, size):
    """Fingerprint of a point grid, the same for every rigidly moved copy: distances of all points to four grid points
    and to the centroid, plus length and kink of all pieces in both directions - relative to the size, to 1e-7."""
    r, m = g.shape[:2]
    refs = (g[0, 0], g[r - 1, m // 3], g[r // 3, m - 1], g[r // 2, m // 2], flat.mean(axis=0))
    parts = [np.linalg.norm(flat - p, axis=1) for p in refs]
    for axis in (0, 1):
        d = np.diff(g, axis=axis)
        parts.append(np.linalg.norm(d, axis=2).ravel())
        if d.shape[axis] > 1:
            parts.append(np.linalg.norm(np.diff(d, axis=axis), axis=2).ravel())
    rad = float(parts[4].max())  # size without reference to the axes; size (hull, the tolerance hangs on it) in proportion
    return np.round(np.concatenate([*parts, [size]]) * (1e7 / max(rad, 1e-300))).astype(np.int64).tobytes()


def adaptive_grid(g, scale, closed, breaks_r=(), breaks_c=(), ring=False, tol=ADAPT_TOL):
    """Resample a point grid (R, M, 3) for display as coarsely as its shape allows (ADAPT_TOL, ADAPT_ANGLE) -
    each direction on its own, both measured on the original grid. Otherwise like resample_grid (closed, creases at
    breaks, ring). scale: slider of the surface times viewport quality."""
    g = np.asarray(g, float)
    flat = g.reshape(-1, 3)
    size = float(np.linalg.norm(flat.max(axis=0) - flat.min(axis=0)))
    if size <= 1e-12 or len(g) < 2 or g.shape[1] < 2:
        return g
    eps = 0.5 * tol * size  # half for each direction
    whole_ring = ring and len(g) >= 4
    key = (g.shape, float(scale), bool(closed), bool(ring), float(tol), tuple(int(b) for b in breaks_r),
           tuple(int(b) for b in breaks_c), _shape_print(g, flat, size))
    plan = _PLANS.get(key)
    if plan is None:
        if len(_PLANS) > 4096:
            _PLANS.clear()
        plan = _PLANS[key] = (
            _axis_plan(g[:-1] if whole_ring else g, eps, scale, whole_ring, () if whole_ring else breaks_r),
            _axis_plan(np.swapaxes(g, 0, 1), eps, scale, closed, breaks_c))
    plan_r, plan_c = plan
    if whole_ring:
        rows = _apply_plan(g[:-1], plan_r, True)
        rows = np.concatenate([rows, rows[:1]])
    else:
        rows = _apply_plan(g, plan_r, False)
    return np.swapaxes(_apply_plan(np.swapaxes(rows, 0, 1), plan_c, closed), 0, 1)


def outlines(sections, closed, samples=SPAN_SAMPLES):
    """Outline for display: first and last cross-section, for open ones also the two sides."""
    secs = np.asarray(sections, float)
    first, last = secs[0], secs[-1]
    if closed:
        return [np.vstack([first, first[:1]]), np.vstack([last, last[:1]])]
    grid = _catmull_rom(secs, samples)
    return [first, last, grid[:, 0], grid[:, -1]]


# --- Lines drawn onto a loft: bound to the surface ---
def bind(points, sections, closed, tolerance, g=None):
    """Points on the surface -> (uv (N, 2) = (row, column) in the grid, on (N,) bool). Points farther than
    tolerance from the surface get on=False (a line tears there when the loft deforms).
    g: finished grid instead of the cross-sections (sections is then not needed)."""
    g = grid(sections) if g is None else np.asarray(g, float)
    r, m = g.shape[:2]
    cols = m if closed else m - 1
    rr, cc = np.meshgrid(np.arange(r - 1), np.arange(cols), indexing="ij")
    rr, cc = rr.ravel(), cc.ravel()
    c1 = (cc + 1) % m
    # two triangles per grid cell, with (row, column) of their corners (column cc+1 unwrapped for interpolation)
    tri_pts = np.concatenate([
        np.stack([g[rr, cc], g[rr, c1], g[rr + 1, c1]], 1),
        np.stack([g[rr, cc], g[rr + 1, c1], g[rr + 1, cc]], 1)])
    tri_uv = np.concatenate([
        np.stack([np.stack([rr, cc], 1), np.stack([rr, cc + 1], 1), np.stack([rr + 1, cc + 1], 1)], 1),
        np.stack([np.stack([rr, cc], 1), np.stack([rr + 1, cc + 1], 1), np.stack([rr + 1, cc], 1)], 1)]).astype(float)
    a, b, c = tri_pts[:, 0], tri_pts[:, 1], tri_pts[:, 2]
    n = np.cross(b - a, c - a)
    nn = np.maximum(np.einsum("ij,ij->i", n, n), 1e-18)
    flat = g.reshape(-1, 3)
    pts = np.asarray(points, float)
    uv = np.zeros((len(pts), 2))
    on = np.zeros(len(pts), bool)
    # prefilter: per point only the triangles whose neighborhood box (enlarged by the tolerance) it lies in
    tri3 = np.stack([a, b, c], 1)
    pad = max(tolerance, 1e-9) * 2
    lo, hi = tri3.min(axis=1) - pad, tri3.max(axis=1) + pad
    block = max(1, int(2_000_000 // max(len(a), 1)))
    for s0 in range(0, len(pts), block):
        P = pts[s0:s0 + block]
        inbox = np.all((P[:, None, :] >= lo[None]) & (P[:, None, :] <= hi[None]), axis=2)   # (B, M)
        pi, ti = np.nonzero(inbox)
        best_d = np.full(len(P), np.inf)
        best_t = np.zeros(len(P), int)
        best_w = np.zeros((len(P), 3))
        if len(pi):
            p, A, B, C, N, NN = P[pi], a[ti], b[ti], c[ti], n[ti], nn[ti]
            dot = np.einsum("ij,ij->i", p - A, N)
            q = p - N * (dot / NN)[:, None]
            w0 = np.einsum("ij,ij->i", np.cross(C - B, q - B), N) / NN
            w1 = np.einsum("ij,ij->i", np.cross(A - C, q - C), N) / NN
            w2 = 1 - w0 - w1
            inside = (w0 >= -1e-6) & (w1 >= -1e-6) & (w2 >= -1e-6)
            d = np.where(inside, np.abs(dot) / np.sqrt(NN), np.inf)
            # outside the triangle: the nearest point on its edges (at a crease the projection falls on the
            # outer side of the kink beside both triangles - otherwise the point would only get the nearest grid point, and
            # several line points would land on the same spot of the surface)
            out = ~inside
            if out.any():
                po = p[out]
                best = np.full(len(po), np.inf)
                wo = np.zeros((len(po), 3))
                for X, Y, ix, iy in ((A, B, 0, 1), (B, C, 1, 2), (C, A, 2, 0)):
                    X, Y = X[out], Y[out]
                    xy = Y - X
                    t = np.clip(np.einsum("ij,ij->i", po - X, xy) / np.maximum(np.einsum("ij,ij->i", xy, xy), 1e-18), 0, 1)
                    de = np.linalg.norm(X + xy * t[:, None] - po, axis=1)
                    better = de < best
                    best = np.where(better, de, best)
                    we = np.zeros((len(po), 3))
                    we[:, ix], we[:, iy] = 1 - t, t
                    wo = np.where(better[:, None], we, wo)
                d[out] = best
                w0, w1, w2 = w0.copy(), w1.copy(), w2.copy()
                w0[out], w1[out], w2[out] = wo[:, 0], wo[:, 1], wo[:, 2]
            order = np.lexsort((d, pi))                  # per point the nearest hit first
            first = order[np.r_[True, pi[order][1:] != pi[order][:-1]]]
            keep = np.isfinite(d[first])
            sel = first[keep]
            best_d[pi[sel]] = d[sel]
            best_t[pi[sel]] = ti[sel]
            best_w[pi[sel]] = np.stack([w0[sel], w1[sel], w2[sel]], 1)
        hit = np.isfinite(best_d)
        k = s0 + np.arange(len(P))
        if hit.any():
            t = best_t[hit]
            uv[k[hit]] = np.einsum("ij,ijk->ik", best_w[hit], tri_uv[t])
            on[k[hit]] = best_d[hit] <= tolerance
        miss = ~hit
        if miss.any():  # outside (beyond the border): nearest grid point
            for j in np.flatnonzero(miss):
                vi = int(np.argmin(np.linalg.norm(flat - P[j], axis=1)))
                uv[k[j]] = (vi // m, vi % m)
                on[k[j]] = np.linalg.norm(flat[vi] - P[j]) <= tolerance
    return uv, on


def evaluate(uv, sections, closed):
    """(row, column) in the grid -> points on the (possibly deformed) surface, bilinear."""
    return evaluate_grid(uv, grid(sections), closed)


def evaluate_grid(uv, g, closed):
    """Like evaluate, on a finished grid (R, M, 3)."""
    uv = np.asarray(uv, float).reshape(-1, 2)
    r, m = g.shape[:2]
    rows = np.clip(uv[:, 0], 0, r - 1)
    cols = np.mod(uv[:, 1], m) if closed else np.clip(uv[:, 1], 0, m - 1)
    r0 = np.minimum(np.floor(rows).astype(int), r - 2)
    c0 = np.floor(cols).astype(int)
    if closed:
        c0 = c0 % m  # mod can return exactly m for tiny negative values
    else:
        c0 = np.minimum(c0, m - 2)
    c1 = (c0 + 1) % m
    fr, fc = (rows - r0)[:, None], (cols - c0)[:, None]
    return (g[r0, c0] * (1 - fr) * (1 - fc) + g[r0, c1] * (1 - fr) * fc
            + g[r0 + 1, c0] * fr * (1 - fc) + g[r0 + 1, c1] * fr * fc)

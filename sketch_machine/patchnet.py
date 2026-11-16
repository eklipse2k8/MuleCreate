"""Curve surface as a curve net (Gordon surface): the rest shape is the result of its net lines.

Net lines are real lines on the surface that run from one border side to the opposite one and are connected to the
border at both ends: transverse (u, from side 3 to side 1 - e.g. the cross-sections of a loft) and longitudinal (v, from
side 0 to side 2). Where a transverse and a longitudinal line cross, they share a point. Each net line lies
exactly on one row or column of the grid; in between, the Gordon surface (loft.gordon) connects everything smoothly. Without
net lines it is the Coons surface of the border. Lines that do not run from border to border shape the surface
further as before (netsurf: smooth bending, between the net lines).

Only the geometry is here (grid, sampling, hardness, lattice); which lines are net lines is decided by the scene.
"""
import numpy as np

from . import components, loft

GRID_SHORT = 40  # grid points across the shorter direction
GRID_MAX = 145  # at most this many in the longer one
MIN_GAP = 3  # at least this many grid steps lie between two net lines


def arc(pts):
    pts = np.asarray(pts, float)
    return np.concatenate([[0], np.cumsum(np.linalg.norm(np.diff(pts, axis=0), axis=1))])


def arc_at(pts, point):
    """Arc length of the spot on the polyline nearest to point."""
    pts = np.asarray(pts, float)
    a, ab = pts[:-1], np.diff(pts, axis=0)
    t = np.clip(np.einsum("ij,ij->i", point - a, ab) / np.maximum(np.einsum("ij,ij->i", ab, ab), 1e-18), 0, 1)
    d = np.linalg.norm(a + ab * t[:, None] - point, axis=1)
    i = int(np.argmin(d))
    return float(arc(pts)[i] + t[i] * np.linalg.norm(ab[i]))


def cut(pts, s0, s1):
    """Piece of the polyline between arc lengths s0 and s1 (backwards if s1 < s0)."""
    pts = np.asarray(pts, float)
    ar = arc(pts)
    lo, hi = min(s0, s1), max(s0, s1)
    at = lambda s: np.array([np.interp(s, ar, pts[:, i]) for i in range(3)])
    inner = pts[(ar > lo) & (ar < hi)]
    seg = np.vstack([at(lo)[None], inner, at(hi)[None]])
    return seg if s0 <= s1 else seg[::-1]


def sample_t(pts, breaks, idx, guide=None):
    """Where a polyline is sampled (arc length per grid point) so that the spot breaks[i] (ascending) falls exactly on
    grid point idx[i]; in between evenly by arc length - or distributed like the polyline guide
    (idx[-1] + 1 points), so both directions of the net have the same division. Corners (kink from
    loft.CORNER_DEG) stay sharp."""
    pts = np.asarray(pts, float)
    ar = arc(pts)
    t = np.empty(idx[-1] + 1)
    g_arc = arc(guide) if guide is not None else None
    for i in range(len(breaks) - 1):
        a, b = idx[i], idx[i + 1]
        if g_arc is not None and g_arc[b] - g_arc[a] > 1e-12:
            f = (g_arc[a:b + 1] - g_arc[a]) / (g_arc[b] - g_arc[a])
        else:
            f = np.linspace(0.0, 1.0, b - a + 1)
        t[a:b + 1] = breaks[i] + f * (breaks[i + 1] - breaks[i])
    if len(pts) > 2:  # real corners: the nearest grid point snaps to them
        u, v = pts[1:-1] - pts[:-2], pts[2:] - pts[1:-1]
        cos = np.einsum("ij,ij->i", u, v) / np.maximum(np.linalg.norm(u, axis=1) * np.linalg.norm(v, axis=1), 1e-18)
        fixed = set(idx)
        for c in ar[1:-1][cos < np.cos(np.radians(loft.CORNER_DEG))]:
            k = int(np.argmin(np.abs(t - c)))
            if k not in fixed:
                t[k] = c
    return t


def sample(pts, breaks, idx, guide=None):
    """Points for sample_t. -> (idx[-1] + 1, 3)"""
    pts = np.asarray(pts, float)
    return at_arc(pts, sample_t(pts, breaks, idx, guide))


def at_arc(pts, t):
    ar = arc(pts)
    return np.stack([np.interp(t, ar, pts[:, i]) for i in range(3)], axis=1)


def to_index(pts, t):
    """Arc length -> fractional point index of the polyline (a fixed spot on the line: stays there when deforming)."""
    return np.interp(t, arc(pts), np.arange(len(pts), dtype=float))


def at_index(pts, fi):
    pts = np.asarray(pts, float)
    i0 = np.clip(np.floor(fi).astype(int), 0, len(pts) - 2)
    f = np.clip(fi - i0, 0.0, 1.0)[:, None]
    return pts[i0] * (1 - f) + pts[i0 + 1] * f


def grid_index(s, breaks, idx):
    """Arc length on a net line -> fractional grid index (piecewise like sample)."""
    return float(np.interp(s, breaks, idx))


def place(fracs, n):
    """Place net lines at their fractions (0 ... 1, ascending) on grid indices 1 ... n-2, at least MIN_GAP apart
    (also from the border) - or None if that is not possible at n."""
    out = []
    for f in fracs:
        i = int(round(f * (n - 1)))
        lo = (out[-1] if out else 0) + MIN_GAP
        out.append(max(i, lo))
    if out and out[-1] > n - 1 - MIN_GAP:  # push back from the end
        hi = n - 1 - MIN_GAP
        for k in range(len(out) - 1, -1, -1):
            out[k] = min(out[k], hi)
            hi = out[k] - MIN_GAP
        if out[0] < MIN_GAP:
            return None
    return out


def layout(sides, u_fracs, v_fracs):
    """Grid size (r, m) from the aspect ratio (cells roughly square) and rows/columns of the net lines.
    -> (r, m, rows, cols) or None (too dense)."""
    len_u = (arc(sides[0])[-1] + arc(sides[2])[-1]) / 2
    len_v = (arc(sides[1])[-1] + arc(sides[3])[-1]) / 2
    ratio = len_v / max(len_u, 1e-12)
    m = GRID_SHORT if ratio >= 1 else int(min(GRID_MAX, round(GRID_SHORT / max(ratio, 1e-6))))
    r = GRID_SHORT if ratio < 1 else int(min(GRID_MAX, round(GRID_SHORT * ratio)))
    while True:
        rows, cols = place(u_fracs, r), place(v_fracs, m)
        if rows is not None and cols is not None:
            return r, m, rows, cols
        if r >= 4 * GRID_MAX and m >= 4 * GRID_MAX:
            return None
        if rows is None:
            r = min(r * 2, 4 * GRID_MAX)
        if cols is None:
            m = min(m * 2, 4 * GRID_MAX)


def _kink_at(pts, breaks, i):
    """Hardness (0 ... 1) of the line pts at its spot breaks[i], measured to the neighboring spots."""
    if i <= 0 or i >= len(breaks) - 1:
        return 0.0
    before, after = cut(pts, breaks[i], breaks[i - 1]), cut(pts, breaks[i], breaks[i + 1])
    return components.sharpness(components.kink_deg(before, after))


def anchor(pts, breaks, idx, fi):
    """Reuse stored spots fi (fractional point indices per grid point): the intersections (breaks)
    lie exactly; a section in which the spots no longer lie in order between its intersections is
    divided evenly again. -> fractional point indices"""
    fi = np.asarray(fi, float).copy()
    br = to_index(pts, np.asarray(breaks, float))
    for i in range(len(breaks) - 1):
        a, b = idx[i], idx[i + 1]
        fi[a], fi[b] = br[i], br[i + 1]
        seg = fi[a:b + 1]
        if np.any(np.diff(seg) < -1e-9):  # reversed (equal spots are allowed: a corner both snap to)
            fi[a:b + 1] = to_index(pts, np.linspace(breaks[i], breaks[i + 1], b - a + 1))
    return fi


def snap(fi, grid_breaks, points):
    """Let grid points snap to the points points (fractional point indices of the line: its connected points) -
    per point the nearest grid point that is not an intersection, as long as the order holds. This way the surface lies
    exactly at every connection point (a bump there, when the point is dragged, gets its grid point)."""
    fi = np.asarray(fi, float).copy()
    fixed = set(int(i) for i in grid_breaks)
    for p in points:
        k = int(np.argmin(np.abs(fi - p)))
        if k in fixed:
            continue
        lo = fi[k - 1] if k > 0 else -np.inf
        hi = fi[k + 1] if k < len(fi) - 1 else np.inf
        if lo < p < hi:
            fi[k] = p
            fixed.add(k)
    return fi


def build(u_lines, v_lines, rows, cols, r, m, anchors=None, snaps=None):
    """Gordon grid from the net lines. u_lines: [(points from column 0 to m-1, arc lengths of the intersections with
    all v lines in column order, border included)] - bottom (row 0) first, top last; v_lines
    likewise. rows/cols: grid indices of all u and v lines respectively (0 ... r-1 / m-1). anchors: stored spots per
    curve (u, then v; fractional point indices) - each grid point stays at its spot of the line, if one drags a
    point only the grid points there go along; None: divide anew. snaps: per curve the connected points (fractional
    point indices) a grid point snaps to.
    -> (grid (r, m, 3), hardness along the u/v lines, spots per curve)"""
    curves = list(u_lines) + list(v_lines)
    grids = [cols] * len(u_lines) + [rows] * len(v_lines)
    if anchors is not None and len(anchors) == len(curves) and all(
            len(a) == g[-1] + 1 for a, g in zip(anchors, grids)):
        fis = [anchor(p, b, g, a) for (p, b), g, a in zip(curves, grids, anchors)]
    else:
        # first evenly, then divide each curve the way the surface of the other direction runs there - otherwise
        # the border correction of the Gordon surface would shift the interior (e.g. side lines of a loft evenly, the
        # rows in between not)
        uc = np.array([sample(p, b, cols) for p, b in u_lines])
        vc = np.array([sample(p, b, rows) for p, b in v_lines])
        pu = loft.interp_rows(uc, rows)
        pv = np.swapaxes(loft.interp_rows(vc, cols), 0, 1)
        fis = [to_index(p, sample_t(p, b, cols, pv[row])) for (p, b), row in zip(u_lines, rows)]
        fis += [to_index(p, sample_t(p, b, rows, pu[:, col])) for (p, b), col in zip(v_lines, cols)]
    if snaps is not None and len(snaps) == len(curves):
        fis = [snap(fi, g, sn) for fi, g, sn in zip(fis, grids, snaps)]
    uc = np.array([at_index(p, fi) for (p, _), fi in zip(u_lines, fis[:len(u_lines)])])  # (K, m, 3)
    vc = np.array([at_index(p, fi) for (p, _), fi in zip(v_lines, fis[len(u_lines):])])  # (L, r, 3)
    cross = uc[:, cols]  # (K, L, 3): the intersection points
    k_, l_ = len(u_lines), len(v_lines)
    # hardness: a net line kinks the surface where the lines crossing it kink there (like components.crease_along)
    hard_u = np.zeros((k_, m))
    for k in range(1, k_ - 1):
        hard_u[k] = np.interp(np.arange(m), cols, [_kink_at(p, b, k) for p, b in v_lines])
    hard_v = np.zeros((l_, r))
    for l in range(1, l_ - 1):
        hard_v[l] = np.interp(np.arange(r), rows, [_kink_at(p, b, l) for p, b in u_lines])
    g = loft.gordon(uc, rows, vc, cols, cross, hard_u if hard_u.any() else None, hard_v if hard_v.any() else None)
    return g, hard_u, hard_v, fis


# --- Tube and ring: the net runs around transversely (cross-sections closed), for the ring also longitudinally ---
def sample_loop(loop, breaks, cols, m):
    """Sample a closed line (points all around, without repeating the first at the end) onto m columns so that the
    spot breaks[i] (arc length from loop[0], ascending, < circumference) falls exactly on column cols[i] (ascending, < m);
    in between evenly by arc length, across the seam. Without spots: evenly from loop[0]. -> (m, 3)"""
    loop = np.asarray(loop, float)
    closed = np.vstack([loop, loop[:1]])
    ar = arc(closed)
    total = ar[-1]
    t = np.empty(m)
    if not len(breaks):
        t[:] = np.linspace(0, total, m, endpoint=False)
    else:
        b = list(breaks) + [breaks[0] + total]
        c = list(cols) + [cols[0] + m]
        for i in range(len(breaks)):
            idx = np.arange(c[i], c[i + 1])
            t[idx % m] = b[i] + (idx - c[i]) / max(c[i + 1] - c[i], 1) * (b[i + 1] - b[i])
    t = np.mod(t, total)
    return np.stack([np.interp(t, ar, closed[:, i]) for i in range(3)], axis=1)


def loop_index(loop, breaks, cols, m, s):
    """Arc length s on the closed line -> fractional column (like sample_loop)."""
    total = float(arc(np.vstack([loop, loop[:1]]))[-1])
    if not len(breaks):
        return float(np.mod(s, total) / total * m)
    b = list(breaks) + [breaks[0] + total]
    c = list(cols) + [cols[0] + m]
    s = s if s >= breaks[0] else s + total
    return float(np.mod(np.interp(s, b, c), m))


def build_tube(loops, rows, v_lines, cols, r, m, ring=False):
    """Gordon grid of a tube (transversely closed) or a ring (also longitudinally closed). loops: cross-sections per
    [(points all around, arc lengths of the intersections with the longitudinal lines in column order)] on rows rows;
    v_lines: longitudinal lines [(points from the first cross-section to the last - for the ring once around -, arc lengths of their
    intersections with the cross-sections)] on columns cols. At least three longitudinal lines (otherwise None). -> (r, m, 3)"""
    if len(v_lines) < 3:
        return None
    uc = np.array([sample_loop(p, b, cols, m) for p, b in loops])  # (K, m, 3)
    vrows = rows + [r - 1] if ring else rows
    vc = np.array([sample(p, b, vrows) for p, b in v_lines])  # (L, r, 3)
    cross = uc[:, cols]  # (K, L, 3)
    if ring:  # longitudinally closed: the first cross-section once more at the end
        uc, cross, rows = np.concatenate([uc, uc[:1]]), np.concatenate([cross, cross[:1]]), rows + [r - 1]
    wrap = lambda a: np.concatenate([a, a[:1]])  # transversely closed: first longitudinal line once more at the end
    cols_w = list(cols) + [cols[0] + m]
    shift = cols[0]  # count columns from the first longitudinal line (the ring interpolation needs them ascending from 0)
    at = [c - shift for c in cols_w]
    pu = loft.interp_rows(uc, rows)  # (r, m)
    pv = np.swapaxes(loft.interp_rows(wrap(vc), at), 0, 1)[:, :m]  # (r, m) from column shift
    t = loft.interp_rows(cross, rows)  # (r, L)
    puv = np.swapaxes(loft.interp_rows(wrap(np.swapaxes(t, 0, 1)), at), 0, 1)[:, :m]
    pv, puv = np.roll(pv, shift, axis=1), np.roll(puv, shift, axis=1)
    return pu + pv - puv

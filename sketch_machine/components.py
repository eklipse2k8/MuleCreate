"""Points and edges on lines – selection mode point (1) and edge (2), as in Houdini.

A line remains a single stroke (pencil grain, smoothing, lofts depend on it). Its points
("knots") are the ends and the corners – kink from extrude.CORNER_DEG, detected on first use and
then remembered on the line (Curve.knots), so that a point does not vanish when one straightens the corner
– plus points inserted with Ctrl+click. Edges are the pieces between two neighboring knots.

References: ("pt", stroke_id, line_id, index) and ("seg", stroke_id, line_id, a, b) with a < b
knot indices. An edge that spans the whole line is the line itself: ("line", stroke_id, line_id).

Moving is soft: a moved knot takes the line along up to the neighboring knots, tapering off linearly by
arc length (straight pieces stay straight); a piece with both ends moved moves
rigidly. Knots at the same place (welded line ends, also on other lines) move together.
"""
import numpy as np

from . import extrude
from .i18n import tr

WELD_TOL = 1e-5  # like edges.WELD_TOL: closer than this = the same point
_CELL = 4 * WELD_TOL
_NEIGHBOURS = [(x, y, z) for x in (-1, 0, 1) for y in (-1, 0, 1) for z in (-1, 0, 1)]


def is_closed(points):
    return len(points) > 2 and np.linalg.norm(points[0] - points[-1]) < WELD_TOL


def detect_corners(points):
    """Inner point indices where the line kinks by at least CORNER_DEG (measured as in
    extruding, over a short piece of the slightly smoothed line – hand jitter does not count)."""
    pts = np.asarray(points, float)
    n = len(pts)
    if n < 3:
        return []
    arc = np.concatenate([[0], np.cumsum(np.linalg.norm(np.diff(pts, axis=0), axis=1))])
    length = arc[-1]
    if length <= 1e-12:
        return []
    closed = is_closed(pts)
    samples = extrude.SAMPLES
    t = np.linspace(0, length, samples + 1)
    even = np.stack([np.interp(t, arc, pts[:, i]) for i in range(3)], axis=1)
    if closed:
        even, t = even[:-1], t[:-1]
    m_n = len(even)
    measure = extrude._smooth(even, closed)
    m = max(2, int(round(extrude.CORNER_SPAN * samples)))
    idx = np.arange(m_n)
    if closed:
        before, after = measure - measure[(idx - m) % m_n], measure[(idx + m) % m_n] - measure
        valid = np.ones(m_n, bool)
    else:
        before = measure - measure[np.clip(idx - m, 0, m_n - 1)]
        after = measure[np.clip(idx + m, 0, m_n - 1)] - measure
        valid = (idx >= m) & (idx < m_n - m)
    knick = np.where(valid, extrude._angle(before, after), 0.0)
    out = set()
    for peak in extrude._peaks(knick >= extrude.CORNER_DEG, knick, closed):
        k = int(np.argmin(np.abs(arc - t[peak])))  # nearest real point of the line
        if 0 < k < n - 1:
            out.add(k)
    return sorted(out)


def knots(curve):
    """Knot indices of the line: [0, corners …, n-1] (closed: 0 and n-1 are the same point).

    Corners are detected only once (on first use, for drawn lines right while drawing). If the point count changes
    afterwards (resampling, smoothing …), the known knots move to the same place on the line
    (same fraction of the arc length) – dissolved corners do not come back, inserted points stay."""
    n = len(curve.points)
    k = curve.knots
    if k is None or k[0] != n:
        memo = getattr(curve, "_knot_t", None)
        if k is not None and memo is not None and memo[0] == k:
            t_new = _arc_t(curve.points)
            k = (n, tuple(sorted({int(np.argmin(np.abs(t_new - t))) for t in memo[2]} - {0, n - 1})))
        else:
            k = (n, tuple(detect_corners(curve.points)))
        curve.knots = k
    memo = getattr(curve, "_knot_t", None)
    if memo is None or memo[0] != k or memo[1] != id(curve.points):  # remember the position of the knots on the line
        t = _arc_t(curve.points)
        curve._knot_t = (k, id(curve.points), tuple(float(t[i]) for i in k[1] if 0 < i < n - 1))
    return [0, *[i for i in k[1] if 0 < i < n - 1], n - 1]


def segments(curve):
    """Edges of the line as [(a, b)] of neighboring knots."""
    ks = knots(curve)
    return list(zip(ks[:-1], ks[1:]))


def segment_of(curve, index):
    """Edge (a, b) in which the line piece index -> index+1 lies."""
    for a, b in segments(curve):
        if a <= index < b:
            return a, b
    return segments(curve)[-1]


def insert_point(curve, index, t):
    """Insert a new knot on the piece index -> index+1 at t (0..1); returns its index.
    If the place is practically on an existing point, that becomes the knot."""
    pts, wid = curve.points, curve.widths
    knots(curve)
    inner = list(curve.knots[1])
    if t < 0.02 or t > 0.98:
        k = index if t < 0.5 else index + 1
    else:
        point = pts[index] + t * (pts[index + 1] - pts[index])
        width = wid[index] + t * (wid[index + 1] - wid[index])
        curve.points = np.vstack([pts[:index + 1], point, pts[index + 1:]])
        curve.widths = np.concatenate([wid[:index + 1], [width], wid[index + 1:]])
        k = index + 1
        inner = [i + 1 if i > index else i for i in inner]
    n = len(curve.points)
    if 0 < k < n - 1:
        inner = sorted(set(inner) | {k})
    curve.knots = (n, tuple(inner))
    return _densify_around(curve, k)


SOFT_MIN_POINTS = 24  # a piece next to an inserted point gets at least this many points (softly draggable)


def _densify_around(curve, k):
    """Subdivide the two pieces next to knot k finely if they have only a few points (e.g. a straight line
    of two points) – otherwise there would be nothing to bend when dragging softly, and a
    corner would result. The shape stays exact (new points lie on the old pieces). Returns the new index of k."""
    ks = knots(curve)
    if k not in ks:
        return k
    j = ks.index(k)
    sparse = {(ks[i], ks[i + 1]) for i in (j - 1, j) if 0 <= i < len(ks) - 1 and ks[i + 1] - ks[i] + 1 < SOFT_MIN_POINTS}
    if not sparse:
        return k
    pts, wid = curve.points, curve.widths
    out_p, out_w, new_index = [pts[0]], [wid[0]], {0: 0}
    for a, b in zip(ks[:-1], ks[1:]):
        seg, sw = pts[a:b + 1], wid[a:b + 1]
        if (a, b) in sparse:
            arc = np.concatenate([[0], np.cumsum(np.linalg.norm(np.diff(seg, axis=0), axis=1))])
            t = np.linspace(0, arc[-1], SOFT_MIN_POINTS)
            seg = np.stack([np.interp(t, arc, seg[:, i]) for i in range(3)], axis=1) if arc[-1] > 0 else seg
            sw = np.interp(t, arc, sw) if arc[-1] > 0 else sw
        out_p.extend(seg[1:])
        out_w.extend(sw[1:])
        new_index[b] = len(out_p) - 1
    curve.points, curve.widths = np.array(out_p), np.array(out_w)
    m = len(curve.points)
    curve.knots = (m, tuple(sorted(new_index[i] for i in ks[1:-1])))
    return new_index[k]


def split_at(curve, cuts):
    """Split the line at the knot indices cuts -> [(new line, start, end)]; the pieces keep their points."""
    from .scene import Curve
    knots(curve)
    inner = curve.knots[1]
    bounds = [0, *cuts, len(curve.points) - 1]
    out = []
    for s, e in zip(bounds[:-1], bounds[1:]):
        piece = Curve(curve.points[s:e + 1].copy(), curve.plane_id, curve.widths[s:e + 1].copy(), curve.generated)
        piece.style, piece.color = curve.style, curve.color
        piece.knots = (e - s + 1, tuple(k - s for k in inner if s < k < e))
        if curve.pids:  # curve net: the pieces keep their points, the same ones at the cuts
            piece.pids = {k - s: pid for k, pid in curve.pids.items() if s <= k <= e}
        out.append((piece, s, e))
    return out


def dissolve(curve, index):
    """Dissolve a corner or inserted point: the handle disappears, the line stays exactly as it is.
    Line ends (and the seam of closed lines) cannot be dissolved -> False."""
    n = len(curve.points)
    if not 0 < index < n - 1:
        return False
    knots(curve)
    inner = [k for k in curve.knots[1] if k != index]
    if len(inner) == len(curve.knots[1]):
        return False
    curve.knots = (n, tuple(inner))
    return True


class KnotIndex:
    """All knots of all lines, gridded by location, with their net points (network.py): which knots lie at
    the same place (at), which are the same point (linked)?"""

    def __init__(self, scene):
        from . import network
        network.sync(scene)
        self.entries = []  # (stroke_id, line, knot index)
        self.points = []
        self.grid = {}
        self.by_pid = {}
        for st in scene.strokes:
            for c in st.curves:
                if len(c.points) < 2 or c.paint:  # painting has no points: does not move along, is not moved
                    continue
                pids = c.pids or {}
                for k in knots(c):
                    self.grid.setdefault(_cell(c.points[k]), []).append(len(self.entries))
                    pid = pids.get(k)
                    if pid is not None:
                        self.by_pid.setdefault(pid, []).append(len(self.entries))
                    self.entries.append((st.id, c, k))
                    self.points.append(c.points[k])

    def at(self, point):
        """Knots at this place: [(stroke_id, line, index)] – also overlapping, unconnected ones."""
        x, y, z = _cell(point)
        return [self.entries[j] for dx, dy, dz in _NEIGHBOURS for j in self.grid.get((x + dx, y + dy, z + dz), ())
                if np.linalg.norm(self.points[j] - point) < WELD_TOL]

    def linked(self, curve, k):
        """Knots that are the same net point as knot k of the line (itself included)."""
        pid = (curve.pids or {}).get(k)
        if pid is None:
            return [e for e in self.at(curve.points[k])]
        return [self.entries[j] for j in self.by_pid.get(pid, ())]


def _cell(point):
    x, y, z = (int(c) for c in np.floor(np.asarray(point) / _CELL))
    return x, y, z


def _arc_t(points):
    arc = np.concatenate([[0], np.cumsum(np.linalg.norm(np.diff(points, axis=0), axis=1))])
    return arc / max(arc[-1], 1e-12)


# --- Hardness = angularity, derived from the shape (nothing stored) ---
# A point is as hard as the line running through it kinks there: soft up to SHARP_FROM_DEG (0), fully hard from
# SHARP_FULL_DEG (1), continuous in between. An edge is hard where the lines that cross it at its points
# (or end at it and continue) kink there – there the surface kinks; in between proportionally.
SHARP_FROM_DEG = 15.0
SHARP_FULL_DEG = 45.0  # middle (hardness 0.5) = extrude.CORNER_DEG: from there on it is a corner everywhere
SHARP_PROBE = 0.08  # direction at the point: measured over this fraction of the adjoining edge (second order)


def sharpness(deg):
    """Kink angle (degrees) -> hardness 0 … 1."""
    return float(np.clip((deg - SHARP_FROM_DEG) / (SHARP_FULL_DEG - SHARP_FROM_DEG), 0.0, 1.0))


def _lead(poly):
    """Direction at the start of the polyline (away from poly[0]): estimated from the places at s and 2s (parabola – a
    curve does not fake a kink), s = SHARP_PROBE of the length. None at length 0."""
    poly = np.asarray(poly, float)
    arc = np.concatenate([[0], np.cumsum(np.linalg.norm(np.diff(poly, axis=0), axis=1))])
    if len(poly) < 2 or arc[-1] <= 1e-12:
        return None
    s = min(SHARP_PROBE * arc[-1], arc[-1] / 2)
    q1, q2 = (np.array([np.interp(x, arc, poly[:, i]) for i in range(3)]) for x in (s, 2 * s))
    d = 2 * (q1 - poly[0]) - 0.5 * (q2 - poly[0])
    n = float(np.linalg.norm(d))
    if n <= 1e-12:
        d, n = q1 - poly[0], float(np.linalg.norm(q1 - poly[0]))
    return d / n if n > 1e-12 else None


def side_points(side):
    """Edge piece (line, a, b, point at b?) as a polyline away from the point."""
    c, lo, hi, p_hi = side
    seg = c.points[lo:hi + 1]
    return seg[::-1] if p_hi else seg


def kink_deg(before, after):
    """Kink (degrees) between two polylines that both start at the point (0 = straight through)."""
    a, b = _lead(before), _lead(after)
    if a is None or b is None:
        return 0.0
    return float(np.degrees(np.arccos(np.clip(float(-a @ b), -1.0, 1.0))))


def pairs_at(refs, exclude=()):
    """Lines running through a point: [(side, side)] with side = (line, a, b, point at b?). A line with
    the point in its middle (or at the seam of a ring) runs through; two line ends likewise, if exactly two are there
    (split line, corner between two lines). refs: [(line, knot)] of the point; exclude: ids of lines that
    do not count (the edge along which the query is made)."""
    out, ends = [], []
    for c, k in refs:
        if c.id in exclude or len(c.points) < 2:
            continue
        ks = knots(c)
        n = len(c.points)
        if 0 < k < n - 1 and k in ks:
            i = ks.index(k)
            out.append(((c, ks[i - 1], k, True), (c, k, ks[i + 1], False)))
        elif is_closed(c.points) and len(ks) > 2:
            if k == 0:
                out.append(((c, ks[-2], n - 1, True), (c, 0, ks[1], False)))
        elif len(ks) >= 2:
            ends.append((c, ks[-2], k, True) if k == n - 1 else (c, 0, ks[1], False))
    if len(ends) == 2 and ends[0][0] is not ends[1][0]:
        out.append(tuple(ends))
    return out


def pair_kink(pair):
    return kink_deg(side_points(pair[0]), side_points(pair[1]))


def point_sharpness(refs, exclude=()):
    """Hardness of a point: the strongest kink of the lines running through it (without exclude)."""
    return max((sharpness(pair_kink(p)) for p in pairs_at(refs, exclude)), default=0.0)


def _refs_at(c, k, index):
    """[(line, knot)] of the same net point as knot k of c."""
    if index is None:
        return [(c, k)]
    out = [(o, j) for _, o, j in index.linked(c, k)]
    return out if any(o is c and j == k for o, j in out) else out + [(c, k)]


def hardness(c, k, index=None, corners=None, auto=True):
    """Hardness of knot k for dragging: how strongly the line itself kinks there (0 curve … 1 corner). A line end
    at which exactly one other line continues has the kink between the two; otherwise it is hard (free end, corner
    of several lines)."""
    n = len(c.points)
    refs = _refs_at(c, k, index)
    if 0 < k < n - 1 or is_closed(c.points):
        mine = pairs_at([(c, 0 if k == n - 1 else k)])
        return sharpness(pair_kink(mine[0])) if mine else 1.0
    others = [(o, j) for o, j in refs if o is not c]
    if len(others) != 1:
        return 1.0
    pairs = pairs_at([(c, k)] + others)
    return sharpness(pair_kink(pairs[0])) if pairs and pairs[0][1][0] is not pairs[0][0][0] else 1.0


def crease_along(c, refs_by_pid):
    """Crease hardness per line point (N,): at each point of the line the kink of the lines that cross it there or continue
    at it (itself does not count); between the points proportional by arc length. refs_by_pid:
    network.refs_by_pid. All soft: zeros."""
    ks = knots(c)
    pids = c.pids or {}
    h = np.array([point_sharpness(refs_by_pid.get(pids[k], []), {c.id}) if k in pids else 0.0 for k in ks])
    if not h.any():
        return np.zeros(len(c.points))
    arc = np.concatenate([[0], np.cumsum(np.linalg.norm(np.diff(c.points, axis=0), axis=1))])
    return np.interp(arc, arc[ks], h)


def width_at(points, widths, p):
    """(distance, stroke width) of the polyline at its place nearest to p (proportional between two points)."""
    pts, w = np.asarray(points, float), np.asarray(widths, float)
    p = np.asarray(p, float)
    if len(pts) < 2:
        return (float(np.linalg.norm(pts[0] - p)), float(w[0])) if len(pts) else (np.inf, 0.0)
    a, ab = pts[:-1], np.diff(pts, axis=0)
    t = np.clip(np.einsum("ij,ij->i", p - a, ab) / np.maximum(np.einsum("ij,ij->i", ab, ab), 1e-18), 0, 1)
    d = np.linalg.norm(a + ab * t[:, None] - p, axis=1)
    i = int(np.argmin(d))
    return float(d[i]), float(w[i] * (1 - t[i]) + w[i + 1] * t[i])


_WIDTH_SEGS = [None, None]  # (key, segment arrays) of the lines asked last – the same ones for each extrusion


def width_near(lines, p, fallback):
    """Stroke width of the line nearest to p there (real, current width) – fallback without lines.
    All segments in one go (harbor test: extruding 123 surfaces, for each connecting line all lines one by one -> 3 s per
    preview image); the stacked segments stay remembered for the same lines."""
    lines = [c for c in lines if c is not None and len(c.points)]
    if not lines:
        return fallback
    key = tuple((id(c.points), id(c.widths)) for c in lines)
    if _WIDTH_SEGS[0] != key:
        a, ab, wa, wb, single = [], [], [], [], []
        for c in lines:
            pts, w = np.asarray(c.points, float), np.asarray(c.widths, float)
            if len(pts) < 2:
                single.append((pts[0], float(w[0])))
                continue
            a.append(pts[:-1]); ab.append(np.diff(pts, axis=0)); wa.append(w[:-1]); wb.append(w[1:])
        segs = (np.vstack(a), np.vstack(ab), np.concatenate(wa), np.concatenate(wb)) if a else None
        _WIDTH_SEGS[:] = [key, (segs, single, [c.points for c in lines])]  # hold on to the points: ids stay valid
    segs, single, _keep = _WIDTH_SEGS[1]
    p = np.asarray(p, float)
    best_d, best_w = np.inf, fallback
    if segs is not None:
        a, ab, wa, wb = segs
        t = np.clip(np.einsum("ij,ij->i", p - a, ab) / np.maximum(np.einsum("ij,ij->i", ab, ab), 1e-18), 0, 1)
        d = np.linalg.norm(a + ab * t[:, None] - p, axis=1)
        i = int(np.argmin(d))
        best_d, best_w = float(d[i]), float(wa[i] * (1 - t[i]) + wb[i] * t[i])
    for q, w in single:
        d = float(np.linalg.norm(q - p))
        if d < best_d:
            best_d, best_w = d, w
    return best_w


def widths_through(points, anchors, fallback):
    """Stroke widths (N,) of a new line that connects existing lines: at the anchor points anchors
    [(point index, width)] their width, in between proportional by arc length, before/after like the nearest."""
    pts = np.asarray(points, float)
    if not anchors:
        return np.full(len(pts), float(fallback))
    arc = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(pts, axis=0), axis=1))])
    anchors = sorted((int(i), float(w)) for i, w in anchors)
    return np.interp(arc, arc[[i for i, _ in anchors]], [w for _, w in anchors])


def widths_between(points, lines_a, lines_b, fallback):
    """Like widths_through for a line from one line (lines_a, at the start) to another (lines_b, at the end)."""
    pts = np.asarray(points, float)
    return widths_through(pts, [(0, width_near(lines_a, pts[0], fallback)),
                                (len(pts) - 1, width_near(lines_b, pts[-1], fallback))], fallback)


def smooth_points(seg, amount):
    """Smooth edge (J): amount 0 = unchanged … 1 = straight line between the two ends. In between the deviation
    from this straight line is smoothly filtered (Gaussian by arc length, odd-mirrored at the ends – the ends stay) and
    at the same time reduced: first small wobbles disappear, then the large arcs. Closed pieces (start = end)
    are filtered all around and only gently smoothed."""
    seg = np.asarray(seg, float)
    n = len(seg)
    if n < 3 or amount <= 0:
        return seg.copy()
    arc = np.concatenate([[0], np.cumsum(np.linalg.norm(np.diff(seg, axis=0), axis=1))])
    length = arc[-1]
    if length <= 1e-12:
        return seg.copy()
    ds = np.gradient(arc)  # weight per point: distance to the neighbors (unevenly distributed points)
    if np.linalg.norm(seg[0] - seg[-1]) < 1e-9 * max(length, 1.0):
        sigma = max(amount * 0.12 * length, 1e-12)
        dx = np.abs(arc[:, None] - arc[None, :])
        dx = np.minimum(dx, length - dx)
        w = np.exp(-0.5 * (dx / sigma) ** 2) * ds[None, :]
        out = (w @ seg) / w.sum(axis=1, keepdims=True)
        out[-1] = out[0]
        return out
    if amount >= 1:
        return seg[0] + (arc / length)[:, None] * (seg[-1] - seg[0])
    chord = seg[0] + (arc / length)[:, None] * (seg[-1] - seg[0])
    dev = seg - chord
    sigma = max(amount ** 1.5 * 0.3 * length, 1e-12)
    k = lambda d: np.exp(-0.5 * (d / sigma) ** 2)
    x, y = arc[:, None], arc[None, :]
    direct, left, right = k(x - y), k(x + y), k(x - (2 * length - y))  # mirrored at the ends
    num = (direct - left - right) * ds[None, :]
    den = ((direct + left + right) * ds[None, :]).sum(axis=1, keepdims=True)
    out = chord + (num @ dev) / den * (1 - amount ** 3)
    out[0], out[-1] = seg[0], seg[-1]
    return out


def _falloff(t, soft_moved, soft_other):
    """Fraction of the displacement along a piece (t: 0 at the dragged point … 1 at the neighboring point). Soft means:
    no kink (slope 0) at this end; hard: straight. soft_*: 0 (hard) … 1 (soft) – intermediate values
    mix the shapes."""
    a, b = float(soft_moved), float(soft_other)
    both = 1 - (3 * t * t - 2 * t * t * t)
    return (a * b * both + a * (1 - b) * (1 - t * t) + (1 - a) * b * (1 - t) ** 2 + (1 - a) * (1 - b) * (1 - t))


class ComponentGroup:
    """Selected points and edges as one gizmo target (same interface as edges.EdgeGroup).
    points: [(line, knot)], segs: [(line, a, b)] (moved rigidly). weld: knots at the same place
    (also on other lines) move along; without (Alt): only exactly what is selected."""
    scale_axes = (0, 1, 2)

    def __init__(self, scene, points, segs, weld=True, mode="auto", only=None, index=None):
        """index: finished knot index of the scene (KnotIndex) – whoever creates several groups at the same state builds
        it once and passes it around (building it runs over all knots of the scene)."""
        self.scene = scene
        self.mode = mode  # dragging points: "auto" (as the line kinks at the point), "soft" or "hard"
        self.curves, self.moved, self.rigid = {}, {}, {}
        # more than one point selected: scaling changes only the position of the points, not their size (pscale) and not
        # the line around each individual point
        chosen = {(c.pids or {}).get(k, (id(c), k)) for c, k in points}
        chosen |= {(c.pids or {}).get(j, (id(c), j)) for c, a, b in segs for j in (a, b)}
        self.multi = len(chosen) > 1
        anchors = []
        for c, k in points:
            self._mark(c, k)
            anchors.append(c.points[k][None])
        for c, a, b in segs:
            self._mark(c, a)
            self._mark(c, b)
            self.rigid.setdefault(id(c), set()).add((a, b))
            anchors.append(c.points[a:b + 1])
        self.anchor_pts = np.vstack(anchors) if anchors else np.zeros((1, 3))
        index = index if index is not None else KnotIndex(scene)
        if weld:
            for key in list(self.moved):
                c = self.curves[key]
                for k in list(self.moved[key]):
                    for _, other, j in index.linked(c, k):
                        if only is None or other.id in only:  # freshly inserted: only within the copy
                            self._mark(other, j)
        self.plan = [(c, knots(c), self.moved[key], self.rigid.get(key, set())) for key, c in self.curves.items()]
        self.soft = {}  # (id(line), knot) -> softness 0 … 1 (1 - hardness)
        for c, ks, moved, _ in self.plan:
            for k in ks:
                soft = 1.0 - hardness(c, k, index)
                if k in moved and self.mode != "auto":
                    soft = 1.0 if self.mode == "soft" else 0.0
                self.soft[(id(c), k)] = soft

    def _mark(self, c, k):
        self.curves[id(c)] = c
        s = self.moved.setdefault(id(c), set())
        s.add(k)
        n = len(c.points)
        if is_closed(c.points) and k in (0, n - 1):  # seam: start and end are the same point
            s.update((0, n - 1))

    @property
    def refs(self):
        return []

    def bounds(self):
        return self.anchor_pts.min(axis=0), self.anchor_pts.max(axis=0)

    def pivot(self):
        lo, hi = self.bounds()
        return (lo + hi) / 2

    def local_axes(self):
        return np.eye(3)

    def _apply(self, fn, lin=None):
        """fn: transformation of the points; lin: its linear part (rotation/scale, None = translation only).
        Pieces between a moved and a fixed point: the surroundings of the moved point do the whole
        transformation around it (rotation turns the line there, scaling stretches it – orient/pscale) and
        taper off softly toward the neighbor; the neighbor stays."""
        for c, ks, moved, rigid in self.plan:
            old = c.points
            new = old.copy()

            def local(k, pts):  # transformation around point k: it ends up where fn puts it, surroundings rotated/stretched
                p = old[k]
                if lin is None:
                    return pts + (fn(p[None])[0] - p)
                return fn(p[None])[0] + (pts - p) @ lin.T

            for a, b in zip(ks[:-1], ks[1:]):
                if (a, b) in rigid or (a in moved and b in moved):
                    new[a:b + 1] = fn(old[a:b + 1])
                elif a in moved or b in moved:
                    t = _arc_t(old[a:b + 1])
                    seg = old[a:b + 1]
                    if a in moved:  # from the dragged point a to the neighbor b
                        w = _falloff(t, self.soft[(id(c), a)], self.soft[(id(c), b)])
                        new[a:b + 1] = seg + w[:, None] * (local(a, seg) - seg)
                    else:
                        w = _falloff(1 - t, self.soft[(id(c), b)], self.soft[(id(c), a)])
                        new[a:b + 1] = seg + w[:, None] * (local(b, seg) - seg)
            c.points = new
        self.anchor_pts = fn(self.anchor_pts)

    def _record(self, rot=None, factor=1.0):
        """Carry along the point attributes of the moved points: orient rotates along, pscale grows along (F4). Points and their
        lines do not change during a drag: determine once."""
        from . import network
        if getattr(self, "_pid_refs", None) is None:
            network.sync(self.scene)
            refs = network.refs_by_pid(self.scene)
            pids = {network.pid_of(c, k) for c, _, moved, _ in self.plan for k in moved} - {None}
            self._pid_refs = (pids, {p: refs.get(p, []) for p in pids})
        pids, refs = self._pid_refs
        q_rot = network.quat_of(rot) if rot is not None else None
        for pid in pids:
            v = network.get_attr(self.scene, pid, refs)
            q = np.asarray(v[:4], float)
            if q_rot is not None:
                q = network.quat_mul(q_rot, q)
                q /= np.linalg.norm(q)
            network.set_attr(self.scene, pid, (*q, v[4] * factor), refs)

    def translate(self, delta):
        self._apply(lambda pts: pts + delta)

    def rotate(self, rot, pivot):
        self._apply(lambda pts: pivot + (pts - pivot) @ rot.T, rot)
        self._record(rot=rot)

    def scale(self, factors, axes, pivot):
        m = axes @ np.diag(factors) @ axes.T
        if self.multi:  # point selection: scale only the position
            return self._apply(lambda pts: pivot + (pts - pivot) @ m.T)
        self._apply(lambda pts: pivot + (pts - pivot) @ m.T, m)
        self._record(factor=float(np.prod(np.abs(factors)) ** (1 / 3)))  # pscale: mean stretch


# --- Rounding (Ctrl+B) ------------------------------------------------------------------------------

def _interp(pts, wid, arc, s):
    """Point and width at arc length s."""
    i = int(np.clip(np.searchsorted(arc, s, side="right") - 1, 0, len(pts) - 2))
    t = (s - arc[i]) / max(arc[i + 1] - arc[i], 1e-12)
    return pts[i] + t * (pts[i + 1] - pts[i]), wid[i] + t * (wid[i + 1] - wid[i])


def fillet(corner, a, b):
    """Circular arc from a to b that touches both legs (corner -> a, corner -> b) tangentially.
    None if the legs continue (almost) straight or reverse."""
    u1, u2 = a - corner, b - corner
    d1, d2 = np.linalg.norm(u1), np.linalg.norm(u2)
    if d1 < 1e-9 or d2 < 1e-9:
        return None
    ang = float(np.arccos(np.clip(u1 @ u2 / (d1 * d2), -1, 1)))  # interior angle of the corner
    if ang > np.pi - 0.03 or ang < 0.02:
        return None
    bis = u1 / d1 + u2 / d2
    bis /= np.linalg.norm(bis)
    center = corner + bis * ((d1 + d2) / 2) / np.cos(ang / 2)
    va, vb = a - center, b - center
    sweep = np.pi - ang
    n = max(4, int(np.ceil(sweep / (np.pi / 24))))
    t = np.linspace(0, 1, n + 1)[:, None]
    return center + (np.sin((1 - t) * sweep) * va + np.sin(t * sweep) * vb) / np.sin(sweep)


def roll_closed(curve, start):
    """Rotate a closed line so that it starts at point start (the old seam becomes an ordinary knot)."""
    pts, wid = curve.points, curve.widths
    n = len(pts)
    inner = knots(curve)[1:-1]
    m = n - 1  # points without the duplicated seam point
    curve.points = np.vstack([pts[start:-1], pts[:start + 1]])
    curve.widths = np.concatenate([wid[start:-1], wid[:start + 1]])
    curve.knots = (n, tuple(sorted({(k - start) % m for k in inner + [0]} - {0})))


class Bevel:
    """Ctrl+B: round selected points. A corner in the middle of a line is replaced by an arc;
    if exactly two line ends meet (e.g. a rectangle made of four lines), both are shortened and connected with
    a new arc. The size is the distance from the corner point along the legs; it is limited
    per corner to just under half of the adjoining edges. apply(d) always starts from the original."""

    def __init__(self, scene, positions):
        from .scene import Curve
        self._Curve = Curve
        self.scene = scene
        owners = {c.id: st for st in scene.strokes for c in st.curves}
        self.jobs = {}  # id(line) -> dict(curve, orig, corners)
        self.joints = []  # (corner point, (line, end), (line, end), stroke for the arc)
        places, seen = [], []
        index = KnotIndex(scene)
        for p in positions:
            if any(np.linalg.norm(p - q) < WELD_TOL for q in seen):
                continue
            seen.append(np.asarray(p, float).copy())
            # corner on the seam of a closed line: move the seam elsewhere, then it is an ordinary corner
            for _, c, k in index.at(p):
                if is_closed(c.points) and k in (0, len(c.points) - 1) and id(c) not in self.jobs:
                    others = knots(c)[1:-1]
                    roll_closed(c, others[len(others) // 2] if others else (len(c.points) - 1) // 2)
                    self._job(c)
            places.append(seen[-1])
        index = KnotIndex(scene)
        for p in places:
            at = [(c, k) for _, c, k in index.at(p)]
            inner = [(c, k) for c, k in at if 0 < k < len(c.points) - 1]
            ends = [(c, 0 if k == 0 else -1) for c, k in at if k in (0, len(c.points) - 1)]
            for c, k in inner:
                self._job(c)["corners"].add(k)
            if not inner and len(ends) == 2 and ends[0][0] is not ends[1][0]:
                for c, _ in ends:
                    self._job(c)
                self.joints.append((p, ends[0], ends[1], owners.get(ends[0][0].id)))
        self.arcs = []  # (stroke, arc) from the last apply
        self.outlines = []  # (fill surface, outline members before): an arc at an outline corner belongs to the outline
        self.flat = False  # straight chamfer instead of arc
        self.count = sum(len(j["corners"]) for j in self.jobs.values()) + len(self.joints)

    def _job(self, c):
        if id(c) not in self.jobs:
            knots(c)
            self.jobs[id(c)] = dict(curve=c, orig=(c.points.copy(), c.widths.copy(), c.knots), corners=set())
        return self.jobs[id(c)]

    def restore(self):
        for job in self.jobs.values():
            c = job["curve"]
            c.points, c.widths, c.knots = job["orig"][0].copy(), job["orig"][1].copy(), job["orig"][2]
        for owner, arc in self.arcs:
            if arc in owner.curves:
                owner.curves.remove(arc)
        self.arcs = []
        for surface, links in reversed(self.outlines):
            surface.links = links
        self.outlines = []

    def apply(self, d):
        self.restore()
        if d <= 1e-9:
            return
        trims = {}  # (id(line), end) -> distance
        for _, (c1, e1), (c2, e2), _ in self.joints:
            dd = min(d, self._limit(c1, e1), self._limit(c2, e2))
            trims[(id(c1), e1)] = trims[(id(c2), e2)] = dd
        new_ends = {}
        for job in self.jobs.values():
            new_ends.update(self._bevel_curve(job, d, trims))
        for p, (c1, e1), (c2, e2), owner in self.joints:
            a, b = new_ends.get((id(c1), e1)), new_ends.get((id(c2), e2))
            if a is None or b is None or owner is None:
                continue
            pts = None if self.flat else fillet(p, a, b)
            if pts is None:
                pts = np.array([a, b])
            w = float((c1.widths.mean() + c2.widths.mean()) / 2)
            # from line end to line end: there their width, in between proportional
            arc = self._Curve(pts, c1.plane_id, widths_between(pts, [c1], [c2], w))
            arc.style, arc.color = c1.style, c1.color
            arc.knots = (len(pts), ())
            owner.curves.append(arc)
            self.arcs.append((owner, arc))
            # corner in the outline of a fill surface: the arc replaces the corner there too (otherwise the outline would be
            # interrupted and the surface would remain with a sharp corner)
            self.outlines += self.scene.outline_insert(c1, e1, c2, arc)

    def _limit(self, c, end):
        """At most just under half of the first/last edge of the line (measured from the original)."""
        pts, _, kn = self.jobs[id(c)]["orig"]
        n = len(pts)
        ks = [0, *[k for k in kn[1] if 0 < k < n - 1], n - 1]
        seg = pts[:ks[1] + 1] if end == 0 else pts[ks[-2]:]
        return 0.49 * float(np.linalg.norm(np.diff(seg, axis=0), axis=1).sum())

    def _bevel_curve(self, job, d, trims):
        c = job["curve"]
        pts, wid, kn = job["orig"]
        n = len(pts)
        arc = np.concatenate([[0], np.cumsum(np.linalg.norm(np.diff(pts, axis=0), axis=1))])
        length = arc[-1]
        ks = [0, *[k for k in kn[1] if 0 < k < n - 1], n - 1]
        ranges = []  # (s0, s1, replacement points, replacement widths, knots in the replacement)
        done = set()
        for k in sorted(job["corners"]):
            j = ks.index(k)
            dd = min(d, 0.49 * (arc[k] - arc[ks[j - 1]]), 0.49 * (arc[ks[j + 1]] - arc[k]))
            (a, wa), (b, wb) = _interp(pts, wid, arc, arc[k] - dd), _interp(pts, wid, arc, arc[k] + dd)
            rep = fillet(pts[k], a, b)
            if rep is None:
                continue
            if self.flat:
                rep = np.array([a, b])
            done.add(k)
            ranges.append((arc[k] - dd, arc[k] + dd, rep, np.linspace(wa, wb, len(rep)), (0, len(rep) - 1)))
        ends = {}
        if (id(c), 0) in trims:
            dd = trims[(id(c), 0)]
            a, wa = _interp(pts, wid, arc, dd)
            ranges.append((-np.inf, dd, a[None], np.array([wa]), ()))
            ends[(id(c), 0)] = a
        if (id(c), -1) in trims:
            dd = trims[(id(c), -1)]
            a, wa = _interp(pts, wid, arc, length - dd)
            ranges.append((length - dd, np.inf, a[None], np.array([wa]), ()))
            ends[(id(c), -1)] = a
        if not ranges:
            return ends
        ranges.sort(key=lambda r: r[0])
        out_p, out_w, new_knots = [], [], []
        keep = set(ks) - done

        def originals(lo, hi):
            for i in range(n):
                if lo < arc[i] < hi or (i == 0 and lo == -np.inf and hi > 0):
                    if i in keep and 0 < i < n - 1:
                        new_knots.append(len(out_p))
                    out_p.append(pts[i])
                    out_w.append(wid[i])

        prev = -np.inf
        for s0, s1, rep, rw, rk in ranges:
            if s0 > -np.inf:
                originals(prev, s0)
            base = len(out_p)
            new_knots += [base + i for i in rk]
            out_p += list(rep)
            out_w += list(rw)
            prev = s1
        if prev < np.inf:
            originals(prev, np.inf)
        c.points, c.widths = np.array(out_p), np.array(out_w)
        m = len(c.points)
        c.knots = (m, tuple(sorted({k for k in new_knots if 0 < k < m - 1})))
        return ends


# --- Bevel at three-way corners (edges of a box, as in Blender) ----------------------------------------

def _leave_dir(c, end):
    """Direction in which line c leaves its end end (0/-1) (first piece)."""
    pts = c.points
    v = pts[1] - pts[0] if end == 0 else pts[-2] - pts[-1]
    n = float(np.linalg.norm(v))
    return v / n if n > 1e-12 else None


def _length(pts):
    return float(np.linalg.norm(np.diff(pts, axis=0), axis=1).sum())


def _trim(c, orig, end, d):
    """Shorten line c (original orig = (points, widths, knots)) at end end by the arc length d; returns
    the new end point."""
    pts, wid, kn = orig
    n = len(pts)
    arc = np.concatenate([[0], np.cumsum(np.linalg.norm(np.diff(pts, axis=0), axis=1))])
    inner = [k for k in kn[1] if 0 < k < n - 1] if kn else []
    if end == 0:
        p, w = _interp(pts, wid, arc, d)
        keep = np.flatnonzero(arc > d + 1e-12)
        c.points, c.widths = np.vstack([p, pts[keep]]), np.concatenate([[w], wid[keep]])
        shift = 1
    else:
        p, w = _interp(pts, wid, arc, arc[-1] - d)
        keep = np.flatnonzero(arc < arc[-1] - d - 1e-12)
        c.points, c.widths = np.vstack([pts[keep], p]), np.concatenate([wid[keep], [w]])
        shift = 0
    pos = {int(k): j + shift for j, k in enumerate(keep)}
    m = len(c.points)
    c.knots = (m, tuple(sorted(pos[k] for k in inner if k in pos and 0 < pos[k] < m - 1)))
    return c.points[0] if end == 0 else c.points[-1]


def star(index, point):
    """Line ends at point, if at least three lines meet there with their ends: [(line, end)],
    otherwise None. Corners in the middle of a line do not count (there rounding two legs applies)."""
    at = index.at(point)
    if any(0 < k < len(c.points) - 1 for _, c, k in at):
        return None
    ends = [(c, 0 if k == 0 else -1) for _, c, k in at]
    if len({id(c) for c, _ in ends}) != len(ends) or len(ends) < 3:
        return None
    return ends


def cyclic_order(dirs):
    """Order of the directions around their corner (like the edges around a mesh point): indices."""
    dirs = np.asarray(dirs, float)
    n = -dirs.sum(axis=0)
    if np.linalg.norm(n) < 0.15 * len(dirs):  # flat (e.g. cross in a plane): normal of the plane
        n = np.linalg.svd(dirs - dirs.mean(axis=0))[2][-1] if len(dirs) > 2 else np.cross(dirs[0], dirs[1])
    n = n / max(np.linalg.norm(n), 1e-12)
    ref = dirs[0] - (dirs[0] @ n) * n
    if np.linalg.norm(ref) < 1e-9:
        ref = np.cross(n, [1.0, 0, 0]) if abs(n[0]) < 0.9 else np.cross(n, [0, 1.0, 0])
    ref /= np.linalg.norm(ref)
    side = np.cross(n, ref)
    ang = np.arctan2(dirs @ side, dirs @ ref)
    return list(np.argsort(ang))


def _neighbours(order, k):
    i = order.index(k)
    return order[i - 1], order[(i + 1) % len(order)]


def _stub(orig, end, d):
    """Piece of the line (original) from end end up to arc length d: points in direction of travel away from the corner."""
    pts, wid, _ = orig
    arc = np.concatenate([[0], np.cumsum(np.linalg.norm(np.diff(pts, axis=0), axis=1))])
    if end == 0:
        p, _ = _interp(pts, wid, arc, d)
        return np.vstack([pts[arc < d - 1e-12], p])
    p, _ = _interp(pts, wid, arc, arc[-1] - d)
    return np.vstack([pts[::-1][arc[-1] - arc[::-1] < d - 1e-12], p])


class EdgeBevel:
    """Edges and corners where three or more lines meet (box, crossings) – as in Blender.
    Edge: is replaced by two edges in the two adjoining sides (sides = the neighbors of the edge
    in the order around the corner); an arc connects it at both ends (flat: straight chamfer). At a three-way
    corner the neighbors are shortened; if more lines meet there, the neighbors are split and the
    corner stays for the rest. Corner (point): all lines shortened, neighbors each connected with an arc.
    apply(d) always starts from the original; finish() re-attaches adjoining fill surfaces and, where
    surfaces adjoin, puts a drawing surface onto the rounding."""

    def __init__(self, scene, edge_curves, corner_points):
        from .scene import Curve
        self._Curve = Curve
        self.scene = scene
        self.flat = False
        owners = {c.id: st for st in scene.strokes for c in st.curves}
        index = KnotIndex(scene)
        self.orig = {}  # id(line) -> (line, (points, widths, knots))
        self.edges = []  # dict(curve, owner, P: (neighbors [(line, end, direction)] x2, split?), Q: ...)
        self.corners = []  # (point, [(line, end, direction)] in around-the-corner order, owner)
        used = set()
        for c in edge_curves:
            if id(c) in used or c.id not in owners:
                continue
            sides = []
            for end in (0, -1):
                ends = star(index, c.points[end])
                if not ends:
                    break
                entries = [(o, e, _leave_dir(o, e)) for o, e in ends]
                if any(t[2] is None for t in entries):
                    break
                me = next((k for k, (o, e, _) in enumerate(entries) if o is c and e == end), None)
                if me is None:
                    break
                order = cyclic_order([t[2] for t in entries])
                a, b = _neighbours(order, me)
                sides.append(([entries[a], entries[b]], len(entries) > 3))
            if len(sides) != 2:
                continue
            (p_side, p_split), (q_side, q_split) = sides
            # assign sides: at the other end the neighbor that goes in the same direction (same side)
            if p_side[0][2] @ q_side[1][2] > p_side[0][2] @ q_side[0][2]:
                q_side = q_side[::-1]
            used.add(id(c))
            self.edges.append(dict(curve=c, owner=owners[c.id], P=p_side, Q=q_side, split=(p_split, q_split)))
            for o in [c] + [t[0] for t in p_side + q_side]:
                self._keep(o)
        for p in corner_points:
            ends = star(index, p)
            if not ends or any(id(o) in used for o, _ in ends):
                continue
            entries = [(o, e, _leave_dir(o, e)) for o, e in ends]
            if any(t[2] is None for t in entries) or any(np.linalg.norm(p - q[0]) < WELD_TOL for q in self.corners):
                continue
            order = cyclic_order([t[2] for t in entries])
            self.corners.append((np.asarray(p, float).copy(), [entries[k] for k in order], owners.get(entries[0][0].id)))
            for o, _, _ in entries:
                self._keep(o)
        self.count = len(self.edges) + len(self.corners)
        self.arcs = []  # (stroke, new line) from the last apply
        self.removed = []  # (stroke, edge, index)
        self.built = []  # per edge dict(e1, e2, arc_p, arc_q, stubs), per corner [(i, j, arc)]

    def _keep(self, c):
        if id(c) not in self.orig:
            knots(c)
            self.orig[id(c)] = (c, (c.points.copy(), c.widths.copy(), c.knots))

    def restore(self):
        for owner, arc in self.arcs:
            if arc in owner.curves:
                owner.curves.remove(arc)
        for owner, c, k in reversed(self.removed):
            if c not in owner.curves:
                owner.curves.insert(min(k, len(owner.curves)), c)
        self.arcs, self.removed, self.built = [], [], []
        for c, (pts, wid, kn) in self.orig.values():
            c.points, c.widths, c.knots = pts.copy(), wid.copy(), kn

    def _limit(self, c):
        return 0.49 * _length(self.orig[id(c)][1][0])

    def _profile(self, corner, a, b):
        pts = None if self.flat else fillet(corner, a, b)
        return np.array([a, b]) if pts is None else pts

    def _add(self, owner, pts, like, widths=None):
        """New line next to/from like: stroke width per point is that of like at the nearest place (before rounding) –
        copies of the edge keep their course, pieces and arcs at the corner the width there."""
        pts = np.asarray(pts, float)
        if widths is None:
            src = self.orig.get(id(like))
            lp, lw = (src[1][0], src[1][1]) if src is not None else (like.points, like.widths)
            widths = (np.array([width_at(lp, lw, p)[1] for p in pts]) if len(lw) else np.full(len(pts), 0.02))
        c = self._Curve(pts, like.plane_id, np.asarray(widths, float))
        c.style, c.color = like.style, like.color
        c.knots = (len(c.points), ())
        owner.curves.append(c)
        self.arcs.append((owner, c))
        return c

    def apply(self, d):
        self.restore()
        if d <= 1e-9:
            return
        for job in self.edges:
            e, owner = job["curve"], job["owner"]
            dd = min([d] + [self._limit(o) for o, _, _ in job["P"] + job["Q"]])
            pts = self.orig[id(e)][1][0]
            s = np.concatenate([[0], np.cumsum(np.linalg.norm(np.diff(pts, axis=0), axis=1))])
            s = (s / max(s[-1], 1e-12))[:, None]
            news = []
            for side in (0, 1):
                a, b = job["P"][side][2], job["Q"][side][2]
                dirs = (1 - s) * a + s * b
                dirs /= np.maximum(np.linalg.norm(dirs, axis=1, keepdims=True), 1e-12)
                news.append(pts + dd * dirs)
            stubs = {}  # id(neighbor) -> piece at the corner (more than three lines: the corner stays)
            for key, split in (("P", job["split"][0]), ("Q", job["split"][1])):
                for o, end, _ in job[key]:
                    if split:
                        stubs[(id(o), end)] = self._add(owner, _stub(self.orig[id(o)][1], end, dd), o)
                    _trim(o, self.orig[id(o)][1], end, dd)
            k = next(j for j, c in enumerate(owner.curves) if c is e)
            owner.curves.remove(e)
            self.removed.append((owner, e, k))
            e1, e2 = self._add(owner, news[0], e), self._add(owner, news[1], e)
            arc_p = self._add(owner, self._profile(pts[0], news[0][0], news[1][0]), e)
            arc_q = self._add(owner, self._profile(pts[-1], news[0][-1], news[1][-1]), e)
            self.built.append(dict(e1=e1, e2=e2, arc_p=arc_p, arc_q=arc_q, stubs=stubs))
        for p, side, owner in self.corners:
            if owner is None:
                self.built.append([])
                continue
            dd = min([d] + [self._limit(o) for o, _, _ in side])
            ends = [_trim(o, self.orig[id(o)][1], end, dd) for o, end, _ in side]
            n = len(side)
            arcs = []
            for i in range(n):
                prof = self._profile(p, ends[i], ends[(i + 1) % n])
                w = float(side[0][0].widths.mean()) if len(side[0][0].widths) else 0.02
                # from one line to the next: at both ends their width, in between proportional
                arcs.append((i, (i + 1) % n, self._add(owner, prof, side[0][0], widths_between(
                    prof, [side[i][0]], [side[(i + 1) % n][0]], w))))
            self.built.append(arcs)

    def finish(self):
        """Re-attach adjoining fill surfaces to the new edges, pieces and arcs; where surfaces adjoin, put a
        drawing surface onto the rounding (loft between the end arcs or surface in the corner)."""
        sc = self.scene
        made = 0
        fills = [f for f in sc.surfaces if type(f).__name__ == "SurfaceObject" and f.links]
        for job, built in zip(self.edges, self.built):
            e = job["curve"]
            touching = [f for f in fills if any(e.id in sc.link_ids(cid) for cid, _ in f.links)]
            for f in touching:  # the surface lies in the side whose neighbor also borders it
                ids = {i for cid, _ in f.links for i in sc.link_ids(cid)}
                pick = built["e1"] if job["P"][0][0].id in ids or job["Q"][0][0].id in ids else built["e2"]
                f.links = [(self._swap(cid, e.id, [pick.id]), fl) for cid, fl in f.links]
            for (key, end), stub in built["stubs"].items():  # remaining surfaces at split neighbors: add the piece
                o = next(t[0] for t in job["P"] + job["Q"] if id(t[0]) == key and t[1] == end)
                for f in fills:
                    if f in touching:
                        continue
                    chain = [stub.id, o.id] if end == 0 else [o.id, stub.id]
                    f.links = [(self._swap(cid, o.id, chain), fl) for cid, fl in f.links]
            if touching:
                sc.create_loft([("lines", [built["arc_p"].id]), ("lines", [built["arc_q"].id])],
                               [built["arc_p"].points, built["arc_q"].points], prefix=tr("Rundung"))
                made += 1
        for (p, side, owner), built in zip(self.corners, self.built[len(self.edges):]):
            if not built:
                continue
            touching = False
            for f in fills:
                links = list(f.links)
                for i, j, arc in built:
                    a, b = side[i][0].id, side[j][0].id
                    for k in range(len(links)):
                        here, nxt = sc.link_ids(links[k][0]), sc.link_ids(links[(k + 1) % len(links)][0])
                        if (a in here and b in nxt) or (b in here and a in nxt):
                            first = side[i] if a in here else side[j]
                            tip = first[0].points[0] if first[1] == 0 else first[0].points[-1]
                            flipped = bool(np.linalg.norm(arc.points[0] - tip) > np.linalg.norm(arc.points[-1] - tip))
                            links.insert(k + 1, (arc.id, flipped))
                            touching = True
                            break
                f.links = links
            if touching:
                sc.create_fill([(arc, False) for _, _, arc in built])
                made += 1
        return made

    @staticmethod
    def _swap(cid, old, new):
        """In outline member cid replace the line old by the chain new."""
        if isinstance(cid, list):
            out = []
            for i in cid:
                out += new if i == old else [i]
            return out
        if cid == old:
            return new[0] if len(new) == 1 else list(new)
        return cid


class BevelSet:
    """Several roundings together (corners of two lines + three-way corners and edges) as one tool."""

    def __init__(self, ops):
        self.ops = [op for op in ops if op.count]
        self.count = sum(op.count for op in self.ops)
        self.flat = False

    @property
    def arcs(self):
        return [a for op in self.ops for a in op.arcs]

    def set_flat(self, flat):
        self.flat = flat
        for op in self.ops:
            op.flat = flat

    def apply(self, d):
        for op in self.ops:
            op.apply(d)

    def restore(self):
        for op in reversed(self.ops):
            op.restore()

    def finish(self):
        return sum(op.finish() for op in self.ops if hasattr(op, "finish"))

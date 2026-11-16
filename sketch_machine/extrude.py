"""Extruding in the line philosophy: a line becomes its offset copy and a few
connecting lines - as few as possible, as many as needed to tell the shape.

Rule for the connecting lines ("edges that are pulled along"):
  1. Ends of an open line: always.
  2. Corners (kink from CORNER_DEG, measured over a short stretch - hand jitter does not count): always.
  3. Curves: one line per about SMOOTH_STEP_DEG of turning, evenly distributed by turning.
     A circle gets four this way; two of them lie on the silhouette from the current view.
"""

import numpy as np

CORNER_DEG = 30.0  # from this kink on it is a corner - the same threshold everywhere (= hardness 0.5, components.sharpness)
SMOOTH_STEP_DEG = 90.0  # curves: one connecting line per this much turning
SAMPLES = 240  # line sampled evenly for measuring
CORNER_SPAN = 0.05  # measure the kink over this much of the line length
SMOOTH_WINDOW = 5  # sample points for smoothing before measuring (against jitter)
CLOSED_GAP = 0.01  # start and end closer than this (fraction of the length): closed line


def _resample(points, n):
    arc = np.concatenate([[0], np.cumsum(np.linalg.norm(np.diff(points, axis=0), axis=1))])
    t = np.linspace(0, arc[-1], n)
    return np.stack([np.interp(t, arc, points[:, i]) for i in range(3)], axis=1), arc[-1]


def _smooth(points, closed):
    """Moving average over SMOOTH_WINDOW sample points (closed: all the way around)."""
    k = SMOOTH_WINDOW // 2
    if closed:
        return np.mean([np.roll(points, s, axis=0) for s in range(-k, k + 1)], axis=0)
    padded = np.vstack([np.repeat(points[:1], k, axis=0), points, np.repeat(points[-1:], k, axis=0)])
    return np.mean([padded[k + s:len(padded) - k + s] for s in range(-k, k + 1)], axis=0)


def _angle(a, b):
    na, nb = np.linalg.norm(a, axis=-1), np.linalg.norm(b, axis=-1)
    cos = np.einsum("...i,...i->...", a, b) / np.maximum(na * nb, 1e-18)
    return np.degrees(np.arccos(np.clip(cos, -1, 1)))


def is_closed(points):
    length = float(np.linalg.norm(np.diff(points, axis=0), axis=1).sum())
    return length > 0 and np.linalg.norm(points[0] - points[-1]) < CLOSED_GAP * length


def rail_points(points, direction, view, fixed=()):
    """Points on the line where connecting lines arise when extruding in direction.
    view: view direction (toward the camera), for the silhouette of closed curves.
    fixed: points on the line that get connecting lines in any case and count like corners
    (joints of composite lines); they are taken over exactly."""
    points = np.asarray(points, float)
    if len(points) < 2:
        return []
    closed = is_closed(points)
    even, length = _resample(points, SAMPLES + (1 if closed else 0))
    if closed:
        even = even[:-1]  # last point = first
    n = len(even)
    measure = _smooth(even, closed)  # measured on the slightly smoothed line
    m = max(2, int(round(CORNER_SPAN * SAMPLES)))
    idx = np.arange(n)
    if closed:
        before, after = measure - measure[(idx - m) % n], measure[(idx + m) % n] - measure
        valid = np.ones(n, bool)
    else:
        before = measure - measure[np.clip(idx - m, 0, n - 1)]
        after = measure[np.clip(idx + m, 0, n - 1)] - measure
        valid = (idx >= m) & (idx < n - m)
    knick = np.where(valid, _angle(before, after), 0.0)
    corners = _peaks(knick >= CORNER_DEG, knick, closed)
    pinned = {}
    for f in fixed:
        i = int(np.argmin(np.linalg.norm(even - f, axis=1)))
        if closed or i not in (0, n - 1):
            pinned[i] = np.asarray(f, float)
    corners = sorted(set(c for c in corners if all(min(abs(c - i), n - abs(c - i)) > m for i in pinned)) | set(pinned))
    # turning between neighboring sample points (for curves), not counted at corners
    # direction measured over the same short span as the corners: jitter does not add up
    if closed:
        tangent = measure[(idx + m) % n] - measure[(idx - m) % n]
        turn = _angle(tangent, tangent[(idx + 1) % n])
    else:
        tangent = measure[np.clip(idx + m, 0, n - 1)] - measure[np.clip(idx - m, 0, n - 1)]
        turn = np.append(_angle(tangent[:-1], tangent[1:]), 0.0)
    near_corner = np.zeros(n, bool)
    for c in corners:
        near_corner[(np.arange(c - m, c + m + 1) % n) if closed else np.clip(np.arange(c - m, c + m + 1), 0, n - 1)] = True
    raw_turn = turn
    turn = np.where(near_corner, 0.0, turn)

    picks = list(corners)
    if not closed:
        picks += [0, n - 1]
        bounds = sorted(set([0, n - 1] + corners))
        for a, b in zip(bounds[:-1], bounds[1:]):
            picks += _spread(turn, list(range(a, b)), closed_loop=False)
    elif corners:
        bounds = sorted(corners)
        for k, a in enumerate(bounds):
            b = bounds[(k + 1) % len(bounds)]
            span = list(range(a, b)) if b > a else list(range(a, n)) + list(range(0, b))
            picks += _spread(turn, span, closed_loop=False)
        # strongly rounded corners count as a corner sometimes, sometimes not (jitter): if the ring thereby has fewer
        # connecting lines than its turning requires, distribute evenly by turning - starting at
        # the strongest corner and at fixed joints
        expected = max(int(round(float(raw_turn.sum()) / SMOOTH_STEP_DEG)), 3)
        if len(set(picks)) < expected and not pinned:
            start = max(corners, key=lambda c: knick[c])
            order = list(range(start, n)) + list(range(0, start))
            cum = np.cumsum(raw_turn[order]) - raw_turn[order][0]
            total = float(raw_turn.sum())
            picks = [order[int(np.searchsorted(cum, total * j / expected))] for j in range(expected)]
    else:  # closed curve (circle): evenly by turning, starting at the silhouette
        side = np.cross(tangent, direction)
        start = int(np.argmin(np.abs(side @ view) / np.maximum(np.linalg.norm(side, axis=1), 1e-12)))
        order = list(range(start, n)) + list(range(0, start))
        total = float(turn.sum())
        count = max(int(round(total / SMOOTH_STEP_DEG)), 3)
        cum = np.cumsum(turn[order]) - turn[order][0]
        picks += [order[int(np.searchsorted(cum, total * j / count))] for j in range(count)]
    out = [points[0]] if not closed else []
    out += [pinned.get(i, even[i]) for i in sorted(set(picks)) if closed or i not in (0, n - 1)]
    if not closed:
        out.append(points[-1])
    return out


def _peaks(mask, values, closed):
    """Per connected region above the threshold the index with the strongest kink."""
    n = len(mask)
    if not mask.any():
        return []
    if mask.all():
        return [int(np.argmax(values))]
    runs, i = [], 0
    start = int(np.argmin(mask)) if closed else 0  # closed: start at a spot without a kink
    order = [(start + k) % n for k in range(n)] if closed else list(range(n))
    run = []
    for i in order + [None]:
        if i is not None and mask[i]:
            run.append(i)
        elif run:
            runs.append(max(run, key=lambda j: values[j]))
            run = []
    return runs


def _spread(turn, span, closed_loop):
    """Inner connecting lines on a smooth piece: max(round(turning / step) - 1, 0),
    evenly distributed by accumulated turning."""
    if len(span) < 3:
        return []
    t = turn[span]
    total = float(t.sum())
    k = max(int(round(total / SMOOTH_STEP_DEG)) - 1, 0)
    if not k:
        return []
    cum = np.cumsum(t)
    return [span[min(int(np.searchsorted(cum, total * j / (k + 1))), len(span) - 1)] for j in range(1, k + 1)]


def chains(polylines, tolerance):
    """Join lines that meet at their ends into chains -> [(points, joints)].
    Branches (more than two ends at a point) end a chain."""
    lines = [np.asarray(p, float) for p in polylines]
    ends = [(k, e) for k in range(len(lines)) for e in (0, -1)]
    def partners(k, e):
        p = lines[k][e]
        return [(j, f) for j, f in ends if (j, f) != (k, e) and np.linalg.norm(lines[j][f] - p) <= tolerance]
    used, out = set(), []
    def walk(k, start_end):
        pts, joints = [lines[k] if start_end == 0 else lines[k][::-1]], []
        first = k
        used.add(k)
        tail = -1 if start_end == 0 else 0
        while True:
            nb = partners(k, tail)
            if len(nb) != 1 or nb[0][0] in used:
                if len(nb) == 1 and nb[0][0] == first and len(pts) > 1:
                    joints.append(lines[k][tail].copy())  # ring closed: the seam is also a joint
                break
            j, f = nb[0]
            joints.append(lines[k][tail].copy())
            used.add(j)
            pts.append((lines[j] if f == 0 else lines[j][::-1])[1:])
            k, tail = j, (-1 if f == 0 else 0)
        return np.vstack(pts), joints
    # open chains first start at a free end, then rings
    for k in range(len(lines)):
        for e in (0, -1):
            if k not in used and len(partners(k, e)) != 1:
                out.append(walk(k, 0 if e == 0 else -1))
    for k in range(len(lines)):
        if k not in used:
            out.append(walk(k, 0))
    return out


def chain_rails(polylines, direction, view, tolerance, extra=()):
    """Connecting lines for several selected lines: connected pieces count as one line
    (an already split copy gets the same connecting lines on the next extrusion, not
    twice as many); their joints always get one. extra: further points that get one in any case
    (nodes with a kink, connections - extruding.knot_rails)."""
    rails = []
    for pts, joints in chains(polylines, tolerance):
        on = [np.asarray(p, float) for p in extra if _near_polyline(pts, p) <= max(tolerance * 10, 1e-9)]
        fixed = list(joints) + [p for p in on if all(np.linalg.norm(p - q) > tolerance for q in joints)]
        for r in rail_points(pts, direction, view, fixed=fixed):
            if all(np.linalg.norm(r - q) > tolerance for q in rails):
                rails.append(np.asarray(r, float))
    return rails


def _near_polyline(pts, p):
    a, b = pts[:-1], pts[1:]
    ab = b - a
    t = np.clip(np.einsum("ij,ij->i", p - a, ab) / np.maximum(np.einsum("ij,ij->i", ab, ab), 1e-18), 0, 1)
    return float(np.min(np.linalg.norm(a + ab * t[:, None] - p, axis=1)))


def reseat(points, widths, start):
    """Reorder a closed line so that it starts and ends at start (a point on it) -
    the seam then lies on a connecting line instead of creating an extra piece."""
    pts, wid = np.asarray(points, float)[:-1], np.asarray(widths, float)[:-1]  # last point = first
    ring = np.vstack([pts, pts[:1]])
    a, b = ring[:-1], ring[1:]
    ab = b - a
    t = np.clip(np.einsum("ij,ij->i", start - a, ab) / np.maximum(np.einsum("ij,ij->i", ab, ab), 1e-18), 0, 1)
    i = int(np.argmin(np.linalg.norm(a + ab * t[:, None] - start, axis=1)))
    w = wid[i] + (wid[(i + 1) % len(wid)] - wid[i]) * t[i]
    order = [(i + 1 + k) % len(pts) for k in range(len(pts))]
    new_pts = np.vstack([start, pts[order], start])
    new_wid = np.concatenate([[w], wid[order], [w]])
    keep = np.concatenate([[True], np.linalg.norm(np.diff(new_pts, axis=0), axis=1) > 1e-12])  # duplicate points
    return new_pts[keep], new_wid[keep]

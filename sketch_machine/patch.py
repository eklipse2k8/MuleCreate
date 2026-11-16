"""Curve surface (Alt+F): a smooth, curved drawing surface made of bent boundary curves – like Fill, but not flat.

Method: Coons surface (the classic method for surfaces from four boundary curves, basis of Rhino's
"Network Surface"): the four borders are blended across each other, the corners subtracted once. From the
chosen curves a closed outline is made (small gaps between the ends are bridged); it is
split into four sides at four corners – at the joints of the curves where the outline bends most; with fewer
than four joints the longest side is split in the middle. The surface is stored as a loft through rows of the Coons
surface and follows its boundary curves, like a loft follows its cross sections.
"""
import numpy as np

ROWS = 13  # rows (cross sections) of the surface
SAMPLES = 48  # points per row
GAP_REL = 0.25  # gap between two curve ends: at most this much of the mean curve length


def _length(pts):
    return float(np.linalg.norm(np.diff(pts, axis=0), axis=1).sum()) if len(pts) > 1 else 0.0


def order_loop(curves):
    """Order curves [points] into an outline: [(index, reversed)] or None (gap too big / no outline)."""
    n = len(curves)
    if n == 0:
        return None
    mean = np.mean([_length(c) for c in curves])
    tol = GAP_REL * max(mean, 1e-9)
    order = [(0, False)]
    left = set(range(1, n))
    end = curves[0][-1]
    while left:
        best = None
        for i in left:
            for flip in (False, True):
                start = curves[i][-1] if flip else curves[i][0]
                d = float(np.linalg.norm(start - end))
                if best is None or d < best[0]:
                    best = (d, i, flip)
        if best[0] > tol:
            return None
        _, i, flip = best
        order.append((i, flip))
        left.remove(i)
        end = curves[i][0] if flip else curves[i][-1]
    first = curves[0][0]
    if n > 1 and float(np.linalg.norm(end - first)) > tol:
        return None
    if n == 1 and float(np.linalg.norm(curves[0][-1] - curves[0][0])) > tol:
        return None
    return order


def loop_points(curves, order, legacy=False):
    """Points of the closed outline and the joints [(index in the outline)] (start of each curve: its first point,
    for coinciding ends the shared one). legacy: as before v0.83 – there the joint lay one point behind
    the shared one (only for converting older corner data)."""
    pts, joints = [], []
    for i, flip in order:
        c = curves[i][::-1] if flip else curves[i]
        shared = bool(pts) and np.linalg.norm(pts[-1] - c[0]) <= 1e-9
        joints.append(len(pts) - 1 if shared and not legacy else len(pts))
        pts.extend(c[1:] if shared else c)
    return np.asarray(pts, float), joints


def _turn(loop, k):
    n = len(loop)
    a, b = loop[k] - loop[(k - 2) % n], loop[(k + 2) % n] - loop[k]
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    if na < 1e-12 or nb < 1e-12:
        return 0.0
    return float(np.arccos(np.clip(a @ b / (na * nb), -1, 1)))


def corners(loop, joints):
    """Four corners (indices in the outline): joints with the strongest bend; if some are missing, the middle of the longest side."""
    arc = np.concatenate([[0], np.cumsum(np.linalg.norm(np.diff(np.vstack([loop, loop[:1]]), axis=0), axis=1))])
    total = arc[-1]
    cs = sorted(set(sorted(joints, key=lambda k: -_turn(loop, k))[:4]))
    while len(cs) < 4:
        if not cs:
            cs = [0]
            continue
        best = None
        for j, a in enumerate(cs):
            b = cs[(j + 1) % len(cs)]
            la = (arc[b] - arc[a]) % total if len(cs) > 1 else total
            la = la or total
            if best is None or la > best[0]:
                best = (la, a)
        la, a = best
        mid = int(np.argmin(np.abs(arc[:-1] - (arc[a] + la / 2) % total)))
        if mid in cs:
            break
        cs = sorted(set(cs + [mid]))
    return cs


def _resample(pts, m):
    pts = np.asarray(pts, float)
    arc = np.concatenate([[0], np.cumsum(np.linalg.norm(np.diff(pts, axis=0), axis=1))])
    if arc[-1] <= 1e-12:
        return np.repeat(pts[:1], m, axis=0)
    t = np.linspace(0, arc[-1], m)
    return np.stack([np.interp(t, arc, pts[:, i]) for i in range(3)], axis=1)


def sides(loop, cs):
    """The four sides between the corners (each including both corners)."""
    n = len(loop)
    out = []
    for j in range(4):
        a, b = cs[j], cs[(j + 1) % 4]
        idx = [(a + k) % n for k in range(((b - a) % n) + 1)]
        out.append(loop[idx])
    return out


def coons_rows(side_pts, rows=ROWS, samples=SAMPLES):
    """Coons surface from four sides (in loop order) -> rows (rows, samples, 3)."""
    c0 = _resample(side_pts[0], samples)  # bottom, u: 0 -> 1
    c1 = _resample(side_pts[1], rows)  # right, v: 0 -> 1
    c2 = _resample(side_pts[2], samples)[::-1]  # top, u: 0 -> 1
    c3 = _resample(side_pts[3], rows)[::-1]  # left, v: 0 -> 1
    u = np.linspace(0, 1, samples)[None, :, None]
    v = np.linspace(0, 1, rows)[:, None, None]
    p00, p10, p11, p01 = c0[0], c0[-1], c2[-1], c2[0]
    ruled_v = (1 - v) * c0[None] + v * c2[None]
    ruled_u = (1 - u) * c3[:, None] + u * c1[:, None]
    bilinear = ((1 - u) * (1 - v)) * p00 + (u * (1 - v)) * p10 + (u * v) * p11 + ((1 - u) * v) * p01
    return ruled_v + ruled_u - bilinear


def _side_fractions(loop, joints, j):
    """For curve j in the outline: (first index, shares of the arc length of its points 0..1)."""
    a = joints[j]
    end = joints[j + 1] if j + 1 < len(joints) else len(loop)
    pts = loop[a:end + 1] if end < len(loop) else np.vstack([loop[a:], loop[:1]])
    arc = np.concatenate([[0], np.cumsum(np.linalg.norm(np.diff(pts, axis=0), axis=1))])
    return a, arc / max(arc[-1], 1e-12)


def corner_indices(loop, joints, spec, arc=False):
    """Corner indices in the outline from stored corners (curve, share); arc: share of the arc length (stays correct
    when a boundary curve gets more points), otherwise share of the points (older files)."""
    cs = []
    for j, f in spec:
        if arc:
            a, frac = _side_fractions(loop, joints, j)
            k = a + int(np.argmin(np.abs(frac - f)))
        else:
            end = joints[j + 1] if j + 1 < len(joints) else len(loop)
            k = joints[j] + int(round(f * max(end - joints[j], 1)))
        cs.append(min(k, len(loop) - 1))
    return sorted(set(cs))


def arc_spec(curves, order, spec):
    """Convert older corner data (share of points, old joints) into shares of the arc length – the corners stay
    at exactly the same point of the outline, the surface keeps its shape."""
    loop, old_joints = loop_points(curves, order, legacy=True)
    _, joints = loop_points(curves, order)
    out = []
    for j, f in spec:
        k = corner_indices(loop, old_joints, [(j, f)])[0]
        a, frac = _side_fractions(loop, joints, j)
        out.append((j, float(frac[min(max(k - a, 0), len(frac) - 1)])))
    return out


def border_sides(curves, order, corner_spec, arc=True):
    """The four sides (polylines, exactly on the boundary curves) for stored corners or None. The first side begins
    at the first stored corner (matches row 0 of the rest shape), even if the loop starts elsewhere."""
    loop, joints = loop_points(curves, order)
    cs = _ordered_corners(loop, joints, corner_spec, arc)
    return sides(loop, cs) if len(cs) == 4 else None


def _ordered_corners(loop, joints, spec, arc):
    """Corner indices in the stored order (the first side begins at the first corner = row 0 of the
    rest shape); if they do not lie in the loop, ascending as before. Rest shape and border must use the same one."""
    cs = [corner_indices(loop, joints, [c], arc)[0] for c in spec]
    n = len(loop)
    if len(set(cs)) != 4 or sum((cs[(i + 1) % 4] - cs[i]) % n for i in range(4)) != n:
        return corner_indices(loop, joints, spec, arc)
    return cs


def keep_direction(curves, order, corner_points):
    """Turn the loop so that the corners (in their previous order) lie in loop direction again."""
    loop, _ = loop_points(curves, order)
    n = len(loop)
    cs = [int(np.argmin(np.linalg.norm(loop - np.asarray(p, float), axis=1))) for p in corner_points]
    if sum((cs[(i + 1) % len(cs)] - cs[i]) % n for i in range(len(cs))) == n:
        return order
    return [(i, not f) for i, f in reversed(order)]


def build_rows(curves, order, corner_spec=None, arc=False):
    """Rows of the surface from the current curves; corner_spec: stored corners (index, share) per curve in the outline,
    so the surface keeps the same corners when deformed (arc: share of the arc length). -> (rows, corner_spec)"""
    loop, joints = loop_points(curves, order)
    if corner_spec is None:
        cs = corners(loop, joints)
        spec = []
        for k in cs:  # remember corner as (curve in the outline, share)
            j = max(i for i, s in enumerate(joints) if s <= k)
            if arc:
                a, frac = _side_fractions(loop, joints, j)
                spec.append((j, float(frac[k - a])))
            else:
                end = joints[j + 1] if j + 1 < len(joints) else len(loop)
                spec.append((j, (k - joints[j]) / max(end - joints[j], 1)))
    else:
        spec = corner_spec
        cs = _ordered_corners(loop, joints, spec, arc)  # like border_sides: row 0 = first side
        if len(cs) < 4:
            return build_rows(curves, order, None, arc)
    return coons_rows(sides(loop, cs)), spec


def spec_for_points(curves, order, corner_points):
    """Corner data (curve in the loop, share of the arc length) for corners at these places – after rebuilding the
    outline (lines merged) the corners stay exactly where they were."""
    loop, joints = loop_points(curves, order)
    spec = []
    for p in corner_points:
        k = int(np.argmin(np.linalg.norm(loop - np.asarray(p, float), axis=1)))
        j = max(i for i, s in enumerate(joints) if s <= k)
        a, frac = _side_fractions(loop, joints, j)
        spec.append((j, float(frac[min(k - a, len(frac) - 1)])))
    return spec


def folds(g):
    """Folds the grid (R, M, 3) – do neighboring cells flip over (normals opposite)? Returns the number of such
    neighbor pairs. Smooth, even strongly curved surfaces have none; a four-corner grid in an inward-bent
    outline (L shape, star) does. Cells without area (sharp corners) do not count."""
    g = np.asarray(g, float)
    n = np.cross(g[:-1, 1:] - g[:-1, :-1], g[1:, :-1] - g[:-1, :-1])
    size = np.linalg.norm(n, axis=2)
    ok = size > 1e-6 * max(float(np.median(size)), 1e-18)
    u = np.where(ok[..., None], n / np.maximum(size, 1e-30)[..., None], 0)
    flip = 0
    for a, b, m in ((u[:, :-1], u[:, 1:], ok[:, :-1] & ok[:, 1:]), (u[:-1], u[1:], ok[:-1] & ok[1:])):
        flip += int(((np.einsum("ijk,ijk->ij", a, b) < -0.5) & m).sum())
    return flip

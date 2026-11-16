"""Net surface (trial run): the surface is the result of its real lines.

The border yields the base surface (curve surface: Coons surface of the border lines). All real lines on the surface
deform it smoothly, like sheet metal: what is sought is a displacement of the surface grid that
  - is null at the border (the base surface is already right there),
  - puts the surface exactly through the line at the lines,
  - in between is bent as little as possible (thin plate: squared Laplace derivative), with some tautness
    (gradient), so that it does not overshoot far between lines lying close together.
It is solved on the full surface grid (sparse, scipy; the factorization is reused as long as the
lines only move). Bending and tautness are computed in world units and do not depend on the resolution:
STIFF is the length (fraction of the surface size) from which the surface becomes taut – below it, it bends
smoothly like sheet metal, above it, it stretches like a membrane and does not overshoot far.

Hardness (K): at hard lines the surface may kink – the bending does not count there (the tautness stays), interpolated along
a line between its points. Without set hardness every line is soft (smooth across).

The lines are never moved by the surface (hierarchy: points -> lines -> surface -> painting). Each line
has a fixed position in the surface parameter (uv, determined when drawing); it only says where the surface meets it.
"""
import numpy as np


from . import loft
from . import lru

import scipy.sparse as sparse
from scipy.sparse.linalg import splu

STIFF = 0.03  # tautness: from this length (fraction of the surface size) the surface stretches; None = pure sheet metal
FIT_REL = 1.0e4  # weight of the lines compared to bending and tautness (practically exact)
MAX_SLOPE = 3.0  # contradiction: two lines lie closer on the surface than their height difference at this slope
                 # (3 = a good 70°) allows (e.g. cross unconnected at different heights) -> averaged there
MAX_SAMPLES = 48  # sample points per line (nodes always)

_CACHE = {}


def samples(points, uv, on, knots=()):
    """Sample points of a line: indices (evenly distributed, at most MAX_SAMPLES, nodes always), only points on the
    surface."""
    n = len(points)
    idx = set(np.linspace(0, n - 1, min(n, MAX_SAMPLES)).astype(int).tolist()) | {k for k in knots if 0 <= k < n}
    return np.array(sorted(k for k in idx if on is None or on[k]), int)


def _frac_index_uniform(side, n):
    """Fractional point indices of n evenly distributed (by arc length) places on the polyline side."""
    arc = np.concatenate([[0], np.cumsum(np.linalg.norm(np.diff(side, axis=0), axis=1))])
    if arc[-1] <= 1e-12:
        return np.zeros(n)
    return np.interp(np.linspace(0, arc[-1], n), arc, np.arange(len(side), dtype=float))


def _at_index(side, idx):
    side = np.asarray(side, float)
    i0 = np.clip(np.floor(idx).astype(int), 0, len(side) - 2)
    t = np.clip(idx - i0, 0.0, 1.0)[:, None]
    return side[i0] * (1 - t) + side[i0 + 1] * t


def _index_of(side, pts):
    """Fractional point indices of the nearest places on the polyline side to pts (in order, never backwards)."""
    side, pts = np.asarray(side, float), np.asarray(pts, float)
    a, ab = side[:-1], np.diff(side, axis=0)
    ll = np.maximum(np.einsum("ij,ij->i", ab, ab), 1e-18)
    t = np.clip(np.einsum("pij,ij->pi", pts[:, None] - a[None], ab) / ll[None], 0, 1)
    d = np.linalg.norm(a[None] + t[..., None] * ab[None] - pts[:, None], axis=2)
    i = np.argmin(d, axis=1)
    return np.maximum.accumulate(i + t[np.arange(len(pts)), i])


def boundary_track(state, sides, r, m):
    """Attach border nodes to fixed places of the border lines: per side one fractional point index per node. If
    only parts of the border line move, only the border nodes there move (redistributing evenly by arc length
    would shift all nodes of the side – the surface shears and folds). If the point count of a side changes
    (new point inserted, shape the same), it is converted via the location. Returns (state, target places per side)."""
    sizes = [m, r, m, r]
    out, targets = [], []
    for k, side in enumerate(sides):
        side = np.asarray(side, float)
        st = state[k] if state and len(state) == 4 and state[k] is not None else None
        if st is None or len(st["idx"]) != sizes[k]:
            idx = _frac_index_uniform(side, sizes[k])
        elif st["n"] != len(side):
            if st.get("pts") is not None:
                idx = _index_of(side, _at_index(st["pts"], st["idx"]))
            else:
                idx = _frac_index_uniform(side, sizes[k])
        else:
            idx = np.asarray(st["idx"], float)
        idx = idx.copy()
        idx[0], idx[-1] = 0.0, float(len(side) - 1)  # corners
        out.append({"idx": idx, "n": len(side), "pts": side.copy()})
        targets.append(_at_index(side, idx))
    return out, targets


def boundary_from_targets(base, targets):
    """Displacement of the border nodes (r, m, 3; inside 0) to the target places of the four sides (bottom, right, top, left)."""
    out = np.zeros_like(base)
    out[0] = targets[0] - base[0]
    out[:, -1] = targets[1] - base[:, -1]
    out[-1] = targets[2][::-1] - base[-1]
    out[:, 0] = targets[3][::-1] - base[:, 0]
    return out


def _q(x):
    """Round to 5 % steps (the factorization stays valid as long as the surface stretches only a little)."""
    return float(np.exp(np.round(np.log(max(x, 1e-12)) / 0.05) * 0.05))


def average_conflicts(at, resid, groups, normals=None):
    """Average contradictions: if sample points of different lines (groups) lie so close on the base surface (at) that
    their height difference (resid along the surface normal normals) would be steeper than MAX_SLOPE, their targets approach
    the mean – fully at distance null, not at all up to the allowed distance. Otherwise the smooth surface would have to
    swing out far there. Lateral differences (line moved, border dragged) are no contradiction."""
    if groups is None or len(at) < 2:
        return resid
    at, resid, groups = np.asarray(at, float), np.asarray(resid, float), np.asarray(groups)
    height = np.einsum("ij,ij->i", resid, normals) if normals is not None else np.linalg.norm(resid, axis=1)
    out = resid.copy()
    reach = float(np.abs(height).max()) / MAX_SLOPE if len(height) else 0.0
    if reach <= 0:
        return out
    for j in range(len(at)):
        other = np.flatnonzero(groups != groups[j])
        d = np.linalg.norm(at[other] - at[j], axis=1)
        near = d < reach
        if not near.any():
            continue
        k = other[near]
        diff = np.abs(height[k] - height[j])
        f = np.clip(1.0 - d[near] * MAX_SLOPE / np.maximum(diff, 1e-12), 0.0, 1.0)
        if f.max() <= 0:
            continue
        w = 0.5 * f  # both move toward each other: at f = 1 they meet in the middle
        dh = (w * (height[k] - height[j])).sum() / max(1.0, w.sum() * 2)
        out[j] = resid[j] + dh * (normals[j] if normals is not None else resid[j] / max(np.linalg.norm(resid[j]), 1e-12))
    return out


def crease_points(uv, groups, hard, step=0.5):
    """Hard places in the surface parameter: sample points with hardness > 0, filled in between (same line) in steps of step
    -> (positions (K, 2), hardness (K,)). Empty if nothing is hard."""
    if hard is None or not len(uv) or not np.any(np.asarray(hard) > 1e-6):
        return np.zeros((0, 2)), np.zeros(0)
    uv, hard = np.asarray(uv, float), np.asarray(hard, float)
    groups = np.zeros(len(uv)) if groups is None else np.asarray(groups)
    pts, hs = [uv[hard > 1e-6]], [hard[hard > 1e-6]]
    for i in range(len(uv) - 1):
        if groups[i] != groups[i + 1] or max(hard[i], hard[i + 1]) <= 1e-6:
            continue
        n = int(np.ceil(np.linalg.norm(uv[i + 1] - uv[i]) / step))
        if n > 1:
            t = np.linspace(0, 1, n + 1)[1:-1, None]
            pts.append(uv[i] + t * (uv[i + 1] - uv[i]))
            hs.append(hard[i] + t[:, 0] * (hard[i + 1] - hard[i]))
    return np.vstack(pts), np.concatenate(hs)


def _crease_grid(r, m, uv, groups, hard, closed=False):
    """Hardness per grid node (r, m): the nodes of the cells a hard line runs through."""
    out = np.zeros((r, m))
    at, hs = crease_points(uv, groups, hard)
    if not len(at):
        return out
    ri = np.clip(np.floor(at[:, 0]).astype(int), 0, r - 2)
    cu = np.mod(at[:, 1], m) if closed else np.clip(at[:, 1], 0, m - 1)
    ci = np.floor(cu).astype(int) % m if closed else np.clip(np.floor(cu).astype(int), 0, m - 2)
    for di in (0, 1):
        for dj in (0, 1):
            np.maximum.at(out, (ri + di, (ci + dj) % m), hs)
    return out


def _bend_weights(crease):
    """Weight of bending per node: (almost) none at hard places – the surface may kink there."""
    return np.maximum(1.0 - np.asarray(crease, float), 1e-4)


def _normals_at(uv, base):
    """Surface normals of the base surface at the places uv."""
    du = loft.evaluate_grid(uv + [0.5, 0], base, False) - loft.evaluate_grid(uv - [0.5, 0], base, False)
    dv = loft.evaluate_grid(uv + [0, 0.5], base, False) - loft.evaluate_grid(uv - [0, 0.5], base, False)
    n = np.cross(du, dv)
    return n / np.maximum(np.linalg.norm(n, axis=1), 1e-12)[:, None]


def solve(base, uv, targets, groups=None, boundary=None, hard=None):
    """Displacement (r, m, 3) of the grid base (r, m, 3) so that the surface at uv (N, 2) goes through targets (N, 3)
    (contradictions between lines – groups: line per sample point – averaged). The border gets the displacement
    boundary (r, m, 3, only border nodes read; None: border fixed). hard: hardness per sample point (it may kink there)."""
    r, m = base.shape[:2]
    if r < 3 or m < 3 or (not len(uv) and boundary is None):
        return np.zeros_like(base)
    uv = np.asarray(uv, float).reshape(-1, 2)
    at = loft.evaluate_grid(uv, base, False) if len(uv) else np.zeros((0, 3))
    if len(uv):
        targets = at + average_conflicts(at, np.asarray(targets, float).reshape(-1, 3) - at, groups, _normals_at(uv, base))
    hr = float(np.mean(np.linalg.norm(np.diff(base, axis=0), axis=2))) or 1.0
    hc = float(np.mean(np.linalg.norm(np.diff(base, axis=1), axis=2))) or 1.0
    size = float(np.linalg.norm(np.ptp(base.reshape(-1, 3), axis=0))) or 1.0
    uv = np.asarray(uv, float)
    crease = _crease_grid(r, m, uv, groups, hard)
    key = ("sparse", r, m, _q(hr), _q(hc), _q(size), STIFF, uv.tobytes(), np.round(crease, 3).tobytes())
    op = _CACHE.get(key)
    if op is None:
        op = _sparse_operator(r, m, _q(hr), _q(hc), _q(size), uv, crease)
        lru.trim(_CACHE, 384)
        _CACHE[key] = op
    lu, p_in, p_bd, q_ib, w, inner, border = op
    d_b = np.zeros((len(border[0]), 3)) if boundary is None else np.asarray(boundary, float)[border[0], border[1]]
    rhs = -(q_ib @ d_b)
    if len(uv):
        rhs = rhs + w * (p_in.T @ ((targets - at) - p_bd @ d_b))
    x = lu.solve(np.ascontiguousarray(rhs))
    out = np.zeros_like(base)
    out[inner[0], inner[1]] = x
    out[border[0], border[1]] = d_b
    return out


def _sparse_operator(r, m, hr, hc, size, uv, crease=None):
    """Factorized system matrix on the full grid: bending (Laplace²) + tautness (gradient²) + lines. Computed
    over all nodes; the border nodes are given (q_ib moves their displacement to the right-hand side)."""
    nn = r * m
    node = np.arange(nn).reshape(r, m)
    ii, jj = np.meshgrid(np.arange(1, r - 1), np.arange(1, m - 1), indexing="ij")
    ii, jj = ii.ravel(), jj.ravel()
    area = hr * hc
    rows, cols, vals = [], [], []
    e = np.arange(len(ii))
    for di, dj, wgt in ((0, 0, -2 / hr ** 2 - 2 / hc ** 2), (-1, 0, 1 / hr ** 2), (1, 0, 1 / hr ** 2),
                        (0, -1, 1 / hc ** 2), (0, 1, 1 / hc ** 2)):
        rows.append(e)
        cols.append(node[ii + di, jj + dj])
        vals.append(np.full(len(e), wgt))
    lap = sparse.csr_matrix((np.concatenate(vals), (np.concatenate(rows), np.concatenate(cols))), shape=(len(e), nn))
    if crease is not None and crease.any():
        lap = sparse.diags(_bend_weights(crease[ii, jj])) @ lap
    q = area * (lap.T @ lap)
    if STIFF:
        grads = []
        for di, dj, hh in ((1, 0, hr), (0, 1, hc)):
            a = node[:r - di, :m - dj].ravel()
            b = node[di:, dj:].ravel()
            k = np.arange(len(a))
            grads.append(sparse.csr_matrix((np.concatenate([np.full(len(a), -1 / hh), np.full(len(b), 1 / hh)]),
                                            (np.concatenate([k, k]), np.concatenate([a, b]))), shape=(len(a), nn)))
        g = sparse.vstack(grads)
        q = q + area / (STIFF * size) ** 2 * (g.T @ g)
    q = q.tocsr()
    is_in = np.zeros(nn, bool)
    is_in[node[ii, jj]] = True
    inn, bd = np.flatnonzero(is_in), np.flatnonzero(~is_in)
    # lines: bilinear weights of the sample points in the grid
    ri = np.clip(np.floor(uv[:, 0]).astype(int), 0, r - 2)
    ci = np.clip(np.floor(uv[:, 1]).astype(int), 0, m - 2)
    rt, ct = np.clip(uv[:, 0] - ri, 0, 1), np.clip(uv[:, 1] - ci, 0, 1)
    prow, pcol, pval = [], [], []
    for di, wr in ((0, 1 - rt), (1, rt)):
        for dj, wc in ((0, 1 - ct), (1, ct)):
            prow.append(np.arange(len(uv)))
            pcol.append(node[ri + di, ci + dj])
            pval.append(wr * wc)
    p = sparse.csr_matrix((np.concatenate(pval), (np.concatenate(prow), np.concatenate(pcol))), shape=(len(uv), nn))
    # sample points in a border cell do not count: there the border fixes the surface; a deviation
    # between line and border would otherwise be hugely amplified via the small inner weight
    inside = np.asarray(p[:, inn].sum(axis=1)).ravel() > 1 - 1e-9
    p = (sparse.diags(inside.astype(float)) @ p).tocsc()
    p_in, p_bd = p[:, inn].tocsr(), p[:, bd].tocsr()
    q_ii, q_ib = q[inn][:, inn], q[inn][:, bd]
    w = FIT_REL * float(q_ii.diagonal().mean())
    a = (q_ii + w * (p_in.T @ p_in) + 1e-12 * w * sparse.identity(len(inn))).tocsc()
    return splu(a), p_in, p_bd, q_ib.tocsr(), w, (inn // m, inn % m), (bd // m, bd % m)


def transfer(old_pts, old_uv, old_on, new_pts):
    """Transfer the uv of a line whose points have changed (points inserted, resampled): each new
    point gets the position of the nearest place on the old line."""
    old_pts, new_pts = np.asarray(old_pts, float), np.asarray(new_pts, float)
    old_uv = np.asarray(old_uv, float)
    on = np.ones(len(old_pts), bool) if old_on is None else np.asarray(old_on, bool)
    if len(old_pts) < 2:
        return np.repeat(old_uv[:1], len(new_pts), axis=0), np.repeat(on[:1], len(new_pts))
    a, ab = old_pts[:-1], np.diff(old_pts, axis=0)
    ll = np.maximum(np.einsum("ij,ij->i", ab, ab), 1e-18)
    t = np.clip(np.einsum("pij,ij->pi", new_pts[:, None] - a[None], ab) / ll[None], 0, 1)  # (N, S)
    d = np.linalg.norm(a[None] + t[..., None] * ab[None] - new_pts[:, None], axis=2)
    i = np.argmin(d, axis=1)
    ti = t[np.arange(len(new_pts)), i][:, None]
    uv = old_uv[i] * (1 - ti) + old_uv[i + 1] * ti
    return uv, np.where(ti[:, 0] < 0.5, on[i], on[i + 1])



REREST = 2.5  # redistribute when the grid cells are stretched more unequally than this relative to each other (compared to the rest shape)


def distortion(g, rest):
    """How unevenly is the grid g stretched compared to the rest shape? Ratio of the strongly to the weakly stretched
    cells (98th to 2nd percentile, per direction); tiny cells of the rest shape (converging corners) do not count."""
    out = 1.0
    for axis in (0, 1):
        lg = np.linalg.norm(np.diff(g, axis=axis), axis=2)
        lr = np.linalg.norm(np.diff(rest, axis=axis), axis=2)
        ok = lr > 0.2 * float(np.median(lr))
        if ok.sum() < 4:
            continue
        ratio = lg[ok] / lr[ok]
        out = max(out, float(np.percentile(ratio, 98)) / max(float(np.percentile(ratio, 2)), 1e-12))
    return out


def project(g, uv, pts, window=2, rounds=8):
    """Determine the position (uv) of the points pts on the grid g: nearest point of the surface near the start value uv
    (window cells wide per round; if the hit lies at the window edge, the search continues from there). (uv, distance)"""
    uv = np.asarray(uv, float).reshape(-1, 2)
    pts = np.asarray(pts, float).reshape(-1, 3)
    out, dist = uv.copy(), np.full(len(uv), np.inf)
    todo = np.arange(len(uv))
    for _ in range(rounds):
        if not len(todo):
            break
        new, d = _project_window(g, out[todo], pts[todo], window)
        moved = np.abs(new - out[todo]).max(axis=1)
        out[todo], dist[todo] = new, d
        todo = todo[moved > window - 1.0]
    return out, dist


def _project_window(g, uv, pts, window):
    r, m = g.shape[:2]
    n = len(pts)
    best_d = np.full(n, np.inf)
    best_uv = uv.copy()
    i0 = np.clip(np.floor(uv[:, 0]).astype(int), 0, r - 2)
    j0 = np.clip(np.floor(uv[:, 1]).astype(int), 0, m - 2)
    for di in range(-window, window + 1):
        for dj in range(-window, window + 1):
            i = np.clip(i0 + di, 0, r - 2)
            j = np.clip(j0 + dj, 0, m - 2)
            p00, p01, p10, p11 = g[i, j], g[i, j + 1], g[i + 1, j], g[i + 1, j + 1]
            for a, b, c, ua, ub, uc in ((p00, p01, p11, (0, 0), (0, 1), (1, 1)), (p00, p11, p10, (0, 0), (1, 1), (1, 0))):
                w = _closest_bary(pts, a, b, c)
                q = w[:, :1] * a + w[:, 1:2] * b + w[:, 2:] * c
                d = np.linalg.norm(q - pts, axis=1)
                better = d < best_d - 1e-12
                if better.any():
                    cu = np.stack([w[:, 0] * ua[0] + w[:, 1] * ub[0] + w[:, 2] * uc[0],
                                   w[:, 0] * ua[1] + w[:, 1] * ub[1] + w[:, 2] * uc[1]], axis=1)
                    best_d[better] = d[better]
                    best_uv[better] = np.stack([i, j], axis=1)[better] + cu[better]
    return best_uv, best_d


def _closest_bary(p, a, b, c):
    """Barycentric weights of the (approximately) nearest point on the triangles (a, b, c) to p."""
    ab, ac, ap = b - a, c - a, p - a
    d00 = np.einsum("ij,ij->i", ab, ab)
    d01 = np.einsum("ij,ij->i", ab, ac)
    d11 = np.einsum("ij,ij->i", ac, ac)
    d20 = np.einsum("ij,ij->i", ap, ab)
    d21 = np.einsum("ij,ij->i", ap, ac)
    den = np.maximum(d00 * d11 - d01 * d01, 1e-18)
    v = np.clip((d11 * d20 - d01 * d21) / den, 0, 1)
    w = np.clip((d00 * d21 - d01 * d20) / den, 0, 1)
    s = v + w
    over = s > 1
    v = np.where(over, v / np.maximum(s, 1e-18), v)
    w = np.where(over, w / np.maximum(s, 1e-18), w)
    return np.stack([1 - v - w, v, w], axis=1)


def _even(values, pos):
    """1D: resample values (n, k) evenly along their arc length; returns (new values, old indices)."""
    n = len(values)
    arc = np.concatenate([[0], np.cumsum(np.linalg.norm(np.diff(pos, axis=0), axis=1))])
    if arc[-1] <= 1e-12:
        return values.copy(), np.arange(n, dtype=float)
    idx = np.interp(np.linspace(0, arc[-1], n), arc, np.arange(n, dtype=float))
    i0 = np.clip(np.floor(idx).astype(int), 0, n - 2)
    t = (idx - i0)[:, None]
    return values[i0] * (1 - t) + values[i0 + 1] * t, idx


def even_grid(g):
    """Redistribute the grid evenly without changing the shape: first each column, then each row by arc length.
    Returns (new grid, old row per new node, old column per new node)."""
    r, m = g.shape[:2]
    g1 = np.empty_like(g)
    i1 = np.empty((r, m))
    for j in range(m):
        vals = np.concatenate([g[:, j], np.arange(r, dtype=float)[:, None]], axis=1)
        new, _ = _even(vals, g[:, j])
        g1[:, j], i1[:, j] = new[:, :3], new[:, 3]
    g2 = np.empty_like(g)
    i2, j2 = np.empty((r, m)), np.empty((r, m))
    for a in range(r):
        vals = np.concatenate([g1[a], i1[a][:, None], np.arange(m, dtype=float)[:, None]], axis=1)
        new, _ = _even(vals, g1[a])
        g2[a], i2[a], j2[a] = new[:, :3], new[:, 3], new[:, 4]
    return g2, i2, j2


def locate(g, pts):
    """Position (uv) of the points pts on the grid g: searched exactly starting from the spatially nearest grid point. (uv, distance)"""
    from scipy.spatial import cKDTree
    r, m = g.shape[:2]
    pts = np.asarray(pts, float).reshape(-1, 3)
    if not len(pts):
        return np.zeros((0, 2)), np.zeros(0)
    _, k = cKDTree(g.reshape(-1, 3)).query(pts)
    start = np.stack([k // m, k % m], axis=1).astype(float)
    return project(g, start, pts)


def solve_rows(base, uv, targets, groups, fixed_rows, closed, hard=None):
    """Loft as net surface: displacement (r, m, 3) of the grid so that the surface goes through the lines (uv/targets).
    Only the cross-section rows fixed_rows are fixed (the surface already lies exactly on the cross-section lines there);
    the sides of open lofts are free, closed lofts run around without a seam (column m-1 borders 0)."""
    r, m = base.shape[:2]
    uv = np.asarray(uv, float).reshape(-1, 2)
    if not len(uv) or r < 2 or m < 2:
        return np.zeros_like(base)
    at = loft.evaluate_grid(uv, base, closed)
    targets = at + average_conflicts(at, np.asarray(targets, float).reshape(-1, 3) - at, groups,
                                     _normals_at_loft(uv, base, closed))
    hr = float(np.mean(np.linalg.norm(np.diff(base, axis=0), axis=2))) or 1.0
    hc = float(np.mean(np.linalg.norm(np.diff(base, axis=1), axis=2))) or 1.0
    size = float(np.linalg.norm(np.ptp(base.reshape(-1, 3), axis=0))) or 1.0
    fixed_rows = tuple(sorted({int(x) for x in fixed_rows if 0 <= x < r}))
    crease = _crease_grid(r, m, uv, groups, hard, closed)
    key = ("rows", r, m, _q(hr), _q(hc), _q(size), STIFF, closed, fixed_rows, uv.tobytes(),
           np.round(crease, 3).tobytes())
    op = _CACHE.get(key)
    if op is None:
        lru.trim(_CACHE, 384)
        op = _CACHE[key] = _rows_operator(r, m, _q(hr), _q(hc), _q(size), uv, fixed_rows, closed, crease)
    lu, p_in, w, inn = op
    out = np.zeros_like(base)
    if lu is None:
        return out
    x = lu.solve(np.ascontiguousarray(w * (p_in.T @ (targets - at))))
    out.reshape(-1, 3)[inn] = x
    return out


def _normals_at_loft(uv, g, closed):
    ev = lambda q: loft.evaluate_grid(q, g, closed)
    du, dv = ev(uv + [0.5, 0]) - ev(uv - [0.5, 0]), ev(uv + [0, 0.5]) - ev(uv - [0, 0.5])
    n = np.cross(du, dv)
    return n / np.maximum(np.linalg.norm(n, axis=1), 1e-12)[:, None]


def _rows_operator(r, m, hr, hc, size, uv, fixed_rows, closed, crease=None):
    nn = r * m
    node = np.arange(nn).reshape(r, m)
    area = hr * hc
    # Laplace over the existing neighbors (open sides: one-sided; closed: all around)
    rows, cols, vals = [], [], []
    for i in range(r):
        for di in (-1, 1):
            if 0 <= i + di < r:
                rows.append(node[i]); cols.append(node[i + di]); vals.append(np.full(m, 1 / hr ** 2))
                rows.append(node[i]); cols.append(node[i]); vals.append(np.full(m, -1 / hr ** 2))
    for dj in (-1, 1):
        j = np.arange(m)
        nb = (j + dj) % m if closed else j + dj
        ok = np.ones(m, bool) if closed else (nb >= 0) & (nb < m)
        for i in range(r):
            rows.append(node[i][ok]); cols.append(node[i][nb[ok]]); vals.append(np.full(ok.sum(), 1 / hc ** 2))
            rows.append(node[i][ok]); cols.append(node[i][ok]); vals.append(np.full(ok.sum(), -1 / hc ** 2))
    lap = sparse.csr_matrix((np.concatenate(vals), (np.concatenate(rows), np.concatenate(cols))), shape=(nn, nn))
    if crease is not None and crease.any():
        lap = sparse.diags(_bend_weights(crease.ravel())) @ lap
    q = area * (lap.T @ lap)
    if STIFF:
        grads = []
        a, b = node[:-1].ravel(), node[1:].ravel()
        k = np.arange(len(a))
        grads.append(sparse.csr_matrix((np.concatenate([np.full(len(a), -1 / hr), np.full(len(a), 1 / hr)]),
                                        (np.concatenate([k, k]), np.concatenate([a, b]))), shape=(len(a), nn)))
        a = node[:, :m if closed else m - 1].ravel()
        b = node[:, (np.arange(m if closed else m - 1) + 1) % m].ravel()
        k = np.arange(len(a))
        grads.append(sparse.csr_matrix((np.concatenate([np.full(len(a), -1 / hc), np.full(len(a), 1 / hc)]),
                                        (np.concatenate([k, k]), np.concatenate([a, b]))), shape=(len(a), nn)))
        g = sparse.vstack(grads)
        q = q + area / (STIFF * size) ** 2 * (g.T @ g)
    q = q.tocsr()
    fixed = np.zeros((r, m), bool)
    fixed[list(fixed_rows)] = True
    inn = np.flatnonzero(~fixed.ravel())
    if not len(inn):
        return None, None, 0.0, inn
    ri = np.clip(np.floor(uv[:, 0]).astype(int), 0, r - 2)
    rt = np.clip(uv[:, 0] - ri, 0, 1)
    cu = np.mod(uv[:, 1], m) if closed else np.clip(uv[:, 1], 0, m - 1)
    ci = np.floor(cu).astype(int)
    ci = ci % m if closed else np.minimum(ci, m - 2)
    ct = np.clip(cu - ci, 0, 1)
    prow, pcol, pval = [], [], []
    for di, wr in ((0, 1 - rt), (1, rt)):
        for dj, wc in ((0, 1 - ct), (1, ct)):
            prow.append(np.arange(len(uv)))
            pcol.append(node[ri + di, (ci + dj) % m])
            pval.append(wr * wc)
    p = sparse.csr_matrix((np.concatenate(pval), (np.concatenate(prow), np.concatenate(pcol))), shape=(len(uv), nn))
    inside = np.asarray(p[:, inn].sum(axis=1)).ravel() > 1 - 1e-9  # sample points at fixed rows: it is already right there
    p = (sparse.diags(inside.astype(float)) @ p).tocsc()
    p_in = p[:, inn].tocsr()
    q_ii = q[inn][:, inn]
    w = FIT_REL * float(q_ii.diagonal().mean())
    a = (q_ii + w * (p_in.T @ p_in) + 1e-12 * w * sparse.identity(len(inn))).tocsc()
    return splu(a), p_in, w, inn


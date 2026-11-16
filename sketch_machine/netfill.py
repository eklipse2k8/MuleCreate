"""Net surface for fill surfaces: the surface is the result of its outline and all real lines on it.

Like the curve surface (netsurf.py), only on a triangle mesh instead of a grid:
  - Rest net: the flat rest shape of the outline (cage.rest) triangulated evenly, with points in the interior. It
    depends only on the rest shape and is cached.
  - Base surface: each net point follows the current outline via mean-value coordinates (like painting and lines);
    border points lie exactly on the outline.
  - Displacement by the lines: smooth like sheet metal (bi-Laplace with cotangent weights) with some tautness,
    border fixed, the surface passes through all real lines; contradictions are averaged (netsurf.average_conflicts).
The surface never moves the lines; painting sits on the deformed surface (evaluate).
"""
import numpy as np

from . import cage, lru, netsurf

DENSITY = 100  # net points along the size of the surface (spacing = size / DENSITY); coarser and the surface overshoots
               # far on narrow, steep line arcs

import scipy.sparse as sparse
from scipy.sparse.linalg import splu
from scipy.spatial import Delaunay

_DOMAINS = {}


class Domain:
    """Rest net of a fill surface: points (N, 2), triangles (M, 3), border points first (0 ... nb-1), weights (N, K) onto
    the cage (base surface = weights @ cage) and a lookup of the triangle of a rest position."""

    def __init__(self, rest, density=DENSITY):
        rest = np.asarray(rest, float)
        size = float(np.linalg.norm(np.ptp(rest, axis=0))) or 1.0
        h = size / max(float(density), 4.0)
        k = len(rest)
        # border: cage edges in pieces of about h, exactly on the edges (linear weights onto two cage points)
        bpts, brows = [], []
        for i in range(k):
            a, b = rest[i], rest[(i + 1) % k]
            n = max(1, int(np.ceil(np.linalg.norm(b - a) / h)))
            for s in range(n):
                t = s / n
                bpts.append(a + t * (b - a))
                w = np.zeros(k)
                w[i] += 1 - t
                w[(i + 1) % k] += t
                brows.append(w)
        bpts = np.array(bpts)
        # interior: offset grid, only clearly inside the outline
        lo, hi = rest.min(axis=0), rest.max(axis=0)
        ys = np.arange(lo[1] + h / 2, hi[1], h * np.sqrt(3) / 2)
        grid = [np.stack([np.arange(lo[0] + (h / 2 if r % 2 else 0) + h / 4, hi[0], h), np.full_like(
            np.arange(lo[0] + (h / 2 if r % 2 else 0) + h / 4, hi[0], h), y)], axis=1) for r, y in enumerate(ys)]
        inner = np.vstack(grid) if grid else np.zeros((0, 2))
        if len(inner):
            inner = inner[_inside(inner, rest)]
            if len(inner):
                d = np.min(np.linalg.norm(inner[:, None] - bpts[None], axis=2), axis=1)
                inner = inner[d > 0.45 * h]
        self.nb = len(bpts)
        self.points = np.vstack([bpts, inner])
        tri = Delaunay(self.points)
        simp = tri.simplices
        cent = self.points[simp].mean(axis=1)
        keep = _inside(cent, rest)
        area = _area2(self.points, simp)
        keep &= np.abs(area) > 1e-12 * size * size
        self.tris = simp[keep].astype(np.int32)
        self.delaunay = tri
        self.map = -np.ones(len(simp), int)  # Delaunay triangle -> kept triangle
        self.map[np.flatnonzero(keep)] = np.arange(keep.sum())
        wi = cage.weights(inner, rest) if len(inner) else np.zeros((0, k))
        self.weights = np.vstack([np.array(brows), wi])
        self.rest = rest
        self.size = size

    def locate(self, uv):
        """(triangle, barycentric weights) per rest position; -1 outside the net."""
        uv = np.asarray(uv, float).reshape(-1, 2)
        s = self.delaunay.find_simplex(uv)
        t = np.where(s >= 0, self.map[np.maximum(s, 0)], -1)
        bary = np.zeros((len(uv), 3))
        ok = t >= 0
        if ok.any():
            tr = self.delaunay.transform[s[ok]]
            b = np.einsum("nij,nj->ni", tr[:, :2], uv[ok] - tr[:, 2])
            full = np.column_stack([b, 1 - b.sum(axis=1)])
            # order of the corners: Delaunay triangle s is the same as kept t
            bary[ok] = full
        return t, bary


def _inside(p, poly):
    """Point-in-polygon (ray test), vectorized."""
    p = np.asarray(p, float)
    x, y = p[:, 0][:, None], p[:, 1][:, None]
    a = poly[None]
    b = np.roll(poly, -1, axis=0)[None]
    cond = (a[..., 1] > y) != (b[..., 1] > y)
    xi = a[..., 0] + (y - a[..., 1]) * (b[..., 0] - a[..., 0]) / np.where(np.abs(b[..., 1] - a[..., 1]) < 1e-18, 1e-18,
                                                                          b[..., 1] - a[..., 1])
    return (cond & (x < xi)).sum(axis=1) % 2 == 1


def _area2(p, t):
    a, b, c = p[t[:, 0]], p[t[:, 1]], p[t[:, 2]]
    return (b[:, 0] - a[:, 0]) * (c[:, 1] - a[:, 1]) - (b[:, 1] - a[:, 1]) * (c[:, 0] - a[:, 0])


def domain(rest, density=DENSITY):
    key = np.asarray(rest, float).tobytes() + np.float64(density).tobytes()
    d = _DOMAINS.get(key)
    if d is None:
        # on overflow discard only the older half (before: everything - if more fill surfaces deform at once than there are
        # slots, every frame rebuilt all nets). Deliberately small: a net takes about 1 MB (harbor 11.11.:
        # 2,048 slots cost 370 MB and gained nothing on load, because there each net is needed only once)
        lru.trim(_DOMAINS, 64)
        d = _DOMAINS[key] = Domain(rest, density)
    return d


def _bary_rows(dom, uv):
    """Sparse rows (support point -> net points) for rest positions; support points outside are dropped."""
    t, bary = dom.locate(uv)
    rows, cols, vals = [], [], []
    for j in range(3):
        ok = t >= 0
        rows.append(np.flatnonzero(ok))
        cols.append(dom.tris[t[ok], j] if ok.any() else np.zeros(0, int))
        vals.append(bary[ok, j])
    # Delaunay weights belong to the corners of the Delaunay triangle - the kept triangles have the same corners
    return t, np.concatenate(rows), np.concatenate(cols), np.concatenate(vals)


def _crease(dom, uv, groups, hard):
    """Hardness per net point: the corners of the triangles through which a hard line runs."""
    out = np.zeros(len(dom.points))
    h_cell = dom.size / max(float(np.sqrt(len(dom.points))), 1.0)
    at, hs = netsurf.crease_points(uv, groups, hard, step=0.5 * h_cell)
    if not len(at):
        return out
    t, _ = dom.locate(at)
    ok = t >= 0
    for j in range(3):
        np.maximum.at(out, dom.tris[t[ok], j], hs[ok])
    return out


def _operator(dom, uv, crease=None, stiff=None):
    """Factorized system matrix (bi-Laplace + tautness + lines) over the inner net points. stiff: tautness like
    netsurf.STIFF (None: pure sheet metal)."""
    p, tris = dom.points, dom.tris
    n = len(p)
    # cotangent Laplace (stiffness) and averaged mass
    rows, cols, vals = [], [], []
    mass = np.zeros(n)
    for i, j, k in ((0, 1, 2), (1, 2, 0), (2, 0, 1)):
        a, b, c = p[tris[:, i]], p[tris[:, j]], p[tris[:, k]]
        u, v = a - c, b - c
        cross = np.abs(u[:, 0] * v[:, 1] - u[:, 1] * v[:, 0])
        cot = np.einsum("ij,ij->i", u, v) / np.maximum(cross, 1e-18)
        w = 0.5 * cot
        rows += [tris[:, i], tris[:, j], tris[:, i], tris[:, j]]
        cols += [tris[:, j], tris[:, i], tris[:, i], tris[:, j]]
        vals += [-w, -w, w, w]
        np.add.at(mass, tris[:, i], cross / 6)
    lap = sparse.csr_matrix((np.concatenate(vals), (np.concatenate(rows), np.concatenate(cols))), shape=(n, n))
    bend = np.ones(n) if crease is None else np.maximum(1.0 - crease, 1e-4)  # hard lines: the surface may kink there
    minv = sparse.diags(bend / np.maximum(mass, 1e-18))
    q = lap.T @ minv @ lap
    if stiff:
        q = q + lap / (stiff * dom.size) ** 2
    q = q.tocsr()
    inn = np.arange(dom.nb, n)
    t, pr, pc, pv = _bary_rows(dom, uv)
    pm = sparse.csr_matrix((pv, (pr, pc)), shape=(len(uv), n))
    # support points in triangles with a border point do not count (there the border fixes the surface)
    touches = np.zeros(len(uv), bool)
    ok = t >= 0
    touches[ok] = (dom.tris[t[ok]] < dom.nb).any(axis=1)
    use = ok & ~touches
    pm = (sparse.diags(use.astype(float)) @ pm).tocsc()
    p_in = pm[:, inn].tocsr()
    q_ii = q[inn][:, inn]
    w = netsurf.FIT_REL * float(q_ii.diagonal().mean())
    a = (q_ii + w * (p_in.T @ p_in) + 1e-12 * w * sparse.identity(len(inn))).tocsc()
    return splu(a), p_in, pm.tocsr(), w, inn


def solve(dom, base, uv, targets, groups=None, normal=None, hard=None, stiff="default"):
    """Displacement (N, 3) of the net points so that the surface at uv (rest positions) passes through targets; border fixed.
    hard: hardness per support point (the surface may kink there). stiff: tautness (default netsurf.STIFF; None: pure
    sheet metal - round through the lines, for net lines)."""
    stiff = netsurf.STIFF if stiff == "default" else stiff
    out = np.zeros_like(base)
    uv = np.asarray(uv, float).reshape(-1, 2)
    if not len(uv):
        return out
    crease = _crease(dom, uv, groups, hard)
    # operators belong to their net (live and die with it): before, in a shared store under id(dom) -
    # after clearing the nets, a new net at an old address could hit the operator of an old one
    ops = dom.__dict__.setdefault("_ops", {})
    key = (uv.tobytes(), stiff, np.round(crease, 3).tobytes())
    op = ops.get(key)
    if op is None:
        lru.trim(ops, 8)
        op = ops[key] = _operator(dom, uv, crease if crease.any() else None, stiff)
    lu, p_in, p_all, w, inn = op
    at = p_all @ base
    resid = np.asarray(targets, float).reshape(-1, 3) - at
    normals = None if normal is None else np.tile(np.asarray(normal, float), (len(uv), 1))
    resid = netsurf.average_conflicts(at, resid, groups, normals)
    out[inn] = lu.solve(np.ascontiguousarray(w * (p_in.T @ resid)))
    return out


def evaluate(dom, verts, uv, fallback):
    """Rest positions -> points on the (deformed) surface; outside the net fallback(uv) (mean-value coordinates)."""
    uv = np.asarray(uv, float).reshape(-1, 2)
    t, bary = dom.locate(uv)
    out = np.empty((len(uv), 3))
    ok = t >= 0
    if ok.any():
        tri = dom.tris[t[ok]]
        out[ok] = np.einsum("nj,njk->nk", bary[ok], verts[tri])
    if (~ok).any():
        out[~ok] = fallback(uv[~ok])
    return out


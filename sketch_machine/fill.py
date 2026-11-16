"""Geometry for filling: line network from end points, finding loops, connecting open ends,
loop to triangles.

Pure numpy logic without Qt. The end points are first merged into nodes in the viewport using a screen
tolerance (snap radius); from there on only node
numbers are used.
"""
import heapq
import itertools

import numpy as np

MAX_FILL_POINTS = 256  # loop is thinned out to at most this many points for triangulation


# --- Net -------------------------------------------------------------------
def cluster_endpoints(screen_points, tolerance):
    """Merge points (M, 2) on screen or (M, 3) in space into nodes: points closer than tolerance
    get the same node number (simple union-find)."""
    n = len(screen_points)
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    pts = np.asarray(screen_points, float)
    # grid with cell size = tolerance: only compare points in the same or a neighboring cell
    cells = {}
    for i, cell in enumerate(np.floor(pts / max(tolerance, 1e-9)).astype(np.int64).tolist()):
        cells.setdefault(tuple(cell), []).append(i)
    steps = list(itertools.product((-1, 0, 1), repeat=pts.shape[1] if pts.ndim == 2 else 2))
    for cell, members in cells.items():
        for step in steps:
            others = cells.get(tuple(c + d for c, d in zip(cell, step)))
            if not others:
                continue
            for i in members:
                for j in others:
                    if i < j and np.linalg.norm(pts[i] - pts[j]) < tolerance:
                        parent[find(i)] = find(j)
    roots = {}
    return [roots.setdefault(find(i), len(roots)) for i in range(n)]


def _length(points):
    return float(np.linalg.norm(np.diff(points, axis=0), axis=1).sum()) if len(points) > 1 else 0.0


def shortest_cycles(edges, start_edge, count):
    """Up to count different short cycles through start_edge.
    edges: {edge_id: (node_a, node_b, length)}. Result: lists of edge_ids.
    Each further cycle avoids the edges of the previous ones (except start_edge)."""
    a, b, _ = edges[start_edge]
    if a == b:  # closed single line
        return [[start_edge]]
    cycles, banned = [], set()
    for _ in range(count):
        path = _dijkstra(edges, b, a, banned | {start_edge})
        if path is None:
            break
        cycles.append([start_edge] + path)
        banned |= set(path)
    return cycles


def _dijkstra(edges, source, target, banned):
    adjacency = {}
    for eid, (u, v, length) in edges.items():
        if eid in banned or u == v:
            continue
        adjacency.setdefault(u, []).append((v, eid, length))
        adjacency.setdefault(v, []).append((u, eid, length))
    queue, seen = [(0.0, source, [])], set()
    while queue:
        dist, node, path = heapq.heappop(queue)
        if node == target:
            return path
        if node in seen:
            continue
        seen.add(node)
        for nxt, eid, length in adjacency.get(node, []):
            if nxt not in seen:
                heapq.heappush(queue, (dist + length, nxt, path + [eid]))
    return None


def close_open_ends(edges, end_points):
    """Iteratively connect open ends in pairs until a single closed drag results.
    edges: {edge_id: (a, b, length)}, end_points: {node: 3D point}.
    Preferably connects ends of different pieces (the nearest pair first);
    if only the two ends of one piece are still open, these are connected.
    Result: list of new edges (node_a, node_b)."""
    degree = {}
    for u, v, _ in edges.values():
        degree[u] = degree.get(u, 0) + 1
        degree[v] = degree.get(v, 0) + 1
    parent = {n: n for n in degree}

    def find(n):
        while parent[n] != n:
            parent[n] = parent[parent[n]]
            n = parent[n]
        return n

    for u, v, _ in edges.values():
        parent[find(u)] = find(v)
    new_edges = []
    while True:
        open_ends = [n for n, d in degree.items() if d == 1]
        if len(open_ends) < 2:
            break
        pairs = [(np.linalg.norm(end_points[p] - end_points[q]), p, q)
                 for p, q in itertools.combinations(open_ends, 2) if find(p) != find(q)]
        if not pairs:  # everything is connected: close the last two ends
            pairs = [(0.0, open_ends[0], open_ends[1])]
        _, p, q = min(pairs)
        new_edges.append((p, q))
        degree[p] += 1
        degree[q] += 1
        parent[find(p)] = find(q)
    return new_edges


def order_cycle(edge_list):
    """Bring the edges [(edge_id, a, b)] of a cycle into running direction:
    result [(edge_id, flipped)], so that each edge starts where the previous one ends.
    None if the edges do not form a simple cycle."""
    if len(edge_list) == 1:
        return [(edge_list[0][0], False)]
    remaining = list(edge_list)
    eid, a, b = remaining.pop(0)
    ordered, node = [(eid, False)], b
    while remaining:
        for i, (e, u, v) in enumerate(remaining):
            if u == node or v == node:
                ordered.append((e, u != node))
                node = v if u == node else u
                remaining.pop(i)
                break
        else:
            return None
    return ordered if node == a else None


def cycles_in(edge_list):
    """Split into connected parts; every part in which each node has degree 2 is a cycle."""
    groups, todo = [], list(edge_list)
    while todo:
        group, nodes = [todo.pop(0)], set()
        nodes |= {group[0][1], group[0][2]}
        changed = True
        while changed:
            changed = False
            for e in list(todo):
                if e[1] in nodes or e[2] in nodes:
                    group.append(e)
                    nodes |= {e[1], e[2]}
                    todo.remove(e)
                    changed = True
        groups.append(group)
    return groups


# --- Triangulation -----------------------------------------------------------
def _resample(points, max_points):
    """Thin out a closed drag evenly by arc length to at most max_points."""
    closed = np.vstack([points, points[:1]])
    seg = np.linalg.norm(np.diff(closed, axis=0), axis=1)
    keep = np.concatenate([[True], seg[:-1] > 1e-9])  # drop duplicate points
    points = points[keep]
    if len(points) <= max_points:
        return points
    closed = np.vstack([points, points[:1]])
    cum = np.concatenate([[0], np.cumsum(np.linalg.norm(np.diff(closed, axis=0), axis=1))])
    targets = np.linspace(0, cum[-1], max_points, endpoint=False)
    return np.stack([np.interp(targets, cum, closed[:, k]) for k in range(3)], axis=1)


def is_degenerate(points, ratio=0.02):
    """True if the loop encloses practically no area (e.g. a single straight line
    whose ends were connected): area relative to the square of the perimeter."""
    pts = np.asarray(points, float)
    if len(pts) < 3:
        return True
    center, u, v, _ = fit_plane(pts)
    uv = np.stack([(pts - center) @ u, (pts - center) @ v], axis=1)
    area = abs(0.5 * np.sum(uv[:, 0] * np.roll(uv[:, 1], -1) - np.roll(uv[:, 0], -1) * uv[:, 1]))
    perimeter = np.linalg.norm(np.diff(np.vstack([pts, pts[:1]]), axis=0), axis=1).sum()
    return area < ratio * perimeter ** 2 / (4 * np.pi)  # circle has ratio 1


def fit_plane(points):
    """Best-fit plane: (center point, u axis, v axis, normal)."""
    center = points.mean(axis=0)
    _, _, vt = np.linalg.svd(points - center)
    return center, vt[0], vt[1], vt[2]


def _cross(o, a, b):
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def _signed_area(uv, idx):
    p = uv[idx]
    return 0.5 * float(np.sum(p[:, 0] * np.roll(p[:, 1], -1) - np.roll(p[:, 0], -1) * p[:, 1]))


def _clean(uv, idx, eps_len, eps_area):
    """Remove duplicate points, points on a straight line and backtracking spikes (they only yield
    sliver triangles with area 0)."""
    idx = list(idx)
    changed = True
    while changed and len(idx) > 3:
        changed = False
        k = 0
        while k < len(idx) and len(idx) > 3:
            a, b, c = uv[idx[k - 1]], uv[idx[k]], uv[idx[(k + 1) % len(idx)]]
            if np.hypot(*(b - a)) < eps_len or abs(_cross(a, b, c)) < eps_area:
                idx.pop(k)
                changed = True
            else:
                k += 1
    return idx


def _first_crossing(uv, idx):
    """First intersection of two non-adjacent edges of the outline: (i, j, t, s) with
    edge i = idx[i] -> idx[i+1] at parameter t, edge j at s; otherwise None."""
    n = len(idx)
    p = uv[idx]
    q = np.roll(p, -1, axis=0)
    d = q - p
    for i in range(n - 2):
        js = np.arange(i + 2, n if i > 0 else n - 1)
        if not len(js):
            continue
        r, s_vec = d[i], d[js]
        denom = r[0] * s_vec[:, 1] - r[1] * s_vec[:, 0]
        w = p[js] - p[i]
        ok = np.abs(denom) > 1e-18
        t = np.where(ok, (w[:, 0] * s_vec[:, 1] - w[:, 1] * s_vec[:, 0]) / np.where(ok, denom, 1), -1)
        u = np.where(ok, (w[:, 0] * r[1] - w[:, 1] * r[0]) / np.where(ok, denom, 1), -1)
        hit = ok & (t > 1e-9) & (t < 1 - 1e-9) & (u > 1e-9) & (u < 1 - 1e-9)
        if hit.any():
            k = int(np.flatnonzero(hit)[0])
            return i, int(js[k]), float(t[k]), float(u[k])
    return None


def _ear_clip_robust(uv, idx, eps_area):
    """Ear clipping for a simple polygon (counter-clockwise). If it finds no clean ear
    any more (rounding errors, nearly touching edges), it cuts off the smallest convex corner instead of
    giving up. Points exactly on the border of an ear do not block it."""
    idx = list(idx)
    tris = []
    while len(idx) > 3:
        n = len(idx)
        best, fallback = None, None
        for k in range(n):
            i0, i1, i2 = idx[k - 1], idx[k], idx[(k + 1) % n]
            a, b, c = uv[i0], uv[i1], uv[i2]
            area = _cross(a, b, c)
            if area <= eps_area:
                continue  # concave or degenerate corner
            if fallback is None or area < fallback[0]:
                fallback = (area, k)
            others = uv[[j for j in idx if j not in (i0, i1, i2)]]
            if len(others):
                c0 = (b[0] - a[0]) * (others[:, 1] - a[1]) - (b[1] - a[1]) * (others[:, 0] - a[0])
                c1 = (c[0] - b[0]) * (others[:, 1] - b[1]) - (c[1] - b[1]) * (others[:, 0] - b[0])
                c2 = (a[0] - c[0]) * (others[:, 1] - c[1]) - (a[1] - c[1]) * (others[:, 0] - c[0])
                if np.any((c0 > eps_area) & (c1 > eps_area) & (c2 > eps_area)):
                    continue  # another point lies in the ear
            best = k
            break
        if best is None:
            if fallback is None:  # only degenerate corners left: the rest has no area
                return tris
            best = fallback[1]
        tris.append((idx[best - 1], idx[best], idx[(best + 1) % n]))
        idx.pop(best)
    if len(idx) == 3 and _cross(uv[idx[0]], uv[idx[1]], uv[idx[2]]) > eps_area:
        tris.append(tuple(idx))
    return tris


def triangulate_loop(points, resample=True):
    """Fill a closed 3D drag. Result: (vertices (N,3), triangles (M,3), uv (N,2) in
    world units on the best-fit plane – for the object-bound hatching).
    Robust against freehand outlines: first clean up (duplicate points, straight lines, spikes), then split at
    self-intersections into simple parts and fill each part by ear clipping. This keeps
    the surface inside the outline (also with indentations) and no sliver triangles arise."""
    # resample=False: exactly these points (a finished border – resampled it would lose its corners)
    pts = _resample(np.asarray(points, float), MAX_FILL_POINTS) if resample else np.asarray(points, float)
    if len(pts) < 3:
        return None
    center, u, v, _ = fit_plane(pts)
    uv = np.stack([(pts - center) @ u, (pts - center) @ v], axis=1)
    size = float(np.linalg.norm(np.ptp(uv, axis=0)))
    if size <= 1e-12:
        return None
    eps_len, eps_area = 1e-6 * size, 1e-9 * size * size
    verts, uvs = list(pts), list(uv)
    todo = [_clean(np.array(uvs), range(len(pts)), eps_len, eps_area)]
    tris, splits = [], 0
    while todo:
        idx = todo.pop()
        if len(idx) < 3:
            continue
        uv_arr = np.array(uvs)
        cross = _first_crossing(uv_arr, idx) if splits < 64 else None
        if cross is not None:  # split into two outlines at the crossing point
            splits += 1
            i, j, t, _ = cross
            a, b = idx[i], idx[(i + 1) % len(idx)]
            verts.append(verts[a] + t * (verts[b] - verts[a]))
            uvs.append(uvs[a] + t * (uvs[b] - uvs[a]))
            x = len(verts) - 1
            uv_arr = np.array(uvs)
            first = [x] + idx[i + 1:j + 1]
            second = idx[j + 1:] + idx[:i + 1] + [x]
            for part in (first, second):
                part = _clean(uv_arr, part, eps_len, eps_area)
                if len(part) >= 3 and abs(_signed_area(uv_arr, part)) > eps_area:
                    todo.append(part)
            continue
        if _signed_area(uv_arr, idx) < 0:
            idx = idx[::-1]
        tris += _ear_clip_robust(uv_arr, idx, eps_area)
    if not tris:
        return None
    return np.array(verts, float), np.array(tris, dtype=np.int32), np.array(uvs, float)

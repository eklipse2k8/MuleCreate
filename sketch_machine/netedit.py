"""Net editing (trial run): delete a point per the topology concept (plan document, "Deleting a point").

A deleted point takes the pieces attached to it with it - up to the next point of the respective line, not
whole lines. Afterwards:
  - Curve surface whose border ran through the point: it takes the outline that is still closed with its remaining
    lines (shortest path over the lines on it between the two open border ends). If there is none, the
    two neighboring points are joined by a straight line (bridge) - only at points with two pieces.
  - Without a surface: two pieces -> bridge between the neighboring points; at crossings (three or more pieces) none.
  - If no surface can be formed any more, it keeps its shape and keeps deforming with the remaining lines.
Dissolve (Del; the point disappears, the shape stays): dissolve_points - corners and inserted points of a line
only lose their handle, at a joint of two line ends the two lines become one continuous line (like a
drawn stroke). Crossings, T-joints and points with three or more lines are not dissolved (for now).
"""
import heapq

import numpy as np

from . import components, loft, network, patch as patch_geo

BRIDGE_POINTS = 12  # points of a bridge line
REBIND_REL = 0.02  # lines and painting bind to the new surface when they lie this close (fraction of the size) to it


def delete_points(scene, pids):
    """Delete points (IDs). Returns (deleted points, bridges, newly formed surfaces)."""
    done = bridges = rebuilt = 0
    for pid in pids:
        res = _delete_one(scene, pid)
        if res is None:
            continue
        done += 1
        bridges += res[0]
        rebuilt += res[1]
    network.sync(scene)
    return done, bridges, rebuilt


def _border_of(scene, surface):
    """Border lines of a curve surface or outline lines of a linked fill surface (split ones as their pieces)."""
    from .scene import PatchSurface, SurfaceObject
    if isinstance(surface, PatchSurface):
        return scene.patch_border(surface)
    if type(surface) is SurfaceObject and surface.links:
        out = []
        for cid, _ in surface.links:
            for i in scene.link_ids(cid):
                for sub in scene.split_pieces(i) or []:
                    c = scene.curve_by_id(sub)
                    if c is not None and not any(c is x for x in out):
                        out.append(c)
        return out
    return []


def _patches_through(scene, pid):
    """Surfaces (curve and fill surfaces) whose border runs through the point."""
    from .scene import PatchSurface, SurfaceObject
    out = []
    for s in scene.surfaces:
        if (isinstance(s, PatchSurface) and s.patch_lines or type(s) is SurfaceObject and s.links) and any(
                pid in (c.pids or {}).values() for c in _border_of(scene, s)):
            out.append(s)
    return out


def _delete_one(scene, pid):
    refs = network.refs_by_pid(scene).get(pid)
    if not refs:
        return None
    patches = _patches_through(scene, pid)
    border_before = {s.id: {c.id for c in _border_of(scene, s)} for s in patches}
    curves = list({id(c): c for c, _ in refs}.values())
    removed = []  # (neighbor ID, neighbor position, line the piece hung on, its stroke)
    for curve in curves:
        removed += _cut_out(scene, curve, pid)
    network.sync(scene)
    bridges = rebuilt = 0
    for surface in patches:
        r = _rebuild_patch(scene, surface, pid, removed, border_before[surface.id])
        bridges += r == "bridge"
        rebuilt += r is not None
    if not patches and len(removed) == 2 and removed[0][0] != removed[1][0]:
        _bridge(scene, removed[0], removed[1])
        bridges += 1
    return bridges, rebuilt


def _cut_out(scene, curve, pid):
    """Remove the pieces of curve attached to point pid; the rest stays (as a line or pieces)."""
    owner = scene.owner_of(curve)
    if owner is None:
        return []
    components.knots(curve)
    n = len(curve.points)
    if components.is_closed(curve.points):
        k0 = next((k for k, p in curve.pids.items() if p == pid), None)
        if k0 is None:
            return []
        if k0 not in (0, n - 1):  # put the seam on the point
            old = dict(curve.pids)
            components.roll_closed(curve, k0)
            m = n - 1
            curve.pids = {(k - k0) % m: p for k, p in old.items() if k != n - 1}
            curve.pids[n - 1] = curve.pids[0]
    ks = components.knots(curve)
    pids = curve.pids or {}
    mine = {k for k in ks if pids.get(k) == pid}
    ranges = list(zip(ks[:-1], ks[1:]))
    gone = [(a, b) for a, b in ranges if a in mine or b in mine]
    if not gone:
        return []
    out = []
    for a, b in gone:
        o = a if b in mine else b
        if o in mine:
            continue  # piece between two references to the same point (loop)
        out.append((pids.get(o), curve.points[o].copy(), curve, owner, _surface_spots(scene, curve, o)))
    cuts = sorted({k for ab in gone for k in ab} - {0, n - 1})
    pieces = components.split_at(curve, cuts)
    keep = [p for p, s, e in pieces if (s, e) not in gone and len(p.points) >= 2]
    from .scene import inherit
    for p in keep:
        inherit(p, curve)
    k = next(j for j, c in enumerate(owner.curves) if c is curve)
    owner.curves[k:k + 1] = keep
    scene.split_map[curve.id] = [p.id for p in keep]
    return out


def _surface_spots(scene, curve, k):
    """Where point k of the line lies on the surfaces it shapes: {surface id: position (uv)}."""
    out = {}
    for s in scene.surfaces:
        att = (getattr(s, "attached", None) or {}).get(curve.id)
        if att is None or len(att["uv"]) != len(curve.points):
            continue
        on = att.get("on")
        if on is None or on[k]:
            out[s.id] = np.asarray(att["uv"], float)[k].copy()
    return out


def _bridge(scene, a, b):
    """Straight line between the neighboring points a and b ((ID, position, line, stroke, position on surfaces)). If the line
    shaped a surface, the bridge keeps shaping it: its position on the surface runs straight between the neighboring points - the
    surface settles onto the straight line as if the line had always been straight."""
    from .scene import Curve, inherit
    pts = np.linspace(a[1], b[1], BRIDGE_POINTS)
    like = a[2]
    width = float(np.mean(like.widths)) if len(like.widths) else 0.02
    # at the neighboring points the width of their lines there, in between proportionally
    c = Curve(pts, like.plane_id, components.widths_between(pts, [a[2]], [b[2]], width))
    inherit(c, like)
    c.knots = (len(pts), ())
    c.pids = {0: a[0], len(pts) - 1: b[0]}
    a[3].curves.append(c)
    from .scene import SurfaceObject
    t = np.linspace(0.0, 1.0, len(pts))[:, None]
    for sid in set(a[4]) & set(b[4]):
        surface = scene.object_by_id(sid)
        if surface is None:
            continue
        uv = a[4][sid] + t * (b[4][sid] - a[4][sid])
        c.plane_id = sid
        if type(surface) is SurfaceObject:  # fill surface: rest position in the cage
            surface.attached[c.id] = {"uv": uv, "last": c.points.tobytes()}
        else:
            surface.attached[c.id] = {"uv": uv, "on": np.ones(len(pts), bool), "last": c.points.tobytes(),
                                      "pos": c.points.copy()}
    return c


def _knot_graph(curves):
    """Edges between consecutive points of the lines: {pid: [(neighbor, length, line, ka, kb)]}."""
    graph = {}
    for c in curves:
        ks = components.knots(c)
        pids = c.pids or {}
        arc = np.concatenate([[0], np.cumsum(np.linalg.norm(np.diff(c.points, axis=0), axis=1))])
        for a, b in zip(ks[:-1], ks[1:]):
            pa, pb = pids.get(a), pids.get(b)
            if pa is None or pb is None or pa == pb:
                continue
            length = float(arc[b] - arc[a])
            graph.setdefault(pa, []).append((pb, length, c, a, b))
            graph.setdefault(pb, []).append((pa, length, c, b, a))
    return graph


def _shortest(graph, start, goal):
    """Shortest path start -> goal: [(line, ka, kb)] or None."""
    dist, prev = {start: 0.0}, {}
    heap = [(0.0, start)]
    while heap:
        d, p = heapq.heappop(heap)
        if p == goal:
            break
        if d > dist.get(p, np.inf):
            continue
        for q, length, c, ka, kb in graph.get(p, ()):
            nd = d + length
            if nd < dist.get(q, np.inf):
                dist[q], prev[q] = nd, (p, c, ka, kb)
                heapq.heappush(heap, (nd, q))
    if goal not in prev:
        return None
    path, p = [], goal
    while p != start:
        q, c, ka, kb = prev[p]
        path.append((c, ka, kb))
        p = q
    return path[::-1]


def _path_curves(scene, path):
    """Split the lines of the path so that each used piece is its own line. Returns the pieces."""
    by_curve = {}
    for c, ka, kb in path:
        lo, hi = by_curve.get(id(c), (c, None, None))[1:]
        a, b = min(ka, kb), max(ka, kb)
        by_curve[id(c)] = (c, a if lo is None else min(lo, a), b if hi is None else max(hi, b))
    out = []
    for c, lo, hi in by_curve.values():
        n = len(c.points)
        cuts = sorted({lo, hi} - {0, n - 1})
        if not cuts:
            out.append(c)
            continue
        owner = scene.owner_of(c)
        pieces = components.split_at(c, cuts)
        from .scene import inherit
        for p, _, _ in pieces:
            inherit(p, c)
        k = next(j for j, cc in enumerate(owner.curves) if cc is c)
        owner.curves[k:k + 1] = [p for p, _, _ in pieces]
        scene.split_map[c.id] = [p.id for p, _, _ in pieces]
        out += [p for p, s, e in pieces if s == lo and e == hi]
    return out


def _rebuild_patch(scene, surface, pid, removed, border_ids):
    """New outline for a curve surface after deleting. Returns "path", "bridge" or None (surface stays)."""
    border = _border_of(scene, surface)
    ends = [r for r in removed if r[2].id in border_ids]
    if len(ends) != 2 or ends[0][0] == ends[1][0]:
        return None
    members = [scene.curve_by_id(sub) for cid in surface.attached for sub in scene.split_pieces(cid) or []]
    members = [c for c in members if c is not None and not c.paint and c.id not in {b.id for b in border}]
    how = "path"
    path = _shortest(_knot_graph(members), ends[0][0], ends[1][0])
    if path is not None:
        outline = border + _path_curves(scene, path)
    elif len(removed) == 2:
        how = "bridge"
        outline = border + [_bridge(scene, ends[0], ends[1])]
    else:
        return None
    network.sync(scene)
    from .scene import PatchSurface
    rebuild = _rebuild_from if isinstance(surface, PatchSurface) else _rebuild_fill
    if not rebuild(scene, surface, outline):
        return None
    return how


def _rebuild_from(scene, surface, outline):
    """Rebuild a curve surface from a new outline (same object); rebind lines and painting on it."""
    old_attached = dict(surface.attached)
    tmp = scene.create_patch(outline)
    if tmp is None:
        return False
    scene.surfaces.remove(tmp)
    surface.curves, surface.closed = tmp.curves, tmp.closed
    surface.patch_lines, surface.patch_order = tmp.patch_lines, tmp.patch_order
    surface.patch_corners, surface.patch_arc = tmp.patch_corners, tmp.patch_arc
    surface._patch_key = tmp._patch_key
    surface.offset = None
    surface.span, surface.bnd = tmp.span, None
    surface.net, surface._net_geo = None, None  # new outline: the grid is laid anew
    for attr in ("_net_key", "_att_geo", "_base", "_synced"):
        if hasattr(surface, attr):
            delattr(surface, attr)
    g = surface.grid()
    size = float(np.linalg.norm(np.ptp(g.reshape(-1, 3), axis=0)))
    tol = REBIND_REL * size
    outline_ids = {c.id for c in outline}
    surface.attached = {}
    for cid in old_attached:
        for sub in scene.split_pieces(cid) or []:
            c = scene.curve_by_id(sub)
            if c is None or c.id in outline_ids:
                if c is not None:
                    c.plane_id = None  # border line: belongs to the outline, no longer onto the surface
                continue
            uv, on = loft.bind(c.points, None, False, tol, g=g)
            if on.any():
                c.plane_id = surface.id
                surface.attached[c.id] = {"uv": uv, "on": on, "last": c.points.tobytes(), "pos": c.points.copy()}
            else:
                c.plane_id = None
    return True


def dissolve_points(scene, pids):
    """Dissolve points without any line changing. Returns (dissolved, merged lines, rejected)."""
    done = merged = refused = 0
    for pid in pids:
        refs = network.refs_by_pid(scene).get(pid)
        if not refs:
            continue
        curves = {id(c): c for c, _ in refs}
        if len(refs) == 1 and 0 < refs[0][1] < len(refs[0][0].points) - 1:
            done += components.dissolve(*refs[0])  # corner / inserted point of a line
            continue
        if len(refs) == 2 and len(curves) == 2 and all(k in (0, len(c.points) - 1) for c, k in refs) \
                and not any(components.is_closed(c.points) for c, _ in refs):
            _merge(scene, refs[0], refs[1])
            done += 1
            merged += 1
            continue
        refused += 1  # crossing, T-joint, three or more lines, open end, seam of a closed line
    network.sync(scene)
    return done, merged, refused


def _oriented(c, k, at_end):
    """Points, widths, inner nodes and point IDs of c rotated so that the joint (node k) lies at the end (at_end) or
    at the start."""
    n = len(c.points)
    flip = (k == 0) == at_end
    idx = (lambda i: n - 1 - i) if flip else (lambda i: i)
    pts, wid = (c.points[::-1], c.widths[::-1]) if flip else (c.points, c.widths)
    inner = [idx(i) for i in components.knots(c)[1:-1]]
    pids = {idx(i): p for i, p in (c.pids or {}).items()}
    return pts, wid, inner, pids


def _merge(scene, ra, rb):
    """Merge two lines that meet at their ends into one line (shape unchanged)."""
    from .scene import Curve, LoftSurface, PatchSurface, inherit
    (a, ka), (b, kb) = ra, rb
    pa, wa, ia, da = _oriented(a, ka, True)
    pb, wb, ib, db = _oriented(b, kb, False)
    off = len(pa) - 1
    pts = np.vstack([pa, pb[1:]])
    wid = np.concatenate([wa, wb[1:]])
    m = Curve(pts, a.plane_id if a.plane_id is not None else b.plane_id, wid, a.generated and b.generated)
    inherit(m, a)
    n = len(pts)
    m.knots = (n, tuple(sorted((set(ia) | {i + off for i in ib}) - {0, off, n - 1})))
    m.pids = {i: p for i, p in da.items() if i != off}
    m.pids.update({i + off: p for i, p in db.items() if i != 0})
    corners = {}  # curve surfaces whose border runs through one of the lines: keep corners at the same place
    for s in scene.surfaces:
        if isinstance(s, PatchSurface) and s.patch_lines:
            border = scene.patch_border(s)
            if any(c is a or c is b for c in border):
                sides = scene._patch_sides(s)
                if sides is not None:
                    corners[s.id] = (s, [sd[0].copy() for sd in sides], border)
    owner_a, owner_b = scene.owner_of(a), scene.owner_of(b)
    k = next(j for j, c in enumerate(owner_a.curves) if c is a)
    owner_a.curves[k] = m
    owner_b.curves = [c for c in owner_b.curves if c is not b]
    network.sync(scene)
    for s, corner_pts, border in corners.values():
        lines = []
        for c in border:
            c = m if c is a or c is b else c
            if not any(c is x for x in lines):
                lines.append(c)
        order = patch_geo.order_loop([c.points for c in lines])
        if order is None:
            continue
        order = patch_geo.keep_direction([c.points for c in lines], order, corner_pts)
        s.patch_lines = [c.id for c in lines]
        s.patch_order = [(int(i), bool(f)) for i, f in order]
        s.patch_corners = patch_geo.spec_for_points([c.points for c in lines], order, corner_pts)
        s.patch_arc = True
        s._patch_key = None
        s._net_key = None
    for s in scene.surfaces:
        if isinstance(s, LoftSurface) and s.sources:  # lofts: cross-sections from the lines
            for src in s.sources:
                if src and src[0] == "lines" and (a.id in src[1] or b.id in src[1]):
                    ids = [m.id if cid in (a.id, b.id) else cid for cid in src[1]]
                    src[1][:] = [cid for i, cid in enumerate(ids) if cid != m.id or m.id not in ids[:i]]
        elif type(s).__name__ == "SurfaceObject" and s.links:  # fill surfaces: relink the outline
            ids = {x for cid, _ in s.links for x in (cid if isinstance(cid, list) else [cid])}
            if a.id in ids or b.id in ids:
                scene._relink_fill(s)
    return m


def _rebuild_fill(scene, surface, outline):
    """Relink a fill surface with a new outline (same object). What then lies outside (painting, lines)
    comes loose from the surface; the rest is rebound at the same place."""
    from . import cage, netfill
    from .scene import Curve
    order = patch_geo.order_loop([c.points for c in outline])
    if order is None:
        return False
    lines = {cid: c for cid in surface.attached if (c := scene.curve_by_id(cid)) is not None}
    outline_ids = {c.id for c in outline}
    old_links = surface.links
    surface.links = [(outline[i].id, bool(f)) for i, f in order]
    surface.curves = [Curve((outline[i].points[::-1] if f else outline[i].points).copy(), None) for i, f in order]
    if not scene._start_fill_links(surface):
        surface.links = old_links
        return False
    surface.netmesh = None
    for attr in ("_net_key", "_fill_key"):
        if hasattr(surface, attr):
            setattr(surface, attr, None)
    now = scene._fill_cage(surface)
    inside = lambda uv: netfill._inside(np.asarray(uv, float).reshape(-1, 2), surface.rest)
    surface.attached = {}
    for cid, c in lines.items():
        if cid in outline_ids:
            c.plane_id = None  # now an outline line
            continue
        uv = cage.bind(c.points, now, surface.rest)
        if inside(uv).any():
            surface.attached[cid] = {"uv": uv, "last": c.points.tobytes()}
            c.plane_id = surface.id
        else:
            c.plane_id = None
    return True


def remove_points(scene, pids):
    """Remove points (Shift+Del): the point disappears, the line is re-run between the neighboring points (smooth,
    at soft neighbors in the direction of the line beyond). If two line ends meet there, they first become one line.
    Crossings, T-joints, open ends and seams stay. Returns (removed, rejected)."""
    done = refused = 0
    for pid in pids:
        refs = network.refs_by_pid(scene).get(pid)
        if not refs:
            continue
        curves = {id(c): c for c, _ in refs}
        if len(refs) == 1 and 0 < refs[0][1] < len(refs[0][0].points) - 1:
            c, k = refs[0]
        elif len(refs) == 2 and len(curves) == 2 and all(k in (0, len(c.points) - 1) for c, k in refs) \
                and not any(components.is_closed(c.points) for c, _ in refs):
            (a, ka), _ = refs
            c, k = _merge(scene, refs[0], refs[1]), len(a.points) - 1
        else:
            refused += 1
            continue
        _reinterpolate(scene, c, k)
        done += 1
    network.sync(scene)
    return done, refused


def _reinterpolate(scene, c, k):
    """Re-lay the piece between the neighboring nodes of k (Hermite curve, same point count), k is no longer a point
    afterwards. Tangents: at a soft neighbor the direction of the line beyond it, otherwise the chord."""
    ks = [j for j in components.knots(c) if j != k]
    a = max(j for j in ks if j < k)
    b = min(j for j in ks if j > k)
    pts = c.points
    pa, pb = pts[a], pts[b]
    chord = pb - pa
    length = float(np.linalg.norm(chord))
    if length < 1e-12:
        return
    index = components.KnotIndex(scene)

    def tangent(j, before):  # running direction (from a to b) of the line beyond j, at chord length
        if components.hardness(c, j, index) < 0.5 and 0 < j < len(pts) - 1:
            step = min(3, j) if before else min(3, len(pts) - 1 - j)
            v = pts[j] - pts[j - step] if before else pts[j + step] - pts[j]
            n = float(np.linalg.norm(v))
            if n > 1e-12:
                return v / n * length
        return chord

    ta, tb = tangent(a, True), tangent(b, False)
    t = components._arc_t(pts[a:b + 1])[:, None]
    h00, h10, h01, h11 = 2 * t ** 3 - 3 * t ** 2 + 1, t ** 3 - 2 * t ** 2 + t, -2 * t ** 3 + 3 * t ** 2, t ** 3 - t ** 2
    new = pts.copy()
    new[a:b + 1] = h00 * pa + h10 * ta + h01 * pb + h11 * tb
    c.points = new
    c.knots = (len(new), tuple(j for j in ks if 0 < j < len(new) - 1))
    if c.pids:
        c.pids = {j: p for j, p in c.pids.items() if j != k}

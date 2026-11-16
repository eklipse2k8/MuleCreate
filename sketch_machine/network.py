"""Curve net (F3, trial run): points with their own identity that lines share.

Every knot of a line (ends, corners, inserted points; see components.knots) refers to a net point
(Curve.pids = {knot index: point ID}). What is connected is what has the same point ID – not what happens to lie at the
same place. The position stays in the lines; all references of a point lie at the same place.

When points arise:
  - Lines without IDs (old files, freshly drawn lines or lines produced by operations) get them at the
    next sync: a knot exactly on an existing point (snapping, splitting, fill additions) shares
    its ID, otherwise a new point arises. This is the adoption of old files – they behave as before.
  - Lines with IDs keep them. If two points happen to lie on top of each other (e.g. an inserted copy), they stay
    separate until Fuse connects them.
  - If references of a point move away from each other (an operation moved only one line), the point is separated at
    that place: the largest group keeps the ID.
"""
import itertools

import numpy as np

from . import components, counters

TOL = components.WELD_TOL
DRIFT_REL = 1e-5  # by this little (fraction of the scene size) the references of a point may lie apart: numerical noise
_CELL = 4 * TOL
_NEIGHBOURS = [(x, y, z) for x in (-1, 0, 1) for y in (-1, 0, 1) for z in (-1, 0, 1)]
_ids = itertools.count(1)


def new_pid():
    return next(_ids)


def _cell(p):
    return tuple(int(c) for c in np.floor(np.asarray(p) / _CELL))


def net_curves(scene):
    """Lines that belong to the net (not painting: it has no points)."""
    return [c for st in scene.strokes for c in st.curves if not c.paint and len(c.points) >= 2]


def _remap(c, ks):
    """Transfer stored IDs to the current knots (after inserting, splitting, resampling …): same index
    (at the same place, as far as known), otherwise an old knot at the same place; the rest get new points."""
    old, old_pos = c.pids or {}, getattr(c, "_pid_pos", None) or {}
    pts, n = c.points, len(c.points)
    out, used = {}, set()
    for k in ks:
        pid = None
        if k in old and (k not in old_pos or np.linalg.norm(old_pos[k] - pts[k]) < TOL):
            pid = old[k]
        else:
            for j, q in old_pos.items():
                if j in old and old[j] not in used and np.linalg.norm(q - pts[k]) < TOL:
                    pid = old[j]
                    break
        if pid is not None and pid not in used:
            out[k] = pid
            used.add(pid)
    if components.is_closed(pts) and 0 in out:  # seam: start and end are the same point
        out[n - 1] = out[0]
    return out


# counter: rises on every assignment of points/knots/pids/paint of a line and on every new line (Curve.__setattr__).
# sync asks hundreds of times per frame (every surface on sync) – without change the counter plus the lists
# of the strokes suffice, instead of rebuilding the key over all lines.
EPOCH = [0]
NET_FIELDS = frozenset(("points", "knots", "pids", "paint"))


def _fast_key(scene):
    lists = [st.curves for st in scene.strokes]
    return EPOCH[0], scene.strokes, len(scene.strokes), lists, [len(cl) for cl in lists]


def _fast_hit(scene):
    fast = getattr(scene, "_net_fast", None)
    if fast is None or fast[1] is not getattr(scene, "_net_sync", None):
        return False
    (epoch, strokes, n, lists, lens), _ = fast
    if epoch != EPOCH[0] or strokes is not scene.strokes or n != len(strokes) or len(lists) != n:
        return False
    # hold on to the lists themselves (not their id): a new list at an old address would otherwise go unnoticed
    return all(st.curves is cl and len(cl) == k for st, cl, k in zip(strokes, lists, lens))


def sync(scene):
    """Sync point IDs of all lines (cheap if nothing has changed). Returns statistics (dict)."""
    if _fast_hit(scene):
        return scene._net_sync[1]
    curves = net_curves(scene)
    key = tuple((id(c), id(c.points), c.knots, id(c.pids)) for c in curves)
    counters.C["netz_schluessel"] += len(curves)
    cache = getattr(scene, "_net_sync", None)
    if cache is not None and cache[0] == key:
        scene._net_fast = (_fast_key(scene), cache)
        return cache[1]
    counters.C["netz_abgleich"] += 1
    counters.C["netz_linien"] += len(curves)
    entries = []  # [curve, k, pos, pid]
    for c in curves:
        ks = components.knots(c)
        pids = c.pids if c.pids is not None and set(c.pids) == set(ks) else _remap(c, ks) if c.pids else {}
        for k in ks:
            entries.append([c, k, c.points[k], pids.get(k)])
    # separated references of a point: at each place a group of its own, the largest keeps the ID. Tiny
    # deviations (numerical noise, e.g. when a surface updates its lines) do not separate: the references are
    # put back onto one place.
    if entries:
        allp = np.array([e[2] for e in entries])
        drift = max(DRIFT_REL * float(np.linalg.norm(np.ptp(allp, axis=0))), TOL)
    groups, first = {}, {}
    lead = np.zeros(len(entries), np.int64)  # per reference: the first reference of the same point
    for i, e in enumerate(entries):
        lead[i] = i
        if e[3] is not None:
            groups.setdefault(e[3], []).append(e)
            lead[i] = first.setdefault(e[3], i)
    # if all references of a point lie EXACTLY on top of each other, there is nothing to separate and nothing to smooth – this is
    # almost always the case; check only the remaining points individually (before: every point on every sync, during a drag every frame)
    apart = np.flatnonzero(np.any(allp != allp[lead], axis=1)) if entries else ()
    loose = {entries[i][3] for i in apart}
    for pid, refs in groups.items():
        if len(refs) < 2 or pid not in loose:
            continue
        clusters = []
        for e in refs:
            for cl in clusters:
                if np.linalg.norm(cl[0][2] - e[2]) < drift:
                    cl.append(e)
                    break
            else:
                clusters.append([e])
        clusters.sort(key=len, reverse=True)
        for cl in clusters[1:]:
            fresh = new_pid()
            for e in cl:
                e[3] = fresh
        for cl in clusters:  # smooth noise: all references exactly onto one place
            if len(cl) > 1 and any(np.linalg.norm(e[2] - cl[0][2]) > 0 for e in cl[1:]):
                target = cl[0][2].copy()
                for e in cl:
                    if np.linalg.norm(e[2] - target) > 0:
                        pts = e[0].points.copy()
                        pts[e[1]] = target
                        e[0].points = pts
                        e[2] = target
    # knots without ID: on an existing point -> its ID, otherwise a new point
    grid = {}
    if any(e[3] is None for e in entries):  # only those without an ID need the grid (usually nobody)
        for e in entries:
            if e[3] is not None:
                grid.setdefault(_cell(e[2]), []).append(e)
    for e in entries:
        if e[3] is not None:
            continue
        x, y, z = _cell(e[2])
        hit = None
        for dx, dy, dz in _NEIGHBOURS:
            for o in grid.get((x + dx, y + dy, z + dz), ()):
                if o[3] is not None and np.linalg.norm(o[2] - e[2]) < TOL:
                    hit = o[3]
                    break
            if hit is not None:
                break
        e[3] = hit if hit is not None else new_pid()
        grid.setdefault((x, y, z), []).append(e)
    by_curve = {}
    for c, k, p, pid in entries:
        by_curve.setdefault(id(c), (c, {}, {}))
        by_curve[id(c)][1][k] = pid
        by_curve[id(c)][2][k] = p.copy()
    for c, pids, pos in by_curve.values():
        fresh = c.pids != pids
        if fresh:
            c.pids = pids
        if fresh or c.__dict__.get("_pid_at") is not c.points:
            # only if points or IDs have changed: the same dictionary means "unchanged" (this is how the
            # undo copy knows it can keep using the image of the line from the last step, Scene._twin_memo)
            c._pid_pos = pos
            c._pid_at = c.points
    stats = _stats(entries)
    key = tuple((id(c), id(c.points), c.knots, id(c.pids)) for c in curves)
    scene._net_sync = (key, stats)
    scene._net_fast = (_fast_key(scene), scene._net_sync)  # after the sync (it assigns pids/points itself)
    return stats


def _stats(entries):
    curves_of = {}
    for c, k, p, pid in entries:
        curves_of.setdefault(pid, set()).add(id(c))
    ends = [(c, k, pid) for c, k, p, pid in entries if k in (0, len(c.points) - 1)]
    free = sum(1 for c, k, pid in ends if len(curves_of[pid]) == 1 and not components.is_closed(c.points))
    return {"points": len(curves_of), "shared": sum(1 for s in curves_of.values() if len(s) > 1), "free_ends": free}


def merge_at(scene, point, tol=TOL):
    """Deliberate connecting (snapping, welding, V): all knots exactly at point become one point – also those
    that already had points of their own. Returns the number of merged points (0: there already was one)."""
    sync(scene)
    point = np.asarray(point, float)
    hits = [(c, k) for c in net_curves(scene) for k, pid in (c.pids or {}).items()
            if np.linalg.norm(c.points[k] - point) < tol]
    pids = {c.pids[k] for c, k in hits}
    if len(pids) < 2:
        return 0
    counts = {}
    for c in net_curves(scene):
        for pid in (c.pids or {}).values():
            counts[pid] = counts.get(pid, 0) + 1
    keep = max(pids, key=lambda p: (counts.get(p, 0), -p))
    gone = pids - {keep}
    for c in net_curves(scene):
        if c.pids and gone & set(c.pids.values()):
            c.pids = {k: keep if pid in gone else pid for k, pid in c.pids.items()}
    sync(scene)
    return len(gone)


def join(scene, a, ka, b, kb):
    """Explicitly make knot ka of line a and knot kb of line b one point (same ID, same position –
    b moves onto a). No searching by position: the connection stands, no matter how close other lines are."""
    sync(scene)
    pa, pb = pid_of(a, ka), pid_of(b, kb)
    target = a.points[ka].copy()
    # all lines at point pb move along (otherwise another connection there would tear)
    for c in net_curves(scene):
        moved = [k for k, pid in (c.pids or {}).items() if pid == pb] if pb is not None else []
        if c is b and kb not in moved:
            moved.append(kb)
        if moved:
            pts = c.points.copy()
            pts[moved] = target
            c.points = pts
    sync(scene)
    pa, pb = pid_of(a, ka), pid_of(b, kb)
    if pa is None or pb is None or pa == pb:
        return
    for c in net_curves(scene):
        if c.pids and pb in c.pids.values():
            c.pids = {k: pa if pid == pb else pid for k, pid in c.pids.items()}
    sync(scene)


def move_point(scene, curve, k, point):
    """Move the net point at knot k of curve to point – with all lines that share it (moving only one
    would tear the connection)."""
    sync(scene)
    pid = pid_of(curve, k)
    point = np.asarray(point, float)
    for c in net_curves(scene):
        ks = [j for j, p in (c.pids or {}).items() if p == pid] if pid is not None else []
        if c is curve and k not in ks:
            ks.append(k)
        if ks:
            pts = c.points.copy()
            pts[ks] = point
            c.points = pts
    sync(scene)


def knot_at(curve, point, i=None, t=None, tol=None, keep=False):
    """Knot of the line at point (existing within tol, otherwise inserted at piece i, fraction t, or at the nearest
    place). Returns the knot index; the knot lies exactly on point afterwards – except keep and it was already there (then
    it stays where it is: an existing net point is not moved)."""
    point = np.asarray(point, float)
    tol = TOL if tol is None else tol
    ks = components.knots(curve)
    near = [k for k in ks if np.linalg.norm(curve.points[k] - point) < tol]
    if near:
        k = min(near, key=lambda j: np.linalg.norm(curve.points[j] - point))
        if keep:
            return k
    else:
        if i is None:
            _, i, t = _closest(curve, point)
        k = components.insert_point(curve, i, t)
    if np.linalg.norm(curve.points[k] - point) > 0:
        pts = curve.points.copy()
        pts[k] = point
        curve.points = pts
        components.knots(curve)
    return k


def crossings(a, b, tol):
    """Places where lines a and b cross in space (closer than tol): [(point_on_a, point_on_b)].
    One place per contact (the closest); lines that only appear to cross (on screen) lie farther apart."""
    pa, pb = np.asarray(a.points, float), np.asarray(b.points, float)
    if len(pa) < 2 or len(pb) < 2:
        return []
    if np.any(pa.min(axis=0) - tol > pb.max(axis=0)) or np.any(pb.min(axis=0) - tol > pa.max(axis=0)):
        return []
    p0, d1 = pa[:-1], np.diff(pa, axis=0)
    q0, d2 = pb[:-1], np.diff(pb, axis=0)
    # only piece pairs whose bounding boxes touch (with tol)
    lo_a, hi_a = np.minimum(pa[:-1], pa[1:]) - tol, np.maximum(pa[:-1], pa[1:]) + tol
    lo_b, hi_b = np.minimum(pb[:-1], pb[1:]), np.maximum(pb[:-1], pb[1:])
    hits = []
    for i in range(len(p0)):
        near = np.flatnonzero(np.all(lo_a[i] <= hi_b, axis=1) & np.all(hi_a[i] >= lo_b, axis=1))
        if not len(near):
            continue
        r = p0[i] - q0[near]
        a_ = d1[i] @ d1[i]
        e = np.einsum("ij,ij->i", d2[near], d2[near])
        b_ = d2[near] @ d1[i]
        c_ = r @ d1[i]
        f = np.einsum("ij,ij->i", d2[near], r)
        den = a_ * e - b_ * b_
        s = np.where(den > 1e-18, np.clip((b_ * f - c_ * e) / np.maximum(den, 1e-18), 0, 1), 0.0)
        t = np.clip((b_ * s + f) / np.maximum(e, 1e-18), 0, 1)
        s = np.clip((b_ * t - c_) / max(a_, 1e-18), 0, 1)
        ca = p0[i] + s[:, None] * d1[i]
        cb = q0[near] + t[:, None] * d2[near]
        d = np.linalg.norm(ca - cb, axis=1)
        for j in np.flatnonzero(d < tol):
            hits.append((float(d[j]), i + float(s[j]), ca[j], cb[j]))
    hits.sort(key=lambda h: h[1])
    out, last = [], None  # merge neighboring hits of the same contact: the closest place
    for h in hits:
        if last is not None and h[1] - last[1] < 2.0:
            if h[0] < last[0]:
                out[-1], last = (h[2], h[3]), h
            continue
        out.append((h[2], h[3]))
        last = h
    return out


def connect_crossings(scene, curve, others, tol, radius=None):
    """At every crossing of curve with one of the lines others, create a shared point (both lines
    stay whole). Crossings at the ends of curve are skipped (there the rule for line ends connects).
    radius: if the two lines already have a shared point that close, it is the same crossing (grazing
    cut: several hits in a row). Returns the number of new connections."""
    made = 0
    radius = tol if radius is None else max(radius, tol)
    for other in others:
        if other is curve:
            continue
        for pa, pb in crossings(curve, other, tol):
            m = pb  # on the existing line: it stays as it is – the new stroke comes to it
            if min(np.linalg.norm(curve.points[0] - m), np.linalg.norm(curve.points[-1] - m)) < tol:
                continue
            sync(scene)
            shared = set((curve.pids or {}).values()) & set((other.pids or {}).values())
            if any(np.linalg.norm(curve.points[k] - m) < radius for k, pid in (curve.pids or {}).items() if pid in shared):
                continue
            # an already existing point (knot, possibly connected to other lines) stays put, the other line
            # comes to it
            if any(np.linalg.norm(other.points[k] - m) < tol for k in components.knots(other)):
                kb = knot_at(other, m, tol=tol, keep=True)
                ka = knot_at(curve, other.points[kb], tol=tol, keep=True)  # join moves it together with all that hang on it
                join(scene, other, kb, curve, ka)
            else:
                # a point of the line's own, otherwise unconnected, very close (e.g. the corner detected while drawing, where the
                # stroke bends over a fold) is absorbed into the crossing: resolved (the shape stays), no second point
                # next to it – pulling one of the two would make the line only run out to the other (a needle)
                free = _free_knot_near(scene, curve, m, radius)
                if free is not None:
                    components.dissolve(curve, free)
                kb = knot_at(other, m, tol=tol, keep=True)
                ka = knot_at(curve, other.points[kb], tol=tol, keep=True)  # join moves it together with all that hang on it
                join(scene, other, kb, curve, ka)
            made += 1
    return made


def _free_knot_near(scene, curve, point, radius):
    """Inner knot of the line closer than radius to point, on which no other line hangs – or None."""
    sync(scene)
    refs = refs_by_pid(scene)
    n = len(curve.points)
    near = [k for k in components.knots(curve) if 0 < k < n - 1 and np.linalg.norm(curve.points[k] - point) < radius
            and len(refs.get(pid_of(curve, k), [])) <= 1]
    return min(near, key=lambda k: np.linalg.norm(curve.points[k] - point)) if near else None


def _closest(curve, point):
    a, b = curve.points[:-1], curve.points[1:]
    ab = b - a
    t = np.clip(np.einsum("ij,ij->i", point - a, ab) / np.maximum(np.einsum("ij,ij->i", ab, ab), 1e-18), 0, 1)
    d = np.linalg.norm(a + ab * t[:, None] - point, axis=1)
    i = int(np.argmin(d))
    return d[i], i, t[i]


def pid_of(curve, k):
    return (curve.pids or {}).get(k)


def refs_by_pid(scene):
    """{point ID: [(line, knot index)]} after a sync (remembered until the next sync – do not modify)."""
    sync(scene)
    state = getattr(scene, "_net_sync", None)
    cache = getattr(scene, "_net_refs", None)
    if cache is not None and cache[0] is state:
        return cache[1]
    out = {}
    curves = net_curves(scene)
    counters.C["netz_verweise"] += len(curves)
    for c in curves:
        for k, pid in (c.pids or {}).items():
            out.setdefault(pid, []).append((c, k))
    scene._net_refs = (state, out)
    return out


def degree(refs):
    """How many edges meet at a point (line ends count one, inner knots two)?"""
    d = 0
    for c, k in refs:
        n = len(c.points)
        if components.is_closed(c.points) and k in (0, n - 1):
            d += 1  # seam: listed twice, one edge each"
        else:
            d += 1 if k in (0, n - 1) else 2
    return d


def fresh_ids(curves):
    """Inserted copy: new point IDs, uniform within the copy (what was connected in the copy stays
    connected; nothing is connected to the original)."""
    remap = {}
    for c in curves:
        if c.pids:
            c.pids = {k: remap.setdefault(pid, new_pid()) for k, pid in c.pids.items()}
    for c in curves:  # point attributes hang on the IDs
        if c.pattr:
            c.pattr = {remap[p]: v for p, v in c.pattr.items() if p in remap}
    return remap


def reassign_loaded(curves):
    """Swap loaded IDs for new ones (counting starts anew each session)."""
    return fresh_ids(curves)


# --- Point attributes (F4): orient (quaternion w, x, y, z) and pscale ---

NEUTRAL = (1.0, 0.0, 0.0, 0.0, 1.0)


def get_attr(scene, pid, refs=None):
    """(qw, qx, qy, qz, pscale) of the point – neutral if nothing is set."""
    refs = refs_by_pid(scene) if refs is None else refs
    for c, _ in refs.get(pid, []):
        if c.pattr and pid in c.pattr:
            return c.pattr[pid]
    return NEUTRAL


def set_attr(scene, pid, value, refs=None):
    """Set an attribute of a point on all lines through it (neutral: remove the entry)."""
    refs = refs_by_pid(scene) if refs is None else refs
    neutral = np.allclose(value, NEUTRAL, atol=1e-9)
    for c, _ in refs.get(pid, []):
        if neutral:
            if c.pattr:
                c.pattr.pop(pid, None)
                c.pattr = c.pattr or None
        else:
            c.pattr = dict(c.pattr or {})
            c.pattr[pid] = tuple(float(x) for x in value)


def quat_of(rot):
    """Rotation matrix -> quaternion (w, x, y, z)."""
    m = np.asarray(rot, float)
    w = np.sqrt(max(0.0, 1 + m[0, 0] + m[1, 1] + m[2, 2])) / 2
    x = np.sqrt(max(0.0, 1 + m[0, 0] - m[1, 1] - m[2, 2])) / 2
    y = np.sqrt(max(0.0, 1 - m[0, 0] + m[1, 1] - m[2, 2])) / 2
    z = np.sqrt(max(0.0, 1 - m[0, 0] - m[1, 1] + m[2, 2])) / 2
    x = np.copysign(x, m[2, 1] - m[1, 2])
    y = np.copysign(y, m[0, 2] - m[2, 0])
    z = np.copysign(z, m[1, 0] - m[0, 1])
    q = np.array([w, x, y, z])
    return q / np.linalg.norm(q)


def quat_mul(a, b):
    """Hamilton product a * b (first b, then a)."""
    aw, ax, ay, az = a
    bw, bx, by, bz = b
    return np.array([aw * bw - ax * bx - ay * by - az * bz, aw * bx + ax * bw + ay * bz - az * by,
                     aw * by - ax * bz + ay * bw + az * bx, aw * bz + ax * by - ay * bx + az * bw])

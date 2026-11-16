"""Convert generators (like "Convert" in Cinema 4D): the instances become real lines and surfaces.

From the inside out – first the generators inside, then the selected one; so exactly what the instances
showed comes out (each generator acts on the result below it). Afterwards every generator is a plain null with everything
below it: original and copies as ordinary objects.

Symmetry: first it is really cut at the plane – lines are split there, the pieces on the mirror side
disappear. A surface that extends beyond the plane gets a real seam line (its cut with the plane) and is
rebuilt from the new outline (curve and fill surfaces; lines on them stay bound). If that does not work (loft tube,
outline falls apart), it stays whole – the message says so. Then everything is copied and mirrored; points on the plane
weld with the original (point IDs), the halves are one net.
Array: everything is duplicated and offset per copy – nothing is welded, what interpenetrates, interpenetrates.
"""
import numpy as np

from . import arrays, components, generators, network
from .clipboard import Clipboard, paste
from .scene import (Curve, ExtrudeSurface, LoftSurface, MeshObject, NullObject, PatchSurface, StrokeObject,
                    SurfaceObject, split_curve)
from .i18n import tr

SIDE_EPS = 1e-6  # this close to the plane counts as on it (cut, weld)


def convert(scene, null):
    """Convert generator null (and everything in it) into real geometry. Returns a message (text)."""
    report = {"cut": 0, "rebuilt": 0, "kept": [], "removed": 0, "copies": 0, "welded": 0}
    inner = [n for n in scene.descendants(null) if isinstance(n, NullObject) and n.kind != "null"]
    for g in sorted(inner, key=lambda n: -len(scene.ancestors(n))) + [null]:  # deepest first
        _convert_one(scene, g, report)
    scene.sync_lofts()
    network.sync(scene)
    parts = [tr("{0} Kopie(n) als echte Objekte").format(report['copies'])]
    if report["cut"]:
        parts.append(tr("{0} Linie(n) an der Spiegelebene geschnitten").format(report['cut']))
    if report["rebuilt"]:
        parts.append(tr("{0} Fläche(n) mit Naht neu gebildet").format(report['rebuilt']))
    if report["removed"]:
        parts.append(tr("{0} Objekt(e) ganz auf der Spiegelseite entfernt").format(report['removed']))
    if report["welded"]:
        parts.append(tr("{0} Nahtpunkt(e) verschweißt").format(report['welded']))
    if report["kept"]:
        parts.append(tr("nicht geschnitten (ragt über die Ebene): ") + ", ".join(report["kept"]))
    return " – ".join(parts)


def _convert_one(scene, g, report):
    if not generators.is_on(g):  # switched off: produces nothing, nothing to convert
        return
    if g.kind == "symmetry":
        n, o = generators.mirror_plane(g)
        cut_at_plane(scene, g, n, o, report)
        before = _net_curves_under(scene, g)
        copies = _duplicate(scene, g)
        apply_matrix_all(scene, copies, generators.reflection(n, o))
        report["copies"] += 1
        _drop_on_plane_copies(scene, before, copies, n, o)
        report["welded"] += _weld_plane(scene, before, _curves_of(copies), n, o)
    elif g.kind == "array":
        mats = arrays.matrices(scene, g)  # from the original (before copying: the content changes right away)
        source = scene.descendants(g)  # copy only the original, not the copies already created
        for m in mats[1:]:
            copies = _duplicate(scene, g, source)
            apply_matrix_all(scene, copies, m)
            report["copies"] += 1
    g.kind, g.params = "null", {}


# --- Copying and offsetting ---
def _duplicate(scene, g, objs=None):
    """Copy everything under g (or objs) once (like copy/paste: own ids, surfaces at their copied lines);
    the copy also lies under g. Lines of surfaces that lie outside come along (the surface needs them) – also
    under g."""
    objs = scene.descendants(g) if objs is None else [o for o in objs if scene.object_by_id(o.id) is o]
    if not objs:
        return []
    clip = Clipboard()
    clip.copy(scene, objs)
    created, _ = paste(scene, clip, "objects")
    for o in created:
        if getattr(o, "parent", None) is None:
            o.parent = g.id
    scene._clean_parents()
    return created


def _curves_of(objs):
    return [c for o in objs if isinstance(o, StrokeObject) and not isinstance(o, SurfaceObject) for c in o.curves]


def _net_curves_under(scene, g):
    return [c for o in scene.descendants(g) if isinstance(o, StrokeObject) and not isinstance(o, SurfaceObject)
            for c in o.curves]


def _xf(points, m):
    return np.asarray(points, float) @ m[:3, :3].T + m[:3, 3]


def apply_matrix_all(scene, objs, m):
    """Move objects rigidly (rotation, translation, mirroring): lines, own shape of the surfaces, nulls, meshes.
    Everything else (fill, nets, bound lines) derives from the lines and follows on sync."""
    m3 = m[:3, :3]
    proper = float(np.linalg.det(m3)) > 0
    q_rot = network.quat_of(m3) if proper else None
    for o in objs:
        if isinstance(o, NullObject):
            o.origin = _xf(o.origin[None], m)[0]
            axes = m3 @ o.axes
            axes[:, 2] = np.cross(axes[:, 0], axes[:, 1])  # mirrored: right-handed again
            o.axes = axes
        elif isinstance(o, MeshObject):
            o.xform = m @ o.xform
        elif isinstance(o, StrokeObject):
            for c in o.curves:
                c.points = _xf(c.points, m)
                if c.normals is not None:
                    c.normals = np.asarray(c.normals, float) @ m3.T
                if c.pattr and q_rot is not None:  # orient rotates along (mirroring: stays – no quaternion)
                    c.pattr = {p: tuple(network.quat_mul(q_rot, v[:4])) + tuple(v[4:]) for p, v in c.pattr.items()}
            ax = m3 @ o.axes
            ax[:, 2] = np.cross(ax[:, 0], ax[:, 1])
            o.axes = ax
            if isinstance(o, ExtrudeSurface):
                o.segments = [np.asarray(seg, float) @ m3.T for seg in o.segments]
    scene.sync_lofts()
    network.sync(scene)


def _drop_on_plane_copies(scene, originals, copies, n, o):
    """Lines lying entirely on the mirror plane mirror onto themselves: their copy would be a duplicate. It is dropped; what
    in the copy refers to them (outline, border, cross-section) points to the original – the halves share the seam."""
    from .clipboard import _relink_surface
    on_plane = lambda c: float(np.abs(_side(c.points, n, o)).max()) < SIDE_EPS
    origs = [c for c in originals if on_plane(c)]
    mapping = {}
    for st in [x for x in copies if isinstance(x, StrokeObject) and not isinstance(x, SurfaceObject)]:
        for c in list(st.curves):
            if not on_plane(c):
                continue
            twin = next((x for x in origs if len(x.points) == len(c.points)
                         and np.abs(x.points - c.points).max() < network.TOL), None)
            if twin is not None:
                mapping[c.id] = twin.id
                st.curves.remove(c)
    if not mapping:
        return
    id_map = {c.id: c.id for c in scene.curves}
    id_map.update(mapping)
    surface_map = {s.id: s.id for s in scene.surfaces}
    for s in copies:
        if isinstance(s, SurfaceObject):
            _relink_surface(s, id_map, surface_map)
    for st in [x for x in copies if isinstance(x, StrokeObject) and not isinstance(x, SurfaceObject)]:
        if not st.curves and st in scene.strokes:
            scene.delete([st])
    scene.sync_lofts()
    network.sync(scene)


def _weld_plane(scene, originals, copies, n, o):
    """Knots of the copy that lie exactly on the mirror plane on a knot of the original: one point."""
    network.sync(scene)
    orig_pts = [c.points[k] for c in originals for k in (c.pids or {})
                if abs(float((c.points[k] - o) @ n)) < SIDE_EPS]
    if not orig_pts:
        return 0
    orig_pts = np.array(orig_pts)
    done, welded = [], 0
    for c in copies:
        for k in list((c.pids or {}).keys()):
            p = c.points[k]
            if abs(float((p - o) @ n)) >= SIDE_EPS or any(np.linalg.norm(p - q) < network.TOL for q in done):
                continue
            if np.min(np.linalg.norm(orig_pts - p, axis=1)) < network.TOL:
                done.append(p.copy())
                welded += network.merge_at(scene, p) > 0
    return welded


# --- Cutting at the plane ---
def _side(points, n, o):
    return (np.asarray(points, float) - o) @ n


def cut_at_plane(scene, g, n, o, report):
    """Cut everything under g at the plane (keep: n·(x-o) >= 0)."""
    from . import netedit
    surfaces = [s for s in scene.descendants(g) if isinstance(s, SurfaceObject)]
    plan = {}  # surface -> ("keep" | "drop" | (net, border line ids))
    for s in surfaces:
        mesh = s.fill_mesh()
        if mesh is None:
            continue
        d = _side(mesh[0], n, o)
        if d.min() >= -SIDE_EPS:
            plan[s.id] = "keep"
        elif d.max() <= SIDE_EPS:
            plan[s.id] = "drop"
        else:
            plan[s.id] = (mesh, [c.id for c in netedit._border_of(scene, s)])
    strokes = [st for st in scene.descendants(g) if isinstance(st, StrokeObject) and not isinstance(st, SurfaceObject)]
    for st in strokes:
        for c in list(st.curves):
            report["cut"] += _cut_curve(scene, st, c, n, o)
        if not st.curves:
            scene.delete([st])
            report["removed"] += 1
    network.sync(scene)
    for s in surfaces:
        what = plan.get(s.id)
        if what == "drop":
            scene.delete([s])
            report["removed"] += 1
        elif isinstance(what, tuple):
            if _rebuild_with_seam(scene, s, what[0], what[1], n, o):
                report["rebuilt"] += 1
            else:
                report["kept"].append(s.name)


def _cut_curve(scene, owner, c, n, o):
    """Split a line at the plane (via scene._split_in: surfaces and notes follow the pieces), delete the pieces on the
    mirror side. Returns 1 if it was cut."""
    d = _side(c.points, n, o)
    if d.min() >= -SIDE_EPS:
        return 0
    if d.max() <= SIDE_EPS:
        owner.curves.remove(c)
        return 1
    pieces = [c]
    changed = True
    while changed:  # split at every crossing (piece by piece)
        changed = False
        for piece in list(pieces):
            parts = _split_once(piece, n, o)
            if parts is None:
                continue
            k = next(j for j, x in enumerate(owner.curves) if x is piece)
            owner.curves[k:k + 1] = list(parts)
            scene.split_map[piece.id] = [parts[0].id, parts[1].id]
            pieces[pieces.index(piece):pieces.index(piece) + 1] = list(parts)
            changed = True
            break
    for piece in pieces:  # pieces on the mirror side (center counts) away
        mid = piece.points[len(piece.points) // 2] if len(piece.points) > 2 else piece.points.mean(axis=0)
        if float((mid - o) @ n) < 0 and piece in owner.curves:
            owner.curves.remove(piece)
    return 1


def _split_once(piece, n, o):
    """Split at the first place where the line changes sides of the plane -> (first, second) or None. If a point lies
    exactly on the plane there, it is split at that point (it stays a point of both pieces), otherwise at the intersection of the segment."""
    d = _side(piece.points, n, o)
    sign = np.where(d > SIDE_EPS, 1, np.where(d < -SIDE_EPS, -1, 0))
    last, last_i = 0, None
    for i, s in enumerate(sign):
        if s == 0:
            continue
        if last and s != last:
            on = [k for k in range(last_i + 1, i) if sign[k] == 0]
            if on:  # point(s) on the plane in between: split at the first
                return _split_at_vertex(piece, on[0])
            t = d[last_i] / (d[last_i] - d[i])
            return split_curve(piece, piece.points[last_i] + (piece.points[i] - piece.points[last_i]) * t, last_i, t)
        last, last_i = s, i
    return None


def _split_at_vertex(curve, k):
    """Split a line at point k (like split_curve, but without a new point: k is the end of the first, the start of the second)."""
    from .scene import inherit
    if k <= 0 or k >= len(curve.points) - 1:
        return None
    first = Curve(curve.points[:k + 1].copy(), curve.plane_id, curve.widths[:k + 1].copy(), curve.generated)
    second = Curve(curve.points[k:].copy(), curve.plane_id, curve.widths[k:].copy(), curve.generated)
    inherit(first, curve)
    inherit(second, curve)
    if curve.normals is not None and len(curve.normals) == len(curve.points):
        first.normals, second.normals = np.asarray(curve.normals)[:k + 1].copy(), np.asarray(curve.normals)[k:].copy()
    if curve.knots is not None and curve.knots[0] == len(curve.points):
        inner = curve.knots[1]
        first.knots = (len(first.points), tuple(j for j in inner if 0 < j < k))
        second.knots = (len(second.points), tuple(j - k for j in inner if k < j < len(curve.points) - 1))
        if curve.pids:
            first.pids = {j: p for j, p in curve.pids.items() if j <= k}
            second.pids = {j - k: p for j, p in curve.pids.items() if j >= k}
    return first, second


def _seam_chains(verts, tris, n, o):
    """Cut edges of the cut net on the plane as polylines (chains, longest first)."""
    v, t = generators.clip_mesh(verts, tris, n, o)
    edges = {}
    for tri in t:
        for k in range(3):
            e = (int(min(tri[k], tri[(k + 1) % 3])), int(max(tri[k], tri[(k + 1) % 3])))
            edges[e] = edges.get(e, 0) + 1
    on = np.abs(_side(v, n, o)) < 1e-6
    seam = [e for e, cnt in edges.items() if cnt == 1 and on[e[0]] and on[e[1]]]
    nbr = {}
    for a, b in seam:
        nbr.setdefault(a, []).append(b)
        nbr.setdefault(b, []).append(a)
    chains, used = [], set()
    for start in [k for k, vs in nbr.items() if len(vs) == 1] + list(nbr):
        if start in used:
            continue
        chain, prev, cur = [start], None, start
        used.add(start)
        while True:
            nxt = [x for x in nbr[cur] if x != prev and x not in used]
            if not nxt:
                break
            prev, cur = cur, nxt[0]
            used.add(cur)
            chain.append(cur)
        if len(chain) >= 2:
            chains.append(v[chain])
    chains.sort(key=lambda p: -float(np.linalg.norm(np.diff(p, axis=0), axis=1).sum()))
    return chains


def _rebuild_with_seam(scene, s, mesh, border_ids, n, o):
    """Rebuild a surface that extended beyond the plane, with a seam. True if it worked."""
    from . import netedit
    if not (isinstance(s, PatchSurface) and s.patch_lines or type(s) is SurfaceObject and s.links):
        return False
    chains = _seam_chains(mesh[0], mesh[1], n, o)
    if len(chains) != 1:
        return False  # falls apart into several parts or no cut
    border = []
    for cid in border_ids:  # the kept pieces of the old border lines
        for sub in _pieces(scene, cid):
            c = scene.curve_by_id(sub)
            if c is not None and not any(c is b for b in border):
                border.append(c)
    on_plane = [(c, k) for c in border for k in (0, len(c.points) - 1)
                if abs(float((c.points[k] - o) @ n)) < SIDE_EPS]
    if len(on_plane) != 2:
        return False
    seam = chains[0].copy()
    a, b = on_plane[0][0].points[on_plane[0][1]], on_plane[1][0].points[on_plane[1][1]]
    if np.linalg.norm(seam[0] - a) + np.linalg.norm(seam[-1] - b) > np.linalg.norm(seam[0] - b) + np.linalg.norm(seam[-1] - a):
        seam = seam[::-1]
    size = float(np.linalg.norm(np.ptp(mesh[0], axis=0)))
    if np.linalg.norm(seam[0] - a) > 0.05 * size or np.linalg.norm(seam[-1] - b) > 0.05 * size:
        return False  # seam does not meet the cut border lines
    seam[0], seam[-1] = a, b  # exactly onto the intersection points
    owner = scene.owner_of(border[0])
    width = float(np.mean([np.mean(c.widths) for c in border]))
    # from intersection point to intersection point: there the width of the cut border lines, in between proportionally
    line = Curve(seam, None, components.widths_between(seam, [on_plane[0][0]], [on_plane[1][0]], width))
    owner.curves.append(line)
    network.sync(scene)
    (ca, ka), (cb, kb) = on_plane
    network.join(scene, ca, ka, line, 0)
    network.join(scene, cb, kb, line, len(line.points) - 1)
    # lines on the surface that now end at the seam: a shared point there (net lines stay net lines)
    for cid in list(s.attached):
        for sub in _pieces(scene, cid):
            c = scene.curve_by_id(sub)
            if c is None:
                continue
            for k in (0, len(c.points) - 1):
                if abs(float((c.points[k] - o) @ n)) < SIDE_EPS:
                    scene.insert_knot_at(c.points[k], tolerance=1e-4 * max(size, 1e-9))
    network.sync(scene)
    rebuild = netedit._rebuild_from if isinstance(s, PatchSurface) else netedit._rebuild_fill
    return bool(rebuild(scene, s, border + [line]))


def _pieces(scene, cid):
    """Remaining pieces of a (possibly split, partly deleted) line."""
    if scene.curve_by_id(cid) is not None:
        return [cid]
    out = []
    for p in scene.split_map.get(cid, []):
        out += _pieces(scene, p)
    return out

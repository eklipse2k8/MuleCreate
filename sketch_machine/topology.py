"""Topology rules after operations that create lines (loft, extrude, fill ...).

Rule: between two points there is at most ONE line of the same shape. What an operation creates twice is merged with the
existing line – the new one disappears, surfaces, lofts and notes follow the existing one via split_map (as with
splitting). Only the newly created lines are checked; foreign ones are never deleted.
Beforehand: points of the new lines that lie exactly (tolerance weld_tol) on an existing point are welded
to it – this way e.g. the copies of two separately extruded legs of an L line meet at the corner.
(Artist, harbor test 09.11.: "This simply must not happen to us.")
"""
import numpy as np

from . import components, network


def _sample(points, n=9):
    seg = np.linalg.norm(np.diff(points, axis=0), axis=1)
    arc = np.concatenate([[0.0], np.cumsum(seg)])
    if arc[-1] <= 0:
        return points[[0]]
    t = np.linspace(0, arc[-1], n)
    return np.stack([np.interp(t, arc, points[:, j]) for j in range(points.shape[1])], axis=1)


def _dist_to_polyline(pts, poly):
    a, b = poly[:-1], poly[1:]
    ab = b - a
    t = np.clip(np.einsum("pmj,mj->pm", pts[:, None] - a[None], ab) / np.maximum((ab * ab).sum(1), 1e-18)[None], 0, 1)
    return np.linalg.norm(a[None] + t[..., None] * ab[None] - pts[:, None], axis=2).min(axis=1)


def same_shape(a, b, tol):
    """Do two lines (in either direction) practically lie on top of each other?"""
    if len(a.points) < 2 or len(b.points) < 2:
        return False
    return (_dist_to_polyline(_sample(a.points), b.points).max() <= tol
            and _dist_to_polyline(_sample(b.points), a.points).max() <= tol)


def weld_onto_existing(scene, new_curves, weld_tol):
    """Nodes of the new lines that lie (almost) exactly on a node of another line, connect them – first to
    an existing line, otherwise to another new one (shared corner of two surfaces extruded at the same time).
    At most one connection per node: two deliberately separate existing points are never connected.
    Returns the number of connections."""
    from scipy.spatial import cKDTree
    network.sync(scene)
    new_ids = {id(c) for c in new_curves}
    spots = [(o, j) for o in network.net_curves(scene) for j in (o.pids or {})]
    if not spots:
        return 0
    tree = cKDTree(np.array([o.points[j] for o, j in spots]))
    made = 0
    for c in new_curves:
        if c.paint or len(c.points) < 2:
            continue
        for k in components.knots(c):
            near = [spots[n] for n in tree.query_ball_point(c.points[k], weld_tol)]
            near = [(o, j) for o, j in near if o is not c and network.pid_of(o, j) != network.pid_of(c, k)]
            if not near:
                continue
            o, j = min(near, key=lambda x: id(x[0]) in new_ids)  # existing line first
            if any(network.pid_of(x, y) == network.pid_of(c, k) for x, y in near):
                continue  # already connected to one of them
            network.join(scene, o, j, c, k)  # the new line moves onto the point
            made += 1
    return made


def merge_new_duplicates(scene, new_curves, tol_rel=0.003, tol_abs=0.0):
    """Remove new lines that run between the same points (IDs) as an existing line and lie on it;
    references follow the existing one via split_map. Returns [(removed, kept)]."""
    network.sync(scene)
    new_ids = {id(c) for c in new_curves}
    by_ends = {}
    for c in network.net_curves(scene):
        a, b = network.pid_of(c, 0), network.pid_of(c, len(c.points) - 1)
        if a is not None and b is not None:
            by_ends.setdefault(frozenset((a, b)), []).append(c)
    gone = []
    removed = set()
    for c in new_curves:
        if c.paint or id(c) in removed or len(c.points) < 2:
            continue
        a, b = network.pid_of(c, 0), network.pid_of(c, len(c.points) - 1)
        if a is None or b is None or a == b:  # closed lines: direction not detectable, better leave alone
            continue
        length = float(np.linalg.norm(np.diff(c.points, axis=0), axis=1).sum())
        tol = max(tol_rel * length, tol_abs, 1e-6)
        keep = None
        for o in by_ends.get(frozenset((a, b)), []):
            if o is c or id(o) in removed or o.paint or not same_shape(c, o, tol):
                continue
            # rather keep an existing (older) line; two new ones: the first
            if keep is None or (id(keep) in new_ids and id(o) not in new_ids):
                keep = o
        if keep is None:
            continue
        reversed_ = network.pid_of(keep, 0) != a
        if reversed_ and _referenced(scene, c.id) and not _rehang_reversed(scene, c, keep):
            continue  # running the opposite way, and a surface hangs on it such that it cannot be turned around: leave alone
        owner = scene.owner_of(c)
        if owner is None:
            continue
        owner.curves[:] = [x for x in owner.curves if x is not c]
        scene.split_map[c.id] = [keep.id]
        removed.add(id(c))
        gone.append((c, keep))
    if gone:
        network.sync(scene)
    return gone


def _referenced(scene, cid):
    """Does any surface (border, outline, cross-section, longitudinal line, attachment) hang on the line?"""
    for srf in scene.surfaces:
        for link, _flipped in getattr(srf, "links", None) or []:
            if cid in scene.link_ids(link):
                return True
        if cid in (getattr(srf, "patch_lines", None) or []):
            return True
        for src in getattr(srf, "sources", None) or []:
            if src is not None and src[0] == "lines" and cid in src[1]:
                return True
        if any(r[0] == cid for r in getattr(srf, "rails", None) or [] if isinstance(r, (list, tuple))):
            return True
        if cid in (getattr(srf, "attached", None) or ()):
            return True
    return False


def _rehang_reversed(scene, c, keep):
    """Re-hang curve surfaces whose border contains c (reverse to keep) directly onto keep and reverse the
    running direction there (patch_order). Only if c hangs on nothing else (outline, cross-section, longitudinal line,
    attachment, net line) – then True, otherwise nothing changed and False."""
    import json
    users = []
    for srf in scene.surfaces:
        lines = getattr(srf, "patch_lines", None) or []
        if c.id in lines:
            if lines.count(c.id) != 1 or str(c.id) in json.dumps(getattr(srf, "net", None) or {}, default=str):
                return False
            users.append(srf)
    probe = [x for x in scene.surfaces if x not in users]
    if any(_referenced_in(x, scene, c.id) for x in probe):
        return False
    for srf in users:
        idx = srf.patch_lines.index(c.id)
        srf.patch_lines = [keep.id if i == idx else cid for i, cid in enumerate(srf.patch_lines)]
        srf.patch_order = [(i, (not f) if i == idx else f) for i, f in srf.patch_order]
    return True


def _referenced_in(srf, scene, cid):
    for link, _flipped in getattr(srf, "links", None) or []:
        if cid in scene.link_ids(link):
            return True
    if cid in (getattr(srf, "patch_lines", None) or []):
        return True
    for src in getattr(srf, "sources", None) or []:
        if src is not None and src[0] == "lines" and cid in src[1]:
            return True
    if any(r[0] == cid for r in getattr(srf, "rails", None) or [] if isinstance(r, (list, tuple))):
        return True
    return cid in (getattr(srf, "attached", None) or ())


def _only_unordered_refs(scene, cid):  # for cleanup: only remove reverse-running ones if nothing hangs on them
    return not _referenced(scene, cid)


def consolidate(scene, new_curves, weld_tol, tol_abs=0.0):
    """After an operation: first connect points lying exactly on each other, then remove duplicate new lines."""
    new_curves = [c for c in new_curves if c is not None]
    if not new_curves:
        return []
    weld_onto_existing(scene, new_curves, weld_tol)
    return merge_new_duplicates(scene, new_curves, tol_abs=tol_abs)

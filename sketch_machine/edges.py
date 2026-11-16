"""Lines as editable edges: select, move/rotate/scale.

A line is addressed via ("line", stroke_id, line_id). Lines lying on top of each other
(same points) are coupled and move together; lines that touch a moving end
(welded nodes) are stretched along toward that end.
"""
import numpy as np

from . import components

COUPLE_TOL = 1e-6  # lines lying on top of each other (same points) count as coupled
COUPLE_GRID = 1e-4  # grid size for the coupling's endpoint index
WELD_TOL = 1e-5  # line ends closer than this count as a welded node
WELD_CELL = 4 * WELD_TOL  # grid size of the endpoint index when welding


def all_edges(scene):
    """[(ref, points)] of all lines (paint strokes not: they are not edges)."""
    return [(("line", st.id, c.id), c.points) for st in scene.strokes for c in st.curves if not c.paint]


def _lines(scene):
    return {("line", st.id, c.id): c for st in scene.strokes for c in st.curves}


def _line(scene, ref):
    stroke = next((st for st in scene.strokes if st.id == ref[1]), None)
    return None if stroke is None else next((c for c in stroke.curves if c.id == ref[2]), None)


def ref_to_curve(scene, ref):
    return _line(scene, ref) if ref[0] == "line" else None


def curve_to_ref(scene, curve):
    owner = scene.owner_of(curve)
    return None if owner is None else ("line", owner.id, curve.id)


def _falloff(points, from_end):
    """Weights 1 at the chosen end down to 0 at the other, linear by arc length."""
    arc = np.concatenate([[0], np.cumsum(np.linalg.norm(np.diff(points, axis=0), axis=1))])
    t = arc / max(arc[-1], 1e-12)
    return t if from_end else 1 - t


def _couple_key(pts):
    """Lines with the same endpoints (in either direction) and the same point count land in the same bucket."""
    ends = sorted(tuple(np.round(p / COUPLE_GRID).astype(np.int64)) for p in (pts[0], pts[-1]))
    return (len(pts), *ends)


def coupled_all(scene, refs):
    """{ref: [other lines lying exactly on it]} for many lines at once (index by endpoints)."""
    pts_of, index = {}, {}
    for ref, pts in all_edges(scene):
        pts_of[ref] = pts
        if len(pts) >= 2:
            index.setdefault(_couple_key(pts), []).append(ref)
    out = {}
    for ref in refs:
        pts = pts_of.get(ref)
        out[ref] = [] if pts is None or len(pts) < 2 else [
            o for o in index.get(_couple_key(pts), ()) if o != ref and (
                np.allclose(pts_of[o], pts, atol=COUPLE_TOL) or np.allclose(pts_of[o][::-1], pts, atol=COUPLE_TOL))]
    return out


def _cell(point):
    x, y, z = (int(c) for c in np.floor(np.asarray(point) / WELD_CELL))
    return x, y, z


_NEIGHBOURS = [(x, y, z) for x in (-1, 0, 1) for y in (-1, 0, 1) for z in (-1, 0, 1)]


def open_end_keys(curves):
    """{(id(line), end)} of all line ends where no other end lies (exact, up to WELD_TOL).
    An end in the middle of another line (T-junction) counts as open: it is not welded."""
    pts, keys, index = [], [], {}
    for c in curves:
        for end in (0, -1):
            index.setdefault(_cell(c.points[end]), []).append(len(pts))
            pts.append(c.points[end])
            keys.append((id(c), end))
    out = set()
    for k, p in enumerate(pts):
        x, y, z = _cell(p)
        if not any(j != k and np.linalg.norm(pts[j] - p) < WELD_TOL
                   for dx, dy, dz in _NEIGHBOURS for j in index.get((x + dx, y + dy, z + dz), ())):
            out.add(keys[k])
    return out


class EdgeHandle:
    """A line (reference) with direct access to its points."""

    def __init__(self, scene, ref, curve):
        self.scene, self.ref, self.curve = scene, ref, curve

    def points(self):
        return self.curve.points

    def set_points(self, pts):
        self.curve.points = np.asarray(pts, float)

    def pivot(self):
        return self.curve.points.mean(axis=0)

    def local_axes(self):
        pts = self.curve.points
        u = pts[-1] - pts[0]
        u = u / np.linalg.norm(u) if np.linalg.norm(u) > 1e-9 else np.array([1.0, 0, 0])
        helper = np.array([0, 1.0, 0]) if abs(u[1]) < 0.9 else np.array([0, 0, 1.0])
        n = np.cross(u, helper)
        n /= np.linalg.norm(n)
        return np.column_stack([u, np.cross(n, u), n])


class EdgeGroup:
    """Selected (and coupled) lines as one gizmo target (same interface as objects): first set all lines,
    then the lines connected at their ends follow softly."""
    scale_axes = (0, 1, 2)

    def __init__(self, scene, handles, frozen, weld=True, only=None):
        self.scene, self.handles, self.frozen, self.weld = scene, handles, frozen, weld
        self.only = only  # weld only with these lines (freshly pasted copy: only among themselves)

    @property
    def refs(self):
        return [h.ref for h in self.handles]

    def bounds(self):
        pts = np.vstack([h.points() for h in self.handles])
        return pts.min(axis=0), pts.max(axis=0)

    def pivot(self):
        lo, hi = self.bounds()
        return (lo + hi) / 2

    def local_axes(self):
        return self.handles[0].local_axes()

    def _apply(self, fn):
        # compute all targets from the initial state, only then set them
        olds = [h.points().copy() for h in self.handles]
        news = [fn(old) for old in olds]
        # Lines connected to the ends of the selected lines (same point id - never by position) go
        # along at this point and taper off softly up to their neighbor points: another line end as well as a
        # line running through (e.g. the side line of a loft at the end of a cross-section). Create before
        # moving: building them reconciles the net while everything still lies on top of each other
        # Once per drag, not per frame: each of these groups needed a directory of all nodes of the
        # scene when created - with 40 selected lines in a large scene 0.2 s per frame, with a whole object seconds
        # (harbor, import_silos, 10.11.). The groups hold as long as the scene is in the same state (a new
        # drag secures an undo step and increments revision); one shared directory for all.
        key = (getattr(self.scene, "revision", None), sum(len(st.curves) for st in self.scene.strokes))
        cached = getattr(self, "_through", None)
        if cached is None or cached[0] != key:
            links = self._through_links() if self.weld else []
            index = components.KnotIndex(self.scene) if links else None
            cached = self._through = (key, [(components.ComponentGroup(self.scene, [(o, j)], [], weld=False, index=index),
                                             hi, end) for (o, j), (hi, end) in links])
        through = cached[1]
        for h, new in zip(self.handles, news):
            h.set_points(new)
        for group, hi, end in through:
            old, new = olds[hi][end], news[hi][end]
            if np.linalg.norm(new - old) > 1e-12:
                group.translate(new - old)

    def _through_links(self):
        """[((line, node), (grip index, end))]: other lines at the same net point as the ends of the selected
        lines (determined before moving - afterwards they would no longer lie on top of each other)."""
        from . import network
        mine = {id(h.curve) for h in self.handles}
        refs = network.refs_by_pid(self.scene)
        out, seen = [], set()
        for hi, h in enumerate(self.handles):
            c = h.curve
            for end in (0, -1):
                pid = network.pid_of(c, end % len(c.points))
                for o, j in refs.get(pid, []) if pid is not None else []:
                    if id(o) in mine or (id(o), j) in seen or o.paint:
                        continue
                    if self.only is not None and not any(o is lc for r, lc in _lines(self.scene).items() if r in self.only):
                        continue
                    seen.add((id(o), j))
                    out.append(((o, j), (hi, end)))
        return out

    def translate(self, delta):
        self._apply(lambda pts: pts + delta)

    def rotate(self, rot, pivot):
        self._apply(lambda pts: pivot + (pts - pivot) @ rot.T)

    def scale(self, factors, axes, pivot):
        m = axes @ np.diag(factors) @ axes.T
        self._apply(lambda pts: pivot + (pts - pivot) @ m.T)


def handles_for(scene, refs, weld=True, only=None):
    """Gizmo target for selected lines plus all lines coupled with them ([EdgeGroup] or []).
    weld=False: only the lines themselves, without coupling and welding. only (freshly pasted copy still lying on
    the original): coupled and welded only within the copy - otherwise it would drag the original along."""
    all_refs = list(dict.fromkeys(refs))
    if weld:
        for others in coupled_all(scene, all_refs).values():
            all_refs += [o for o in others if only is None or o in only]
        all_refs = list(dict.fromkeys(all_refs))
    lines = _lines(scene)
    handles = [EdgeHandle(scene, r, lines[r]) for r in all_refs if r in lines]
    return [EdgeGroup(scene, handles, frozenset(all_refs), weld, only)] if handles else []

"""Scene surfaces: fill surfaces (follow their outline via a cage), lofts and curve surfaces (net surfaces:
their real lines shape them), cross-sections, side lines, sync after every change.

Part of the Scene class (scene.py), split out as a mixin like the viewport parts under vp/."""
import numpy as np


from . import cage, components, extrude, loft, netfill, netsurf, network, patchnet
from . import counters, lru
from . import patch as patch_geo
from .scene import (_CHAIN_CACHE, DEFAULT_WIDTH, LOFT_BIND_TOL, Curve, ExtrudeSurface, LoftSurface, PatchSurface,
                    SurfaceObject, inherit)
from .i18n import tr


def _same_objs(memo, objs):
    """The same objects as remembered (identity)? For inputs that are replaced instead of changed in place."""
    return memo is not None and len(memo) == len(objs) and all(a is b for a, b in zip(memo, objs))


def _closest_on_poly(pts, p):
    """Nearest point on the polyline pts to p."""
    pts = np.asarray(pts, float)
    a, ab = pts[:-1], np.diff(pts, axis=0)
    t = np.clip(np.einsum("ij,ij->i", p - a, ab) / np.maximum(np.einsum("ij,ij->i", ab, ab), 1e-18), 0, 1)
    q = a + ab * t[:, None]
    return q[int(np.argmin(np.linalg.norm(q - p, axis=1)))]


def _project_many(pts, P):
    """For each point in P (N, 3): distance to the polyline pts and arc length of the nearest place (like patchnet.arc_at)."""
    pts = np.asarray(pts, float)
    if not len(P):
        return np.zeros(0), np.zeros(0)
    a, ab = pts[:-1], np.diff(pts, axis=0)
    rel = P[:, None, :] - a[None]
    t = np.clip(np.einsum("nij,ij->ni", rel, ab) / np.maximum(np.einsum("ij,ij->i", ab, ab), 1e-18)[None], 0, 1)
    d = np.linalg.norm(a[None] + ab[None] * t[..., None] - P[:, None, :], axis=2)
    i = np.argmin(d, axis=1)
    n = np.arange(len(P))
    return d[n, i], patchnet.arc(pts)[i] + t[n, i] * np.linalg.norm(ab[i], axis=1)


def _arc_of_pid(line, other):
    """Arc length along the net line line (ids, points, {index: point ID}, …) up to its shared point with other."""
    shared = set(line[2].values()) & set(other[2].values())
    if not shared:
        return -1.0
    pid = next(iter(shared))
    k = next(i for i, p in line[2].items() if p == pid)
    return float(patchnet.arc(line[1])[k])


def _row_curves(g):
    """Grid rows of a surface as lines. They belong to no stroke object and lie on no drawing surface:
    the index "lines per drawing surface" (Scene.curves_on) and the sync of the curve net (network.sync)
    stay valid – otherwise the sync would re-check all lines of the scene after every single surface (harbor 11.11.:
    on each release 50 times the index, 400 times the net)."""
    from . import scene as scene_mod
    plane, net = scene_mod.PLANE_EPOCH[0], network.EPOCH[0]
    rows = [Curve(row.copy(), None) for row in g]
    scene_mod.PLANE_EPOCH[0], network.EPOCH[0] = plane, net
    return rows


# --- Release without recomputation ---
# If a surface was only moved together with all its lines, its finished state is the same as before, just in a different
# place: grid rows, net geometry, fill net and the displayed net move along, the sync stamp is set for
# the new position – the sync then skips it like any unchanged surface. Before, every
# co-moved surface was rebuilt from its lines once after release (harbor 11.11.: 94 surfaces, 0.4 s per release).
# When rotated or scaled it is still recomputed (there directions, lengths and the division of the net change).
_PLACED = ("_net_pts", "_net_geo", "_gordon", "_tube_geo", "netmesh")  # fields of a surface that hold locations in space
_NOT_PLACED = frozenset(("hard_u", "hard_v", "fis", "uv", "on", "fi", "rows", "cols", "key", "last", "idx"))


def _shifted(x, t):
    """All locations in x (float arrays (…, 3)) shifted by t – lists, tuples, dicts are traversed, everything newly
    created (nothing in place). Triangle indices (int), uv and hardness values stay."""
    tx = type(x)
    if tx is np.ndarray:
        return x + t if x.dtype == np.float64 and x.ndim >= 2 and x.shape[-1] == 3 else x
    if tx is list:
        return [_shifted(v, t) for v in x]
    if tx is tuple:
        return tuple(_shifted(v, t) for v in x)
    if tx is dict:
        return {k: (v if k in _NOT_PLACED else _shifted(v, t)) for k, v in x.items()}
    return x


def _loose_diff(a, b, tol, path):
    """Check mode: first place where two states differ by more than tol, or None."""
    if a is b:
        return None
    if type(a) is not type(b):
        return f"{path}: {type(a).__name__} / {type(b).__name__}"
    if isinstance(a, np.ndarray):
        if a.shape != b.shape:
            return f"{path}: {a.shape} / {b.shape}"
        if a.dtype.kind != "f":
            return None if np.array_equal(a, b) else f"{path}: Werte"
        if a.ndim < 2 or a.shape[-1] != 3:
            return None  # not a location (places on lines, uv, hardness): does not depend on the position
        worst = float(np.abs(a - b).max()) if a.size else 0.0
        return None if worst <= tol else f"{path}: Abstand {worst:.3g}"
    if isinstance(a, (list, tuple)):
        if len(a) != len(b):
            return f"{path}: Länge {len(a)} / {len(b)}"
        return next((r for r in (_loose_diff(x, y, tol, f"{path}[{i}]") for i, (x, y) in enumerate(zip(a, b))) if r), None)
    if isinstance(a, dict):
        if a.keys() != b.keys():
            return f"{path}: Schlüssel"
        return next((r for r in (_loose_diff(v, b[k], tol, f"{path}.{k}") for k, v in a.items()
                                 if k not in _NOT_PLACED) if r), None)
    if isinstance(a, float):
        return None if abs(a - b) <= tol else f"{path}: {a} / {b}"
    if isinstance(a, int) and not isinstance(a, bool):
        return None  # point IDs in the remembered net geometry: may be from earlier even without a drag (locations are checked)
    if isinstance(a, Curve):
        return _loose_diff(a.points, b.points, tol, path + ".points")
    return None if a == b else f"{path}: {a!r} / {b!r}"[:200]


def _placed_state(s):
    """Check mode: everything on a surface that holds locations (moved along for comparison versus recomputed)."""
    d = s.__dict__
    out = {name: d.get(name) for name in _PLACED}
    out["rows"] = [c.points for c in s.curves]
    out["offset"] = d.get("offset")  # (shift of the surface by lines on it: does not depend on the position)
    out["attached"] = {cid: dict(att) if isinstance(att, dict) else att for cid, att in (s.attached or {}).items()}
    out["mesh"] = s.fill_mesh()
    return out


class SurfaceSyncMixin:
    # --- Drawing surfaces ---
    def create_fill(self, ordered):
        """Create a drawing surface from an ordered loop [(Curve, reversed)]. The surface gets its own
        copy of the outline – the lines themselves stay where and what they are."""
        outline = []
        for curve, flipped in ordered:
            pts, widths = (curve.points[::-1], curve.widths[::-1]) if flipped else (curve.points, curve.widths)
            outline.append(Curve(pts.copy(), None, widths.copy()))
        surface = SurfaceObject(self._unique_name(tr("Fläche"), self.surfaces), outline)
        surface.links = [(curve.id if self.curve_by_id(curve.id) is curve else None, bool(flipped))
                         for curve, flipped in ordered]
        self.place_with_lines(surface, [curve for curve, _ in ordered])
        self.surfaces.append(surface)
        self._start_fill_links(surface)
        return surface

    def surface_lines(self, surface):
        """The net of a surface – what belongs to it when it is copied or moved: border lines or outline,
        cross-sections, side lines and everything drawn on it (real lines and painting) – each line once."""
        out, seen = [], set()

        def add(c):
            if c is not None and id(c) not in seen:  # (out holds the lines: ids stay valid)
                seen.add(id(c))
                out.append(c)
        pieces = lambda cid: [self.curve_by_id(i) for i in (self.split_pieces(cid) or [])]
        if isinstance(surface, PatchSurface):
            for c in self.patch_border(surface):
                add(c)
        if isinstance(surface, LoftSurface):
            for src in surface.sources:
                if src and src[0] == "lines":
                    for cid in src[1]:
                        for c in pieces(cid):
                            add(c)
            for cid, _ in surface.rails:
                for c in pieces(cid):
                    add(c)
        elif isinstance(surface, SurfaceObject):
            for cid, _ in surface.links:
                for i in self.link_ids(cid):
                    for c in pieces(i):
                        add(c)
        for cid in getattr(surface, "attached", {}) or {}:
            add(self.curve_by_id(cid))
        for c in self.curves_on(surface.id):
            add(c)
        return out

    def split_pieces(self, cid):
        """Ids of the lines cid was split into (recursively, in direction of travel), or None if there is no
        complete chain for it. A line that still exists is its own piece."""
        if self.curve_by_id(cid) is not None:
            return [cid]
        parts = self.split_map.get(cid)
        if not parts:
            return None
        out = []
        for pid in parts:
            sub = self.split_pieces(pid)
            if sub is None:
                return None
            out += sub
        return out

    @staticmethod
    def link_ids(cid):
        """Lines of an outline member: None (gap), an id or a chain (list, after splitting)."""
        return [] if cid is None else list(cid) if isinstance(cid, (list, tuple)) else [cid]

    def _follow_splits(self, surface):
        """Replace outline members whose line was split by the chain of their pieces – the surface keeps
        following, even if split and moved in the same step (cage stays the same)."""
        changed = False
        links = []
        for cid, flipped in surface.links:
            ids = self.link_ids(cid)
            if ids and any(self.curve_by_id(i) is None for i in ids):
                chain = []
                for i in ids:
                    sub = self.split_pieces(i)
                    if sub is None:
                        chain = None
                        break
                    chain += sub
                if chain:
                    cid = chain if len(chain) > 1 else chain[0]
                    changed = True
            links.append((cid, flipped))
        if changed:
            surface.links = links
        return changed

    def outline_insert(self, c1, end1, c2, new):
        """Rounding of an outline corner (Ctrl+B): lines c1 and c2 meet there, were shortened, new connects
        them (c1 at its end end1). new becomes part of the outline member of c1 – like an arc that would have been rounded into c1
        itself: cage and rest shape stay, the surface follows the arc. -> [(surface, old members)]"""
        out = []
        for surface in self.surfaces:
            if type(surface) is not SurfaceObject or not surface.links or surface.frozen is not None:
                continue
            ids = [self.link_ids(cid) for cid, _ in surface.links]
            k = next((j for j, chain in enumerate(ids) if c1.id in chain), None)
            n = len(ids)
            if k is None or not any(c2.id in ids[j] for j in (k, (k - 1) % n, (k + 1) % n)):
                continue
            chain = ids[k]
            i = chain.index(c1.id)
            if i > 0 and chain[i - 1] == c2.id:
                chain.insert(i, new.id)
            elif i + 1 < len(chain) and chain[i + 1] == c2.id:
                chain.insert(i + 1, new.id)
            elif len(chain) == 1:
                chain.insert(0 if end1 == 0 else 1, new.id)
            else:
                chain.insert(0 if i == 0 else len(chain), new.id)
            out.append((surface, list(surface.links)))
            surface.links = [(chain, link[1]) if j == k else link for j, link in enumerate(surface.links)]
        return out

    def _chain_points(self, ids):
        """Points of a chain of lines (each turned so that it attaches at the end of the previous) or None."""
        curves = [self.curve_by_id(i) for i in ids]
        if any(c is None or len(c.points) < 2 for c in curves):
            return None
        pts = np.asarray(curves[0].points, float)
        if len(curves) > 1:  # turn the first piece so that it fits the second
            nxt = curves[1].points
            if min(np.linalg.norm(pts[0] - nxt[0]), np.linalg.norm(pts[0] - nxt[-1])) < \
                    min(np.linalg.norm(pts[-1] - nxt[0]), np.linalg.norm(pts[-1] - nxt[-1])):
                pts = pts[::-1]
        for c in curves[1:]:
            q = c.points if np.linalg.norm(c.points[0] - pts[-1]) <= np.linalg.norm(c.points[-1] - pts[-1]) else c.points[::-1]
            pts = np.vstack([pts, q[1:]])
        return pts

    # --- Fill surfaces follow their outline (cage, cage.py) ---
    def _fill_pieces(self, surface):
        """Current outline pieces from the linked lines (gaps as straight pieces) or None if a
        line is missing or the outline is no longer closed."""
        if not surface.links:
            return None
        lines = []
        for cid, flipped in surface.links:
            if cid is None:
                lines.append(None)
                continue
            pts = self._chain_points(self.link_ids(cid))
            if pts is None:
                return None
            lines.append(pts[::-1] if flipped else pts)
        known = [p for p in lines if p is not None]
        if not known:
            return None
        size = float(np.linalg.norm(np.ptp(np.vstack(known), axis=0)))
        tol = max(1e-4 * size, 1e-7)
        n = len(lines)
        pieces = []
        for k, pts in enumerate(lines):
            if pts is None:  # straight gap from the end of the previous to the start of the next piece
                prev = next(lines[(k - j) % n] for j in range(1, n + 1) if lines[(k - j) % n] is not None)
                nxt = next(lines[(k + j) % n] for j in range(1, n + 1) if lines[(k + j) % n] is not None)
                pieces.append(np.array([prev[-1], nxt[0]]))
                continue
            follow = lines[(k + 1) % n]
            if follow is not None and n > 1 and np.linalg.norm(pts[-1] - follow[0]) > tol:
                return None  # outline interrupted
            pieces.append(np.asarray(pts, float))
        return pieces

    def _start_fill_links(self, surface):
        """Begin linking: distribute cage points, rest cage = current outline."""
        pieces = self._fill_pieces(surface)
        if pieces is None:
            surface.links = []
            return False
        lengths = [float(np.linalg.norm(np.diff(p, axis=0), axis=1).sum()) for p in pieces]
        surface.counts = cage.allocate(lengths)
        surface.rest = cage.flat(cage.build(pieces, surface.counts))
        total = sum(lengths)
        surface.link_cover = sum(l for l, (cid, _) in zip(lengths, surface.links) if cid is not None) / max(total, 1e-12)
        surface._fill_key = b"".join(np.ascontiguousarray(p).tobytes() for p in pieces)
        return True

    def _fill_cage(self, surface):
        pieces = self._fill_pieces(surface)
        if pieces is None or not surface.counts or len(surface.counts) != len(pieces):
            return None
        return cage.build(pieces, surface.counts)

    def _relink_fill(self, surface, min_cover=None):
        """Find outline lines again by position (after splitting a line, older files): lines that
        lie entirely on the outline, order them in direction of travel, gaps as straight pieces. Then rebind everything that hangs
        on the surface (the shape is unchanged at this moment)."""
        loop = surface.loop_points()
        if len(loop) < 3:
            return False
        closed = np.vstack([loop, loop[:1]])
        seg_a, seg_b = closed[:-1], closed[1:]
        seg_len = np.linalg.norm(seg_b - seg_a, axis=1)
        arc0 = np.concatenate([[0], np.cumsum(seg_len)])
        total = arc0[-1]
        size = float(np.linalg.norm(np.ptp(loop, axis=0)))
        tol = 0.004 * max(size, 1e-9)

        def param(p):
            ab = seg_b - seg_a
            t = np.clip(np.einsum("ij,ij->i", p - seg_a, ab) / np.maximum(np.einsum("ij,ij->i", ab, ab), 1e-18), 0, 1)
            d = np.linalg.norm(seg_a + ab * t[:, None] - p, axis=1)
            i = int(np.argmin(d))
            return arc0[i] + t[i] * seg_len[i], d[i]

        found = []
        for curve in self.pickable_curves():
            pts = curve.points
            if len(pts) < 2:
                continue
            length = float(np.linalg.norm(np.diff(pts, axis=0), axis=1).sum())
            if length < 1e-3 * total:
                continue
            probe = pts[np.linspace(0, len(pts) - 1, min(len(pts), 9)).astype(int)]
            params = [param(p) for p in probe]
            if max(d for _, d in params) > tol:
                continue
            s = [t for t, _ in params]
            steps = np.diff(s)
            steps = (steps + total / 2) % total - total / 2  # across the seam
            flipped = float(np.sum(steps)) < 0
            mid = (s[0] + float(np.sum(steps)) / 2) % total
            found.append((mid, curve, flipped, length))
        if not found:
            return False
        cover = sum(f[3] for f in found) / max(total, 1e-12)
        need = surface.link_cover - 0.02 if min_cover is None else min_cover
        if cover < need or cover > 1.2:
            return False
        found.sort(key=lambda f: f[0])
        links = []
        for k, (_, curve, flipped, _) in enumerate(found):
            links.append((curve.id, flipped))
            nxt_curve, nxt_flip = found[(k + 1) % len(found)][1], found[(k + 1) % len(found)][2]
            end = curve.points[0] if flipped else curve.points[-1]
            start = nxt_curve.points[-1] if nxt_flip else nxt_curve.points[0]
            if np.linalg.norm(end - start) > 1e-4 * max(size, 1e-9):
                links.append((None, False))
        old_links = surface.links
        surface.links = links
        positions = self._fill_bound_positions(surface)
        if not self._start_fill_links(surface):
            surface.links = old_links
            return False
        self._rebind_fill(surface, positions)
        return True

    def _fill_bound_positions(self, surface):
        """What currently hangs on the surface (lines, painting), with its current position (before rebinding)."""
        lines = {cid: self.curve_by_id(cid) for cid in surface.attached}
        return {cid: c.points.copy() for cid, c in lines.items() if c is not None}

    def _rebind_fill(self, surface, lines):
        now = self._fill_cage(surface)
        if now is None:
            return
        for cid, pts in lines.items():
            surface.attached[cid] = {"uv": cage.bind(pts, now, surface.rest), "last": pts.tobytes()}

    def _sync_fills(self, free, only=None):
        """Make fill surfaces follow their outline; deform painting on them along (real lines are not moved by the surface –
        they belong to the net, not to the surface).
        free (Alt in the middle of a drag): it stays in space and detaches from the surface. only: only this surface."""
        changed = False
        skip = getattr(self, "_sync_skip", ()) if only is None else ()
        for surface in self.surfaces if only is None else [only]:
            if type(surface) is not SurfaceObject or surface.rest is None or surface.frozen is not None \
                    or id(surface) in skip:
                continue
            if surface.links:
                self._follow_splits(surface)
            pieces = self._fill_pieces(surface)
            if pieces is None and surface.links and self._relink_fill(surface):
                pieces = self._fill_pieces(surface)
            if pieces is None:
                continue  # outline interrupted or lines gone: surface stays in its last shape
            key = b"".join(np.ascontiguousarray(p).tobytes() for p in pieces)
            geo_changed = key != getattr(surface, "_fill_key", None)
            surface._fill_key = key
            built = []

            def now():  # compute the cage only when it is needed (usually nothing changes)
                if not built:
                    built.append(cage.build(pieces, surface.counts))
                return built[0]

            previous = []

            def before():  # cage of the previous shape (drawn or changed on it just now)
                if not previous:
                    old = [c.points for c in surface.curves]
                    previous.append(cage.build(old if len(old) == len(surface.counts) else pieces, surface.counts))
                return previous[0]

            linked = {i for cid, _ in surface.links for i in self.link_ids(cid)}
            for curve in self.curves_on(surface.id):  # freshly drawn on it: bind
                if curve.plane_id == surface.id and curve.id not in surface.attached and curve.id not in linked:
                    surface.attached[curve.id] = {"uv": cage.bind(curve.points, before() if geo_changed else now(),
                                                                  surface.rest),
                                                  "last": None if geo_changed else curve.points.tobytes()}
            for cid in list(surface.attached):
                att, curve = surface.attached[cid], self.curve_by_id(cid)
                if curve is None:
                    del surface.attached[cid]
                elif att["last"] is not None and curve.points.tobytes() != att["last"] and not geo_changed:
                    att.update(uv=cage.bind(curve.points, now(), surface.rest), last=curve.points.tobytes())
            if geo_changed:
                # lines changed by hand in the same step (point inserted, crossing connected …): rebind to the old
                # shape, otherwise the old binding would overwrite the change
                for cid, att in surface.attached.items():
                    curve = self.curve_by_id(cid)
                    if curve is not None and att["last"] is not None and curve.points.tobytes() != att["last"]:
                        att["uv"] = cage.bind(curve.points, before(), surface.rest)
                        if not curve.paint:
                            att["last"] = curve.points.tobytes()
            for cid, att in surface.attached.items():  # real lines: remember their state (the surface never moves them)
                curve = self.curve_by_id(cid)
                if curve is not None and not curve.paint and att["last"] is None:
                    att["last"] = curve.points.tobytes()
            mesh_changed = self._sync_fill_net(surface, now, geo_changed)
            if not geo_changed and not mesh_changed:
                continue
            now = now()
            if geo_changed:
                for k, (c, p) in enumerate(zip(surface.curves, pieces)):
                    if len(c.points) != len(p) or not np.array_equal(c.points, p):
                        c.points, c.widths = np.array(p, float), np.full(len(p), DEFAULT_WIDTH)
                if len(surface.curves) != len(pieces):
                    surface.curves = [Curve(np.array(p, float), None) for p in pieces]
            if free:  # Alt: lines and painting stay put and detach
                for cid in list(surface.attached):
                    curve = self.curve_by_id(cid)
                    if curve is not None:
                        curve.plane_id = None
                    del surface.attached[cid]
                changed = True
                continue
            on_surface = self._fill_evaluator(surface, now)
            for cid, att in surface.attached.items():
                curve = self.curve_by_id(cid)
                if not curve.paint:
                    continue  # real line: the surface does not move it (topology concept); painting follows it
                curve.points = on_surface(att["uv"])
                if len(curve.widths) != len(curve.points):  # safety net: widths matching the point count
                    curve.widths = np.interp(np.linspace(0, 1, len(curve.points)),
                                             np.linspace(0, 1, len(curve.widths)), curve.widths)
                att["last"] = curve.points.tobytes()
            changed = True
        return changed

    def _sync_fill_net(self, surface, now, geo_changed):
        """Recompute the net surface of a fill surface when its outline or real lines on it have changed.
        now: function for the current cage. Returns True if the surface changed."""
        if surface.rest is None:
            return False
        uv, targets, groups, parts, hard, is_net = [], [], [], [], [], []
        refs = network.refs_by_pid(self)
        nets = self._fill_net_ids(surface, refs)
        for cid, att in surface.attached.items():
            curve = self.curve_by_id(cid)
            if curve is None or curve.paint or len(att["uv"]) != len(curve.points):
                continue
            idx = netsurf.samples(curve.points, att["uv"], None, components.knots(curve))
            if len(idx):
                uv.append(np.asarray(att["uv"])[idx])
                targets.append(curve.points[idx])
                groups.append(np.full(len(idx), cid))
                hard.append(self._line_hardness(curve, refs)[idx])
                is_net.append(np.full(len(idx), cid in nets))
                parts.append(curve.points.tobytes() + np.asarray(att["uv"]).tobytes() + hard[-1].tobytes()
                             + bytes([cid in nets]))
        key = (surface._fill_key or b"") + b"|".join(parts) + np.float64(surface.res).tobytes()
        key = hash(key)  # only the fingerprint (the keys are large and would otherwise travel into every undo copy)
        if key == getattr(surface, "_net_key", None) and surface.netmesh is not None:
            return False
        surface._net_key = key
        cage_now = now()
        dom = netfill.domain(surface.rest, netfill.DENSITY * surface.res)
        base = dom.weights @ cage_now
        if uv:
            uv_a, tg_a, gr_a, hd_a = np.vstack(uv), np.vstack(targets), np.concatenate(groups), np.concatenate(hard)
            net = np.concatenate(is_net)
            normal = cage.normal(cage_now)
            # net lines (from border to border) shape the surface as with the curve surface: exactly and round through them (pure
            # sheet metal, no tautness – otherwise it would tent toward them); at hard ones it kinks
            if net.any():
                base = base + netfill.solve(dom, base, uv_a[net], tg_a[net], gr_a[net], normal, hard=hd_a[net],
                                            stiff=None)
            # the remaining lines then bend it taut in between; the net lines hold it in place
            if not net.all():
                base = base + netfill.solve(dom, base, uv_a, tg_a, gr_a, normal, hard=hd_a)
        surface.netmesh = (base, dom.tris, dom.points.copy())
        return True

    def _fill_net_ids(self, surface, refs):
        """Net lines of a fill surface: chains of real lines on it that are connected to the outline at both ends
        (two different points) – as with the curve surface, just without sides. -> ids of their pieces"""
        border = [self.curve_by_id(i) for cid, _ in surface.links for i in self.link_ids(cid)]
        border = [c for c in border if c is not None]
        border_ids = {c.id for c in border}
        border_pids = {p for c in border for p in (c.pids or {}).values()}
        out = set()
        for ids, pts, pids in self._net_chains(surface, border_ids, refs):
            a, b = pids.get(0), pids.get(len(pts) - 1)
            if a in border_pids and b in border_pids and a != b:
                out |= set(ids)
        return out

    @staticmethod
    def _line_hardness(curve, refs):
        """Crease hardness per line point for net surfaces: the surface kinks along the line where the lines crossing
        it kink (components.crease_along); otherwise smooth across."""
        return components.crease_along(curve, refs)

    def _fill_evaluator(self, surface, cage_now):
        """Rest position -> point on the (deformed) fill surface."""
        fallback = lambda q: cage.evaluate(q, surface.rest, cage_now)
        if surface.netmesh is None:
            return fallback
        dom = netfill.domain(surface.rest, netfill.DENSITY * surface.res)
        verts = surface.netmesh[0]
        return lambda q: netfill.evaluate(dom, verts, q, fallback)

    def create_loft(self, sources, sections, prefix="Loft", wrap=False):
        """Create a loft drawing surface through cross-sections (in order); sources as LoftSurface. wrap: the last
        cross-section lofts back to the first (ring, e.g. a circumferential profile)."""
        aligned, closed = loft.prepare(sections)
        surface = LoftSurface(self._unique_name(prefix, self.surfaces), [Curve(sec, None) for sec in aligned],
                              sources=list(sources), closed=closed, wrap=wrap)
        members = [self.curve_by_id(cid) if src[0] == "lines" else self.object_by_id(cid)
                   for src in sources if src is not None
                   for cid in (src[1] if src[0] == "lines" else [src[1]])]
        self.place_with_lines(surface, members)
        self.surfaces.append(surface)
        return surface

    def create_extrude_loft(self, profile, offset):
        """Extrusion drawing surface as a loft from two cross-sections (original and offset copy): follows both
        lines like any loft, painting drawn on it deforms along."""
        sections = [np.asarray(profile, float), np.asarray(profile, float) + offset]
        sources = [self._lines_along(sec) for sec in sections]
        return self.create_loft([("lines", ids) if ids else None for ids in sources], sections, prefix=tr("Fläche"))

    def _lines_along(self, poly, min_cover=0.9):
        """ids of the lines that lie entirely on the polyline and cover it (almost) entirely, otherwise None."""
        poly = np.asarray(poly, float)
        if len(poly) < 2:
            return None
        a, b = poly[:-1], poly[1:]
        ab = b - a
        lengths = np.linalg.norm(ab, axis=1)
        total = float(lengths.sum())
        size = float(np.linalg.norm(np.ptp(poly, axis=0)))
        tol = max(0.002 * size, 1e-6)
        lo, hi = poly.min(axis=0) - tol, poly.max(axis=0) + tol
        ids, covered = [], 0.0
        curves = self.pickable_curves()
        key = tuple(id(c.points) for c in curves)
        cache = self.__dict__.get("_along_bounds")
        if cache is None or cache[0] != key:  # bounding boxes of all lines stacked, as long as no line changes
            boxes = [self.curve_bounds(c) if len(c.points) >= 2 else (np.full(3, np.inf), np.full(3, -np.inf))
                     for c in curves]
            cache = (key, np.array([b[0] for b in boxes]).reshape(-1, 3), np.array([b[1] for b in boxes]).reshape(-1, 3),
                     [c.points for c in curves])
            self.__dict__["_along_bounds"] = cache
        inside = np.flatnonzero(np.all(cache[1] >= lo, axis=1) & np.all(cache[2] <= hi, axis=1))
        for n in inside:
            curve = curves[n]
            pts = curve.points
            if len(pts) < 2:
                continue
            probe = pts[np.linspace(0, len(pts) - 1, min(len(pts), 9)).astype(int)]
            t = np.clip(np.einsum("pmj,mj->pm", probe[:, None] - a[None], ab) / np.maximum(lengths ** 2, 1e-18)[None], 0, 1)
            d = np.linalg.norm(a[None] + t[..., None] * ab[None] - probe[:, None], axis=2).min(axis=1)
            if d.max() <= tol:
                ids.append(curve.id)
                covered += float(np.linalg.norm(np.diff(pts, axis=0), axis=1).sum())
        return ids if ids and covered >= min_cover * total else None

    def _upgrade_extrude_surfaces(self, id_map):
        """Older scenes: convert rigid extrusion surfaces into lofts of two cross-sections if the lines
        for it (original and copy) are still there."""
        for k, surface in enumerate(list(self.surfaces)):
            if not isinstance(surface, ExtrudeSurface) or len(surface.segments) != 1:
                continue
            rows = surface.rows()
            sources = [self._lines_along(r) for r in (rows[0], rows[-1])]
            if not all(sources):
                continue
            aligned, closed = loft.prepare([rows[0], rows[-1]])
            new = LoftSurface(surface.name, [Curve(sec, None) for sec in aligned],
                              sources=[("lines", ids) for ids in sources], closed=closed)
            self.surfaces[self.surfaces.index(surface)] = new
            for old_id, new_id in list(id_map.items()):
                if new_id == surface.id:
                    id_map[old_id] = new.id

    def add_loft_rails(self, surface, view, owner=None):
        """Create real lines along the loft surface (open: side edges, closed: longitudinal lines)."""
        secs = np.array(surface.sections())
        direction = secs[-1].mean(axis=0) - secs[0].mean(axis=0)
        if surface.wrap:  # ring: direction to the second cross-section
            direction = secs[1].mean(axis=0) - secs[0].mean(axis=0)
        cols = loft.rail_columns(secs, surface.closed, direction, view)
        if owner is None:
            owner = self.active_stroke if self.active_stroke in self.strokes else self.new_stroke()
        g = surface.grid()
        width = float(np.mean([c.widths.mean() for c in owner.curves])) if owner.curves else DEFAULT_WIDTH
        secs_at = self._section_rows(surface, len(g))
        cols = sorted(set(cols) | set(self._knot_columns(g, secs_at)))
        made = []
        for col in cols:
            if any(c == col for _, c in surface.rails) or self._lines_along(g[:, col]):
                continue  # a line already lies there (e.g. created twice): no duplicate
            # stroke width: at each cross-section its width where the side line crosses it, proportional in between
            wid = components.widths_through(g[:, col], [(row, components.width_near(lines, g[row, col], width))
                                                        for row, lines in secs_at if lines], width)
            curve = Curve(g[:, col].copy(), None, wid)
            owner.curves.append(curve)
            surface.rails.append((curve.id, col))
            made.append((curve, col))
        self._join_rails(surface, made, g)
        return cols

    def _knot_columns(self, g, secs_at):
        """Columns at the knots of the first cross-section that get a longitudinal line (as with extruding: kink from
        5° or another line attaches – extruding.knot_rails)."""
        from . import extruding
        if not secs_at or not secs_at[0][1]:
            return []
        row, lines = secs_at[0]
        ring = g[row]
        tol = 0.02 * max(float(np.linalg.norm(np.ptp(ring, axis=0))), 1e-9)
        out = []
        for p in extruding.knot_rails(extruding.knot_marks(self, lines)):
            d = np.linalg.norm(ring - p, axis=1)
            col = int(np.argmin(d))
            if d[col] <= tol and col not in out:
                out.append(col)
        return out

    def _section_rows(self, surface, n_rows):
        """[(grid row, real lines of the cross-section)] – ring: the first cross-section also closes at the end."""
        secs = list(surface.sources)
        if surface.wrap and len(secs) >= 3:
            secs.append(secs[0])
        out = []
        for k, src in enumerate(secs):
            row = k * surface.span
            if src is None or src[0] != "lines" or row >= n_rows:
                continue
            out.append((row, [c for cid in src[1] for sub in (self.split_pieces(cid) or [])
                              if (c := self.curve_by_id(sub))]))
        return out

    def _join_rails(self, surface, rails, g):
        """Connect side lines to the cross-section lines (shared points where they cross them): afterwards they are
        real lines of the net – the loft no longer moves them, cross-sections pull them along at these points."""
        span = surface.span
        secs = list(zip(surface.sources, range(len(surface.sources))))
        if surface.wrap and len(secs) >= 3:
            secs.append(secs[0])  # ring: the first cross-section closes again
        for rail, col in rails:
            for k, (src, _) in enumerate(secs):
                if src is None or src[0] != "lines":
                    continue
                row = k * span
                if row >= len(rail.points):
                    continue
                point = g[row, col]
                lines = [c for cid in src[1] for sub in (self.split_pieces(cid) or []) if (c := self.curve_by_id(sub))]
                if not lines:
                    continue
                line = min(lines, key=lambda c: self._closest_on(c, point)[0])
                # the grid lies on the resampled cross-section, not exactly on its polyline: the same
                # tolerance as "line lies on the loft" (the longitudinal line moves onto the cross-section when connecting)
                if self._closest_on(line, point)[0] > LOFT_BIND_TOL * float(np.linalg.norm(np.ptp(g.reshape(-1, 3), axis=0))):
                    continue
                network.sync(self)
                j = network.knot_at(line, point)
                kr = network.knot_at(rail, point)
                network.join(self, line, j, rail, kr)

    def _update_loft_rails(self, surface):
        if not surface.rails:
            return
        g = surface.grid()
        for cid, col in surface.rails:
            curve = self.curve_by_id(cid)
            if curve is None or col >= g.shape[1]:
                continue  # line deleted: stays away
            old = np.asarray(curve.widths, float) if len(curve.widths) else np.full(1, DEFAULT_WIDTH)
            curve.points = g[:, col].copy()
            # keep the width profile (proportional along the line), do not set it to the mean
            n = len(curve.points)
            curve.widths = old.copy() if len(old) == n else np.interp(np.linspace(0, 1, n), np.linspace(0, 1, len(old)), old)

    def loft_source_points(self, source):
        """Current shape of a loft cross-section from its source or None (source gone)."""
        if source is None:
            return None
        kind, ref = source
        if kind == "surface":
            other = next((f for f in self.surfaces if f.id == ref), None)
            outlines = other.outlines() if other is not None else []
            return outlines[0] if outlines else None
        ids = []
        for cid in ref:  # split lines: their pieces
            sub = self.split_pieces(cid)
            if sub is None:
                return None
            ids += sub
        if ids != list(ref):
            ref[:] = ids
        curves = [self.curve_by_id(cid) for cid in ids]
        if not curves or any(c is None for c in curves):
            return None
        key = b"|".join(np.ascontiguousarray(c.points).tobytes() for c in curves)
        if key not in _CHAIN_CACHE:  # building chains is expensive, the lines rarely change
            lru.trim(_CHAIN_CACHE, 4096)
            chains = extrude.chains([c.points for c in curves], 1e-6 * max(
                float(np.linalg.norm(np.ptp(np.vstack([c.points for c in curves]), axis=0))), 1.0))
            _CHAIN_CACHE[key] = chains[0][0] if len(chains) == 1 else None
        return _CHAIN_CACHE[key]

    def _sync_stamp_now(self, free):
        """What shows whether the sync has something to do since last time: every assignment to a
        line (points, knots, point IDs, painting, drawing surface) or to a field of a surface counts a counter
        up; plus the lists themselves (lines/surfaces added or removed) and the size of each surface's reference
        lists (those are extended in place)."""
        from . import scene as scene_mod
        lists = [st.curves for st in self.strokes]
        sizes = [(len(s.attached), len(s.links), len(getattr(s, "rails", ())), len(getattr(s, "sources", ())),
                  len(getattr(s, "patch_lines", ())), s.frozen is None) for s in self.surfaces]
        values = (network.EPOCH[0], scene_mod.PLANE_EPOCH[0], scene_mod.SURF_EPOCH[0], bool(free),
                  SurfaceObject.display_res, len(self.split_map), [len(cl) for cl in lists], sizes)
        return values, (self.strokes, self.surfaces, getattr(self, "_rigid_active", None)), lists

    @staticmethod
    def _same_stamp(a, b):
        """Same stamp? Numbers by value, the lists themselves by identity (held on to, not their id)."""
        return (a is not None and a[0] == b[0] and all(x is y for x, y in zip(a[1], b[1]))
                and len(a[2]) == len(b[2]) and all(x is y for x, y in zip(a[2], b[2])))

    def sync_lofts(self, free=False, lazy=False):
        """Make loft surfaces follow their cross-sections (lines/surfaces), then deform the lines drawn on them
        along with the surface. free (Alt in the middle of a drag): the lines stay in space and detach
        from the loft. Cheap if nothing has changed.
        lazy (sync before a frame without anyone having reported a change – hover, preview of an extrusion,
        camera move): if nobody has touched a line or surface since the last sync (_sync_stamp_now), only
        follow up the notes. Every reported change (Viewport._changed) still syncs fully."""
        if lazy and getattr(self, "_sync_lazy_ok", False) and self._same_stamp(
                getattr(self, "_sync_stamp", None), self._sync_stamp_now(free)):
            return self._sync_notes()
        changed = self._sync_lofts(free)
        # if a loft hangs on something other than lines (plane, mesh, other surface), the stamp does not see its movement
        self._sync_lazy_ok = not any(src is not None and src[0] != "lines"
                                     for s in self.surfaces for src in getattr(s, "sources", ()))
        self._sync_stamp = self._sync_stamp_now(free)
        return changed

    # --- Sync only what may have changed ---
    # After a sync each surface remembers what it depends on (_dep_curves: its lines, their neighbors at
    # shared points, what lies on it) and a stamp over it (_sync_ok). If the stamp is the same next time,
    # nothing has changed for it – it is not touched at all. Before, every change checked every
    # surface individually (harbor 11.11.: 308 surfaces, ~50 ms per change, on every stroke, click, delete).
    VERIFY_SYNC = False  # Tests: sync skipped surfaces anyway and check that nothing happens

    def transfer_rigid(self, moved, t):
        """Surfaces that were moved by t together with all their lines (TransformSet.end_rigid): move their state
        along instead of recomputing. moved: [(surface, own rows already moved?, net from the start of the drag)]."""
        from . import scene as scene_mod
        t = np.asarray(t, float)
        plane, net = scene_mod.PLANE_EPOCH[0], network.EPOCH[0]
        for f, own, _base in moved:
            if not own:  # not in the target itself: the drag did not move their grid rows
                for row in f.curves:
                    row.points = row.points + t
        scene_mod.PLANE_EPOCH[0], network.EPOCH[0] = plane, net  # (grid rows do not belong to the curve net)
        world, refs = self._sync_world(False), network.refs_by_pid(self)
        for f, own, base in moved:
            d = f.__dict__
            for name in _PLACED:
                value = d.get(name)
                if value is not None:
                    setattr(f, name, _shifted(value, t))
            if d.get("_net_geo"):
                d["_net_geo"]["key"] = None  # key via the old position: recomputed at the next real change
            for name in ("_synced", "_fill_key"):
                if d.get(name) is not None:
                    setattr(f, name, None)
            for cid, att in (f.attached or {}).items():  # bound items moved along: remembered state = current position
                c = self.curve_by_id(cid)
                if c is None or not isinstance(att, dict):
                    continue
                if "last" in att:
                    att["last"] = c.points.tobytes()
                if att.get("pos") is not None and len(att["pos"]) == len(c.points):
                    att["pos"] = c.points.copy()
            # store the displayed net under the key of the new position
            mesh = (base[0] + t, *base[1:])
            key = (type(f).__name__, f._cache_key())
            if key not in scene_mod._FILL_CACHE:
                lru.trim(scene_mod._FILL_CACHE, 4096)
                scene_mod._FILL_CACHE[key] = (mesh, scene_mod.PickProxy(scene_mod.Geometry(mesh[0], mesh[1]), f))
            f._sync_ok = self._surface_stamp(f, world, refs)
            if self.VERIFY_SYNC:
                f._moved_whole = True

    def _sync_asked(self, book, added=(), refs=None):
        """id() of the surfaces that have been given a reason to look again since book["seq"]: they themselves or a
        line they depend on has reported (scene.touched_since); a reported line lies on them
        or shares a point with one of their lines; a line has come (back) into the scene (added, ids);
        at a point of one of their lines more or fewer lines hang than last time (refs – this also catches
        the line that left the point or was deleted without itself belonging to the dependencies).
        None: all (the report ledger does not reach back that far)."""
        from . import scene as scene_mod
        touched = scene_mod.touched_since(book["seq"])
        if touched is None:
            return None
        by_curve, by_pid = book["by_curve"], book["by_pid"]
        by_sid = None
        out = set()
        curves = [o for o in touched if not isinstance(o, SurfaceObject)]
        out.update(id(o) for o in touched if isinstance(o, SurfaceObject))
        added = set(added) - {c.id for c in curves}  # (a new line has already reported itself on creation)
        curves += [c for c in map(self.curve_by_id, added) if c is not None]
        for c in curves:
            hit = by_curve.get(id(c))
            if hit:
                out |= hit
            if c.plane_id is not None:
                if by_sid is None:
                    by_sid = {s.id: id(s) for s in self.surfaces}
                sid = by_sid.get(c.plane_id)
                if sid is not None:
                    out.add(sid)
            if c.pids:
                for pid in c.pids.values():
                    hit = by_pid.get(pid)
                    if hit:
                        out |= hit
        if refs is not None:
            known = book["pidn"]
            for pid, hit in by_pid.items():
                if len(refs.get(pid, ())) != known.get(pid, -1):
                    out |= hit
        return out

    @staticmethod
    def _sync_enrol(book, s):
        """Enter a surface in the report ledger of the sync: who has to report so that it looks again – its
        grid rows, the lines it depends on (_dep_curves), and the points of those lines."""
        key = id(s)
        by_curve, by_pid = book["by_curve"], book["by_pid"]
        old = book["mine"].get(key)
        if old is not None and book["reg"].get(key) is s:
            for i in old[0]:
                hit = by_curve.get(i)
                if hit is not None:
                    hit.discard(key)
                    if not hit:
                        del by_curve[i]
            for pid in old[1]:
                hit = by_pid.get(pid)
                if hit is not None:
                    hit.discard(key)
                    if not hit:
                        del by_pid[pid]
        deps = s.__dict__.get("_dep_curves") or ()
        ids = [id(c) for c in s.curves] + [id(c) for c in deps]
        pids = {pid for c in deps if not c.paint and c.pids for pid in c.pids.values()}
        for i in ids:
            by_curve.setdefault(i, set()).add(key)
        for pid in pids:
            by_pid.setdefault(pid, set()).add(key)
        book["reg"][key] = s
        book["mine"][key] = (ids, pids, deps, list(s.curves))  # (holds lines and rows: their id() stays valid)

    def _sync_world(self, free):
        """What applies to all surfaces: if anything about it changes (line added/removed, drawing surface switched, resolution),
        every one is checked again."""
        return (bool(free), SurfaceObject.display_res, bool(SurfaceObject.auto_res))

    def _surface_stamp(self, s, world, refs, count=True):
        """Stamp of a surface: its own state, the state of each line it depends on (Curve._v counts every
        assignment), what lies on it (a new line on it) and how many lines hang at the points of its lines
        (a new neighbor line at a shared point changes hardness and connections)."""
        if count:  # (not if only the test check mode recomputes)
            counters.C["flaechen_stempel"] += 1
        deps = s.__dict__.get("_dep_curves")
        if deps is None:
            return None
        on = self.curves_on(s.id)
        near = 0
        for c in deps:
            if not c.paint and c.pids:
                for pid in c.pids.values():
                    near += len(refs.get(pid, ()))
        return (world, s.__dict__.get("_sv", 0), len(s.attached), sum(s.attached), len(s.curves),
                sum(c.__dict__.get("_v", 0) for c in s.curves), sum(c.__dict__.get("_v", 0) for c in deps),
                s.frozen is None, len(on), sum(c.id for c in on), near)

    def _surface_deps(self, s):
        """Lines on which the sync of this surface depends: what describes it, what adheres to it or lies on it,
        and all lines that share a point with these (hardness, connections, chains)."""
        out, seen = [], set()

        def add(c):
            if c is not None and id(c) not in seen:
                seen.add(id(c))
                out.append(c)

        for i in self.defining_line_ids(s):
            add(self.curve_by_id(i))
        for i in s.attached:
            add(self.curve_by_id(i))
        for c in self.curves_on(s.id):
            add(c)
        for name in ("_netpatch_key", "_drv_key", "_tube_key"):  # what the surface's own caches hold on to
            memo = s.__dict__.get(name)
            if memo:
                for o in memo[0]:
                    if isinstance(o, Curve):
                        add(o)
        refs = network.refs_by_pid(self)
        for c in list(out):
            if not c.paint:
                for pid in (c.pids or {}).values():
                    for o, _k in refs.get(pid, ()):
                        add(o)
        return out

    def _sync_lofts(self, free):
        carrying = getattr(self, "_rigid_active", None)
        for s in self.surfaces:  # safety net: carried along, but no drag is running (undo copy, aborted drag)
            if getattr(s, "_carried", False) and (carrying is None or s not in carrying):
                s.frozen, s._carried = None, False
                s.__dict__.pop("_idle_hold", None)
        world = self._sync_world(free)
        # only whoever currently follows its lines needs a stamp. In a rigid drag all surfaces are held:
        # then neither sync the curve net nor compute a stamp (cost ~25 ms per frame of the drag)
        any_live = any(s.frozen is None and not s.aid for s in self.surfaces)
        refs = network.refs_by_pid(self) if any_live else None  # (syncs the curve net)
        # lines that no longer exist: every surface that depended on one has to look again
        ids = {c.id for st in self.strokes for c in st.curves}
        gone = getattr(self, "_sync_ids", ids) - ids
        self._sync_ids_before = getattr(self, "_sync_ids", ids)
        self._sync_ids = ids
        if gone:
            for s in self.surfaces:
                if any(c.id in gone for c in s.__dict__.get("_dep_curves", ())):
                    s.__dict__.pop("_sync_ok", None)
        from . import scene as scene_mod
        clean = set()
        seq0 = scene_mod.TOUCH_SEQ[0]  # what is reported from here on was moved by this sync itself
        book = self.__dict__.get("_sync_book")
        # (new also if it filled up with surfaces that no longer exist – deleted, replaced by undo)
        if book is None or book["world"] != world or len(book["reg"]) > 2 * len(self.surfaces) + 256:
            book = self._sync_book = {"world": world, "seq": -1, "reg": {}, "by_curve": {}, "by_pid": {}, "mine": {},
                                      "pidn": {}}
        # (in a rigid drag all surfaces are held: nobody follows its lines, nobody needs to be asked)
        asked = self._sync_asked(book, ids - getattr(self, "_sync_ids_before", ids), refs) if any_live else None
        for s in self.surfaces:
            ok = s.__dict__.get("_sync_ok")
            if ok is None or s.frozen is not None or s.aid:
                continue
            # Nobody has reported that this surface depends on: its stamp holds, without recomputing it. What is changed
            # in place (bound lines, number of rows) does not report – that is compared.
            trusted = (asked is not None and id(s) not in asked and book["reg"].get(id(s)) is s and ok[0] == world
                       and ok[2] == len(s.attached) and ok[3] == sum(s.attached) and ok[4] == len(s.curves))
            if trusted and self.VERIFY_SYNC:
                assert ok == self._surface_stamp(s, world, refs, count=False), \
                    f"„{s.name}“: niemand hat sich gemeldet, aber ihr Stempel hat sich geändert"
            if (trusted or ok == self._surface_stamp(s, world, refs)) \
                    and not any(src is not None and src[0] != "lines" for src in getattr(s, "sources", ())):
                clean.add(id(s))
        calm = set(clean) if asked is not None else set()  # … and after the sync, if nobody else reports
        # (counted before the check mode: in the tests it additionally syncs every surface)
        counters.C["flaechen_abgleich"] += sum(1 for s in self.surfaces if id(s) not in clean and s.frozen is None and not s.aid)
        before = None
        if self.VERIFY_SYNC and clean:
            # (just co-moved surfaces: their whole state is compared with the recomputed one, with tolerance)
            before = {id(s): (s, s._cache_key(), tuple(s.attached),
                              _placed_state(s) if s.__dict__.pop("_moved_whole", False) else None)
                      for s in self.surfaces if id(s) in clean}
            clean = set()
        # State of the surfaces that are synced now: only whoever is unchanged afterwards counts as settled
        # (some surface needs two passes until everything is bound – it stays in until then)
        state = lambda f: (f._cache_key(), tuple(f.attached), sum(c.__dict__.get("_v", 0) for c in f.curves))
        pre = {id(f): state(f) for f in self.surfaces if id(f) not in clean and f.frozen is None and not f.aid}
        self._sync_skip = clean
        try:
            changed = self._sync_surfaces(free)
        finally:
            self._sync_skip = frozenset()
        if before is not None:
            for s, key, att, placed in before.values():
                if placed is None:
                    assert s._cache_key() == key and tuple(s.attached) == att, \
                        f"Abgleich übersprungen, obwohl sich „{s.name}“ dabei geändert hätte"
                    continue
                size = float(np.linalg.norm(np.ptp(placed["mesh"][0], axis=0))) if placed["mesh"] is not None else 1.0
                now = _placed_state(s)
                m0, m1 = placed.pop("mesh"), now.pop("mesh")
                why = _loose_diff(placed, now, 1e-9 * max(size, 1e-9), "Stand")
                if why is None and m0 is not None and m1 is not None:
                    if m0[0].shape != m1[0].shape or _loose_diff(m0[0], m1[0], 1e-6 * size, "Netz"):
                        # different division of the displayed net (the curvature lies at a threshold, and recomputed
                        # the grid differs in the last digit): then at least the same position
                        why = _loose_diff(np.array([m0[0].min(axis=0), m0[0].max(axis=0)]),
                                          np.array([m1[0].min(axis=0), m1[0].max(axis=0)]), 1e-3 * size, "Netz-Hülle")
                assert why is None, f"„{s.name}“ mitverschoben statt neu gerechnet, aber nicht gleich – {why}"
            clean = set(before)
        if any(s.frozen is None and not s.aid for s in self.surfaces):
            refs = network.refs_by_pid(self)  # state after the sync (it assigns point IDs)
        self._sync_ids = {c.id for st in self.strokes for c in st.curves}
        # whoever the sync itself alarmed (a neighboring surface has updated a shared line, a point
        # has got a new neighbor): its stamp is brought to the new state as before
        stirred = self._sync_asked(dict(book, seq=seq0), self._sync_ids - ids, refs) if calm else None
        for s in self.surfaces:
            if s.frozen is not None or s.aid:
                if not (s.__dict__.get("_idle_hold") and s.__dict__.get("_carried")):  # held only during the drag:
                    s.__dict__.pop("_sync_ok", None)  # … whose stamp keeps holding after release
                continue
            if id(s) in pre and pre[id(s)] != state(s):
                s.__dict__.pop("_sync_ok", None)  # moved during this pass: again next time
                continue
            if id(s) in calm and stirred is not None and id(s) not in stirred and "_dep_curves" in s.__dict__:
                if self.VERIFY_SYNC:
                    assert s._sync_ok == self._surface_stamp(s, world, refs, count=False), \
                        f"„{s.name}“: im Abgleich hat sich niemand gemeldet, aber ihr Stempel ist ein anderer"
                if book["reg"].get(id(s)) is not s:  # came back from an undo copy: in the book from now on
                    self._sync_enrol(book, s)
                continue  # nothing has changed for it: stamp and dependencies stay
            # (dependencies always new: the sync may have given it a neighbor that has to report later)
            s._dep_curves = self._surface_deps(s)
            s._sync_ok = self._surface_stamp(s, world, refs)
            self._sync_enrol(book, s)
        book["seq"] = seq0  # (not the current state: what the sync itself set is re-checked next time)
        if refs is not None:  # this many lines now hang at each point a surface watches (_sync_asked)
            book["pidn"] = {pid: len(refs.get(pid, ())) for pid in book["by_pid"]}
        for surface in self.surfaces:
            if surface.aid and surface.frozen is None:  # helper surface from an older file: freeze now
                self.freeze_surface(surface)
        changed |= self._sync_notes()
        return changed

    def _sync_surfaces(self, free):
        skip = self._sync_skip
        changed = self._sync_sections()
        live = [s for s in self.surfaces if s.frozen is None and id(s) not in skip]  # frozen ones follow no line
        for surface in live:
            if type(surface) is LoftSurface and surface.closed:  # tube (open rings stay loft)
                changed |= self._sync_tube_net(surface)
        for surface in live:
            if isinstance(surface, LoftSurface):
                changed |= self._sync_attached(surface, free)
        changed |= self._sync_fills(free)
        return changed

    def sync_painted(self, curves):
        """Only new paint strokes have been added: bind them to their surfaces. The full sync (sync_lofts) is not
        needed – painting follows the surfaces but never shapes them, no other surface or line has changed."""
        ids = {c.plane_id for c in curves}
        for surface in self.surfaces:
            if surface.id not in ids or surface.frozen is not None:
                continue
            if isinstance(surface, LoftSurface):
                self._sync_attached(surface, False)
            else:
                self._sync_fills(False, only=surface)

    # --- Helper surface: frozen as long as it is a helper surface ---
    def _held_lines(self, surface):
        """{line id: points} of the lines the surface hangs on: outline, cross-sections, longitudinal/border lines,
        net lines, bound ones and ones drawn on it (without painting)."""
        ids = set(surface.attached) | {i for cid, _ in surface.links for i in self.link_ids(cid)}
        if isinstance(surface, LoftSurface):
            ids |= {cid for src in surface.sources if src and src[0] == "lines" for cid in src[1]}
            ids |= {cid for cid, _ in surface.rails}
        if isinstance(surface, PatchSurface):
            ids |= {c.id for c in self.patch_border(surface)}
            ids |= {i for key in ("u", "v") for chain, _ in (surface.net or {}).get(key, []) for i in chain}
        ids |= {c.id for c in self.pickable_curves() if c.plane_id == surface.id and not c.paint}
        return {i: c.points.copy() for i in ids if (c := self.curve_by_id(i)) is not None}

    @staticmethod
    def _frozen_sample(verts):
        return verts[np.linspace(0, len(verts) - 1, min(len(verts), 16)).astype(int)].copy()

    def freeze_surface(self, surface):
        """Freeze a helper surface: hold on to its current shape – lines drawn on it or pulled away
        from it no longer change it, only the gizmo moves it."""
        mesh = surface.fill_mesh()
        if mesh is None or not len(mesh[0]):
            return
        uv = np.asarray(mesh[2], float).copy() if len(mesh) > 2 and mesh[2] is not None else None
        verts = np.asarray(mesh[0], float).copy()
        surface.frozen = ((verts, np.asarray(mesh[1], np.int32).copy(), uv),
                          [np.asarray(line, float).copy() for line in surface.outlines()], self._frozen_sample(verts))
        surface.frozen_lines = self._held_lines(surface)

    def unfreeze_surface(self, surface):
        """Helper surface back to a surface: if all lines it hung on at freezing still lie exactly there (and
        it was not moved itself), it hangs on them again – otherwise it keeps its fixed shape and follows no
        line (nothing jumps anywhere). Lines drawn on it do not belong to it. True: connected again."""
        if surface.frozen is None:
            return True
        (verts, _, _), _, sample = surface.frozen
        tol = 1e-4 * max(float(np.linalg.norm(np.ptp(verts, axis=0))), 1e-9)
        now = self._frozen_sample(verts)
        in_place = now.shape == sample.shape and np.allclose(now, sample, atol=tol) and all(
            (c := self.curve_by_id(cid)) is not None and c.points.shape == pts.shape and
            np.allclose(c.points, pts, atol=tol) for cid, pts in surface.frozen_lines.items())
        for c in self.pickable_curves():  # drawn on it while frozen: free, not part of the surface
            if c.plane_id == surface.id and c.id not in surface.frozen_lines and not c.paint:
                c.plane_id = None
        if in_place:
            surface.frozen, surface.frozen_lines = None, {}
        return in_place

    def _chain_pieces(self, ids):
        """Like _chain_points, plus per piece (line, indices of its points in the chain) – or None."""
        sub = [s for cid in ids for s in (self.split_pieces(cid) or [None])]
        curves = [self.curve_by_id(i) if i is not None else None for i in sub]
        if not curves or any(c is None or len(c.points) < 2 for c in curves):
            return None
        pts = self._chain_points([c.id for c in curves])
        out, at = [], 0
        for k, c in enumerate(curves):
            n = len(c.points)
            idx = np.arange(at, at + n)
            if k == 0:
                forward = len(curves) == 1 or np.linalg.norm(c.points[-1] - pts[n - 1]) <= np.linalg.norm(c.points[0] - pts[n - 1])
            else:
                forward = np.linalg.norm(c.points[0] - pts[at]) <= np.linalg.norm(c.points[-1] - pts[at])
            out.append((c, idx if forward else idx[::-1]))
            at += n - 1
        return pts, out

    # --- Curve surface as curve net (patchnet.py): net lines from border to border form the rest shape ---
    def _net_chains(self, surface, border_ids, refs):
        """Chains of real lines on the surface (pieces that meet at a point with exactly two line ends):
        [(ids, points, {chain index: point ID})]."""
        # bound or just drawn onto the surface (is bound in the same sync)
        ids = list(surface.attached) + [c.id for c in self.curves_on(surface.id) if c.id not in surface.attached]
        lines = [c for cid in ids if (c := self.curve_by_id(cid)) is not None and not c.paint
                 and c.id not in border_ids and len(c.points) >= 2]
        mine = {c.id for c in lines}
        used, out = set(), []

        def partner(c, end, seen):
            pid = network.pid_of(c, end)
            at = refs.get(pid, []) if pid is not None else []
            if len(at) != 2:
                return None
            others = [(o, j) for o, j in at if o is not c]
            if len(others) != 1:
                return None
            o, j = others[0]
            if o.id not in mine or o.id in seen or j not in (0, len(o.points) - 1):
                return None
            return o, j

        for c in lines:
            if c.id in used:
                continue
            start, end, seen = c, 0, {c.id}  # run to the start of the chain
            while (p := partner(start, end, seen)) is not None:
                seen.add(p[0].id)
                start, end = p[0], len(p[0].points) - 1 if p[1] == 0 else 0
            ids, cur, k = [], start, end
            while cur is not None and cur.id not in used:
                ids.append(cur.id)
                used.add(cur.id)
                p = partner(cur, len(cur.points) - 1 if k == 0 else 0, used)
                cur, k = (p[0], p[1]) if p is not None else (None, None)
            chain = self._chain_pieces(ids)
            if chain is None:
                continue
            pts, pieces = chain
            pids = {}
            for pc, idx in pieces:
                for kk, pid in (pc.pids or {}).items():
                    if 0 <= kk < len(idx):
                        pids[int(idx[kk])] = pid
            out.append((ids, pts, pids))
        return out

    def _net_classify(self, surface, sides, refs):
        """Net lines of the surface -> (transverse [(ids, points from side 3 to 1, {index: point ID}, fraction)], longitudinal [… from
        side 0 to 2 …]), sorted by fraction. A net line runs from one border side to the opposite one, is
        connected to the border at both ends and crosses each net line of the other direction in exactly one shared
        point; net lines of one direction do not touch each other. What does not satisfy that remains a line that only
        bends the surface."""
        border = self.patch_border(surface)
        border_ids = {c.id for c in border}
        border_pids = {p for c in border for p in (c.pids or {}).values()}
        sd = [np.asarray(s, float) for s in sides]
        size = max(float(np.linalg.norm(np.ptp(np.vstack(sd), axis=0))), 1e-9)
        on = lambda p: [s for s in range(4) if float(np.linalg.norm(_closest_on_poly(sd[s], p) - p)) < 1e-6 * size]
        frac = lambda poly, p: patchnet.arc_at(poly, p) / max(float(patchnet.arc(poly)[-1]), 1e-12)
        u_lines, v_lines = [], []
        for ids, pts, pids in self._net_chains(surface, border_ids, refs):
            if any(pids.get(e) not in border_pids for e in (0, len(pts) - 1)):
                continue  # one end not connected to the border
            s0, s1 = on(pts[0]), on(pts[-1])
            if len(s0) != 1 or len(s1) != 1:
                continue  # free-ending or in a corner
            a, b = s0[0], s1[0]
            flipped = (pts[::-1], {len(pts) - 1 - k: p for k, p in pids.items()})
            if {a, b} == {3, 1}:
                p_, d_ = (pts, pids) if a == 3 else flipped
                u_lines.append((ids, p_, d_, (frac(sd[3][::-1], p_[0]) + frac(sd[1], p_[-1])) / 2))
            elif {a, b} == {0, 2}:
                p_, d_ = (pts, pids) if a == 0 else flipped
                v_lines.append((ids, p_, d_, (frac(sd[0], p_[0]) + frac(sd[2][::-1], p_[-1])) / 2))
        u_lines.sort(key=lambda x: x[3])
        v_lines.sort(key=lambda x: x[3])
        side_pair = {id(u_lines): (sd[3][::-1], sd[1]), id(v_lines): (sd[0], sd[2][::-1])}

        def fits(lines, accepted, cand):
            """One direction: no shared points, same order on both border sides."""
            if any(set(o[2].values()) & set(cand[2].values()) for o in accepted):
                return False
            pos = sorted(accepted + [cand], key=lambda x: x[3])
            for side, end in zip(side_pair[id(lines)], (0, -1)):
                arcs = [patchnet.arc_at(side, x[1][end]) for x in pos]
                if any(q <= p for p, q in zip(arcs, arcs[1:])):
                    return False
            return True

        first, second = (u_lines, v_lines) if len(u_lines) >= len(v_lines) else (v_lines, u_lines)
        acc1 = []
        for c in first:
            if fits(first, acc1, c):
                acc1.append(c)
        acc2 = []
        for c in second:
            if not fits(second, acc2, c):
                continue
            if any(len(set(o[2].values()) & set(c[2].values())) != 1 for o in acc1):
                continue  # does not cross a net line of the other direction (or crosses several times) in a shared point
            trial = sorted(acc2 + [c], key=lambda x: x[3])
            if any(any(q <= p for p, q in zip(arcs, arcs[1:]))
                   for arcs in ([_arc_of_pid(o, x) for x in trial] for o in acc1)):
                continue  # intersection points lie in a different order along a net line
            acc2.append(c)
        acc1.sort(key=lambda x: x[3])
        acc2.sort(key=lambda x: x[3])
        return (acc1, acc2) if first is u_lines else (acc2, acc1)

    def _sync_net_patch(self, surface, fresh=False):
        """Curve surface: rest shape = Gordon surface from border and net lines (patchnet), each time from the current lines.
        The grid (which net line on which row/column) stays as long as the same net lines are there; if one is
        added or one drops out, it is laid anew and everything on the surface keeps its location. Returns True if
        the rest shape has changed. Each grid point on a net line or border side hangs at a fixed place
        of the line (fractional point index): when a point is dragged, only the grid points there move along, the rest stays
        (otherwise all would slide along, and the surface would shift away from under the lines on it). fresh: redistribute
        (redistributing after strong distortion)."""
        sides = self._patch_sides(surface)
        if sides is None or len(surface.curves) < 2:
            surface._net_geo = None
            return False
        refs = network.refs_by_pid(self)
        # asked per sync: curve net, bound lines and border unchanged -> rest shape unchanged (do not recompute division,
        # arc lengths, connections at all)
        memo = self._net_patch_memo(surface)
        cached = getattr(surface, "_netpatch_key", None)
        if not fresh and cached is not None and cached[1] == memo[1] and _same_objs(cached[0], memo[0]):
            return False
        u_lines, v_lines = self._net_classify(surface, sides, refs)
        norm = lambda ids: frozenset(i for cid in ids for i in (self.split_pieces(cid) or []))
        net = surface.net
        relayout = fresh or not (net is not None and net.get("r") and
                        [norm(ids) for ids, _ in net.get("u", [])] == [norm(x[0]) for x in u_lines] and
                        [norm(ids) for ids, _ in net.get("v", [])] == [norm(x[0]) for x in v_lines])
        if relayout:
            lay = patchnet.layout(sides, [x[3] for x in u_lines], [x[3] for x in v_lines])
            if lay is None:
                return False
            r, m, rows_i, cols_i = lay
            surface.net = {"r": r, "m": m, "u": [[list(x[0]), int(i)] for x, i in zip(u_lines, rows_i)],
                           "v": [[list(x[0]), int(i)] for x, i in zip(v_lines, cols_i)]}
        r, m = surface.net["r"], surface.net["m"]
        rows = [0] + [int(i) for _, i in surface.net["u"]] + [r - 1]
        cols = [0] + [int(i) for _, i in surface.net["v"]] + [m - 1]
        sd = [np.asarray(s, float) for s in sides]
        low, high, left, right = sd[0], sd[2][::-1], sd[3][::-1], sd[1]
        length = lambda p: float(patchnet.arc(p)[-1])
        u_geo = [(low, [0.0] + [patchnet.arc_at(low, v[1][0]) for v in v_lines] + [length(low)])]
        u_geo += [(u[1], [0.0] + [_arc_of_pid(u, v) for v in v_lines] + [length(u[1])]) for u in u_lines]
        u_geo += [(high, [0.0] + [patchnet.arc_at(high, v[1][-1]) for v in v_lines] + [length(high)])]
        v_geo = [(left, [0.0] + [patchnet.arc_at(left, u[1][0]) for u in u_lines] + [length(left)])]
        v_geo += [(v[1], [0.0] + [_arc_of_pid(v, u) for u in u_lines] + [length(v[1])]) for v in v_lines]
        v_geo += [(right, [0.0] + [patchnet.arc_at(right, u[1][-1]) for u in u_lines] + [length(right)])]
        if any(any(q <= p for p, q in zip(b, b[1:])) for _, b in u_geo + v_geo):
            return False  # intersection points not in order (e.g. net line just moved): last shape stays
        key = hash(b"".join(np.ascontiguousarray(p).tobytes() + np.asarray(b).tobytes() for p, b in u_geo + v_geo)
                   + str((rows, cols)).encode())
        geo = getattr(surface, "_net_geo", None)
        if geo is not None and geo.get("key") == key and not relayout:
            surface._netpatch_key = self._net_patch_memo(surface)
            return False
        g_old = surface.grid() if relayout else None
        curves_now = [p for p, _ in u_geo + v_geo]
        anchors = None if relayout else self._net_anchors(surface, curves_now)
        # points on border and net lines where another line attaches: there lies one grid point each (connections
        # lie exactly); a merely inserted point does not count – it changes nothing about the surface
        size = max(float(np.linalg.norm(np.ptp(np.vstack(sd), axis=0))), 1e-9)
        # (also lines of the neighboring surface on the shared border: when the point is dragged, the border bulges exactly there)
        joined = lambda pid: len({id(o) for o, _ in refs.get(pid, [])}) >= 2
        border_knots = [c.points[k] for c in self.patch_border(surface) for k, pid in (c.pids or {}).items() if joined(pid)]
        snaps = []
        bk = np.array(border_knots, float).reshape(-1, 3)
        for p in curves_now:  # all connection points at once (like _closest_on_poly / arc_at per point)
            d, s_at = _project_many(p, bk)
            snaps.append([float(patchnet.to_index(p, x)) for x in s_at[d < 1e-6 * size]])
        # curves: border bottom, transverse lines, border top, border left, longitudinal lines, border right
        for k, x in enumerate(u_lines):
            snaps[1 + k] = [float(i) for i, pid in x[2].items() if joined(pid)]
        for k, x in enumerate(v_lines):
            snaps[len(u_geo) + 1 + k] = [float(i) for i, pid in x[2].items() if joined(pid)]
        g, hard_u, hard_v, fis = patchnet.build(u_geo, v_geo, rows, cols, r, m, anchors, snaps)
        surface.net["idx"] = [{"n": len(p), "fi": np.asarray(fi, float)} for p, fi in zip(curves_now, fis)]
        surface._net_pts = [np.asarray(p, float).copy() for p in curves_now]
        surface.curves = _row_curves(g)
        surface.span = 1
        surface.offset = None
        for attr in ("_base", "_net_key"):
            if hasattr(surface, attr):
                delattr(surface, attr)
        surface._net_geo = {"key": key, "rows": rows, "cols": cols, "u": u_geo, "v": v_geo, "hard_u": hard_u,
                            "hard_v": hard_v, "u_lines": u_lines, "v_lines": v_lines, "fis": fis}
        if relayout:  # new grid: lines and painting keep their location on the surface
            # all points of all lines in ONE computation step (each point independent, same result): with ~500
            # paint strokes every new net line cost 1.4 s because each stroke was searched individually (Talking Points)
            todo, old_uv = [], []
            for cid, att in surface.attached.items():
                c = self.curve_by_id(cid)
                if c is None or not len(c.points):
                    continue
                if c.paint and g_old is not None and len(att["uv"]) == len(c.points):
                    old_uv.append((len(todo), np.asarray(att["uv"], float).reshape(-1, 2)))
                todo.append((c, att))
            parts = [np.asarray(c.points, float) for c, _a in todo]
            if old_uv:
                at_old = loft.evaluate_grid(np.concatenate([uv for _k, uv in old_uv]), g_old, False)
                at = 0
                for k, uv in old_uv:
                    parts[k] = at_old[at:at + len(uv)]
                    at += len(uv)
            if todo:
                located = netsurf.locate(g, np.concatenate(parts))[0]
                at = 0
                for (c, att), pts in zip(todo, parts):
                    att["uv"] = located[at:at + len(pts)].copy()
                    at += len(pts)
                    att["on"] = np.ones(len(c.points), bool)
                    att["last"], att["pos"] = c.points.tobytes(), c.points.copy()
        # net lines: their position in the grid is fixed (row or column, proportional along as sampled)
        K = len(u_geo)
        for lines, geos, fixed, fis_l, quer in ((u_lines, u_geo[1:-1], rows[1:-1], fis[1:K - 1], True),
                                                (v_lines, v_geo[1:-1], cols[1:-1], fis[K + 1:-1], False)):
            for x, (pts, breaks), at, fi in zip(lines, geos, fixed, fis_l):
                chain = self._chain_pieces(x[0])
                if chain is None:
                    continue
                cpts, pieces = chain
                flip = np.linalg.norm(cpts[0] - pts[0]) > np.linalg.norm(cpts[-1] - pts[0])
                for pc, idx in pieces:
                    ii = len(cpts) - 1 - idx if flip else idx
                    along = np.interp(ii.astype(float), fi, np.arange(len(fi), dtype=float))
                    fix = np.full(len(ii), float(at))
                    surface.attached[pc.id] = {"uv": np.stack([fix, along] if quer else [along, fix], 1),
                                               "on": np.ones(len(ii), bool), "last": pc.points.tobytes(),
                                               "pos": pc.points.copy()}
                    pc.plane_id = surface.id
        surface._netpatch_key = self._net_patch_memo(surface)
        return True

    def _line_deps(self, lines, refs):
        """What the sync of a surface depends on for these lines (by identity, arrays are replaced): the
        lines themselves with points and point IDs, plus the lines that share a point with them (hardness,
        connections, chains). What happens elsewhere in the net does not concern the surface."""
        objs = []
        for c in lines:
            if c is None:
                objs.append(None)
                continue
            objs += [c, c.points, c.pids]
            for pid in (c.pids or {}).values():
                for o, _ in refs.get(pid, ()):
                    if o is not c:
                        objs += [o, o.points]
        return objs

    def _surface_lines(self, surface):
        """Real lines a net surface depends on: bound, freshly drawn on it, border."""
        ids = list(surface.attached) + [c.id for c in self.curves_on(surface.id) if c.id not in surface.attached]
        lines = [c for cid in ids if (c := self.curve_by_id(cid)) is not None and not c.paint]
        if isinstance(surface, PatchSurface) and surface.patch_lines:
            lines += self.patch_border(surface)
        return lines

    def _net_patch_memo(self, surface):
        """Inputs of _sync_net_patch: (by identity: its lines and their neighbors, rest shape; by value: which
        lines, border, grid). The curve net must have just been synced (refs_by_pid)."""
        net = surface.net or {}
        lines = self._surface_lines(surface)
        return ([getattr(surface, "_net_geo", None), *self._line_deps(lines, network.refs_by_pid(self))],
                (tuple(surface.attached), tuple(c.id for c in lines), tuple(c.knots for c in lines),
                 repr((surface.patch_lines, surface.patch_order, surface.patch_corners, surface.patch_arc)),
                 repr((net.get("r"), net.get("m"), net.get("u"), net.get("v")))))

    def _net_anchors(self, surface, curves):
        """Stored places of the grid points per net curve, converted to the current lines (point count changed:
        via location) – or None (redistribute)."""
        idx = (surface.net or {}).get("idx")
        if not idx or len(idx) != len(curves):
            return None
        old_pts = getattr(surface, "_net_pts", None)
        out = []
        for k, (p, st) in enumerate(zip(curves, idx)):
            fi = np.asarray(st["fi"], float)
            old = old_pts[k] if old_pts is not None and len(old_pts) == len(curves) else None
            # point count changed or just distributed differently (sliding): convert via location; otherwise the place stays
            if int(st["n"]) != len(p) or (old is not None and self._same_shape(old, p)):
                if old is None or len(old) != int(st["n"]):
                    return None
                fi = netsurf._index_of(p, patchnet.at_index(old, fi))
            out.append(fi)
        return out

    def _net_line_ids(self, surface):
        """ids of all pieces of the net lines of the surface."""
        geo = getattr(surface, "_net_geo", None)
        if geo is None:
            return set()
        return {i for x in geo["u_lines"] + geo["v_lines"] for cid in x[0] for i in (self.split_pieces(cid) or [])}

    def _net_pid_uv(self, surface):
        """{point ID: uv} of the points on border and net lines – there the surface is fixed."""
        geo = getattr(surface, "_net_geo", None)
        sides = self._patch_sides(surface)
        if geo is None or sides is None:
            return {}
        # asked per frame, changes only with the net or the border lines: cache (copy – is extended)
        border = self.patch_border(surface)
        key = b"|".join(np.ascontiguousarray(c.points).tobytes() + str(sorted((c.pids or {}).items())).encode()
                        for c in border)
        cached = getattr(surface, "_pid_uv_cache", None)
        if cached is not None and cached[0] is geo and cached[1] == key:
            return dict(cached[2])
        out = self._net_pid_uv_calc(surface, geo, sides, border)
        surface._pid_uv_cache = (geo, key, out)
        return dict(out)

    def _net_pid_uv_calc(self, surface, geo, sides, border):
        rows, cols = geo["rows"], geo["cols"]
        r, m = rows[-1] + 1, cols[-1] + 1
        size = max(float(np.linalg.norm(np.ptp(np.vstack(sides), axis=0))), 1e-9)
        fis, K = geo["fis"], len(geo["u"])
        (low, _), (high, _) = geo["u"][0], geo["u"][-1]
        (left, _), (right, _) = geo["v"][0], geo["v"][-1]
        side_maps = ((low, fis[0], 0, 0.0), (high, fis[K - 1], 0, float(r - 1)),
                     (left, fis[K], 1, 0.0), (right, fis[-1], 1, float(m - 1)))
        grid_at = lambda fi, x: float(np.interp(x, fi, np.arange(len(fi), dtype=float)))
        out = {}
        knots = [(pid, c.points[k]) for c in border for k, pid in (c.pids or {}).items()]
        # all points at once per side: distance and position along (like _closest_on_poly / arc_at per point)
        near = []
        for pts, fi, _, _ in side_maps:
            d, s_at = _project_many(pts, np.array([q for _, q in knots]).reshape(-1, 3))
            idx = np.interp(s_at, patchnet.arc(pts), np.arange(len(pts), dtype=float))
            near.append((d < 1e-6 * size, np.interp(idx, fi, np.arange(len(fi), dtype=float))))
        for j, (pid, p) in enumerate(knots):
            for (pts, fi, fixed_axis, fixed), (ok, alongs) in zip(side_maps, near):
                if not ok[j]:
                    continue
                along = float(alongs[j])
                uv = list(out.get(pid, (None, None)))
                uv[fixed_axis] = fixed  # corner: row from one side, column from the other
                if uv[1 - fixed_axis] is None:
                    uv[1 - fixed_axis] = along
                out[pid] = tuple(uv)
        for lines, fixed, fis_l, quer in ((geo["u_lines"], rows[1:-1], fis[1:K - 1], True),
                                          (geo["v_lines"], cols[1:-1], fis[K + 1:-1], False)):
            for x, at, fi in zip(lines, fixed, fis_l):
                for ci, pid in x[2].items():
                    along = grid_at(fi, float(ci))
                    out[pid] = (float(at), along) if quer else (along, float(at))
        return {pid: uv for pid, uv in out.items() if None not in uv}

    def _sync_tube_net(self, surface):
        """Tube (closed transversely) or ring (also longitudinally): curve net as with the curve surface – the cross-sections and
        the longitudinal lines that cross each cross-section in a shared point form the rest shape (closed
        Gordon surface, patchnet.build_tube); each longitudinal line lies on its column. With fewer than three longitudinal lines
        it stays the loft through the cross-sections. Returns True if the rest shape has changed."""
        # asked per frame: rebuild only if cross-sections or longitudinal lines have changed (not on every
        # change anywhere in the net)
        network.sync(self)
        refs = network.refs_by_pid(self)
        pieces = tuple((cid, tuple(self.split_pieces(cid) or ())) for cid in
                       [cid for cid, _ in surface.rails] + [cid for src in surface.sources if src for cid in src[1]])
        lines = [self.curve_by_id(p) for _, ps in pieces for p in ps]
        memo = (*(c.points for c in surface.curves), *self._line_deps(lines, refs))
        vals = (repr(surface.rails), repr(surface.sources), surface.span, surface.wrap, pieces,
                tuple(c.knots if c is not None else None for c in lines))
        cached = getattr(surface, "_tube_key", None)
        if cached is not None and cached[1] == vals and _same_objs(cached[0], memo):
            return False
        surface._tube_key = (memo, vals)
        old = getattr(surface, "_gordon", None)
        surface._gordon, surface._tube_geo = None, None
        k_ = len(surface.curves)
        if k_ < 2 or not surface.rails or any(src is None or src[0] != "lines" for src in surface.sources):
            return old is not None
        span, m = surface.span, len(surface.curves[0].points)
        ring = surface.wrap and k_ >= 3
        r = (k_ if ring else k_ - 1) * span + 1
        rows = [k * span for k in range(k_)]
        sec_pids = []
        for src in surface.sources:
            pids = set()
            for cid in src[1]:
                for sub in self.split_pieces(cid) or []:
                    c = self.curve_by_id(sub)
                    if c is not None:
                        pids |= set((c.pids or {}).values())
            sec_pids.append(pids)
        v_lines, cols, v_ids = [], [], []
        for cid, col in sorted(surface.rails, key=lambda x: x[1]):
            chain = self._chain_pieces([cid])
            if chain is None:
                continue
            pts, pieces = chain
            pid_at = {}
            for pc, idx in pieces:
                for kk, pid in (pc.pids or {}).items():
                    if 0 <= kk < len(idx):
                        pid_at.setdefault(pid, []).append(int(idx[kk]))
            hits = []
            for pids in sec_pids:
                shared = [i for pid in pids & set(pid_at) for i in pid_at[pid]]
                if not shared:
                    break
                hits.append(min(shared))
            if len(hits) != k_:
                continue  # does not meet every cross-section in a shared point: no longitudinal line of the net
            if hits[0] > hits[-1] and not ring:
                pts, hits = pts[::-1], [len(pts) - 1 - i for i in hits]
            ar = patchnet.arc(pts)
            breaks = [float(ar[i]) for i in hits]
            if ring:
                if np.linalg.norm(pts[0] - pts[-1]) > 1e-6 * max(float(np.ptp(pts, axis=0).max()), 1e-9):
                    continue
                breaks = [b - breaks[0] for b in breaks]
                pts = np.vstack([pts[hits[0]:-1], pts[:hits[0] + 1]]) if hits[0] else pts
                ar = patchnet.arc(pts)
                breaks = [float(patchnet.arc_at(pts, pts[0]))] + [float(patchnet.arc_at(pts, p)) for p in
                                                                   (chain[0][i] for i in hits[1:])] + [float(ar[-1])]
            if any(b2 <= b1 for b1, b2 in zip(breaks, breaks[1:])):
                continue
            v_lines.append((pts, breaks))
            cols.append(int(col))
            v_ids.append(cid)
        if len(v_lines) < 3 or len(set(cols)) != len(cols):
            return old is not None
        loops = []
        for k, c in enumerate(surface.curves):
            loop = np.asarray(c.points, float)
            closed = np.vstack([loop, loop[:1]])
            total = float(patchnet.arc(closed)[-1])
            arcs = [patchnet.arc_at(closed, v[0][self._index_on(v[0], v[1][k])]) for v in v_lines]
            for i in range(1, len(arcs)):  # ascending across the seam
                while arcs[i] <= arcs[i - 1]:
                    arcs[i] += total
            if arcs[-1] >= arcs[0] + total:
                return old is not None
            loops.append((loop, arcs))
        g = patchnet.build_tube(loops, rows, v_lines, cols, r, m, ring)
        if g is None:
            return old is not None
        surface._gordon = g
        surface._tube_geo = {"rows": rows, "cols": cols, "v_ids": v_ids, "loops": loops, "v_lines": v_lines, "ring": ring}
        return old is None or old.shape != g.shape or not np.array_equal(old, g)

    @staticmethod
    def _index_on(pts, s):
        """Index of the point of the polyline pts at arc length s (the nearest)."""
        return int(np.argmin(np.abs(patchnet.arc(pts) - s)))

    def _tube_rail_uv(self, surface):
        """Tube/ring: {line ID: uv per point} of the longitudinal lines of the net (column fixed, row by arc length)."""
        geo = surface._tube_geo
        r_last = (len(surface.curves) if geo["ring"] else len(surface.curves) - 1) * surface.span
        vrows = geo["rows"] + ([r_last] if geo["ring"] else [])
        out = {}
        for cid, (pts, breaks), col in zip(geo["v_ids"], geo["v_lines"], geo["cols"]):
            for sub in self.split_pieces(cid) or []:
                c = self.curve_by_id(sub)
                if c is None or sub not in surface.attached:
                    continue
                rows = [float(np.interp(patchnet.arc_at(pts, p), breaks, vrows)) for p in c.points]
                out[sub] = np.stack([rows, np.full(len(rows), float(col))], axis=1)
        return out

    def _tube_pid_uv(self, surface):
        """Tube/ring: {point ID: uv} of the points on cross-sections and longitudinal lines – there the surface is fixed."""
        geo = getattr(surface, "_tube_geo", None)
        if geo is None:
            return {}
        m = len(surface.curves[0].points)
        out = {}
        for k, (src, (loop, arcs)) in enumerate(zip(surface.sources, geo["loops"])):
            closed = np.vstack([loop, loop[:1]])
            for cid in src[1]:
                for sub in self.split_pieces(cid) or []:
                    c = self.curve_by_id(sub)
                    for kk, pid in ((c.pids or {}).items() if c is not None else ()):
                        col = patchnet.loop_index(loop, arcs, geo["cols"], m, patchnet.arc_at(closed, c.points[kk]))
                        out[pid] = (float(geo["rows"][k]), col)
        r_last = (len(surface.curves) if geo["ring"] else len(surface.curves) - 1) * surface.span
        vrows = geo["rows"] + ([r_last] if geo["ring"] else [])
        for cid, (pts, breaks), col in zip(geo["v_ids"], geo["v_lines"], geo["cols"]):
            for sub in self.split_pieces(cid) or []:
                c = self.curve_by_id(sub)
                for kk, pid in ((c.pids or {}).items() if c is not None else ()):
                    row = float(np.interp(patchnet.arc_at(pts, c.points[kk]), breaks, vrows))
                    out.setdefault(pid, (row, float(col)))
        return out

    def _derive_shared_uv(self, surface, nets, target=None):
        """Derive the position of shared points on the surface from the net instead of remembering it per line: a point of a line
        that lies on the border or a net line gets its position; two free lines that share a point get
        the same one (the middle). The line in between moves along proportionally up to its neighboring points."""
        target = self._net_pid_uv(surface) if target is None else dict(target)
        free = []
        for cid, att in surface.attached.items():
            c = self.curve_by_id(cid)
            if c is None or c.paint or cid in nets or len(att["uv"]) != len(c.points) or not c.pids:
                continue
            free.append((c, att))
        shared = {}
        for c, att in free:
            for k, pid in c.pids.items():
                if pid not in target and 0 <= k < len(att["uv"]):
                    shared.setdefault(pid, []).append(np.asarray(att["uv"][k], float))
        target.update({pid: tuple(np.mean(v, axis=0)) for pid, v in shared.items() if len(v) > 1})
        for c, att in free:
            ks = components.knots(c)
            delta = np.zeros((len(ks), 2))
            for i, k in enumerate(ks):
                pid = c.pids.get(k)
                if pid in target:
                    delta[i] = np.asarray(target[pid], float) - att["uv"][k]
            if np.abs(delta).max() <= 1e-9:
                continue
            uv = np.asarray(att["uv"], float).copy()
            for i in range(len(ks) - 1):
                a, b = ks[i], ks[i + 1]
                t = np.linspace(0.0, 1.0, b - a + 1)[:, None]
                uv[a:b + 1] += delta[i] * (1 - t) + delta[i + 1] * t
            att["uv"] = uv

    def _sync_patches(self):
        changed = False
        skip = getattr(self, "_sync_skip", ())
        for surface in self.surfaces:
            if not isinstance(surface, PatchSurface) or not surface.patch_lines or surface.frozen is not None \
                    or id(surface) in skip:
                continue
            changed |= self._sync_net_patch(surface)
        return changed

    def patch_border(self, surface):
        """Border lines of a curve surface (split ones as their pieces)."""
        out = []
        for cid in surface.patch_lines:
            for sub in self.split_pieces(cid) or []:
                c = self.curve_by_id(sub)
                if c is not None:
                    out.append(c)
        return out

    def create_patch(self, curves, corner_points=None, name=None):
        """Create a curve surface from the border curves (Curve objects) or None (no closed outline).
        corner_points: specify the four corners (otherwise: the strongest kinks at the joints)."""
        pts = [c.points for c in curves]
        order = patch_geo.order_loop(pts)
        if order is None:
            return None
        if corner_points is not None:
            order = patch_geo.keep_direction(pts, order, corner_points)
            spec = patch_geo.spec_for_points(pts, order, corner_points)
            rows, spec = patch_geo.build_rows(pts, order, spec, arc=True)
        else:
            rows, spec = patch_geo.build_rows(pts, order, arc=True)
        surface = PatchSurface(name or self._unique_name(tr("Kurvenfläche"), self.surfaces),
                               [Curve(np.asarray(r, float), None) for r in rows],
                               sources=[], closed=False, patch_lines=[c.id for c in curves],
                               patch_order=[(int(i), bool(f)) for i, f in order], patch_corners=[(int(j), float(t)) for j, t in spec], patch_arc=True)
        surface._patch_key = hash(b"".join(np.ascontiguousarray(p).tobytes() for p in pts))
        self.place_with_lines(surface, curves)
        self.surfaces.append(surface)
        return surface

    def loft_to_patch(self, surface):
        """Convert an open loft (sheet) into a curve surface: border = first cross-section, side line, last
        cross-section, other side line (corners at the ends of the cross-sections); the middle cross-sections become lines
        on the surface. Afterwards it is a curve surface like any other – it only originated as a loft.
        Returns the curve surface or None (tube/ring, cross-sections without lines, side lines missing)."""
        if surface.closed or surface.wrap or len(surface.curves) < 2:
            return None
        if any(src is None or src[0] != "lines" for src in surface.sources):
            return None
        m = len(surface.curves[0].points)
        g = surface.grid()
        sides = {col: self.curve_by_id(cid) for cid, col in surface.rails if col in (0, m - 1)}
        for col in (0, m - 1):  # without a recorded side line (extruding, older scenes): line at this place
            if sides.get(col) is None:
                ids = self._lines_along(g[:, col])
                sides[col] = self.curve_by_id(ids[0]) if ids and len(ids) == 1 else None
        if any(sides.get(col) is None for col in (0, m - 1)):
            return None
        lines = lambda src: [c for cid in src[1] for sub in (self.split_pieces(cid) or []) if (c := self.curve_by_id(sub))]
        first, last = lines(surface.sources[0]), lines(surface.sources[-1])
        if not first or not last:
            return None
        corners = [g[0, 0], g[0, -1], g[-1, -1], g[-1, 0]]
        border = first + [sides[m - 1]] + last + [sides[0]]
        # what hangs on the loft (painting, lines) – with its current position
        held = [c for cid in surface.attached if (c := self.curve_by_id(cid)) is not None]
        size_l = max(float(np.linalg.norm(np.ptp(g.reshape(-1, 3), axis=0))), 1e-9)

        def loft_uv(c, section=False):  # position of a line on the loft (row, column)
            att = surface.attached.get(c.id)
            if att is not None and len(att["uv"]) == len(c.points) and not section:
                return np.asarray(att["uv"], float), np.asarray(att.get("on", np.ones(len(c.points), bool)), bool)
            uv, on = loft.bind(c.points, None, surface.closed, LOFT_BIND_TOL * size_l, g=g)
            if section:  # a cross-section belongs to it entirely (the loft only cuts the corners of its polyline slightly)
                on = np.ones(len(c.points), bool)
            return uv, on
        name = surface.name.replace("Loft", tr("Kurvenfläche"))
        if any(s.name == name for s in self.surfaces if s is not surface):
            name = None  # already taken: next free name
        patch = self.create_patch(border, corners, name=name)
        if patch is None:
            return None
        # rest shape: the loft itself (cross-sections as rows, smoothly connected), not the Coons surface of the border – it
        # does not know the middle cross-sections and would have to stretch toward them (tent instead of curve)
        self.surfaces.remove(patch)
        self.surfaces[self.surfaces.index(surface)] = patch
        border_ids = {c.id for c in border}
        size = float(np.linalg.norm(np.ptp(g.reshape(-1, 3), axis=0)))
        on_loft = {}  # line -> position on the loft, before it is replaced

        def on_border(c):  # lies entirely on the border (e.g. duplicate side line from the neighboring loft): shapes nothing
            probe = patchnet.at_arc(c.points, np.linspace(0, patchnet.arc(c.points)[-1], 7))  # along, not only
            # at the line points: a straight connecting line of two points would otherwise lie "entirely on the border"
            return all(min(self._closest_on(e, p)[0] for e in border) < 1e-3 * size for p in probe)

        for src in surface.sources[1:-1]:  # middle cross-sections: lines on the surface (they shape it)
            for c in lines(src):
                c.plane_id = patch.id
                on_loft[c.id] = loft_uv(c, section=True)
        for cid, col in surface.rails:  # further longitudinal lines (if present) likewise
            c = self.curve_by_id(cid)
            if c is not None and c.id not in border_ids:
                c.plane_id = patch.id
                on_loft[c.id] = loft_uv(c)
        network.sync(self)  # transverse lines from the first to the last cross-section (extruding: at corners) likewise
        ends_a = {p for c in first for p in (c.pids or {}).values()}
        ends_b = {p for c in last for p in (c.pids or {}).values()}
        for c in self.pickable_curves():
            if c.paint or c.id in border_ids or c.plane_id is not None or len(c.points) < 2:
                continue
            a, b = network.pid_of(c, 0), network.pid_of(c, len(c.points) - 1)
            if (a in ends_a and b in ends_b or a in ends_b and b in ends_a) and not on_border(c):
                c.plane_id = patch.id
                on_loft[c.id] = loft_uv(c)
        for c in held:  # painting and lines on it: now hang on the curve surface (at their place)
            if c.id not in border_ids:
                c.plane_id = patch.id if c.paint or not on_border(c) else None
                if c.plane_id is not None:
                    on_loft[c.id] = loft_uv(c)
        # hold at the same place of the curve surface (row/column of the loft converted): also lines that lie far
        # from the still raw surface (strongly curved middle cross-sections) shape it – no binding by proximity
        rp, mp = patch.base_grid().shape[:2]
        rl, ml = g.shape[:2]
        for cid, (uv, on) in on_loft.items():
            c = self.curve_by_id(cid)
            if c is None or not on.any():
                continue
            uvp = np.stack([uv[:, 0] * (rp - 1) / max(rl - 1, 1), uv[:, 1] * (mp - 1) / max(ml - 1, 1)], axis=1)
            patch.attached[cid] = {"uv": uvp, "on": on.copy(), "last": c.points.tobytes(), "pos": c.points.copy()}
        if self.active_mesh is surface:
            self.active_mesh = patch
        return patch

    def _upgrade_open_lofts(self):
        """Older scenes: open lofts are now curve surfaces (tubes and rings stay lofts)."""
        for surface in list(self.surfaces):
            if type(surface) is LoftSurface and not surface.closed and not surface.wrap:
                self.loft_to_patch(surface)

    def net_rows_lines(self, surface):
        """Curve surface: per transverse row of the net (border bottom, transverse lines, border top) the ids of their lines."""
        geo = getattr(surface, "_net_geo", None)
        sides = self._patch_sides(surface)
        if geo is None or sides is None:
            return []
        size = max(float(np.linalg.norm(np.ptp(np.vstack(sides), axis=0))), 1e-9)
        on_side = lambda c, s: all(float(np.linalg.norm(_closest_on_poly(np.asarray(sides[s], float), p) - p)) < 1e-6 * size
                                   for p in c.points[::max(1, len(c.points) // 6)])
        border = self.patch_border(surface)
        out = [{c.id for c in border if on_side(c, 0)}]
        out += [{i for cid in x[0] for i in (self.split_pieces(cid) or [])} for x in geo["u_lines"]]
        out.append({c.id for c in border if on_side(c, 2)})
        return out

    def divide_patch(self, surface, spans, owner):
        """Split loft on a curve surface: between the transverse rows spans[i] and spans[i]+1 (border bottom, transverse lines,
        border top) one new line each exactly on the surface – from side to side, connected to border and longitudinal lines with shared
        points. It is thus a net line (the shape stays, it can be moved deliberately)."""
        geo = getattr(surface, "_net_geo", None)
        sides = self._patch_sides(surface)
        if geo is None or sides is None:
            return []
        rows, cols = geo["rows"], geo["cols"]
        g = surface.grid()
        border = self.patch_border(surface)
        width = float(np.mean([c.widths.mean() for c in owner.curves])) if owner.curves else DEFAULT_WIDTH
        made = []
        for i in sorted(set(spans)):
            if not 0 <= i < len(rows) - 1 or rows[i + 1] - rows[i] < 2:
                continue
            pts = g[(rows[i] + rows[i + 1]) // 2].copy()
            # from border to border: at both ends the width of the border there, in between proportional
            line = Curve(pts, surface.id, components.widths_between(pts, border, border, width))
            owner.curves.append(line)
            made.append(line)
            network.sync(self)
            # ends to the border, crossings to the longitudinal lines: shared points
            joints = [(0, border), (len(pts) - 1, border)]
            for x, col in zip(geo["v_lines"], cols[1:-1]):
                joints.append((col, [c for cid in x[0] for sub in (self.split_pieces(cid) or [])
                                     if (c := self.curve_by_id(sub)) is not None]))
            for k, candidates in joints:
                p = line.points[k]
                if not candidates:
                    continue
                other = min(candidates, key=lambda c: self._closest_on(c, p)[0])
                network.sync(self)
                kl = network.knot_at(line, p)
                ko = network.knot_at(other, line.points[kl])
                network.join(self, other, ko, line, kl)
        return made

    def divide_loft(self, surface, spans, owner):
        """Split loft: insert a new cross-section in each section (index of the front cross-section), exactly on
        the surface in the middle of the section. The new cross-sections are real lines (in owner) and sources of the
        loft. What was drawn on it keeps its position (rows are converted)."""
        secs = np.array(surface.sections())
        k = len(surface.curves)
        g = surface.grid()
        step = loft.SPAN_SAMPLES
        spans = sorted({s for s in spans if 0 <= s < len(secs) - 1})
        if not spans:
            return []
        new_lines = []
        width = float(np.mean([c.widths.mean() for c in owner.curves])) if owner.curves else DEFAULT_WIDTH
        lines_of = [[c for cid in src[1] for sub in (self.split_pieces(cid) or []) if (c := self.curve_by_id(sub))]
                    if src is not None and src[0] == "lines" else [] for src in surface.sources]  # per cross-section
        if surface.wrap and lines_of:
            lines_of.append(lines_of[0])  # ring: after the last the first again
        for s in reversed(spans):
            row = g[s * step + step // 2].copy()
            pts = np.vstack([row, row[:1]]) if surface.closed else row
            wid = np.full(len(pts), width)
            if s + 1 < len(lines_of) and lines_of[s] and lines_of[s + 1] and (s + 1) * step < len(g):
                # per point the mean of the two neighboring cross-sections at the same place (grid column)
                wid = np.array([(components.width_near(lines_of[s], g[s * step, j % len(row)], width) +
                                 components.width_near(lines_of[s + 1], g[(s + 1) * step, j % len(row)], width)) / 2
                                for j in range(len(pts))])
            line = Curve(pts, None, wid)  # source of the loft, not drawn on it
            owner.curves.append(line)
            new_lines.append(line)
            at = s + 1 if s + 1 <= k else k  # ring: section after the last cross-section -> to the end
            surface.curves.insert(at, Curve(row.copy(), None))
            surface.sources.insert(at, ("lines", [line.id]))
        # convert rows (uv = (row, column) in the grid): split sections become two sections
        old_spans = len(secs) - 1
        split = set(spans)

        def remap(r):
            r = np.asarray(r, float)
            s = np.clip(np.floor(r / step).astype(int), 0, old_spans - 1)
            u = r / step - s
            shift = np.array([sum(1 for x in split if x < si) for si in np.ravel(s)]).reshape(s.shape)
            j = s + shift
            here = np.isin(s, list(split))
            return np.where(here, (j + np.minimum(2 * u, 2.0)) * step, (j + u) * step)

        for att in surface.attached.values():
            att["uv"][:, 0] = remap(att["uv"][:, 0])
        surface._synced = None
        return new_lines

    def _sync_sections(self):
        changed = self._sync_patches()
        skip = getattr(self, "_sync_skip", ())
        for surface in self.surfaces:
            if not isinstance(surface, LoftSurface) or not any(surface.sources) or surface.frozen is not None \
                    or id(surface) in skip:
                continue
            current = []
            for src, sec in zip(surface.sources, surface.curves):
                pts = self.loft_source_points(src)
                current.append(pts if pts is not None else None)
            key = b"".join(np.ascontiguousarray(p).tobytes() if p is not None else b"-" for p in current)
            if key == getattr(surface, "_synced", None):
                continue
            surface._synced = key
            if all(p is None for p in current):
                continue
            gone = [k for k, (src, p) in enumerate(zip(surface.sources, current)) if src is not None and p is None]
            if gone and self._net_loft(surface) and len(current) - len(gone) >= 2:
                self._drop_sections(surface, gone)  # cross-section deleted: the loft loses it (no ghost)
                current = [p for k, p in enumerate(current) if k not in gone]
            sections = [p if p is not None else sec.points for p, sec in zip(current, surface.curves)]
            aligned, closed = loft.prepare(sections)
            if len(aligned) != len(surface.curves):
                continue
            for c, sec in zip(surface.curves, aligned):
                c.points = sec
                c.widths = np.full(len(sec), DEFAULT_WIDTH)
            surface.closed = closed
            if not self._net_loft(surface):
                self._update_loft_rails(surface)  # net surface: side lines are real lines, the loft does not move them
            changed = True
        return changed

    @staticmethod
    def _net_loft(surface):
        """Is the loft a net surface (scipy present)? Then all real lines shape it, and it moves none."""
        return isinstance(surface, LoftSurface)

    def _drop_sections(self, surface, gone):
        """Remove cross-sections gone (indices) from the loft; painting stays at its place on the surface."""
        g_old = surface.grid()
        follow = {cid: loft.evaluate_grid(att["uv"], g_old, surface.closed) for cid, att in surface.attached.items()
                  if (c := self.curve_by_id(cid)) is not None and c.paint}
        surface.curves = [c for k, c in enumerate(surface.curves) if k not in gone]
        surface.sources = [src for k, src in enumerate(surface.sources) if k not in gone]
        surface.offset = None
        for attr in ("_net_key", "_base", "_att_geo"):
            if hasattr(surface, attr):
                delattr(surface, attr)
        g_new = surface.base_grid()
        for cid, att in surface.attached.items():
            c = self.curve_by_id(cid)
            if c is None:
                continue
            pts = follow.get(cid, c.points)
            att["uv"] = netsurf.locate(g_new, pts)[0]
            att["last"], att["pos"] = c.points.tobytes(), c.points.copy()

    def _sync_attached(self, surface, free):
        """Lines drawn on it: rebind (freshly drawn or moved by hand), deform along
        (loft has changed), detach (pulled away from the loft or Alt) or tear at the loft boundary.
        Net surface (curve surface, trial run): real lines on it are not moved by the surface – they shape it
        (_sync_drivers); only painting is deformed along."""
        if len(surface.curves) < 2:
            return False
        net = isinstance(surface, PatchSurface) or self._net_loft(surface)
        g = surface.grid()
        memo = getattr(surface, "_tol_memo", None)  # asked per frame: remember the grid size as long as it is the same
        if memo is None or memo[0] is not g:
            lo, hi = g.reshape(-1, 3).min(axis=0), g.reshape(-1, 3).max(axis=0)
            memo = surface._tol_memo = (g, LOFT_BIND_TOL * max(float(np.linalg.norm(hi - lo)), 1e-9))
        tol = memo[1]
        rails = {cid for cid, _ in surface.rails}
        changed = False
        # freshly drawn on it (net loft: also side lines): bind
        for curve in self.curves_on(surface.id, rails if net else ()):
            mine = curve.plane_id == surface.id and curve.id not in rails or net and curve.id in rails
            if mine and curve.id not in surface.attached:
                uv, on = loft.bind(curve.points, None, surface.closed, tol, g=g)
                if on.any():
                    surface.attached[curve.id] = {"uv": uv, "on": on, "last": curve.points.tobytes(),
                                                  "pos": curve.points.copy()}
                else:
                    curve.plane_id = None
        if net:
            changed |= self._sync_drivers(surface, free, g, tol)
            g = surface.grid()
        key = hash(surface._cache_key())
        # first sync (newly created or loaded): only remember the state, deform nothing
        geo_changed = getattr(surface, "_att_geo", key) != key
        surface._att_geo = key
        batch = []  # deform strokes along: evaluate all uv at once (one computation step instead of per stroke)
        for cid in list(surface.attached):
            att = surface.attached[cid]
            curve = self.curve_by_id(cid)
            if curve is None:
                del surface.attached[cid]
                continue
            if net and not curve.paint:
                continue  # real line: shapes the surface (_sync_drivers)
            if curve.points.tobytes() != att["last"]:  # changed by hand: rebind or detach
                uv, on = loft.bind(curve.points, None, surface.closed, tol, g=g)
                if not on.any():
                    curve.plane_id = None
                    del surface.attached[cid]
                else:
                    att.update(uv=uv, on=on, last=curve.points.tobytes())
                continue
            if not geo_changed:
                continue
            if free:  # Alt: stays in space, no longer belongs to the loft
                curve.plane_id = None
                del surface.attached[cid]
                continue
            if not att["on"].all():
                self._tear(surface, curve, att)
            else:
                batch.append((curve, att))
            changed = True
        if batch:
            uv = np.concatenate([np.asarray(att["uv"], float).reshape(-1, 2) for _c, att in batch])
            pts = loft.evaluate_grid(uv, g, surface.closed)
            at = 0
            for curve, att in batch:
                n = len(np.asarray(att["uv"]).reshape(-1, 2))
                curve.points = pts[at:at + n].copy()  # own array per stroke (never shared)
                at += n
                att["last"] = curve.points.tobytes()
        return changed

    @staticmethod
    def _same_shape(old, new):
        """Are all changed points of new on the polyline old (only distributed differently, same shape)?"""
        old, new = np.asarray(old, float), np.asarray(new, float)
        if len(old) < 2 or len(old) != len(new):
            return False
        moved = np.flatnonzero(np.any(old != new, axis=1))
        if not len(moved):
            return False
        eps = 1e-6 * max(float(np.linalg.norm(np.ptp(old, axis=0))), 1e-12)
        a, ab = old[:-1], np.diff(old, axis=0)
        p = new[moved]
        t = np.clip(np.einsum("pij,ij->pi", p[:, None] - a[None], ab) / np.maximum(np.einsum("ij,ij->i", ab, ab), 1e-18)[None], 0, 1)
        d = np.linalg.norm(a[None] + t[..., None] * ab[None] - p[:, None], axis=2).min(axis=1)
        return bool(d.max() <= eps)

    def _sync_drivers(self, surface, free, g, tol):
        """Net surface: the real lines on the surface shape it. Their position in the surface parameter (uv) stays when
        they are moved (there the surface meets them); if points are added, uv is transferred. Alt in a drag detaches the
        line from the surface. Afterwards the displacement of the surface is recomputed if something has changed."""
        network.sync(self)  # once here – _driver_objs only reads the state
        changed = False
        for cid in list(surface.attached):
            att, curve = surface.attached[cid], self.curve_by_id(cid)
            if curve is None or curve.paint:
                continue
            if att.get("pos") is None or len(att["pos"]) != len(att["uv"]):
                att["pos"] = curve.points.copy() if len(curve.points) == len(att["uv"]) else None
            if curve.points.tobytes() == att["last"]:
                continue
            if free:
                curve.plane_id = None
                del surface.attached[cid]
                changed = True
                continue
            if len(curve.points) != len(att["uv"]):
                if att.get("pos") is not None:
                    att["uv"], att["on"] = netsurf.transfer(att["pos"], att["uv"], att["on"], curve.points)
                else:
                    att["uv"], att["on"] = loft.bind(curve.points, None, surface.closed, tol, g=g)
            elif att.get("pos") is not None and self._same_shape(att["pos"], curve.points):
                # same point count, same shape, points only moved (sliding): transfer uv via location –
                # otherwise every point would get the position of its neighbor and the surface shears
                att["uv"], att["on"] = netsurf.transfer(att["pos"], att["uv"], att["on"], curve.points)
            att["last"], att["pos"] = curve.points.tobytes(), curve.points.copy()
        # asked per frame: if nothing has changed since the last sync, the key below is the same too –
        # do not recompute line positions, shared points and hardness values (expensive) at all
        cached = getattr(surface, "_drv_key", None)
        if cached is not None and cached[1] == self._driver_vals(surface) and _same_objs(
                cached[0], self._driver_objs(surface)):
            return changed
        uv, targets, parts, groups, hard = [], [], [], [], []
        refs = network.refs_by_pid(self)
        geo = getattr(surface, "_net_geo", None) if isinstance(surface, PatchSurface) else None
        tube = getattr(surface, "_tube_geo", None) if not isinstance(surface, PatchSurface) else None
        nets = self._net_line_ids(surface) if geo is not None else set()
        if geo is not None:
            self._derive_shared_uv(surface, nets)
        if tube is not None:  # tube/ring: longitudinal lines shape the rest shape and lie on their column (row proportional
            # by arc length between the cross-sections); shared points of other lines follow the net
            rails = self._tube_rail_uv(surface)
            for cid, uv_r in rails.items():
                surface.attached[cid]["uv"] = uv_r
            self._derive_shared_uv(surface, set(rails), self._tube_pid_uv(surface))
        for cid, att in surface.attached.items():
            curve = self.curve_by_id(cid)
            if curve is None or curve.paint or len(att["uv"]) != len(curve.points) or cid in nets:
                continue
            idx = netsurf.samples(curve.points, att["uv"], att.get("on"), components.knots(curve))
            if len(idx):
                uv.append(att["uv"][idx])
                targets.append(curve.points[idx])
                hard.append(self._line_hardness(curve, refs)[idx])
                parts.append(att["last"] + np.asarray(att["uv"]).tobytes() + hard[-1].tobytes())
                groups.append(np.full(len(idx), cid))
        if geo is not None:
            # net lines: the rest shape lies exactly on them; each grid point of their row or column holds the surface
            # there (regardless of how many points the line has), free lines only bend it in between
            base_net = surface.base_grid()
            r, m = base_net.shape[:2]
            for k, row in enumerate(geo["rows"][1:-1], 1):
                uv.append(np.stack([np.full(m, float(row)), np.arange(m, dtype=float)], axis=1))
                targets.append(base_net[row])
                hard.append(np.asarray(geo["hard_u"][k], float))
                groups.append(np.full(m, -k))
            for l, col in enumerate(geo["cols"][1:-1], 1):
                uv.append(np.stack([np.arange(r, dtype=float), np.full(r, float(col))], axis=1))
                targets.append(base_net[:, col])
                hard.append(np.asarray(geo["hard_v"][l], float))
                groups.append(np.full(r, -1000 - l))
            parts.append(str((geo["rows"], geo["cols"])).encode() + geo["hard_u"].tobytes() + geo["hard_v"].tobytes())
        if tube is not None:
            parts.append(hash(surface._gordon.tobytes()).to_bytes(8, "little", signed=True))
        sides = self._patch_sides(surface) if isinstance(surface, PatchSurface) else None
        side_key = b"".join(np.ascontiguousarray(p).tobytes() for p in sides) if sides is not None else b"-"
        key = b"".join(np.ascontiguousarray(c.points).tobytes() for c in surface.curves) + b"|".join(parts) + side_key
        key = hash(key)
        if key == getattr(surface, "_net_key", None):
            surface._drv_key = (self._driver_objs(surface), self._driver_vals(surface))
            return changed
        surface._net_key = key
        base = surface.base_grid()
        uv_all = np.vstack(uv) if uv else np.zeros((0, 2))
        tg = np.vstack(targets) if targets else np.zeros((0, 3))
        hd = np.concatenate(hard) if hard else None
        if not isinstance(surface, PatchSurface):
            # loft: the cross-sections already lie exactly on their lines (fixed rows), in between through all lines
            span = surface.span
            rows = [k * span for k in range(len(surface.sections()))]
            fix = netsurf.solve_rows(base, uv_all, tg, np.concatenate(groups) if groups else None, rows,
                                     surface.closed, hard=hd)
        else:
            # rest shape + smooth deformation: border exactly onto the border lines (border knots hang at fixed places of the
            # border lines), inside through all lines
            boundary = None  # curve net: the rest shape lies exactly on the border
            if sides is not None and geo is None:
                surface.bnd, targets_b = netsurf.boundary_track(surface.bnd, sides, *base.shape[:2])
                boundary = netsurf.boundary_from_targets(base, targets_b)
            fix = netsurf.solve(base, uv_all, tg, np.concatenate(groups) if groups else None, boundary=boundary,
                                hard=hd)
        surface.offset = fix
        surface._drv_key = (self._driver_objs(surface), self._driver_vals(surface))
        return True

    def _driver_objs(self, surface):
        """Inputs of _sync_drivers that are replaced rather than changed (compared by identity): curve net
        (every change of a line gives a new state), rest shape, displacement and the bound lines. The
        curve net is synced by _sync_drivers at the start (not once more here: twice per surface and frame)."""
        objs = [getattr(surface, "_gordon", None), getattr(surface, "_tube_geo", None),
                getattr(surface, "_net_geo", None), surface.base_grid(), surface.offset]
        for att in surface.attached.values():
            objs += [att, att["uv"], att.get("on"), att["last"]]
        return objs + self._line_deps(self._surface_lines(surface), network.refs_by_pid(self))

    def _driver_vals(self, surface):
        """Inputs of _sync_drivers that are compared by value (_net_key = None forces new)."""
        patch = ((surface.patch_lines, surface.patch_order, surface.patch_corners, surface.patch_arc)
                 if isinstance(surface, PatchSurface) else None)
        lines = self._surface_lines(surface)
        return (tuple(surface.attached), getattr(surface, "_net_key", None), surface.res, repr(patch),
                tuple(c.id for c in lines), tuple(c.knots for c in lines))

    def rerest_patches(self):
        """After a deformation: redistribute curve surfaces whose grid is stretched very unevenly –
        the current shape becomes the new rest shape (not rebuilt as a Coons surface, the shape stays). Lines,
        painting get their position on the new grid. Returns the number of redistributed surfaces."""
        done = 0
        for surface in self.surfaces:
            if not isinstance(surface, PatchSurface) or len(surface.curves) < 2 or surface.frozen is not None or (
                    surface.offset is None and getattr(surface, "_net_geo", None) is None):
                continue
            if getattr(surface, "_net_geo", None) is not None:
                # curve net: the grid points hang at fixed places of the lines and stay there; redistributing
                # would change the shape (the surface depends on the division) – after release it would jump
                continue
            g, rest = surface.grid(), surface.base_grid()
            if netsurf.distortion(g, rest) < netsurf.REREST:
                continue
            g2 = netsurf.even_grid(g)[0]

            def rebind(uv):  # same place on the surface, in the new grid
                return netsurf.locate(g2, loft.evaluate_grid(uv, g, False))[0]
            surface.curves = _row_curves(g2)  # all rows: the shape stays exact
            surface.span = 1
            surface.bnd = None  # the new rest shape is distributed evenly at the border
            for att in surface.attached.values():
                att["uv"] = rebind(att["uv"])
            surface.offset = None
            for attr in ("_net_key", "_base"):
                if hasattr(surface, attr):
                    delattr(surface, attr)
            done += 1
        if done:
            self.sync_lofts()
        return done

    def _patch_sides(self, surface):
        """The four sides of a curve surface, exactly on their border lines (None: border incomplete)."""
        if not isinstance(surface, PatchSurface) or not surface.patch_lines or not surface.patch_corners:
            return None
        ids = [self.split_pieces(cid) for cid in surface.patch_lines]
        if any(sub is None for sub in ids):
            return None
        curves = [self._chain_points(sub) for sub in ids]
        if any(c is None for c in curves):
            return None
        # asked per frame, rarely changes: cache as long as border lines and corners stay the same
        key = (b"".join(np.ascontiguousarray(c).tobytes() for c in curves), tuple(map(tuple, surface.patch_order)),
               tuple(map(tuple, surface.patch_corners)), surface.patch_arc)
        cached = getattr(surface, "_sides_cache", None)
        if cached is None or cached[0] != key:
            cached = surface._sides_cache = (key, patch_geo.border_sides(curves, surface.patch_order,
                                                                         surface.patch_corners, arc=surface.patch_arc))
        return cached[1]

    def relink_patch(self, surface):
        """Reattach a curve surface that lacks border lines (deleted, or their id was lost – alpaca tank 14.11.) to
        the lines that lie exactly on its border and connect the neighboring sides. Only unambiguous cases: if
        no chain or more than one chain lies there, the side stays open. Returns the number of reattached sides."""
        from .scene import _new_id
        if not isinstance(surface, PatchSurface) or not surface.patch_lines or not surface.patch_order:
            return 0
        resolved = [self.split_pieces(cid) for cid in surface.patch_lines]
        if all(r is not None for r in resolved):
            return 0
        g = surface.grid()
        border = np.vstack([g[0], g[:, -1], g[-1, ::-1], g[::-1, 0]])
        tol = max(0.002 * float(np.linalg.norm(np.ptp(border, axis=0))), 1e-6)
        lo, hi = border.min(axis=0) - tol, border.max(axis=0) + tol
        a_, ab = border[:-1], np.diff(border, axis=0)
        ab2 = np.maximum(np.einsum("ij,ij->i", ab, ab), 1e-18)

        def on_border(pts):
            probe = pts[np.linspace(0, len(pts) - 1, min(len(pts), 9)).astype(int)]
            t = np.clip(np.einsum("pmj,mj->pm", probe[:, None] - a_[None], ab) / ab2[None], 0, 1)
            return np.linalg.norm(a_[None] + t[..., None] * ab[None] - probe[:, None], axis=2).min(axis=1).max() <= tol

        used = {x for r in resolved if r for x in r}
        cands = [c for s in self.strokes for c in s.curves
                 if c.id not in used and not c.paint and len(c.points) >= 2
                 and np.all(c.points.min(axis=0) >= lo) and np.all(c.points.max(axis=0) <= hi) and on_border(c.points)]

        def chains(a, b):
            """All chains of candidates from a to b (at most 4 pieces), each line with its direction."""
            found = []

            def walk(at, path):
                if path and np.linalg.norm(at - b) <= tol:
                    found.append(list(path))
                    return
                if len(path) >= 4 or len(found) > 1:
                    return
                for c in cands:
                    if any(c is p for p in path):
                        continue
                    for start, end in ((c.points[0], c.points[-1]), (c.points[-1], c.points[0])):
                        if np.linalg.norm(start - at) <= tol:
                            walk(end, path + [c])
            walk(a, [])
            return found

        def oriented(pos):
            i, flipped = surface.patch_order[pos]
            pts = self._chain_points(resolved[i])
            return None if pts is None else pts[::-1] if flipped else pts

        order, n, fixed = list(surface.patch_order), len(surface.patch_order), 0
        for pos, (i, _fl) in enumerate(order):
            if resolved[i] is not None:
                continue
            before, after = order[(pos - 1) % n][0], order[(pos + 1) % n][0]
            if resolved[before] is None or resolved[after] is None:
                continue  # neighboring side is missing too: start and end of the gap unknown
            pa, pb = oriented((pos - 1) % n), oriented((pos + 1) % n)
            if pa is None or pb is None:
                continue
            a, b = pa[-1], pb[0]
            found = chains(a, b)
            if len(found) != 1:
                continue
            chain = found[0]
            if len(chain) == 1:
                c = chain[0]
                new_id, flipped = c.id, bool(np.linalg.norm(c.points[0] - a) > np.linalg.norm(c.points[-1] - a))
            else:  # several pieces from a to b: refer to as a split line (_chain_points then starts from a)
                new_id, flipped = _new_id(), False
                self.split_map[new_id] = [c.id for c in chain]
            surface.patch_lines[i] = new_id
            order[pos] = (i, flipped)
            resolved[i] = [c.id for c in chain]
            used.update(resolved[i])
            cands = [c for c in cands if c.id not in used]
            fixed += 1
        if fixed:
            surface.patch_order = order
        return fixed

    def _tear(self, surface, curve, att):
        """Split a line that lies only partly on the loft at the boundary: the pieces on the loft
        deform along, the others stay put (with the last point before the boundary)."""
        owner = self.owner_of(curve)
        del surface.attached[curve.id]
        if owner is None:
            return
        on, pts, wid = att["on"], curve.points, curve.widths
        runs, start = [], 0
        for k in range(1, len(on) + 1):
            if k == len(on) or on[k] != on[start]:
                runs.append((start, k - 1, bool(on[start])))
                start = k
        g = surface.grid()
        pieces = []
        for s, e, is_on in runs:
            if is_on:
                idx = np.arange(s, e + 1)
            else:  # one point into the neighboring pieces: the tear stays at the old place
                idx = np.arange(max(s - 1, 0), min(e + 2, len(pts)))
            if len(idx) < 2:
                continue
            piece = inherit(Curve(pts[idx].copy(), surface.id if is_on else None, wid[idx].copy()), curve)
            if is_on:
                piece.points = loft.evaluate_grid(att["uv"][idx], g, surface.closed)
                surface.attached[piece.id] = {"uv": att["uv"][idx], "on": np.ones(len(idx), bool),
                                              "last": piece.points.tobytes()}
            pieces.append(piece)
        k = owner.curves.index(curve)
        owner.curves[k:k + 1] = pieces

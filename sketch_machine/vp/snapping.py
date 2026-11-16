"""Snapping: line ends, lines, directions."""
from .common import *  # noqa: F401,F403


ON_PLANE_REL = 1e-3  # point lies in a plane: closer than 0.1 % of its size


class SnapMixin:
        # --- Snapping while drawing ---
    def _surface_snap_points(self):
        """Points (ends, corners, inserted points) attached to the drawing surfaces (N,3) – only to these does the
        pen snap when drawing on surfaces and planes (as in free mode, but without the others). Plane: points in
        it, surface: points on it (also those of its neighbors at the shared border), mesh: points of the lines on it.
        Cached until _changed or until the drawing surface changes."""
        every = self._snap_points()
        surfaces = [x for x in self._drawing_surfaces() if x is not None]
        ids = tuple(id(x) for x in surfaces)
        cache = getattr(self, "_surface_points_cache", None)
        if cache is not None and cache[0] is every and cache[1] == ids:
            return cache[2]
        flat = [x for x in surfaces if not isinstance(x, MeshObject)]
        pts = every[self._on_drawing_surface(every, flat)] if flat and len(every) else np.zeros((0, 3))
        meshes = {x.id for x in surfaces if isinstance(x, MeshObject)}
        if meshes:
            on_mesh = [c.points[k] for c in self._visible_curves() if c.plane_id in meshes and not c.paint
                       for k in components.knots(c)]
            if on_mesh:
                pts = np.vstack([pts, np.array(on_mesh)])
        self._surface_points_cache = (every, ids, pts)
        return pts

    def _snap_reach(self, pos):
        """(Point, tolerance): where the pen lands on the drawing surface at pos, and how far a
        snap point may be from it in space. Being close on screen only is not enough – otherwise one
        snaps to lines far behind or below. (None, None): no restriction."""
        if self.multi_mode:
            ref = self._multi_samples([pos])[0][0]
        else:
            ref = self._surface_hit(pos)
        if ref is None:
            return None, None
        depth = (ref - self.cam.eye) @ -self.cam.back
        return ref, 2 * SNAP_PX * float(self._world_per_px(depth))

    def _end_snap(self, pos):
        """Point on the drawing surface (end, corner, inserted point, _surface_snap_points) within FREE_POINT_PX
        under the cursor or None – as in free mode the nearest on screen, on a tie the frontmost;
        only points that are also close to the pen position in space. Fast enough for every mouse move."""
        pts = self._surface_snap_points()
        if pos is None or not len(pts) or not self.ws.magnet:  # magnet off: draw freely
            return None
        screen, ok = self.project(pts)
        d = np.hypot(screen[:, 0] - pos.x(), screen[:, 1] - pos.y())
        d[~ok | np.isnan(d)] = np.inf
        if not (d < FREE_POINT_PX).any():
            return None
        ref, tol = self._snap_reach(pos)
        if ref is not None:
            d[np.linalg.norm(pts - ref, axis=1) > tol] = np.inf
        near = np.flatnonzero(d < FREE_POINT_PX)
        if not len(near):
            return None
        best = near[d[near] <= d[near].min() + TIE_SCREEN_PX]
        return pts[best[np.argmin((pts[best] - self.cam.eye) @ -self.cam.back)]].copy()

    def _on_drawing_surface(self, pts, surfaces=None):
        """bool per point: does it lie on a drawing surface (plane: in it; surface: on it)? When drawing, the
        pen only snaps there – not to lines in front, behind or crossing through. Without drawing surface (free) or on
        a mesh: no restriction. surfaces: instead of the current drawing surfaces."""
        pts = np.asarray(pts, float).reshape(-1, 3)
        if surfaces is None:
            surfaces = [x for x in self._drawing_surfaces() if x is not None]
        if not len(pts) or not surfaces or any(isinstance(x, MeshObject) for x in surfaces):
            return np.ones(len(pts), bool)
        out = np.zeros(len(pts), bool)
        for x in surfaces:
            if isinstance(x, Plane):
                tol = ON_PLANE_REL * max(x.size_u, x.size_v, 1e-9)
                out |= np.abs((pts - x.origin) @ x.normal) <= tol
            elif isinstance(x, SurfaceObject):
                out |= self._on_surface(x, pts)
        return out

    def _draw_snap(self, pos):
        """(Point, on_line): a nearby line end takes priority, otherwise a point on a nearby line."""
        if not self.ws.magnet:
            return None, False
        point = self._end_snap(pos)
        if point is not None:
            return point, False
        curve, point = self._curve_under(pos, SNAP_PX)
        if curve is None:
            return self._mirror_snap(pos), False  # mirror plane of the symmetry being drawn into
        ref, tol = self._snap_reach(pos)
        if ref is not None:
            # the point of the line that is nearest in space to the pen position on the drawing surface
            # – if a line is seen from the side (circle in front view), the point
            # under the cursor would be somewhere on it, not where it intersects the drawing plane
            point = _closest_on_polyline(curve.points, ref)
            if np.linalg.norm(point - ref) > tol:
                return None, False  # line is only close on screen, elsewhere in space
        # only lines that lie on the drawing surface: the piece at the snap point lies entirely on it (a line that
        # only pokes through does not count)
        i = int(np.argmin(np.linalg.norm(curve.points - point, axis=1)))
        piece = curve.points[max(i - 1, 0):i + 2]
        if not self._on_drawing_surface(np.vstack([piece, point[None]])).all():
            return self._mirror_snap(pos), False
        return point, True

    def _edge_lines(self, surface, visible=None):
        """The lines that really bound a surface on the outside (visible, without painting):
          - curve surface: its border curves; fill surface: its outline;
          - loft: first and last cross-section (ring: none), for an open sheet also the two lateral
            side lines – middle cross-sections and longitudinal lines lie inside (shape-giving, like grid lines).
        Other (older) surfaces: their lines without those drawn on them. visible: {id(line)} of the visible lines,
        if already known (for many surfaces in a row determine only once)."""
        sc = self.scene
        if visible is None:
            visible = {id(c) for c in self._visible_curves()}
        pieces = lambda ids: [c for cid in ids for sub in (sc.split_pieces(cid) or [])
                              if (c := sc.curve_by_id(sub)) is not None and id(c) in visible]
        if isinstance(surface, PatchSurface):
            return [c for c in sc.patch_border(surface) if id(c) in visible]
        if isinstance(surface, LoftSurface):
            if surface.wrap:
                return []
            out = []
            for src in (surface.sources[:1] + surface.sources[-1:] if len(surface.sources) > 1 else surface.sources):
                if src and src[0] == "lines":
                    out += pieces(src[1])
            if not surface.closed and surface.curves:
                m = len(surface.curves[0].points)
                out += pieces([cid for cid, col in surface.rails if col in (0, m - 1)])
            return out
        if type(surface) is SurfaceObject and surface.links:
            return pieces([i for cid, _ in surface.links for i in sc.link_ids(cid)])
        lines = [c for c in self._border_lines(surface) if c.plane_id != surface.id]
        return lines or self._border_lines(surface)

    def _border_lines(self, surface):
        """Lines that belong to a drawing surface (outline, cross-sections, side lines, border curves, those drawn
        on it) – visible, without painting."""
        owners = self._line_owners()
        return [c for c in self._visible_curves() if surface.id in owners.get(c.id, ()) or c.plane_id == surface.id]

    def _border_snap_hit(self, point, surface=None):
        """Nearest point on a border line of the surface within BORDER_SNAP: (point, line) or None."""
        surface = self.scene.active_mesh if surface is None else surface
        if not isinstance(surface, SurfaceObject):
            return None
        mesh = surface.fill_mesh()
        if mesh is None or not len(mesh[0]):
            return None
        tol = BORDER_SNAP * float(np.linalg.norm(np.ptp(mesh[0], axis=0)))
        best = None
        for c in self._edge_lines(surface):
            d, i, t = self.scene._closest_on(c, point)
            if d <= tol and (best is None or d < best[0]):
                best = (d, c.points[i] + t * (c.points[i + 1] - c.points[i]), c)
        return None if best is None else (best[1], best[2])

    def _off_surface(self, pos):
        """Is the cursor next to the active drawing surface (not on it)?"""
        return isinstance(self.scene.active_mesh, SurfaceObject) and not self.multi_mode and self._surface_hit(pos) is None

    def _border_reach_hit(self, pts, surface=None):
        """Stroke left the surface (surface, otherwise the active one) or came from outside: extend the end (last point
        of pts) in stroke direction up to the border line – even if the last hit is still some distance from the
        border. Without intersection: nearest border point nearby. Returns (point, border line) or None."""
        surface = self.scene.active_mesh if surface is None else surface
        if not isinstance(surface, SurfaceObject) or not len(pts):
            return None
        mesh = surface.fill_mesh()
        if mesh is None or not len(mesh[0]):
            return None
        size = float(np.linalg.norm(np.ptp(mesh[0], axis=0)))
        last = np.asarray(pts[-1], float)
        back = next((np.asarray(p, float) for p in reversed(pts[:-1])
                     if np.linalg.norm(last - np.asarray(p, float)) > BORDER_DIR * size), None)
        if back is None and len(pts) > 1:
            back = np.asarray(pts[0], float)
        if back is not None and np.linalg.norm(last - back) > 1e-9:
            d = (last - back) / np.linalg.norm(last - back)
            ray = types.SimpleNamespace(points=np.array([last - d * 0.002 * size, last + d * BORDER_REACH * size]))
            best = None
            for c in self._edge_lines(surface):  # meant to go beyond the border: the border line
                for pa, pb in network.crossings(ray, c, BORDER_HIT * size):
                    t = float((pa - last) @ d)
                    if best is None or t < best[0]:
                        best = (t, pb, c)
            if best is not None:
                return best[1], best[2]
            hit = self._border_reach_screen(last, d, surface, BORDER_REACH * size)
            if hit is not None:
                return hit
        return self._border_snap_hit(last, surface)

    def _border_reach_screen(self, last, d, surface, reach):
        """Like the extension in space, but on screen (curved surfaces: the straight direction in space runs
        over the border line). Returns (point on the border line, line) or None."""
        ray, ok = self.project(np.array([last, last + d * reach]))
        if not ok.all():
            return None
        a, b = ray[0], ray[1]
        best = None
        for c in self._edge_lines(surface):
            scr, vis = self.project(c.points)
            for i in np.flatnonzero(vis[:-1] & vis[1:]):
                p, q = scr[i], scr[i + 1]
                den = (b[0] - a[0]) * (q[1] - p[1]) - (b[1] - a[1]) * (q[0] - p[0])
                if abs(den) < 1e-12:
                    continue
                t = ((p[0] - a[0]) * (q[1] - p[1]) - (p[1] - a[1]) * (q[0] - p[0])) / den
                u = ((p[0] - a[0]) * (b[1] - a[1]) - (p[1] - a[1]) * (b[0] - a[0])) / den
                if -0.02 <= t <= 1 and 0 <= u <= 1 and (best is None or t < best[0]):
                    best = (t, c.points[i] + u * (c.points[i + 1] - c.points[i]), c)
        return None if best is None else (best[1], best[2])

    def _stroke_kinds(self, runs, pos):
        """Per piece (start, end): "hit" (on the surface), "switch" (change to the neighboring surface), "gap" (the
        stroke came from outside or left the surface). That is all the connection rule needs to know about the
        input path."""
        kinds = None
        if self.multi_mode or self._shape is not None and self._shape["frame"]["project"]:
            kinds = self._finished_kinds()
        if kinds is None or len(kinds) != len(runs):
            kinds = [("hit", "hit")] * len(runs)
            if self.scene.active_mesh is not None and not self.multi_mode:  # on a mesh / a surface
                start = "gap" if getattr(self, "_lazy_start", False) else "hit"
                end = "gap" if self._draw_ended or self._off_surface(pos) else "hit"
                kinds[0] = (start, kinds[0][1])
                kinds[-1] = (kinds[-1][0], end)
        return list(kinds)

    def _cursor_point(self, pos):
        """World point under the cursor on the drawing surfaces (smoothing: the tip lags behind the cursor)."""
        if self.multi_mode:
            return self._multi_samples([pos])[0][0]
        if self.scene.active_mesh is not None:
            return self._surface_hit(pos)
        return self._ray_plane(pos, self.scene.active_plane)[0]

    def _resolve_stroke(self, curves, kinds, hint=None):
        """The one connection rule after every stroke – on the finished geometry, the same as it was created:
          1. Pieces of the same stroke that meet at a surface change: shared point on the
             border line that separates them.
          2. Ends where the stroke left the surface or came from outside: extended to the border line.
          3. All other ends (magnet on): if a point (END_SNAP_PX) or a visible line (SNAP_PX, measured in space
             at the depth of the end) is that close, they end exactly there – as a shared point or T-junction. hint:
             with smoothing the place under the cursor (where the stroke wanted to go).
          4. Crossings with lines of the same surface/plane: shared points; strokes over a shared border line
             are split there."""
        if not curves:
            return
        sc = self.scene
        kinds = list(kinds) if kinds and len(kinds) == len(curves) else [("hit", "hit")] * len(curves)
        done = set()  # (line, end) already connected
        end_index = lambda c, side: len(c.points) - 1 if side else 0

        def attach(c, side, x, line):
            """Put the end of c on line (a node there) and connect explicitly – with everything already
            attached to that end."""
            k = end_index(c, side)
            network.move_point(sc, c, k, x)
            if line is not None and line is not c:
                j = network.knot_at(line, x)
                network.join(sc, line, j, c, k)
            done.add((id(c), side))

        wpp = lambda p: float(self._world_per_px(float((np.asarray(p) - self.cam.eye) @ -self.cam.back)))
        for i in range(len(curves) - 1):  # 1. transitions within the stroke
            a, b = curves[i], curves[i + 1]
            near = float(np.linalg.norm(a.points[-1] - b.points[0])) < 2 * SNAP_PX * wpp(a.points[-1])
            # change to the neighboring surface – even if exactly at the shared border line a sample point
            # fell into the void (hairline gap between the surface nets): consecutive pieces of different surfaces, close
            if (kinds[i][1] == "switch" and kinds[i + 1][0] == "switch") or \
                    (kinds[i][1] == "gap" and kinds[i + 1][0] == "gap" and near and a.plane_id != b.plane_id):
                self._join_transition(a, 1, b, 0, attach, done)
        loose = lambda c, k: network.degree(network.refs_by_pid(sc).get(network.pid_of(c, k), [])) < 2
        ends = [(c, side) for c in curves for side in (0, 1)
                if (id(c), side) not in done and loose(c, end_index(c, side))]
        for n, (a, sa) in enumerate(ends):  # 1b. loose ends of different surfaces that meet (cleanup)
            for b, sb in ends[n + 1:]:
                if a is b or a.plane_id == b.plane_id or (id(a), sa) in done or (id(b), sb) in done:
                    continue
                pa, pb = a.points[end_index(a, sa)], b.points[end_index(b, sb)]
                if float(np.linalg.norm(pa - pb)) < 2 * SNAP_PX * wpp(pa):
                    self._join_transition(a, sa, b, sb, attach, done)
        for n, (c, (start, end)) in enumerate(zip(curves, kinds)):  # 2. borders
            for side, kind in ((0, start), (1, end)):
                if (id(c), side) in done:
                    continue
                partner_missing = kind == "switch"  # piece on the neighboring surface was too short: as if left
                if kind != "gap" and not partner_missing:
                    continue
                pts = list(c.points) if side else list(c.points[::-1])
                hit = self._border_reach_hit(pts, self._surface_at(pts[-1], c))
                if hit is not None:
                    attach(c, side, hit[0], hit[1])
        for n, c in enumerate(curves):  # 3. nearby points and lines (only with magnet)
            if not self.ws.magnet:
                break
            for side in (0, 1):
                if (id(c), side) in done:
                    continue
                k = end_index(c, side)
                found = self._end_target(c, k)
                if found is None and hint is not None and side and n == len(curves) - 1:
                    found = self._end_target(c, k, at=hint)
                if found is None:  # nothing in reach: mirror plane of a symmetry (the seam closes)
                    on_mirror = self._mirror_snap_at(c.points[k])
                    if on_mirror is not None:
                        attach(c, side, on_mirror, None)
                if found is not None:
                    # own start (stroke closes itself): counts, no pushing onto a neighboring line (harbor test:
                    # rectangle corner slid onto the neighboring line after closing)
                    partner_loose = found[2] is not c and not found[1] and loose(found[2], min(
                        components.knots(found[2]), key=lambda j: np.linalg.norm(found[2].points[j] - found[0])))
                    attach(c, side, found[0], found[2])
                    if partner_loose:  # two loose ends: if a line is in reach, the point goes onto it
                        line = self._end_target(c, k, exclude=(found[2],), lines_only=True)
                        if line is not None:
                            attach(c, side, line[0], line[2])
        network.sync(sc)
        self._connect_new_crossings(curves)  # 4.

    def _join_transition(self, a, sa, b, sb, attach, done):
        """End sa of a and end sb of b (different surfaces) meet: shared point on the border line
        between the surfaces (otherwise in the middle)."""
        pa = list(a.points) if sa else list(a.points[::-1])
        pb = list(b.points[::-1]) if sb else list(b.points)
        sfa, sfb = self.scene.object_by_id(a.plane_id), self.scene.object_by_id(b.plane_id)
        x, on_line = self._transition_point(pa, sfa, pb, sfb)
        line = None
        if on_line:
            lines = []
            for srf in (sfa, sfb):
                if isinstance(srf, SurfaceObject):
                    lines += self._edge_lines(srf)
            line = min(lines, key=lambda c: self.scene._closest_on(c, x)[0]) if lines else None
        attach(a, sa, x, line)
        attach(b, sb, x, line)
        if line is None:
            ka, kb = (len(a.points) - 1 if sa else 0), (len(b.points) - 1 if sb else 0)
            network.join(self.scene, a, ka, b, kb)

    def _surface_at(self, point, curve):
        """The drawing surface the point lies on (a stroke may have continued onto the neighboring surface);
        otherwise the surface of the line."""
        own = self.scene.object_by_id(curve.plane_id)
        best = (None, np.inf)
        for s in self.scene.surfaces:
            if not isinstance(s, SurfaceObject) or self.scene.is_hidden(s):
                continue
            mesh = s.fill_mesh()
            if mesh is None or not len(mesh[0]):
                continue
            verts, tris = mesh[0], mesh[1]
            size = float(np.linalg.norm(np.ptp(verts, axis=0)))
            tol = 0.01 * size
            if np.any(point < verts.min(axis=0) - tol) or np.any(point > verts.max(axis=0) + tol):
                continue
            d = float(_dist_to_triangles_fast(np.asarray(point, float)[None], verts[tris])[0])
            if d < tol and d < best[1]:
                best = (s, d)
        return best[0] if best[0] is not None else own

    def _end_target(self, curve, k, at=None, exclude=(), lines_only=False):
        """(Point, on_line) for end k of curve: an existing point within END_SNAP_PX, otherwise the nearest
        point of a visible line within SNAP_PX (in space, at the depth of the end); otherwise None. at: search from this
        place instead of from the end (smoothing: cursor)."""
        p = np.asarray(curve.points[k] if at is None else at, float)
        depth = float((p - self.cam.eye) @ -self.cam.back)
        wpp = float(self._world_per_px(depth))
        tol_point, tol_line = END_SNAP_PX * wpp, SNAP_PX * wpp
        length = float(np.linalg.norm(np.diff(curve.points, axis=0), axis=1).sum())
        best_point, best_line, best_own = None, None, None
        for c in self._visible_curves():
            if c.paint or len(c.points) < 2 or any(c is x for x in exclude):
                continue
            lo, hi = c.points.min(axis=0) - tol_line, c.points.max(axis=0) + tol_line
            if np.any(p < lo) or np.any(p > hi):
                continue
            own = c is curve
            for j in components.knots(c):
                if own and (j == k or abs(j - k) < len(c.points) // 2):
                    continue  # own end only with the other end (stroke closes itself)
                d = float(np.linalg.norm(c.points[j] - p))
                if own:  # closing: only at the other end, close by and clearly shorter than the stroke
                    if j in (0, len(c.points) - 1) and d < tol_point and d < 0.25 * length and (best_own is None or d < best_own[0]):
                        best_own = (d, c.points[j].copy(), c)
                    continue
                if d < tol_point and (best_point is None or d < best_point[0]):
                    best_point = (d, c.points[j].copy(), c)
            if own:
                continue
            d, i, t = self.scene._closest_on(c, p)
            if d < tol_line and (best_line is None or d < best_line[0]):
                best_line = (d, c.points[i] + t * (c.points[i + 1] - c.points[i]), c)
        if best_own is not None and not lines_only:  # the own start takes priority over foreign points and lines
            return best_own[1], False, best_own[2]
        if best_point is not None and not lines_only:
            return best_point[1], False, best_point[2]
        if best_line is not None:
            return best_line[1], True, best_line[2]
        return None

    def _transition_point(self, pa, sa, pb, sb):
        """(Point, on_line): where the stroke changes from surface sa to sb – intersection of the transition with a border line
        of the two surfaces, otherwise the middle between the pieces."""
        a, b = np.asarray(pa[-1], float), np.asarray(pb[0], float)
        mid = (a + b) / 2
        d = b - a
        length = float(np.linalg.norm(d))
        lines = []
        for s in (sa, sb):
            if isinstance(s, SurfaceObject):
                lines += [c for c in self._edge_lines(s) if not any(c is x for x in lines)]
        if lines and length > 1e-12:
            sizes = [float(np.linalg.norm(np.ptp(s.fill_mesh()[0], axis=0))) for s in (sa, sb)
                     if isinstance(s, SurfaceObject) and s.fill_mesh() is not None]
            size = max(sizes) if sizes else length
            u = d / length
            ray = types.SimpleNamespace(points=np.array([a - u * 0.01 * size, b + u * 0.01 * size]))
            best = None
            for c in lines:
                for p_ray, p_line in network.crossings(ray, c, max(BORDER_HIT * size, 0.6 * length)):
                    dist = float(np.linalg.norm(p_ray - mid))
                    if best is None or dist < best[0]:
                        best = (dist, p_line)
            if best is not None:
                return np.asarray(best[1], float), True
        return mid, False

    def _connect_new_crossings(self, curves):
        """Curve network: new lines get shared points where they cross lines on the same drawing surface or
        plane (they really intersect there; only apparently crossing lines stay untouched)."""
        made = self._connect_crossings_of(curves)
        pieces = self._split_over_borders(curves)
        if pieces:  # pieces on the neighboring surface: their lines cross too
            made += self._connect_crossings_of(pieces)
        return made

    def _connect_crossings_of(self, curves):
        made = 0
        for c in curves:
            if c.plane_id is None or c.paint:
                continue
            surface = self.scene.object_by_id(c.plane_id)
            others = (self._border_lines(surface) if isinstance(surface, SurfaceObject) else
                      [o for o in self._visible_curves() if o.plane_id == c.plane_id])
            for o in others:
                if o is not c:
                    radius = SNAP_PX * float(self._world_per_px(float((c.points.mean(axis=0) - self.cam.eye) @ -self.cam.back)))
                    made += network.connect_crossings(self.scene, c, [o], self._cross_tol(c, o), radius)
        return made

    def _split_over_borders(self, curves):
        """If a stroke runs over a border line of its surface (curve as well as fill surface), it is split at every
        border point – each piece belongs to the surface it lies on (a line never runs beyond the border of its surface
        and never hangs on it in the middle). A piece on another surface or next to it that goes less than
        BORDER_SNAP of the surface beyond the edge (dragged beyond the border or slipped briefly, also in the middle of the
        stroke) is dropped."""
        sc = self.scene
        moved = []  # pieces that now belong to another surface
        hosts = [s for s in sc.surfaces if self._has_border(s)]
        if not hosts:
            return moved
        network.sync(sc)
        border_of = {s.id: {pid for c in self._surface_border(s) for pid in (c.pids or {}).values()} for s in hosts}
        for c in curves:
            surf = sc.object_by_id(c.plane_id)
            owner = sc.owner_of(c)
            if surf is None or surf.id not in border_of or c.paint or owner is None:
                continue
            self._cut_where_host_changes(c, surf, hosts)
            network.sync(sc)  # new border points count too
            border_of[surf.id] = {pid for b in self._surface_border(surf) for pid in (b.pids or {}).values()}
            n = len(c.points)
            cuts = sorted(k for k, pid in (c.pids or {}).items() if 0 < k < n - 1 and pid in border_of[surf.id])
            if not cuts:
                continue
            pieces = components.split_at(c, cuts)
            own = self._surface_size(surf)
            keep = []
            for piece, _, _ in pieces:
                mid = piece.points[len(piece.points) // 2]
                host = surf if self._on_surface(surf, mid[None])[0] else self._host_of(hosts, mid)
                if host is not surf:
                    # how far does the piece go beyond the edge? (not its length – driving along the edge does not count)
                    lines = self._surface_border(surf)
                    reach = max(min(sc._closest_on(b, p)[0] for b in lines) for p in piece.points) if lines else np.inf
                    if reach < BORDER_SNAP * own:
                        continue  # dragged beyond the border or slipped briefly
                piece.plane_id = host.id if host is not None else None
                keep.append(piece)
            k = next(i for i, cc in enumerate(owner.curves) if cc is c)
            owner.curves[k:k + 1] = keep
            sc.split_map[c.id] = [p.id for p in keep]
            moved += [p for p in keep if p.plane_id != c.plane_id]
        return moved

    def _cut_where_host_changes(self, c, surf, hosts):
        """Where the stroke changes from its surface to another (or into the void), it gets a shared point
        with the border line it crosses – exactly on it, the border line stays as it is (the new stroke comes to
        it). This is determined per stroke point (which surface does it lie on?), not via crossings: a short
        slip over the edge and back yields two changes, even if they lie close together."""
        sc = self.scene
        on = self._on_surface(surf, c.points)
        border = self._surface_border(surf)
        if not border:
            return
        changes = [i for i in range(len(on) - 1) if on[i] != on[i + 1]]
        network.sync(sc)
        border_pids = {pid for line in border for pid in (line.pids or {}).values()}
        arc = np.concatenate([[0], np.cumsum(np.linalg.norm(np.diff(c.points, axis=0), axis=1))])
        reach = BORDER_SNAP * self._surface_size(surf)
        have = [arc[k] for k, pid in (c.pids or {}).items() if pid in border_pids]
        skip = set()  # per existing border point (crossing) at most one change, the next: no second point next to it
        for x in have:
            near = [i for i in changes if abs(arc[i] - x) < reach and i not in skip]
            if near:
                skip.add(min(near, key=lambda i: abs(arc[i] - x)))
        for i in reversed(changes):  # from the back: inserted points do not shift the indices before them
            if i in skip:
                continue
            a, b = c.points[i], c.points[i + 1]
            best = None
            for line in border:
                for t in np.linspace(0.0, 1.0, 9):
                    q = a + t * (b - a)
                    d, j, s = sc._closest_on(line, q)
                    if best is None or d < best[0]:
                        best = (d, line, j, s, t)
            d, line, j, s, t = best
            # place on the border line nearest to the stroke piece; the stroke gets a point there
            q = line.points[j] + s * (line.points[j + 1] - line.points[j])
            if float(np.linalg.norm(q - (a + t * (b - a)))) > 0.05 * self._surface_size(surf):
                continue  # no border nearby (gap in the hit, no real change)
            network.sync(sc)
            kb = network.knot_at(line, q, i=j, t=s, keep=True)
            q = line.points[kb]
            k = components.insert_point(c, i, float(np.clip(t, 0.0, 1.0)))  # also on an existing point: node
            if not 0 < k < len(c.points) - 1:
                continue
            pts = c.points.copy()
            pts[k] = q
            c.points = pts
            components.knots(c)
            network.sync(sc)
            network.join(sc, line, kb, c, k)

    def _on_surface(self, surf, pts):
        """Does every point lie practically on the surface (closer than 0.3 % of its size)? A stroke on it lies exactly on
        it; a piece that slipped over the edge onto the neighboring surface does not – even close to the edge."""
        mesh = surf.fill_mesh()
        pts = np.asarray(pts, float).reshape(-1, 3)
        if mesh is None or not len(mesh[0]):
            return np.zeros(len(pts), bool)
        # remember the result per point as long as the surface has the same shape (net arrays are replaced on changes,
        # never changed in place): otherwise after every stroke EVERY point of the scene has to be checked anew against the triangle net
        # – harbor test 09.11.: 1,876 points, 2.7 s in the first frame after every change
        memos = self.__dict__.setdefault("_on_surface_memo", {})
        # remembered by the net, not by the surface object: after undo the object is new, the net the same
        memo = memos.get(id(mesh[0]))
        if memo is None or memo[0] is not mesh[0] or memo[1] is not mesh[1]:
            tol = 0.003 * self._surface_size(surf)
            lo, hi = mesh[0].min(axis=0) - tol, mesh[0].max(axis=0) + tol
            from scipy.spatial import cKDTree
            v, t = mesh[0], mesh[1]
            edge = max(float(np.linalg.norm(v[t[:, a]] - v[t[:, b]], axis=1).max()) for a, b in ((0, 1), (1, 2), (2, 0)))                 if len(t) else 0.0
            cent = v[t].mean(axis=1) if len(t) else np.zeros((0, 3))
            memo = (v, t, surf, tol, lo, hi, {}, cKDTree(v), tol + edge, cKDTree(cent) if len(t) else None)
            if len(memos) > 64:
                memos.clear()
            memos[id(mesh[0])] = memo
        _v, _t, _s, tol, lo, hi, known, tree, reach, ctree = memo
        if len(known) > 200000:
            known.clear()
        out = np.zeros(len(pts), bool)
        cand = np.flatnonzero(np.all((pts >= lo) & (pts <= hi), axis=1))  # outside the outline box: never
        if len(cand):  # farther than (tolerance + longest triangle edge) from every corner: surely not on the surface
            near, _ = tree.query(pts[cand], distance_upper_bound=reach)
            cand = cand[np.isfinite(near)]
        for i in cand:
            key = pts[i].tobytes()
            hit = known.get(key)
            if hit is None:
                near_tris = ctree.query_ball_point(pts[i], reach)  # only check triangles in reach
                hit = known[key] = bool(near_tris) and _point_mesh_distance(pts[i], mesh[0], mesh[1][near_tris]) < tol
            out[i] = hit
        return out

    @staticmethod
    def _has_border(s):
        if isinstance(s, PatchSurface):
            return bool(s.patch_lines) and len(s.curves) >= 2
        return type(s) is SurfaceObject and bool(s.links) and s.rest is not None

    def _surface_border(self, s):
        """Border lines of a curve or fill surface."""
        if isinstance(s, PatchSurface):
            return self.scene.patch_border(s)
        return [c for cid, _ in s.links for i in self.scene.link_ids(cid) if (c := self.scene.curve_by_id(i)) is not None]

    @staticmethod
    def _surface_size(s):
        mesh = s.fill_mesh()
        pts = mesh[0] if mesh is not None and len(mesh[0]) else np.vstack([c.points for c in s.curves])
        return float(np.linalg.norm(np.ptp(pts, axis=0)))

    @staticmethod
    def _host_of(hosts, point):
        """The surface (curve or fill surface) the point lies on, or None: the nearest, closer than 1 % of its size."""
        best = (None, np.inf)
        for s in hosts:
            mesh = s.fill_mesh()
            if mesh is None or not len(mesh[0]):
                continue
            verts, tris = mesh[0], mesh[1]
            lo, hi = verts.min(axis=0), verts.max(axis=0)
            tol = 0.01 * float(np.linalg.norm(hi - lo))
            if np.any(point < lo - tol) or np.any(point > hi + tol):
                continue
            d = _point_mesh_distance(point, verts, tris)
            if d < tol and d < best[1]:
                best = (s, d)
        return best[0]

    @staticmethod
    def _cross_tol(a, b):
        """Lines cross if they visibly touch: midpoints closer than half the mean stroke width."""
        wa = float(np.mean(a.widths)) if len(a.widths) else 0.0
        wb = float(np.mean(b.widths)) if len(b.widths) else 0.0
        return max(0.25 * (wa + wb), 1e-5)

    def _connect_at(self, point):
        """Deliberately snapped (V when moving): whatever lies exactly at point becomes a point; if only a
        line lies there (line middle), it gets a shared point."""
        self.scene.insert_knot_at(point, tolerance=1e-5)  # merges whatever lies there
        self._changed()

    def _snap_dirs(self, normal):
        """Reference directions for snapped straight lines in a plane: (0°, 90°). 0° is the direction in
        the plane that points vertically up on screen (exact in orthographic), 90° is in
        the plane perpendicular to it, to the right – this gives vertical and horizontal lines."""
        c = self.cam
        up = np.cross(normal, c.right)
        if np.linalg.norm(up) < 1e-6:  # plane stands edge-on to the camera
            up = c.up - (c.up @ normal) * normal
        up = up / np.linalg.norm(up)
        if up @ c.up < 0:
            up = -up
        side = np.cross(up, normal)
        if side @ c.right < 0:
            side = -side
        return up, side

    def _snap_line_end(self, start, end, normal):
        """Rotate the end of a straight line in the plane (normal) in snap_angle steps around the start."""
        up, side = self._snap_dirs(normal)
        v = end - start
        v = v - (v @ normal) * normal
        length = float(np.linalg.norm(v))
        if length < 1e-12:
            return end
        step = math.radians(self.ws.snap_angle)
        angle = round(math.atan2(v @ side, v @ up) / step) * step
        return start + length * (math.cos(angle) * up + math.sin(angle) * side)

    def _snap_screen(self, pos):
        """Like _snap_line_end, but on screen (meshes, multi mode): 0° = vertically up."""
        d = pos - self._press_pos
        length = math.hypot(d.x(), d.y())
        if length < 1e-9:
            return pos
        step = math.radians(self.ws.snap_angle)
        angle = round(math.atan2(d.x(), -d.y()) / step) * step
        return self._press_pos + QPointF(math.sin(angle), -math.cos(angle)) * length


def _point_mesh_distance(p, verts, tris):
    """Smallest distance of the point p to the triangle net (inside perpendicular, otherwise to the nearest edge)."""
    a, b, c = verts[tris[:, 0]], verts[tris[:, 1]], verts[tris[:, 2]]
    n = np.cross(b - a, c - a)
    nn = np.maximum(np.einsum("ij,ij->i", n, n), 1e-18)
    dot = np.einsum("ij,ij->i", p - a, n)
    q = p - n * (dot / nn)[:, None]
    w0 = np.einsum("ij,ij->i", np.cross(c - b, q - b), n) / nn
    w1 = np.einsum("ij,ij->i", np.cross(a - c, q - c), n) / nn
    inside = (w0 >= 0) & (w1 >= 0) & (1 - w0 - w1 >= 0)
    d = np.where(inside, np.abs(dot) / np.sqrt(nn), np.inf)
    for x, y in ((a, b), (b, c), (c, a)):
        xy = y - x
        t = np.clip(np.einsum("ij,ij->i", p - x, xy) / np.maximum(np.einsum("ij,ij->i", xy, xy), 1e-18), 0, 1)
        d = np.minimum(d, np.linalg.norm(x + xy * t[:, None] - p, axis=1))
    return float(d.min()) if len(d) else np.inf

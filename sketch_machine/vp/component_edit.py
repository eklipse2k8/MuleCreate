"""Edit mode points/edges: find components, insert, convert, bevel."""
from .common import *  # noqa: F401,F403
from ..i18n import tr


class ComponentEditMixin:
    # --- Components: point (1) / edge (2) / surface (3) in selection mode ---
    def set_component(self, comp):
        """Switch selection mode; the selection is converted (edge -> its points, points -> edges
        with both ends selected, surface -> its lines), as in Houdini."""
        if comp == self.ws.component:
            return
        self._convert_selection(comp)
        self.ws.component = comp
        self._select_hover = None
        self.notify(tr("Edit: {0} (1 Punkte · 2 Kanten · 3 Flächen)").format(COMPONENT_NAMES[comp]))
        self.toggles_changed.emit()
        self._changed()

    def _line_of(self, ref):
        return edges.ref_to_curve(self.scene, ("line", ref[1], ref[2]))

    def _valid_points(self):
        out = []
        for r in self.point_selection:
            c = self._line_of(r)
            if c is not None and not c.paint and r[3] in components.knots(c):
                out.append((r, c))
        return out

    def _valid_segs(self):
        out = []
        for r in self.seg_selection:
            c = self._line_of(r)
            if c is not None and not c.paint and (r[3], r[4]) in components.segments(c):
                out.append((r, c))
        return out

    def _point_pos(self, ref):
        c = self._line_of(ref)
        return c.points[ref[3]] if c is not None and ref[3] < len(c.points) else None

    def _unique_points(self, refs):
        """Point references without duplicates (welded points at the same place count once)."""
        out, seen = [], []
        for r in dict.fromkeys(refs):
            q = self._point_pos(r)
            if q is None or any(np.linalg.norm(q - s) < components.WELD_TOL for s in seen):
                continue
            out.append(r)
            seen.append(q)
        return out

    def _active_strokes(self):
        """ids of the line objects whose points are shown: the active one, the selected ones and everything under selected
        nulls. Empty: none active (then all).
        Whoever has selected several objects and then clicks a point loses the object selection that way - the points of the
        other objects stay anyway (remembered set ws.edit_set): it holds until objects are selected again
        (new set), the active object no longer belongs to it or edit mode is left (harbor test 10.11.: after
        the first point only the points of the most recently active object were selectable)."""
        sc = self.scene
        active = {sc.active_stroke.id} if sc.active_stroke is not None and sc.active_stroke in sc.strokes else set()
        chosen = set()
        for i in self.selection:
            obj = sc.object_by_id(i)
            found = sc.descendants(obj) if isinstance(obj, NullObject) else [obj]
            chosen |= {o.id for o in found if isinstance(o, StrokeObject) and not isinstance(o, SurfaceObject)}
        kept = getattr(self.ws, "edit_set", frozenset())
        if chosen:
            kept = self.ws.edit_set = frozenset(chosen | active)
        elif kept and (not self.select_mode or not active or not active <= kept):
            kept = self.ws.edit_set = frozenset()
        out = active | chosen | kept
        # objects of selected points, sub-edges and edges: their points never vanish from under the selection
        out |= {r[1] for r in (*self.point_selection, *self.seg_selection, *self.edge_selection)} if out else set()
        live = {st.id for st in sc.strokes}
        return frozenset(i for i in out if i in live)

    def _knot_list(self):
        """[(ref, line, node)] of all points (line ends, corners, inserted points)."""
        active = self._active_strokes()
        key = (id(self.scene), self.scene.revision, len(self.scene.curves), tuple(self.ws.layers_visible.values()),
               id(getattr(self.scene, "_net_sync", None)), active)  # curve net reconciled anew: nodes may be new
        if self._knot_cache is None or self._knot_cache[0] != key:
            out = []
            for st in self.scene.strokes:
                if active and st.id not in active:  # only the points of the active object (clear, structures the scene)
                    continue
                for c in st.curves:
                    if len(c.points) >= 2 and not c.paint and self._curve_shown(st, c):  # painting: no points
                        ks = components.knots(c)
                        if components.is_closed(c.points):
                            ks = ks[:-1]  # seam only once
                        out += [(("pt", st.id, c.id, k), c, k) for k in ks]
            self._knot_cache = (key, out)
        return self._knot_cache[1]

    def _point_under(self, pos, tolerance=POINT_PX):
        """Point reference under the cursor (not clearly behind a drawing surface), otherwise None."""
        entries = self._knot_list()
        if not entries:
            return None
        pts = np.array([c.points[k] for _, c, k in entries])
        screen, ok = self.project(pts)
        d = np.hypot(screen[:, 0] - pos.x(), screen[:, 1] - pos.y())
        d[~ok | np.isnan(d)] = np.inf
        near = np.flatnonzero(d < tolerance)
        if not len(near):
            return None
        behind = self._behind_surface(pos)(pts[near])
        near = near[~behind] if (~behind).any() else near
        return entries[int(near[np.argmin(d[near])])][0]

    def _edge_component_under(self, pos):
        """Edge under the cursor: the whole line or - if it has corners - the piece between two points."""
        hit = self._edge_under(pos, visible=True)
        if hit is None:
            return None
        c = edges.ref_to_curve(self.scene, hit[0])
        if c is None:
            return None
        parts = components.segments(c)
        if len(parts) <= 1:
            return hit[0]
        _, i, _ = self.scene._closest_on(c, hit[2])
        a, b = components.segment_of(c, i)
        return ("seg", hit[0][1], hit[0][2], a, b)

    def _component_hover(self, pos):
        comp = self.ws.component
        if comp == "point":
            ref = self._point_under(pos)
        elif comp == "edge":
            ref = self._edge_component_under(pos)
        else:
            return None
        return (ref, None) if ref is not None else None

    def _aid_under(self, pos):
        """Plane or mesh under the cursor (drawing surfaces belong in surface mode)."""
        obj = self._surface_under(pos)[0]
        return None if isinstance(obj, SurfaceObject) else obj

    def _component_click(self, pos, how):
        comp = self.ws.component
        null = self._null_under(pos)  # axis cross of a null: clickable in every mode (like an object)
        if null is not None:
            return self._select_click(null, how)
        if comp == "point":
            ref = self._point_under(pos)
            if ref is None and how == "remove" and self._edge_under(pos) is not None:
                return self._insert_point(pos)  # Ctrl + click on a line: insert point
            if ref is not None:
                return self._apply_selection((), (), how, pts=[ref])
            return self._select_click(self._instance_line_under(pos) or self._aid_under(pos), how)
        if comp == "edge":
            ref = self._edge_component_under(pos)
            if ref is not None and ref[0] == "seg":
                return self._apply_selection((), (), how, segs=[ref])
            if ref is not None:
                return self._select_edge_click(ref, how)
            return self._select_click(self._instance_line_under(pos) or self._aid_under(pos), how)
        # Surfaces: drawing surfaces, planes, meshes; a copy in front (symmetry, array) selects its generator
        self._select_click(self._instance_surface_under(pos) or self._instance_line_under(pos)
                           or self._surface_under(pos)[0], how)

    def _insert_point(self, pos):
        """Ctrl + click in point mode: insert a point on the line under the cursor (and select it)."""
        hit = self._edge_under(pos)
        c = edges.ref_to_curve(self.scene, hit[0]) if hit else None
        if c is None:
            return
        self.scene.checkpoint()
        _, i, t = self.scene._closest_on(c, hit[2])
        k = components.insert_point(c, i, t)
        # remembered pivot no longer applies: the point numbers have shifted, the new point often has the same
        # number as the previously selected one - the gizmo then stayed there (harbor test 09.11.)
        self.ws.selection_pivot = None
        self.ws.target_cache = (None, None)
        self._apply_selection((), (), "replace", pts=[("pt", hit[0][1], hit[0][2], k)])
        self.notify(tr("Punkt eingefügt – verschieben, abrunden (Strg+B) …"))

    def _points_in_rect(self, rect):
        """Visible points in the selection rectangle (occluded ones only in X-ray mode)."""
        entries = self._knot_list()
        if not entries:
            return []
        pts = np.array([c.points[k] for _, c, k in entries])
        screen, ok = self.project(pts)
        inside = ok & (screen[:, 0] >= rect.left()) & (screen[:, 0] <= rect.right()) & \
            (screen[:, 1] >= rect.top()) & (screen[:, 1] <= rect.bottom())
        idx = np.flatnonzero(inside)
        if not len(idx):
            return []
        if not self.xray:
            positions = [QPointF(*screen[i]) for i in idx]
            keep = []
            for i, q, (mesh, _, m_dist) in zip(idx, positions, self._mesh_samples(positions, exact=False)):
                origin, d = self.ray(q)
                if mesh is None or m_dist >= (pts[i] - origin) @ d - OCCLUDE_TOL * self.cam.dist:
                    keep.append(i)
            idx = keep
        return [entries[i][0] for i in idx]

    def _convert_selection(self, comp):
        """Convert the selection to another mode (see set_component)."""
        # frozen helper surfaces stay selected as a whole (without their lines)
        surfaces = [o for o in self.selected_objects if isinstance(o, SurfaceObject) and o.frozen is None]
        if comp == "face":  # points drop out; lines, edges and surfaces stay
            self.point_selection = []
            # ... and every surface whose describing lines are ALL selected is added (recording 10.11. 22:10:
            # select all lines of an object, go to surface mode - the surfaces should come along for duplicating)
            chosen = {r[2] for r in self.edge_selection if r[0] == "line"}
            if chosen:
                have, more = set(self.selection), []
                for f in self.scene.surfaces:
                    if f.id in have or f.frozen is not None or f.aid or self.scene.is_hidden(f):
                        continue
                    ids = self.scene.defining_line_ids(f)
                    if ids and all(i in chosen for i in ids):
                        more.append(f.id)
                if more:
                    self.selection = list(self.selection) + more
            return
        lines = [edges.ref_to_curve(self.scene, r) for r in self.edge_selection]
        refs = [r for r, c in zip(self.edge_selection, lines) if c is not None]
        for s in surfaces:  # surface -> its lines
            refs += [r for r in (edges.curve_to_ref(self.scene, c) for c in self._lines_on_surface(s)) if r is not None]
        refs = list(dict.fromkeys(refs))
        self.selection = [i for i in self.selection if not any(i == s.id for s in surfaces)]
        if comp == "point":
            pts = list(self.point_selection)
            for r in refs:
                c = edges.ref_to_curve(self.scene, r)
                if c is not None and not c.paint:  # painting has no points
                    pts += [("pt", r[1], r[2], k) for k in components.knots(c)]
            pts += [("pt", r[1], r[2], k) for r, _ in self._valid_segs() for k in (r[3], r[4])]
            self.point_selection = self._unique_points(pts)
            self.edge_selection, self.seg_selection = [], []
            return
        # -> edges: from points the edges whose two ends are both selected
        segs = list(self.seg_selection)
        if self.point_selection:
            index = components.KnotIndex(self.scene)
            chosen = set()
            for r in self.point_selection:
                q = self._point_pos(r)
                if q is not None:
                    chosen |= {(id(c), k) for _, c, k in index.at(q)}
            for st in self.scene.strokes:
                for c in st.curves:
                    if len(c.points) < 2 or c.paint:
                        continue
                    n = len(c.points)
                    closed = components.is_closed(c.points)
                    has = lambda k: (id(c), k) in chosen or closed and k in (0, n - 1) and \
                        ((id(c), 0) in chosen or (id(c), n - 1) in chosen)
                    parts = components.segments(c)
                    hit = [(a, b) for a, b in parts if has(a) and has(b)]
                    if hit and len(hit) == len(parts):
                        refs.append(("line", st.id, c.id))
                    else:
                        segs += [("seg", st.id, c.id, a, b) for a, b in hit]
        self.edge_selection = list(dict.fromkeys(refs))
        self.seg_selection = list(dict.fromkeys(segs))
        self.point_selection = []

    def _materialize_segments(self):
        """Line operations (X, F, delete, copy ...) on sub-edges: split the line there at its points,
        so the operation gets real lines (one undo step together with the operation)."""
        segs = self._valid_segs()
        if not segs:
            self.seg_selection = []
            return False
        self.scene.checkpoint()
        self.scene.merge_next()
        by_curve = {}
        for r, c in segs:
            by_curve.setdefault(id(c), (r, c, []))[2].append((r[3], r[4]))
        new_refs = []
        for r, c, ranges in by_curve.values():
            owner = next((st for st in self.scene.strokes if st.id == r[1]), None)
            if owner is None:
                continue
            n = len(c.points)
            cuts = sorted({i for a, b in ranges for i in (a, b)} - {0, n - 1})
            pieces = components.split_at(c, cuts)
            k = next(j for j, cc in enumerate(owner.curves) if cc is c)
            owner.curves[k:k + 1] = [piece for piece, _, _ in pieces]
            self.scene.split_map[c.id] = [piece.id for piece, _, _ in pieces]
            for piece, s, e in pieces:
                if any(a <= s and e <= b for a, b in ranges):
                    new_refs.append(("line", owner.id, piece.id))
        self.seg_selection = []
        self.edge_selection = list(dict.fromkeys(self.edge_selection + new_refs))
        self._changed()
        return True

    # --- Rounding (Ctrl+B) ---
    def start_bevel(self):
        """Ctrl+B in selection mode: round off selected points (or the corners of selected edges). Mouse away from the
        start point = size, Ctrl snaps, click confirms, Esc/right-click cancels."""
        if not self.select_mode or self._mode in ("bevel", "extrude", "transform"):
            return
        if self.seg_selection:
            self._materialize_segments()  # sub-edges become real lines (edge bevel needs them)
        points = [q for q in (self._point_pos(r) for r in self.point_selection) if q is not None]
        curves = [c for c in (edges.ref_to_curve(self.scene, r) for r in self.edge_selection) if c is not None and not c.paint]
        if not points and not curves:
            return self.notify(tr("Abrunden: erst Punkte (1) oder Kanten (2) wählen"))
        # edges at three-way corners (box) and three-way corners: edge bevel; otherwise corners of two lines as before
        edge_op = components.EdgeBevel(self.scene, curves, points)
        done = {id(job["curve"]) for job in edge_op.edges}
        corner_pts = [q for q, _, _ in edge_op.corners]
        positions = [q for q in points if not any(np.linalg.norm(q - c) < components.WELD_TOL for c in corner_pts)]
        for c in curves:
            if id(c) not in done:
                positions += [c.points[k] for k in components.knots(c)]
        self.scene.checkpoint()
        op = components.BevelSet([components.Bevel(self.scene, positions), edge_op])
        if not op.count:
            self.scene.undo()
            self.scene._redo.clear()
            return self.notify(tr("Abrunden: keine Ecke in der Auswahl (Linienenden ohne Partner zählen nicht)"))
        pos = self._last_pos if self._last_pos is not None else QPointF(self.width() / 2, self.height() / 2)
        center = np.mean(positions + points + [c.points[0] for c in curves], axis=0)
        depth = max((center - self.cam.eye) @ -self.cam.back, NEAR)
        self._bevel = dict(op=op, start=QPointF(pos), depth=depth, size=0.0,
                           sel=(list(self.point_selection), list(self.edge_selection), list(self.seg_selection)))
        self._mode = "bevel"
        self.emit_status()
        self.update()

    def _bevel_update(self, pos):
        b = self._bevel
        size = math.hypot(pos.x() - b["start"].x(), pos.y() - b["start"].y()) * float(self._world_per_px(b["depth"]))
        snap = self._snap_step()
        if snap:
            step = self.ws.snap_move * 0.1 * snap
            size = round(size / step) * step
        b["size"] = size
        b["op"].apply(size)
        self._changed()

    def _finish_bevel(self, ok):
        b, self._bevel = self._bevel, None
        self._mode = "consumed"
        if b is None:
            return
        if ok and b["size"] > 1e-9:
            made = b["op"].finish()  # rehang adjoining surfaces, create rounding surfaces
            self.point_selection, self.seg_selection = [], []
            self.edge_selection = [r for r in self.edge_selection if edges.ref_to_curve(self.scene, r) is not None]
            if self.ws.component == "edge" and self.edge_selection:  # new arcs belong to the selected shape
                self.edge_selection += [("line", owner.id, arc.id) for owner, arc in b["op"].arcs]
            self.notify(tr("{0} Ecke(n)/Kante(n) {1} – Größe {2:.3g}").format(b['op'].count, 'gefast' if b['op'].flat else 'abgerundet', b['size'])
                        + (tr(" · {0} Zeichenfläche(n) auf der Rundung").format(made) if made else ""))
        else:
            b["op"].restore()
            self.scene.undo()
            self.scene._redo.clear()
            self.point_selection, self.edge_selection, self.seg_selection = b["sel"]
        self._changed()

    def _net_marks(self):
        """Connection display: ([connected points], [open line ends], [other points]). Connected is every point
        where it continues: shared points of several lines and points in the middle of a line (corners, inserted ones,
        e.g. with Ctrl+click on a border line) - only free line ends are open. The third list stays empty.
        In a gizmo drag it stays remembered which point is connected and which is open; only their position is read anew: a
        drag changes no connection (except with Alt, then it is computed as usual), but looking up reconciled the whole curve net
        in every frame (harbor scene 12.11.: ~240 ms per frame in edge and point mode)."""
        held = self._mode == "transform" and self.gizmo.dragging and not self._free_move
        memo = getattr(self, "_marks_memo", None)
        if held and memo is not None and memo[0] is self.scene and memo[1] == self.scene.revision \
                and all(k < len(c.points) for c, k, _ in memo[2]):
            kinds = memo[2]
            fast = ([c.points[k] for c, k, tied in kinds if tied], [c.points[k] for c, k, tied in kinds if not tied], [])
            if self.VERIFY_LISTS:
                slow = self._net_marks_now()[0]
                assert all(len(a) == len(b) and (not len(a) or np.allclose(np.array(a), np.array(b)))
                           for a, b in zip(fast[:2], slow[:2])), "gemerkte Punkt-Marken weichen im Zug von den frischen ab"
            return fast
        marks, kinds = self._net_marks_now()
        self._marks_memo = (self.scene, self.scene.revision, kinds)
        return marks

    def _net_marks_now(self):
        """(_net_marks freshly computed, [(line, node, connected?)] in the same order per list)"""
        entries = self._knot_list()
        if not entries:
            return ([], [], []), []
        refs = network.refs_by_pid(self.scene)  # also lines of other objects: connected there means no open end
        count = {pid: len(at) for pid, at in refs.items()}
        shared, free, plain, seen, kinds = [], [], [], set(), []
        for _, c, k in entries:
            pid = network.pid_of(c, k)
            n = count.get(pid, 1)
            if n > 1:
                if pid not in seen:
                    seen.add(pid)
                    shared.append(c.points[k])
                    kinds.append((c, k, True))
            elif k in (0, len(c.points) - 1) and not components.is_closed(c.points):
                free.append(c.points[k])
                kinds.append((c, k, False))
            elif pid not in seen:  # in the middle of the line: connected (filled like a shared point)
                seen.add(pid)
                shared.append(c.points[k])
                kinds.append((c, k, True))
        return (shared, free, plain), kinds

    MARK_CROWD_MIN = 0.3  # point marks shrink at most this far when they are dense (fraction of their size)

    def _mark_crowd(self, pts):
        """Factor (MARK_CROWD_MIN ... 1) for the size of the point marks: if the points are denser in the image than a mark
        is large, the marks shrink - zoomed out they would otherwise clump into black blots that
        cover the object (artist 12.11.). Measure: how many points share one mark-sized cell in the image; if each
        has its own (zoomed in close), the full size stays."""
        if len(pts) < 8:
            return 1.0
        screen, ok = self.project(np.array(pts))
        w, h = self.width(), self.height()
        inside = ok & (screen[:, 0] >= 0) & (screen[:, 0] <= w) & (screen[:, 1] >= 0) & (screen[:, 1] <= h)
        n = int(inside.sum())
        if n < 8:
            return 1.0
        # grid in mark size: if many points share a cell, they are denser than a mark is large
        cell = 14.0
        cells = np.floor(screen[inside] / cell).astype(np.int64)
        occupied = len(np.unique(cells[:, 0] * 100003 + cells[:, 1]))
        return float(min(1.0, max(self.MARK_CROWD_MIN, np.sqrt(occupied / n))))

    def _draw_net_marks(self, p, plain=True):
        """Connected points (shared and in the middle of a line) filled, open line ends as open rings;
        plain: point mode (stronger), otherwise subtle (edge mode). Every point has a narrow halo in background color:
        it separates it from the line it sits on - on black, colored (border) and light lines, on paper as
        on the chalkboard."""
        marks = getattr(self, "_frame_marks", None)  # this image, without occluded ones (paintGL)
        shared, free, rest = (marks[0], marks[1], []) if marks is not None else self._net_marks()
        crowd = self._mark_crowd(shared + free + rest)
        if not plain:  # edge mode: strongly toned down, only in stroke color (pencil on paper, chalk at night)
            # with a narrow halo in background color: on a line in stroke color (white brush line on the
            # chalkboard, pencil on paper) the point would otherwise be invisible (harbor test 10.11.)
            color, halo = QColor(theme.STROKE_COLOR), QColor(theme.PAPER)
            for pts, filled in ((shared + rest, True), (free, False)):
                if not pts:
                    continue
                screen, ok = self.project(np.array(pts))
                r = (EDGE_MARK_R if filled else EDGE_MARK_R + 0.6) * self.ws.point_scale * crowd
                spots = [QPointF(x, y) for (x, y), visible in zip(screen, ok) if visible]
                hof = EDGE_MARK_HALO * crowd
                p.setPen(Qt.NoPen if filled else QPen(halo, (1.1 + 2 * EDGE_MARK_HALO) * crowd))
                p.setBrush(halo if filled else Qt.NoBrush)
                for q in spots:
                    p.drawEllipse(q, r + (hof if filled else 0.0), r + (hof if filled else 0.0))
                p.setPen(Qt.NoPen if filled else QPen(color, 1.1 * max(crowd, 0.6)))
                p.setBrush(color if filled else Qt.NoBrush)
                for q in spots:
                    p.drawEllipse(q, r, r)
            return
        scale = POINT_SCALE * self.ws.point_scale * crowd
        for pts, core, r in ((shared + rest, MARK_DARK, 3.8), (free, None, 3.8)):
            if not pts:
                continue
            screen, ok = self.project(np.array(pts))
            for (x, y), visible in zip(screen, ok):
                if visible:
                    if core is None:  # open end: light core with dark circle
                        _point_mark(p, QPointF(x, y), r * scale, MARK_LIGHT, plain)
                        p.setPen(QPen(MARK_DARK, 1.6 * scale))
                        p.setBrush(Qt.NoBrush)
                        p.drawEllipse(QPointF(x, y), r * scale, r * scale)
                    else:
                        _point_mark(p, QPointF(x, y), r * scale, core, plain)

    def _draw_hardness(self, p):
        """Hardness tool (K) on: a square around every angular point (the lines kink there), the stronger the harder.
        The hardness is read from the shape, not stored."""
        if self.ws.value_tool != "hardness":
            return
        refs = network.refs_by_pid(self.scene)
        key = getattr(self.scene, "_net_sync", (None,))[0]
        cached = getattr(self, "_hard_marks", None)
        if cached is None or cached[0] is not key or self._mode == "value":
            marks = []
            for pid, at in refs.items():
                h = components.point_sharpness(at)
                if h > 0.02:
                    marks.append((at[0][0].points[at[0][1]], h))
            cached = self._hard_marks = (key, marks)
        marks = cached[1]
        if not marks:
            return
        screen, ok = self.project(np.array([q for q, _ in marks]))
        p.setBrush(Qt.NoBrush)
        for (x, y), visible, (_, h) in zip(screen, ok, marks):
            if not visible:
                continue
            color = QColor(theme.GRAPHITE)
            color.setAlphaF(0.3 + 0.7 * h)
            p.setPen(QPen(color, 0.8 + 1.0 * h))
            p.drawRect(QRectF(x - 6.0, y - 6.0, 12.0, 12.0))

    def _draw_points(self, p):
        """Point mode: shared points filled, open ends as a ring; selected ones terracotta, the one under the cursor with
        a green ring."""
        if not self._knot_list():
            return
        chosen = [q for q in (self._point_pos(r) for r in self.point_selection) if q is not None]
        self._draw_net_marks(p)
        self._draw_hardness(p)
        if chosen:
            s, sok = self.project(np.array(chosen))
            for (x, y), visible in zip(s, sok):
                if visible:
                    _point_mark(p, QPointF(x, y), 4.6 * POINT_SCALE * self.ws.point_scale, theme.TERRACOTTA, True)
        hover = self._select_hover[0] if self._select_hover else None
        if hover is not None and hover[0] == "pt" and (q := self._point_pos(hover)) is not None:
            s, sok = self.project(q[None])
            if sok[0]:
                p.setPen(QPen(CONNECT_COLOR, 2))
                p.setBrush(Qt.NoBrush)
                ring = 7.0 * POINT_SCALE * self.ws.point_scale + 1.5
                p.drawEllipse(QPointF(*s[0]), ring, ring)


POINT_SCALE = 0.7  # point mode: base size of the point symbols (plus the slider View -> Point size)
EDGE_MARK_R = 2.0  # edge mode: points small, only in stroke color
EDGE_MARK_HALO = 1.3  # ... with a halo of this width in background color (px) so they are visible on any line
MARK_DARK = QColor(34, 33, 31)  # point symbols: same in both modes - dark core, white ring, dark outer edge
MARK_LIGHT = QColor(252, 251, 248)


def _point_mark(p, at, r, fill, strong=True):
    """A point symbol as in CAD programs: dark outer edge, white ring, core in fill. A part of it always contrasts
    with what lies underneath (dark or colored lines, light surfaces, paper, chalkboard)."""
    alpha = 1.0 if strong else 0.85
    outer = QColor(MARK_DARK)
    outer.setAlphaF(0.75 * alpha)
    ring = QColor(MARK_LIGHT)
    ring.setAlphaF(alpha)
    core = QColor(fill)
    core.setAlphaF(alpha)
    p.setPen(QPen(outer, 1.0))
    p.setBrush(ring)
    ring = r * (2.6 / 3.8)  # white ring grows with the point
    p.drawEllipse(at, r + ring, r + ring)
    p.setPen(Qt.NoPen)
    p.setBrush(core)
    p.drawEllipse(at, r, r)

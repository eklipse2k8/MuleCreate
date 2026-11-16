"""Drawing: pen width, smoothing, pressure, tool choice, straight lines and shapes, multi-surfaces."""
from .common import *  # noqa: F401,F403
from ..i18n import tr


class DrawingMixin:
    def set_pen_world_mode(self, on):
        self.pen_world_mode = on
        self._changed()

    def _scale_pen(self, factor):
        if self.erase_mode:  # D held: eraser size instead of pen size
            self.eraser_px = max(4.0, min(400.0, self.eraser_px * factor))
            self.update()
            return
        if self.pen_world_mode:
            self.pen_world = max(0.0005, min(self.pen_max_world, self.pen_world * factor))
            pos = self._press_pos if self._mode == "pensize" else self._last_pos
            hit = self._surface_hit(pos) if pos is not None else None  # depth for the size circle
            self._feedback_depth = (hit - self.cam.eye) @ -self.cam.back if hit is not None else self.cam.dist
        else:
            self.pen_px = max(1.0, min(80.0, self.pen_px * factor))
        self._pen_feedback_until = time.monotonic() + PEN_FEEDBACK_SECONDS
        QTimer.singleShot(int(PEN_FEEDBACK_SECONDS * 1000) + 50, self.update)  # hide the circle again
        self.emit_status()
        self.update()

    def _width_targets(self, mods):
        """Lines for scaling the thickness: [(line, mask of the points)]. Edge mode: selected lines and
        partial edges (Ctrl); drawing (Ctrl + Shift): all lines of the scene."""
        scene = self.scene
        if self.select_mode and self.ws.component == "edge":
            out = {}

            def add(curve, a=None, b=None):
                if curve is None:
                    return
                mask = out.setdefault(id(curve), (curve, np.zeros(len(curve.points), bool)))[1]
                mask[slice(a, None if b is None else b + 1)] = True

            for r in self.edge_selection:
                add(edges.ref_to_curve(scene, r))
            for owner in scene.strokes:
                if owner.id in self.selection:
                    for c in owner.curves:
                        add(c)
            for r in self.seg_selection:
                add(edges.ref_to_curve(scene, ("line", r[1], r[2])), r[3], r[4])
            return list(out.values())
        if not self.select_mode and not self.notes_mode and mods & Qt.ShiftModifier:
            return [(c, np.ones(len(c.points), bool)) for owner in scene.strokes for c in owner.curves]
        return []

    def _scale_widths(self, targets, factor):
        """Scale line thickness (like scaling, only for the thickness): ratios within a line stay."""
        for curve, mask in targets:
            curve.widths = np.where(mask, np.clip(curve.widths * factor, 1e-4, max(self.pen_max_world, 1e-4)), curve.widths)
        self._width_total = getattr(self, "_width_total", 1.0) * factor
        n = len(targets)
        self.notify(tr("Liniendicke × {0:.2f} – {1} Linie{2}").format(self._width_total, n, 'n' if n != 1 else ''))
        self.scene.dirty = True
        self._changed()

    def set_smooth(self, value):
        self.smooth = max(0.0, min(1.0, value))

    def _smooth_radius(self):
        """String length in pixels: relative to the pen radius (with world units at the depth of the tip)."""
        if self.smooth <= 0:
            return 0.0
        if self.pen_world_mode:
            depth = (self.current[-1] - self.cam.eye) @ -self.cam.back if self.current else self.cam.dist
            radius = self.pen_world / self._world_per_px(depth) / 2
        else:
            radius = self.pen_px / 2
        return self.smooth * self.smooth_max_factor * radius

    def _pull_tip(self, pos):
        """Trail the tip: only moves once the cursor is farther away than the radius."""
        delta = pos - self._tip
        dist = (delta.x() ** 2 + delta.y() ** 2) ** 0.5
        radius = self._smooth_radius()
        if dist > radius:
            self._tip = self._tip + delta * ((dist - radius) / dist)

    def _freehand_add(self, pos):
        """Append a freehand point at screen position pos (plane, mesh or multi)."""
        if self.multi_mode:
            self._multi_freehand(pos)
        elif not self._draw_ended:
            hit = self._surface_hit(pos)
            if hit is not None:
                self._exit = None  # back on the active surface: a detour over the edge stays (Z stroke)
            elif self.scene.active_mesh is not None and self.current:
                # adjacent drawing surface/mesh directly at the border: keep drawing there – but only if the stroke comes back onto the
                # active surface; if it ends outside, _trim_exit cuts it off at the edge
                other, point, _ = self._mesh_under(pos)
                if other is not None and self._continues(self.current[-1], point):
                    if getattr(self, "_exit", None) is None:
                        last = getattr(self, "_last_hit_pos", None)
                        edge = self._edge_point(last, pos) if last is not None else None
                        self._exit = (len(self.current), edge)
                    hit = point  # the clicked surface stays active
            if hit is None:
                # stroke ends at the mesh border – single misses (stroke grazes the silhouette,
                # pick inaccuracy) do not end it, though, only a stretch of END_GAP_PX away from it
                if self._miss_start is None:
                    self._miss_start = pos
                    # the last point on the surface between the mouse positions (fast strokes)
                    last = getattr(self, "_last_hit_pos", None)
                    edge = self._edge_point(last, pos) if last is not None and self.current else None
                    if edge is not None and np.linalg.norm(edge - self.current[-1]) > 1e-9:
                        self.current.append(edge)
                elif (pos - self._miss_start).manhattanLength() > END_GAP_PX:
                    if self._lazy_start and self._screen_span(self.current) < 2 * SNAP_PX:
                        # only a corner grazed: discard tiny piece, wait for the proper entry
                        self.current, self._mode, self._press_hit, self._lazy_start = [], "pending", None, False
                        self._miss_start = None
                        return
                    self._draw_ended = self.scene.active_mesh is not None
            else:
                self._miss_start = None
                self._last_hit_pos = QPointF(pos)
                if np.linalg.norm(hit - self.current[-1]) > 0.001 * self.cam.dist:
                    self.current.append(hit)

    def _screen_span(self, pts):
        """Length of a drag on screen (pixels)."""
        if pts is None or len(pts) < 2:
            return 0.0
        screen, ok = self.project(np.asarray(pts, float))
        return float(np.nansum(np.linalg.norm(np.diff(screen[ok], axis=0), axis=1))) if ok.sum() > 1 else 0.0

    def _edge_point(self, a, b):
        """Last point on the active surface (mesh) when going from a to b on screen – finely sampled,
        so exactly at the border; None without mesh or if a itself does not hit."""
        mesh = self.scene.active_mesh
        if mesh is None or a is None or b is None:
            return None
        last = None
        for hit, point, _ in self._mesh_samples(self._line_samples(QPointF(a), QPointF(b)), [mesh] if self.xray else None):
            if hit is not mesh:
                break
            last = point
        return last

    def _trim_exit(self):
        """On release: if the stroke left the active surface and did not come back, it ends at its
        edge – the piece on the neighboring surface is dropped (drawing target is the active surface)."""
        exit_, self._exit = getattr(self, "_exit", None), None
        if exit_ is None or not self.current:
            return
        k, edge = exit_
        self.current = self.current[:k]
        if edge is not None and (not self.current or np.linalg.norm(edge - self.current[-1]) > 1e-9):
            self.current.append(edge)

    def _finish_line(self, pos):
        """On release with smoothing: the stroke ends at the pen tip (at the end of the string), it no longer
        jumps ahead to the cursor (the artist's request)."""
        return

    def _world_per_px(self, depth):
        """World units per (logical) pixel at a given depth (orthographic: same everywhere).
        depth may also be an array."""
        if self.cam.ortho:
            scale = 2 * self._half_height() / max(self.height(), 1)
            return scale if np.ndim(depth) == 0 else np.full(np.shape(depth), scale)
        return np.maximum(depth, NEAR) * 2 * self._tan_half() / max(self.height(), 1)

    def _widths_for(self, points, pressure=False):
        """Stroke width per point in world units. Pixel mode: so wide that the stroke looks
        pen_px pixels wide everywhere while drawing; afterwards it behaves like a 3D object.
        pressure: the running stroke – pen pressure curve distributed over the points."""
        points = np.asarray(points, float)
        if self.pen_world_mode:
            widths = np.full(len(points), self.pen_world)
        else:
            depth = (points - self.cam.eye) @ -self.cam.back
            widths = self.pen_px * self._world_per_px(depth)
        line_tool = "brush" if self.ws.draw_tool == "brush" else "pen"
        if pressure and self._pressure_trace and self.ws.pressure[line_tool] > 0 and len(points):
            trace = np.asarray(self._pressure_trace, float)
            if len(trace) >= 5:  # smooth slightly (the pressure jitters)
                trace = np.convolve(np.pad(trace, 2, mode="edge"), np.ones(5) / 5, mode="valid")
            at = np.linspace(0, len(trace) - 1, len(points))
            widths = widths * self._pressure_factor(np.interp(at, np.arange(len(trace)), trace), line_tool)
        return widths

    def _pressure_factor(self, p, tool):
        """Factor from the pen pressure p (0..1) for the tool: 1 without pressure sensitivity, at full
        sensitivity from PRESSURE_MIN (lightest touch) to PRESSURE_MAX (firmest)."""
        s = self.ws.pressure.get(tool, 0.0)
        lo, hi = 1 + s * (PRESSURE_MIN - 1), 1 + s * (PRESSURE_MAX - 1)
        return lo + (hi - lo) * np.clip(p, 0.0, 1.0)

    def _current_pressure(self):
        """Pen pressure just now (0..1) or None (mouse, no tablet)."""
        if self._pressure is None or time.monotonic() - self._pressure_at > TABLET_FRESH_S:
            return None
        return self._pressure

    def _click_px(self):
        """Movement up to which a press still counts as a click: more with the pen shortly after touching down."""
        if getattr(self, "_press_tablet", False) and time.monotonic() - getattr(self, "_press_time", 0.0) < TABLET_CLICK_S:
            return TABLET_CLICK_PX
        return CLICK_PX

    def set_pressure(self, tool, value):
        self.ws.pressure[tool] = max(0.0, min(1.0, float(value)))
        self.emit_status()

    def set_multi_mode(self, on):
        """Default: only the active surface, a click switches it; multi (B): a click collects surfaces."""
        self.multi_mode = on
        if on and not self._multi_surfaces():  # start: selected surfaces, otherwise the active one
            chosen = [o for o in self.selected_objects if self._is_drawing_surface(o)]
            self.scene.multi_ids = [o.id for o in chosen or [self.scene.active_surface]]
        self.toggles_changed.emit()
        self._changed()

    def _shift_plane(self, distance, burst=None):
        """Move the active plane along its normal (not with a mesh as drawing surface)."""
        if self.scene.active_mesh is not None:
            self.status_changed.emit(tr("Zeichenfläche ist ein Mesh – Verschieben per Mausrad gilt nur für Ebenen."))
            return
        if self.scene.active_plane.flipbook:  # fixed objects: only with the gizmo (together with all drawings)
            self.status_changed.emit(tr("Flipbook-Ebenen bewegt man mit T / R / E (Gizmo) – nicht mit Mausrad, [ ] oder Shift+Rechtsklick"))
            return
        plane = self.scene.active_plane
        if burst is not None:
            self.scene.checkpoint(burst=burst)
        step = self._plane_step()
        n = distance / step
        if abs(n - round(n)) < 1e-6 and round(n) != 0:  # mouse wheel/[ ]: to multiples of the step (clean heights)
            n = round(n)
            offset = float(plane.origin @ plane.normal)
            base = math.floor(offset / step + 1e-6) if n > 0 else math.ceil(offset / step - 1e-6)
            distance = (base + n) * step - offset
        plane.translate(plane.normal * distance)
        self.emit_status()

        # --- Eraser (hold D) ----------------------------------------------
    def set_draw_tool(self, tool):
        """A pen/brush, D eraser – always means: draw (back from edit and notes)."""
        if tool == "eraser":
            if self.ws.draw_tool != "eraser":
                self.ws.last_draw_tool = self.ws.draw_tool
        else:
            self.ws.last_draw_tool = tool
        if tool in ("pen", "brush"):
            self.ws.last_line_tool = tool
        self.ws.draw_tool = tool
        if self.notes_mode:
            self._leave_notes()
        if self.select_mode:
            self.set_select_mode(False)
        self.toggles_changed.emit()
        self._changed()

    def toggle_edit(self):
        """Tab (as in Blender): draw <-> edit; from the notes back to drawing."""
        if self.notes_mode:
            return self.set_notes_mode(False)
        self.set_select_mode(not self.select_mode)

    def set_paint_color(self, rgb):
        """Color for the brush and for tinting the surfaces (RGB 0..1)."""
        self.ws.paint_color = tuple(float(x) for x in rgb)
        self.emit_status()
        self.emit_status()

    def _straighten(self):
        """Holding still at the stroke end: recognize circle, ellipse, rectangle or arc, otherwise straight line."""
        drawn = sum(len(s) for s, _ in self._segments) + len(self.current or [])
        if self._mode == "draw" and drawn > 1 and not self._straight and self._last_pos is not None:
            # started outside the surfaces? (the recognized shape begins at the first point on the surface)
            if self.multi_mode:
                first = self._seg_kinds[0][0] if getattr(self, "_seg_kinds", None) else getattr(self, "_cur_start", None)
                self._shape_start_gap = first == "gap"
            else:
                self._shape_start_gap = bool(getattr(self, "_lazy_start", False))
            self._straight = True
            self._shape = self._recognize_shape()
            if self._shape is not None and self._shape["kind"] != "arc":
                self._draw_snaps = []  # the shape replaces the stroke: its snapped start does not count
            elif self._shape is not None:  # arc: start and end snap as with strokes
                self._draw_snaps = [sn for sn in self._draw_snaps[:1]]
                self._arc_end_snap = None
            if self._shape is not None:
                self.status_changed.emit(tr("{0} erkannt – Maus: Größe").format(shapes.NAMES[self._shape['kind']])
                                         + (tr(" · Strg: Quadrat") if self._shape["kind"] == "rect" else "")
                                         + tr(" · Loslassen: fertig"))
            self._update_straight(self._last_pos)
            self.update()

        # --- Shape recognition ---
    def _shape_frame(self, points):
        """Plane the shape lies in: the active drawing plane (x/y as on screen), on
        meshes and in multi mode an imaginary plane across the view direction through the stroke center –
        the shape is then projected onto the mesh."""
        if not self.multi_mode and self.scene.active_mesh is None:
            plane = self.scene.active_plane
            up, side = self._snap_dirs(plane.normal)
            return {"origin": plane.origin.copy(), "x": side, "y": up, "plane": plane, "project": False}
        origin = np.mean(points, axis=0)
        c = self.cam
        return {"origin": origin, "x": c.right.copy(), "y": c.up.copy(),
                "plane": Plane("", origin, c.right.copy(), c.up.copy()), "project": True}

    def _to2d(self, frame, points):
        d = np.asarray(points) - frame["origin"]
        return np.stack([d @ frame["x"], d @ frame["y"]], axis=1)

    def _cursor2d(self, frame, pos):
        hit = self._ray_plane(pos, frame["plane"])[0]
        return None if hit is None else self._to2d(frame, hit[None])[0]

    def _recognize_shape(self):
        points = [pt for seg, _ in self._segments for pt in seg] + list(self.current or [])
        if len(points) < 5:
            return None
        points = np.array(points)
        frame = self._shape_frame(points)
        if frame["project"]:  # stroke lies on the mesh: via the screen onto the imaginary plane
            screen, ok = self.project(points)
            hits = [self._ray_plane(QPointF(*q), frame["plane"])[0] for q, k in zip(screen, ok) if k]
            points = np.array([h for h in hits if h is not None])
            if len(points) < 5:
                return None
        angles = []
        if not frame["project"]:  # axes of the drawing plane as they lie in the shape plane
            u = frame["plane"].axis_u
            angles.append(math.atan2(float(u @ frame["y"]), float(u @ frame["x"])))
        shape = shapes.recognize(self._to2d(frame, points), angles)
        cursor = self._cursor2d(frame, self._last_pos)
        if shape is None or cursor is None:
            return None
        shape = shapes.prepare(shape, cursor)
        shape["frame"] = frame
        return shape

    def _update_shape(self, pos):
        frame = self._shape["frame"]
        cursor = self._cursor2d(frame, pos)
        end_snap = None
        if self._shape["kind"] == "arc" and not self._ctrl and not frame["project"] and self._free_saved is not None:
            snap, on_line = self._free_end_snap(pos)  # free mode: points/lines at any depth
            if snap is not None:  # the arc ends where the point lies on screen
                s, ok = self.project(snap[None])
                hit = self._ray_plane(QPointF(*s[0]), frame["plane"])[0] if ok[0] else None
                if hit is not None:
                    end_snap = (snap, on_line)
                    cursor = self._to2d(frame, hit[None])[0]
            self._arc_end_snap = end_snap
        elif self._shape["kind"] == "arc" and not self._ctrl and not frame["project"]:
            snap, on_line = self._draw_snap(pos)  # arc end snaps to lines (ends)
            if snap is not None:
                end_snap = (snap, on_line)
                cursor = self._to2d(frame, snap[None])[0]
            self._arc_end_snap = end_snap
        if cursor is not None:
            adjusted = shapes.adjust(self._shape, cursor, square=self._ctrl,
                                     snap_deg=self.ws.snap_angle if self._ctrl else None)
            adjusted["frame"] = frame
            self._shape = adjusted
        runs, kinds = [], []
        for line in shapes.polylines(self._shape):
            pts = frame["origin"] + line[:, :1] * frame["x"] + line[:, 1:] * frame["y"]
            if frame["project"]:  # laid onto the mesh / the surfaces: like freehand pieces (borders, transitions)
                r, k = self._project_runs(pts, kinds=True)
                runs += r
                kinds += k
            else:
                runs.append((list(pts), self.scene.active_surface))
                kinds.append(("hit", "hit"))
        if kinds and kinds[0][0] == "hit" and getattr(self, "_shape_start_gap", False):
            kinds[0] = ("gap", kinds[0][1])  # stroke came from outside: the shape begins on the border
        self._segments, self._seg_kinds = runs[:-1], kinds[:-1]
        self.current, self._current_surface = (list(runs[-1][0]), runs[-1][1]) if runs else ([], None)
        self._cur_start, self._cur_end = kinds[-1] if kinds else (None, None)
        if self._shape["kind"] == "arc" and self.current and not frame["project"]:
            if self._draw_snaps:  # exactly onto the snap points, otherwise hairline gaps stay open
                self.current[0] = self._draw_snaps[0][0].copy()
            if end_snap is not None:
                self.current[-1] = end_snap[0].copy()
        elif self._shape["kind"] == "arc" and self.current and frame["project"] and not self._ctrl:
            # arc laid on surfaces: start and end snap to lines if they lie on the surface
            first = self._segments[0][0] if self._segments else self.current
            if self._draw_snaps and kinds and kinds[0][0] == "hit":
                first[0] = self._draw_snaps[0][0].copy()
            end_snap = None
            if kinds and kinds[-1][1] == "hit":
                snap, on_line = self._draw_snap(pos)
                if snap is not None:
                    end_snap = (snap, on_line)
                    self.current[-1] = snap.copy()
            self._arc_end_snap = end_snap

    def _project_runs(self, pts, kinds=False):
        """Project a line from the imaginary plane onto the mesh (or the multi surfaces): finely sampled
        over the screen; where nothing is hit, a gap arises (several lines). kinds: per line (start, end)
        as in _split_runs."""
        screen, ok = self.project(pts)
        samples = []
        for i in range(len(pts) - 1):
            if ok[i] and ok[i + 1]:
                a, b = QPointF(*screen[i]), QPointF(*screen[i + 1])
                samples += self._line_samples(a, b)[:-1]
        if ok[-1]:
            samples.append(QPointF(*screen[-1]))
        if not samples:
            return ([], []) if kinds else []
        if self.multi_mode:
            hits = self._multi_samples(samples)
        else:
            mesh = self.scene.active_mesh
            hits = [(point if hit is mesh else None, mesh)
                    for hit, point, _ in self._mesh_samples(samples, [mesh] if self.xray else None)]
        return self._split_runs(hits, kinds=kinds)

    def _multi_start(self, hit):
        point, surface = hit
        self._segments = []
        self.current = [point] if point is not None else []
        self._current_surface = surface
        # how each piece begins/ends: "hit" (started/released on the surface), "switch" (change to another
        # surface without a gap), "gap" (before/after there was no surface under the pen)
        self._seg_kinds, self._cur_start, self._cur_end = [], ("hit" if point is not None else None), None
        self._prev_miss = point is None
        self._multi_prev = QPointF(self._press_pos) if self._press_pos is not None else None

    def _multi_freehand(self, pos):
        point, surface = self._multi_samples([pos])[0]
        prev, self._multi_prev = getattr(self, "_multi_prev", None), QPointF(pos)
        if point is None or surface is not self._current_surface:  # gap or other surface: new line
            entry = point
            if prev is not None:  # sample finely between the mouse positions: exactly where the surface ends/begins
                hits = self._multi_samples(self._line_samples(prev, QPointF(pos)))
                if self.current and self._current_surface is not None:
                    last = None
                    for p, srf in hits:
                        if p is None or srf is not self._current_surface:
                            break
                        last = p
                    if last is not None and np.linalg.norm(last - self.current[-1]) > 1e-9:
                        self.current.append(last)
                if point is not None:
                    first = None
                    for p, srf in reversed(hits):
                        if p is None or srf is not surface:
                            break
                        first = p
                    entry = first if first is not None else point
            if len(self.current) > 1:
                self._segments.append((self.current, self._current_surface))
                self._seg_kinds.append((self._cur_start, "gap" if point is None else "switch"))
            self.current = [] if point is None else (
                [entry, point] if np.linalg.norm(entry - point) > 1e-9 else [point])
            self._current_surface = surface
            self._cur_start = None if point is None else ("gap" if self._prev_miss else "switch")
        elif not self.current or np.linalg.norm(point - self.current[-1]) > 0.001 * self.cam.dist:
            self.current.append(point)
        self._prev_miss = point is None

    def _multi_straight(self, pos):
        if self._penetrate:
            start = self._segments[0][0][0] if self._segments else (self.current[0] if self.current else None)
            end, _ = self._multi_samples([pos])[0]
            if start is not None:
                end = end if end is not None else (self.current[-1] if self.current else start)
                self._segments, self.current = [], [start, end]
            return
        runs, kinds = self._split_runs(self._multi_samples(self._line_samples(self._press_pos, pos)), kinds=True)
        if runs:
            self._segments, self._seg_kinds = runs[:-1], kinds[:-1]
            self.current, self._current_surface = runs[-1]
            self._cur_start, self._cur_end = kinds[-1]
        else:
            self._segments, self.current, self._seg_kinds = [], [], []

    def _finished_runs(self):
        """All pieces of the current drag as [(points, surface)]."""
        runs = list(self._segments)
        if self.current and len(self.current) > 1:
            runs.append((self.current, self._current_surface if self.multi_mode else self.scene.active_surface))
        return runs

    def _finished_kinds(self):
        """Multi mode: per piece (start, end) as "hit" / "switch" / "gap" (see _multi_start) or None."""
        kinds = list(getattr(self, "_seg_kinds", []))
        if self.current and len(self.current) > 1:
            end = self._cur_end if self._straight and self._cur_end else (
                "gap" if getattr(self, "_prev_miss", False) else "hit")
            kinds.append((self._cur_start, end))
        return kinds if len(kinds) == len(self._finished_runs()) else None

    def _update_straight(self, pos):
        if self._shape is not None:
            return self._update_shape(pos)
        mesh = self.scene.active_mesh
        if self._ctrl and (self.multi_mode or mesh is not None):
            pos = self._snap_screen(pos)  # Ctrl: end snaps in angle steps
        if self.multi_mode:
            self._multi_straight(pos)
        elif mesh is None:
            hit = self._ray_plane(pos, self.scene.active_plane)[0]
            if hit is not None:
                if self._ctrl:
                    hit = self._snap_line_end(self.current[0], hit, self.scene.active_plane.normal)
                else:
                    snap, _ = self._draw_snap(pos)  # end already snaps in the preview
                    hit = snap if snap is not None else hit
                self.current = [self.current[0], hit]
        elif self._penetrate:
            hit = self._surface_hit(pos)
            self.current = [self.current[0], hit if hit is not None else self.current[-1]]
        else:
            points = self._mesh_line(self._press_pos, pos, mesh)
            if len(points) >= 2:
                points[0] = self.current[0]
                self.current = points

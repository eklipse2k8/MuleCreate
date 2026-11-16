"""Cleanup: weld, fuse, cleanup section."""
from .common import *  # noqa: F401,F403
from ..i18n import tr


def _length(points):
    return float(np.linalg.norm(np.diff(points, axis=0), axis=1).sum())


class CleanupMixin:
    # --- Weld (Ctrl + Shift + F) and cleanup (Ctrl + F) ---
    def cleanup(self):
        """Ctrl + F: first weld (close gaps, snap ends), then fuse."""
        self.weld(then_fuse=True)

    def weld(self, then_fuse=False):
        self._materialize_segments()
        return self._weld(then_fuse)

    def _weld(self, then_fuse=False):
        """Close gaps: pull line ends that are closer in space than the snap distance (ws.cleanup_dist) onto a
        common point; then set loose ends near a line exactly onto it and split the
        line there (real node). Acts on the selection, without selection on everything. Selected points: exactly those
        - when close together they each become one point (also corners in the middle of lines and points that already
        join several lines); the other ends of their lines stay as they are."""
        scope = self._fuse_scope()
        chosen = self._chosen_ends()

        def in_scope(c, e):
            return scope is None or id(c) in scope and (chosen is None or (id(c), e) in chosen)

        self.scene.checkpoint()
        moved, done = self._weld_points() if chosen is not None else (0, set())
        moved += self._weld_ends(lambda c, e: in_scope(c, e) and (id(c), e) not in done)
        moved += self._weld_onto_lines(lambda c, e: in_scope(c, e) and (id(c), e) not in done)
        joined = self.fuse_lines(checkpoint=False, report=False) if then_fuse else 0
        if not moved and not joined:
            self.scene._undo.pop()  # nothing changed: no empty undo step
        self._changed()
        parts = [tr("{0} Ende(n) verschweißt").format(moved)] + ([tr("{0} Stelle(n) verschmolzen").format(joined)] if then_fuse else [])
        self.status_changed.emit(tr("Aufräumen: ") + ", ".join(parts) if (moved or joined) else
                                 tr("Aufräumen: nichts zu verschweißen") + (tr(" oder zu verschmelzen") if then_fuse else ""))

    def _weld_ends(self, in_scope):
        curves = [c for c in self.scene.pickable_curves() if not c.paint]
        ends = [(c, e) for c in curves for e in (0, -1)]
        if not ends:
            return 0
        tol = self.ws.cleanup_dist
        nodes = fill.cluster_endpoints(np.array([c.points[e] for c, e in ends]), tol)
        groups = {}
        for end, node in zip(ends, nodes):
            groups.setdefault(node, []).append(end)
        moved = 0
        for members in groups.values():
            if len(members) < 2:
                continue
            # do not pull a short line with both ends together to a point here (long: close the circle)
            short = {id(c) for c, e in members if e == 0 and any(o is c and oe == -1 for o, oe in members)
                     and _length(c.points) < 3 * tol}
            members = [(c, e) for c, e in members if id(c) not in short]
            mine = [(c, e) for c, e in members if in_scope(c, e)]
            if not mine or len(members) < 2:
                continue
            anchors = [c.points[e] for c, e in members if not in_scope(c, e)]
            target = np.mean(anchors or [c.points[e] for c, e in mine], axis=0)
            here = sum(self._move_end(c, e, target) for c, e in mine)
            # curve net: welded means connected - also ends that already lay exactly on each other
            merged = network.merge_at(self.scene, target)
            moved += here or (1 if merged else 0)
        return moved

    def _weld_onto_lines(self, in_scope):
        """Set loose ends closer than the snap distance to another line exactly onto it (T-junction) and split the line
        there."""
        curves = [c for c in self.scene.pickable_curves() if not c.paint and len(c.points) >= 2]
        open_keys = edges.open_end_keys(curves)
        tol = self.ws.cleanup_dist
        boxes = [(c.points.min(axis=0) - tol, c.points.max(axis=0) + tol) for c in curves]
        moved = 0
        for c in curves:
            for e in (0, -1):
                if (id(c), e) not in open_keys or not in_scope(c, e):
                    continue
                p, best = c.points[e], None
                for other, (lo, hi) in zip(curves, boxes):
                    if other is c or (p < lo).any() or (p > hi).any():
                        continue
                    d, i, t = self.scene._closest_on(other, p)
                    if d < tol and (best is None or d < best[0]):
                        best = (d, other, i, t)
                if best is None:
                    continue
                _, other, i, t = best
                target = other.points[i] + t * (other.points[i + 1] - other.points[i])
                moved += self._move_end(c, e, target)
                self.scene.insert_knot_at(target)  # T-junction: common point, the line stays whole
        return moved

    def _chosen_ends(self):
        """Selected points (without "Global"): {(id(line), 0 | -1)} of the selected line ends - including the ends that already share
        a point with them; None: no point selection (then whole lines count)."""
        pts = self._valid_points()
        if self.ws.cleanup_global or not pts or self.selection or self.edge_selection or self._valid_segs():
            return None
        index = components.KnotIndex(self.scene)
        out = set()
        for r, c in pts:
            for _, other, j in [(None, c, r[3])] + list(index.linked(c, r[3])):
                if j in (0, len(other.points) - 1):
                    out.add((id(other), 0 if j == 0 else -1))
        return out

    def _weld_points(self):
        """Selected points that are closer together than the snap distance, each merged into one point: all
        pulled to their middle (as when dragging in point mode - what is already connected to them moves along) and connected.
        -> (number of merged points, {(id(line), end)} of the line ends treated this way)."""
        sc = self.scene
        network.sync(sc)
        groups = {}  # point id (or line+node without id) -> [(line, node)]
        for r, c in self._valid_points():
            k = r[3]
            groups.setdefault((c.pids or {}).get(k, (id(c), k)), []).append((c, k))
        keys = list(groups)
        if len(keys) < 2:
            return 0, set()
        where = np.array([groups[key][0][0].points[groups[key][0][1]] for key in keys])
        nodes = fill.cluster_endpoints(where, self.ws.cleanup_dist)
        clusters = {}
        for key, node in zip(keys, nodes):
            clusters.setdefault(node, []).append(key)
        index = components.KnotIndex(sc)
        merged, done = 0, set()
        for members in clusters.values():
            if len(members) < 2:
                continue
            knots = [groups[key][0] for key in members]
            if len({id(c) for c, _ in knots}) == 1:
                continue  # only points of a single line (e.g. start and end): as before via the ends
            target = np.mean([c.points[k] for c, k in knots], axis=0)
            for c, k in knots:
                delta = target - c.points[k]
                if np.linalg.norm(delta) > 1e-12:
                    components.ComponentGroup(sc, [(c, k)], [], mode=self.ws.knot_mode).translate(delta)
            merged += max(1, network.merge_at(sc, target))
            index = components.KnotIndex(sc)
            for c, k in knots:
                for _, other, j in [(None, c, k)] + list(index.linked(c, k)):
                    if j in (0, len(other.points) - 1):
                        done.add((id(other), 0 if j == 0 else -1))
        return merged, done

    def connect_crossings(self, curves):
        """Cleanup: apply the connection rule (_resolve_stroke) to existing lines (selection or all) - loose
        ends close to points/lines get connected - and where they cross other lines in space, create common
        points (also between different drawing surfaces, after moving, extruding, mirroring ...). When
        drawing, this happens automatically for new strokes."""
        self.scene.checkpoint()
        lines = [c for c in curves if not c.paint]
        loose_before = network.sync(self.scene)["free_ends"]
        self._resolve_stroke(lines, None)
        ends = max(0, loose_before - network.sync(self.scene)["free_ends"])
        everything = [c for c in self._visible_curves() if not c.paint]
        done, made = set(), 0
        curves = [self.scene.curve_by_id(sub) for c in lines for sub in (self.scene.split_pieces(c.id) or [])]
        curves = [c for c in curves if c is not None]  # split/replaced lines: their current pieces
        for c in curves:
            for o in everything:
                if o is c or (id(o), id(c)) in done:
                    continue
                done.add((id(c), id(o)))
                made += network.connect_crossings(self.scene, c, [o], self._cross_tol(c, o))
        if not made and not ends:
            self.scene._undo.pop()
        self.notify(tr("Cleanup: {0} Ende(n) und {1} Kreuzung(en) verbunden").format(ends, made) if made or ends
                    else tr("Cleanup: nichts zu verbinden"))
        self._changed()
        return made + ends

    @staticmethod
    def _move_end(curve, end, target):
        """Pull line end onto target, tapering off toward the other end. 1 if it moved."""
        disp = target - curve.points[end]
        if np.linalg.norm(disp) < 1e-12:
            return 0
        curve.points = curve.points + edges._falloff(curve.points, from_end=(end == -1))[:, None] * disp
        return 1

    # --- Fuse (Ctrl + F): merge split lines back together ---
    def _fuse_scope(self):
        """Lines that weld/fuse act on: cleanup global -> all (None), otherwise the selected ones."""
        if self.ws.cleanup_global:
            return None
        return {id(c) for c in self.cleanup_scope()[0]}

    def cleanup_scope(self):
        """(lines, stroke objects, surfaces) for the cleanup menu: the selection, with "Global" everything."""
        sc = self.scene
        if self.ws.cleanup_global:
            return [c for c in sc.pickable_curves() if not c.paint], list(sc.strokes), list(sc.surfaces)
        curves = {id(c): c for o in self.selected_objects if o in sc.strokes for c in o.curves}
        for ref in self.edge_selection:
            c = edges.ref_to_curve(sc, ref)
            if c is not None:
                curves[id(c)] = c
        for r, c in list(self._valid_points()) + list(self._valid_segs()):
            curves[id(c)] = c
        strokes = [o for o in self.selected_objects if o in sc.strokes]
        surfaces = [o for o in self.selected_objects if isinstance(o, SurfaceObject)]
        return [c for c in curves.values() if not c.paint], strokes, surfaces


    def set_cleanup_global(self, on):
        self.ws.cleanup_global = bool(on)
        self.toggles_changed.emit()
        self.notify(tr("Cleanup: wirkt jetzt auf ALLES") if on else tr("Cleanup: wirkt nur auf die Auswahl"))

    def run_cleanup(self, what):
        """Apply a function from the cleanup menu to the selection (or with "Global" to everything)."""
        from .. import cleanup
        curves, strokes, surfaces = self.cleanup_scope()
        nothing = not curves and not strokes and not surfaces
        if nothing and not self.ws.cleanup_global:
            return self.notify(tr("Cleanup: nichts ausgewählt – „Global“ anhaken, um alles aufzuräumen"))
        if what == "all":
            return self.cleanup()
        if what == "weld":
            return self.weld()
        if what == "fuse":
            return self.fuse_lines()
        if what == "crossings":
            return self.connect_crossings(curves)
        self.scene.checkpoint()
        size = cleanup.scene_size(self.scene)
        if what == "dissolve":
            n, text = cleanup.dissolve_inserted(curves), tr("eingefügte Punkt(e) aufgelöst")
        elif what == "duplicates":
            n, text = cleanup.remove_duplicates(self.scene, curves, size), tr("doppelte Linie(n) entfernt")
        elif what == "tiny":
            n, text = cleanup.remove_tiny(self.scene, curves, size), tr("winzige Linie(n) gelöscht")
        elif what == "empty":
            n, text = cleanup.remove_empty_strokes(self.scene, strokes or list(self.scene.strokes)), tr("leere(s) Objekt(e) gelöscht")
        elif what == "straighten":
            n, text = cleanup.straighten(curves), tr("Stück(e) begradigt")
        elif what == "relink":
            n, text = cleanup.relink_surfaces(self.scene, surfaces), tr("Fläche(n) wieder verknüpft")
        else:
            return
        if not n:
            self.scene._undo.pop()  # nothing changed: no empty undo step
        self.notify(tr("Cleanup: {0} {1}").format(n, text) if n else tr("Cleanup: nichts zu tun"))
        self._changed()

    def fuse_lines(self, checkpoint=True, report=True):
        """Ctrl + F: join line ends that lie closer together in space than the snap distance (ws.cleanup_dist), where
        nothing else ends (no node with three or more ends) and where the line
        continues without a kink (below FUSE_MAX_DEG), into one line. Only within a stroke object."""
        scope = self._fuse_scope()
        # selected points: merge only at them, not at the other ends of their lines
        spots = None if self._chosen_ends() is None else np.array(
            [q for q in (self._point_pos(r) for r, _ in self._valid_points()) if q is not None]).reshape(-1, 3)
        joined, changed = 0, True
        while changed:  # several passes: chains of many pieces
            changed = False
            owners = {id(c): o for o in self.scene.strokes for c in o.curves}
            real = [c for o in self.scene.strokes for c in o.curves if len(c.points) >= 2]
            ends = [(c, e) for c in real for e in (0, -1)]
            if not ends:
                break
            nodes = fill.cluster_endpoints(np.array([c.points[e] for c, e in ends]), self.ws.cleanup_dist)
            at_node = {}
            for (c, e), node in zip(ends, nodes):
                at_node.setdefault(node, []).append((c, e))
            used = set()
            pairs = []
            for members in at_node.values():
                if len(members) != 2:
                    continue  # node (or free end)
                (a, ea), (b, eb) = members
                if a is b or id(a) in used or id(b) in used:
                    continue
                if scope is not None and not (id(a) in scope and id(b) in scope):
                    continue
                if spots is not None and (not len(spots) or np.linalg.norm(spots - a.points[ea], axis=1).min()
                                          > self.ws.cleanup_dist):
                    continue
                owner = owners.get(id(a))
                if owner is None or owner is not owners.get(id(b)) or not self._fusable(owner, a, ea, b, eb):
                    continue
                used.update((id(a), id(b)))
                pairs.append((owner, a, ea, b, eb))
            if pairs and not joined and checkpoint:
                self.scene.checkpoint()
            for owner, a, ea, b, eb in pairs:
                self._fuse_pair(owner, a, ea, b, eb)
                joined += 1
                changed = True
        if report:
            if joined:
                self._changed()
            self.status_changed.emit(tr("Fuse: {0} Stelle(n) zusammengeführt.").format(joined) if joined else
                                     tr("Fuse: keine Linienenden gefunden, die sich zusammenführen lassen."))
        return joined

    @staticmethod
    def _end_direction(points, end, dist):
        """Direction in which the line runs out at this end - measured over a stretch of length
        dist (not just the last segment, which jitters on freehand lines)."""
        pts = points if end == -1 else points[::-1]
        seg = np.linalg.norm(np.diff(pts[::-1], axis=0), axis=1)
        k = int(np.searchsorted(np.cumsum(seg), dist)) + 1  # first point at least dist from the end
        d = pts[-1] - pts[-1 - min(k, len(pts) - 1)]
        n = np.linalg.norm(d)
        return d / n if n > 1e-12 else None

    def _fusable(self, owner, a, ea, b, eb):
        # only straight continuations (e.g. splits by connect), no corners. Measured shortly
        # before the meeting point: far enough against freehand jitter, near enough that curvature hardly counts
        length = lambda c: float(np.linalg.norm(np.diff(c.points, axis=0), axis=1).sum())
        meet = a.points[ea]
        depth = (meet - self.cam.eye) @ -self.cam.back
        dist = min(0.1 * min(length(a), length(b)), FUSE_MEASURE_PX * float(self._world_per_px(depth)))
        da, db = self._end_direction(a.points, ea, dist), self._end_direction(b.points, eb, dist)
        return not (da is None or db is None or da @ -db < math.cos(math.radians(FUSE_MAX_DEG)))

    @staticmethod
    def _fuse_pair(owner, a, ea, b, eb):
        """Join a and b at the common end into one line (meeting point: middle of the two ends)."""
        pa, wa = (a.points, a.widths) if ea == -1 else (a.points[::-1], a.widths[::-1])
        pb, wb = (b.points, b.widths) if eb == 0 else (b.points[::-1], b.widths[::-1])
        meet = (pa[-1] + pb[0]) / 2
        points = np.vstack([pa[:-1], meet, pb[1:]])
        widths = np.concatenate([wa[:-1], [(wa[-1] + wb[0]) / 2], wb[1:]])
        merged = inherit(Curve(points, a.plane_id if a.plane_id == b.plane_id else None, widths,
                               a.generated and b.generated), a)
        curves = owner.curves
        k = next(i for i, c in enumerate(curves) if c is a)
        curves[k] = merged
        curves.remove(b)

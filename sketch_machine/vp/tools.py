"""Extrude and connect tools."""
from .common import *  # noqa: F401,F403
from .. import extruding
from ..i18n import tr


class ToolsMixin:
    def start_extrude(self):
        before = (list(self.seg_selection), list(self.edge_selection))
        split = self._materialize_segments()
        result = self._start_extrude()
        self._extrude_undo = before if split else None  # Esc: undo the split again
        if split and self._mode != "extrude":
            self._undo_materialize()
        return result

    def _undo_materialize(self):
        """Aborted operation on partial edges: make the line whole again, selection as before."""
        before, self._extrude_undo = self._extrude_undo, None
        if before is None:
            return
        self.scene.undo()
        if self.scene._redo:
            self.scene._redo.pop()
        self.seg_selection, self.edge_selection = before
        self._changed()

    def _start_extrude(self):
        """X: extrude the selected lines immediately - the mouse sets the length, a click confirms. Result: normal
        lines (offset copy + connecting lines per extrude.rail_points) and surfaces in between
        (extruding.py). In surface mode the selected surfaces move up with it."""
        faces = []
        if self.ws.component == "face" and self.select_mode:
            faces = [o for o in self.selected_objects if isinstance(o, SurfaceObject)
                     and extruding.face_outline(self.scene, o)]
            if not faces:
                return self.notify(tr("Extrudieren: Flächen (Kurvenflächen, Füllflächen) wählen – Röhren und Lofts nicht"))
            curves = list({id(c): c for f in faces for c in extruding.face_outline(self.scene, f)}.values())
            walls = extruding.walls_of(self.scene, faces)
        else:
            curves = [c for c in (edges.ref_to_curve(self.scene, r) for r in dict.fromkeys(self.edge_selection))
                      if c is not None and not c.paint]
            walls = curves
        if not curves:
            self.status_changed.emit(tr("Extrudieren: erst Linien auswählen (Edit/Tab, Klick / Doppelklick)."))
            return
        pos = self._last_pos or QPointF(self.width() / 2, self.height() / 2)
        self._press_pos = self._last_pos = pos
        self._mode = "extrude"
        self._extrude = {"curves": curves, "walls": walls, "faces": faces,
                         "origin": np.vstack([c.points for c in curves]).mean(axis=0), "length": 0.0}
        self._extrude_set_axis("n")
        self.emit_status()
        self.update()

    def cancel_extrude(self):
        self._extrude = None
        self._mode = None
        self._undo_materialize()
        self._changed()

    def _extrude_set_axis(self, name):
        ex = self._extrude
        axes = {"x": np.array([1.0, 0, 0]), "y": np.array([0, 1.0, 0]), "z": np.array([0, 0, 1.0]),
                "n": self._face_normal(ex["faces"]) if ex["faces"] else self._surface_normal(ex["curves"])}
        ex["axis"], ex["axis_name"] = axes[name], name
        t = self.gizmo._axis_param(self._press_pos, ex["origin"], ex["axis"])
        ex["start_t"] = t if t is not None else 0.0
        self._extrude_update(self._last_pos)

    def _extrude_update(self, pos):
        ex = self._extrude
        t = self.gizmo._axis_param(pos, ex["origin"], ex["axis"])
        if t is not None:
            ex["length"] = t - ex["start_t"]
            if self._ctrl:  # Ctrl: length snaps like when moving (Ctrl+Shift: tenths)
                step = self.ws.snap_move * self._snap_step()
                ex["length"] = round(ex["length"] / step) * step

    def _extrude_plan(self):
        """(offset, lines, points of the connecting lines) of the running extrusion or None.
        Connected selected lines count as one (extrude.chain_rails)."""
        ex = self._extrude
        if ex is None or abs(ex["length"]) < 1e-6:
            return None
        curves = ex["curves"]
        if ex.get("rails_for") != ex["axis_name"]:  # only recompute when the axis changes
            size = max(float(np.linalg.norm(np.ptp(np.vstack([c.points for c in curves]), axis=0))), 1.0)
            ex["tol"] = 1e-5 * size
            # connecting lines only where walls arise (none between two selected surfaces)
            extra = extruding.knot_rails(extruding.knot_marks(self.scene, ex["walls"]))  # nodes with a kink, connections
            rails = extrude.chain_rails([c.points for c in ex["walls"]], ex["axis"], self.cam.back, ex["tol"], extra)
            ex["rails"] = extruding.snap_rails(rails, ex["walls"])
            ex["rails_for"] = ex["axis_name"]
        return ex["axis"] * ex["length"], curves, ex["rails"]

    def _extrude_preview(self):
        """Preview of the side surfaces of the running extrusion (one curtain per wall line)."""
        plan = self._extrude_plan()
        if plan is None or not self.ws.extrude_surface:  # off (right-click menu): extruding only pulls lines
            return []
        offset = plan[0]
        return [ExtrudeSurface("", [Curve(c.points.copy(), None)], direction=offset) for c in self._extrude["walls"]]

    def _extrude_preview_lines(self):
        """Preview lines: offset copies and connecting lines."""
        plan = self._extrude_plan()
        if plan is None:
            return []
        offset, curves, rails = plan
        out = [(c.points + offset, c.widths) for c in curves]
        w = float(curves[0].widths.mean())
        return out + [(np.array([p, p + offset]), np.full(2, components.width_near(curves, p, w))) for p in rails]

    def _finish_extrude(self):
        self._extrude_undo = None
        plan = self._extrude_plan()
        if plan is None:
            return
        offset, curves, rails = plan
        faces = self._extrude["faces"]
        self.scene.checkpoint()
        before = ({c.id for c in self.scene.curves}, {x.id for x in self.scene.surfaces})
        copies = extruding.apply(self.scene, curves, offset, rails, self._extrude["tol"], faces=faces,
                                 surfaces=self.ws.extrude_surface)
        kept = {id(c): keep for c, keep in self._consolidate_new(before)}
        # replace merged copies by the kept line (stays selected, X pulls on)
        swapped = []
        for sid, c in copies:
            if id(c) in kept:
                c = kept[id(c)]
                owner = self.scene.owner_of(c)
                if owner is None:  # the kept line was itself merged: no longer select
                    continue
                sid = owner.id
            swapped.append((sid, c))
        copies = list({id(c): (sid, c) for sid, c in swapped}.values())
        faces = [self._replaced.get(f.id, f) for f in faces] if getattr(self, "_replaced", None) else faces
        if faces:  # the surfaces stay selected: X again pulls them on
            self.selection = [f.id for f in faces]
            self.edge_selection = []
        else:  # leave the new copies selected: X again pulls on directly (in the same direction)
            self.selection = []
            self.edge_selection = [("line", sid, c.id) for sid, c in copies]
        self._last_extrude = ({c.id for _, c in copies}, offset / max(np.linalg.norm(offset), 1e-12))
        self._changed()

    def _behind_surface(self, pos):
        """Check function: which 3D points lie (seen from the cursor) clearly behind the frontmost
        drawing surface or the frontmost mesh under pos? One sees them through the tracing paper,
        but one should not snap there. Planes do not count: they are often huge and stand across the space."""
        surface, hit, _ = self._mesh_under(pos)
        if surface is None or hit is None:
            return lambda pts: np.zeros(len(pts), bool)
        origin, d = self.ray(pos)
        depth = (hit - self.cam.eye) @ -self.cam.back
        limit = (hit - origin) @ d + 2 * SNAP_PX * float(self._world_per_px(depth))
        return lambda pts: (np.asarray(pts) - origin) @ d > limit

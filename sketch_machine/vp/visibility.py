"""Visibility: drawing aids, X-ray, plane switches, hide/isolate, paint mode."""
from .common import *  # noqa: F401,F403
from ..i18n import tr


class VisibilityMixin:
    def set_planes_visible(self, visible):  # drawing aids: own planes and drawing surfaces
        self.planes_visible = visible
        self.toggles_changed.emit()
        self._changed()

    def set_xray(self, on):
        self.xray = on
        self.toggles_changed.emit()
        self._changed()

    def _shown_lines(self, include_paint=False):
        """[(stroke, line)] visible - like _curve_shown per line, but hidden items are determined only once per pass
        (per line it would be quadratic: in edit mode tens of thousands of queries on every mouse move)."""
        sc, out, hidden = self.scene, [], None
        for st in sc.strokes:
            if sc.is_hidden(st):
                continue
            for c in st.curves:
                if (not include_paint and c.paint) or not self._layer_visible(c):
                    continue
                if c.paint and c.plane_id is not None:
                    hidden = self._hidden_ids() if hidden is None else hidden
                    if c.plane_id in hidden:
                        continue
                out.append((st, c))
        return out

    def _visible_curves(self, include_paint=False):
        """Lines that can be clicked, selected and snapped to - hidden ones not, paint strokes only
        with include_paint (they are not selectable, but go along with their surface)."""
        return [c for _, c in self._shown_lines(include_paint)]

    def _visible_edges(self, include_paint=False):
        """[(ref, points)] of the visible lines (edge selection, rectangle, hover)."""
        return [(("line", st.id, c.id), c.points) for st, c in self._shown_lines(include_paint)]

    def _layer_visible(self, curve):
        """Is the line currently shown? (pencil, color lines and painting can each be hidden, top right; individually
        hidden lines not)"""
        layer = "paint" if curve.paint else "brush" if curve.style == "brush" else "lines"
        if curve.frame is not None and not self._flip_shown_curve(curve):  # flipbook: only the current drawing
            return False
        return self.ws.layers_visible[layer] and not curve.hidden

    def _hidden_ids(self):
        """ids of hidden objects (eye in the outliner, H; also via their null) - their painting is off too."""
        sc = self.scene
        return {o.id for o in list(sc.planes) + sc.meshes + sc.strokes + sc.surfaces + sc.nulls if sc.is_hidden(o)}

    def _curve_shown(self, owner, curve, hidden_ids=None):
        """Line visible: plane on at top right, not hidden individually or with its object; painting also not
        hidden with its surface."""
        # hidden_ids already contains all hidden stroke objects (also via their null): do not walk the chain of
        # nulls above them anew for each line
        known = hidden_ids is not None and type(owner) is StrokeObject
        gone = owner.id in hidden_ids if known else self.scene.is_hidden(owner)
        if gone or not self._layer_visible(curve):
            return False
        if curve.paint and curve.plane_id is not None:
            ids = self._hidden_ids() if hidden_ids is None else hidden_ids
            return curve.plane_id not in ids
        return True

    def set_layer_visible(self, name, on):
        """Show/hide lines, color lines or painting - display only; the eraser leaves hidden items
        alone."""
        self.ws.layers_visible[name] = bool(on)
        self.toggles_changed.emit()
        self._changed()

    def set_material_scale(self, value):
        """Global material scale of the surfaces (world units per texture unit, display only)."""
        self.ws.material_scale = max(0.01, float(value))
        for vp in self.ws.viewports:
            vp.update()

    def set_wireframe(self, on):
        """Wireframe: in X-ray, additionally show edges of imported meshes (overlay, all edges, also inside)."""
        self.ws.wireframe = bool(on)
        self.toggles_changed.emit()
        self._changed()

    def set_wire_opacity(self, value):
        self.ws.wire_opacity = max(0.0, min(1.0, value))
        for vp in self.ws.viewports:
            vp.update()

    def set_xray_opacity(self, value):
        """X-ray: opacity of the front layer; occluded parts scale along (renderer.XRAY_BEHIND)."""
        self.xray_opacity = max(0.0, min(1.0, value))
        for vp in self.ws.viewports:
            vp.update()

    def set_paint_mode(self, on):
        """Paint mode (S): pen and brush paint dead strokes lying flat on the surface."""
        self.ws.paint_mode = bool(on)
        if on and self.ws.draw_tool not in ("pen", "brush"):
            self.set_draw_tool(getattr(self.ws, "last_line_tool", "brush"))
        elif on and (self.select_mode or self.notes_mode):
            self.set_draw_tool(self.ws.draw_tool)
        self.notify(tr("Malmodus: Stift und Pinsel malen Farbe auf die Fläche (keine editierbaren Linien) – S zurück") if on else tr("Malmodus aus: Stift und Pinsel zeichnen Linien"))
        self.toggles_changed.emit()
        self.update()

    # --- Hide / isolate (H, Shift+H, Alt+H; eye in the outliner) ---
    def set_hidden(self, oid, hidden):
        """Show/hide object (eye in the outliner) - one undo step."""
        obj = self.scene.object_by_id(oid)
        if obj is None or obj.hidden == bool(hidden):
            return
        self.scene.checkpoint()
        obj.hidden = bool(hidden)
        if hidden:  # with the null, everything below it leaves the selection
            gone = {oid} | ({o.id for o in self.scene.descendants(obj)} if isinstance(obj, NullObject) else set())
            self.selection = [i for i in self.selection if i not in gone]
        self._after_visibility()

    def hide_selection(self):
        """H: hide selected - whole objects, in edit mode also single lines."""
        objs = [self.scene.object_by_id(i) for i in self.selection]
        objs = [o for o in objs if o is not None and not (isinstance(o, Plane) and o.preset)]
        curves = [c for c in (edges.ref_to_curve(self.scene, r) for r in self.edge_selection) if c is not None]
        curves += [edges.ref_to_curve(self.scene, ("line", r[1], r[2])) for r in self.seg_selection]
        curves = [c for c in curves if c is not None]
        if not objs and not curves:
            return self.notify(tr("Nichts gewählt zum Ausblenden"))
        self.scene.checkpoint()
        for o in objs:
            o.hidden = True
        for c in curves:
            c.hidden = True
        self._clear_selection_after_hide()
        self.notify(tr("Ausgeblendet: {0} Objekt(e), {1} Linie(n) – Alt+H zeigt alles wieder").format(len(objs), len(curves)))

    def isolate_selection(self):
        """Shift+H: show only the selection - hide everything else (Alt+H shows everything again)."""
        sc = self.scene
        keep_objs = set(self.selection)
        for o in [sc.object_by_id(i) for i in self.selection]:  # a null brings everything below it along, a child its null
            if isinstance(o, NullObject):
                keep_objs |= {d.id for d in sc.descendants(o)}
            if o is not None:
                keep_objs |= {n.id for n in sc.ancestors(o)}
        keep_curves = {id(c) for c in (edges.ref_to_curve(sc, r) for r in self.edge_selection) if c is not None}
        keep_curves |= {id(c) for c in (edges.ref_to_curve(sc, ("line", r[1], r[2])) for r in self.seg_selection)
                        if c is not None}
        if not keep_objs and not keep_curves:
            return self.notify(tr("Nichts gewählt zum Isolieren"))
        self.scene.checkpoint()
        for o in list(sc.custom) + sc.meshes + sc.surfaces + sc.nulls:
            if o.id not in keep_objs:
                o.hidden = True
        for st in sc.strokes:
            if st.id in keep_objs:
                continue
            if any(id(c) in keep_curves for c in st.curves):
                for c in st.curves:  # the object stays, only the selected lines in it
                    if id(c) not in keep_curves and not (c.paint and c.plane_id in keep_objs):
                        c.hidden = True
            else:
                st.hidden = True
        self._after_visibility()
        self.notify(tr("Isoliert: nur die Auswahl ist sichtbar – Alt+H zeigt alles wieder"))

    def unhide_all(self):
        """Alt+H: show everything again."""
        sc = self.scene
        objs = [o for o in list(sc.planes) + sc.meshes + sc.strokes + sc.surfaces + sc.nulls if o.hidden]
        curves = [c for st in sc.strokes for c in st.curves if c.hidden]
        if not objs and not curves:
            return self.notify(tr("Es ist nichts ausgeblendet"))
        self.scene.checkpoint()
        for o in objs:
            o.hidden = False
        for c in curves:
            c.hidden = False
        self._after_visibility()
        self.notify(tr("Wieder eingeblendet: {0} Objekt(e), {1} Linie(n)").format(len(objs), len(curves)))

    def _clear_selection_after_hide(self):
        self.selection, self.edge_selection, self.point_selection, self.seg_selection = [], [], [], []
        self._after_visibility()

    def _after_visibility(self):
        self.ws.target_cache = (None, None)
        self.ws.scene_changed.emit()
        self._changed()

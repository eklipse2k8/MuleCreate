"""Null objects and generators in the viewport: create (Alt+G, Objects menu), reparent (outliner), dissolve (Shift+G),
draw as an axis cross and click."""
from .common import *  # noqa: F401,F403
from ..i18n import tr

NULL_PICK_PX = 9  # a click this close to the axis cross counts as a hit
NULL_AXIS_PX = 26  # length of the axes on screen (same size at every distance)
KIND_NAMES = {"null": "Null", "symmetry": tr("Symmetrie"), "array": "Array"}


class NullMixin:
    # --- Create, reparent, dissolve ---
    def _tree_selection(self):
        """Selected objects that belong in the hierarchy (no planes), without those whose null is also selected."""
        objs = [o for o in self.selected_objects if hasattr(o, "parent")]
        ids = {o.id for o in objs}
        return [o for o in objs if not any(n.id in ids for n in self.scene.ancestors(o))]

    def create_null(self, kind="null"):
        """Alt+G (null) or Objects menu: new null/generator; the selected objects go under it. A null sits in
        the middle of the selection. Symmetry and array take position and rotation of the selected null (or of the null the
        selection lies in), otherwise they sit at the world origin (there lies the mirror plane or the pivot -
        moving in axis mode Alt+A, the objects then stay put). Without a selection a generator gets an
        empty stroke object that is drawn into from now on."""
        sc = self.scene
        picked = self._tree_selection()
        sc.checkpoint()
        origin = np.zeros(3)
        if kind == "null" and picked:
            boxes = [o.bounds() for o in self._with_descendants(picked) if not isinstance(o, NullObject)
                     and not (isinstance(o, StrokeObject) and not o.curves)]
            if boxes:
                origin = (np.min([b[0] for b in boxes], axis=0) + np.max([b[1] for b in boxes], axis=0)) / 2
        parent = sc.common_parent(picked) if picked else None
        frame = self._generator_frame(picked, parent) if kind != "null" else None
        null = sc.new_null(kind, frame.origin if frame else origin, frame.axes if frame else None, parent=parent)
        sc.set_parent(picked, null)
        made = ""
        if not picked and kind != "null":
            stroke = sc.new_stroke(parent=null.id)
            made = tr(" – neue Linien landen in „{0}“ darunter").format(stroke.name)
        if kind == "symmetry":
            null.params["side"] = self._symmetry_side(null)
        self.selection, self.edge_selection, self.point_selection, self.seg_selection = [null.id], [], [], []
        self.ws.target_cache = (None, None)
        where = (tr("in der Mitte der Auswahl") if kind == "null" and picked else
                 tr("an „{0}“").format(frame.name) if frame else tr("am Weltursprung"))
        self.notify(tr("{0} „{1}“ {2} mit {3} Objekt(en){4}").format(KIND_NAMES[kind], null.name, where, len(picked), made))
        self._changed()
        return null

    def _generator_frame(self, picked, parent):
        """Null whose position and rotation a new generator takes over: the only selected null, otherwise the null the
        selected objects all lie in - or None (world origin)."""
        nulls = [o for o in picked if isinstance(o, NullObject)]
        if len(nulls) == 1:
            return nulls[0]
        return self.scene.null_by_id(parent) if parent is not None else None

    def _symmetry_side(self, null):
        """Kept side of a new symmetry: the one its children lie on (on average)."""
        from .. import generators
        n, o = generators.mirror_plane(null)
        pts = [c.points for x in self.scene.descendants(null) if isinstance(x, StrokeObject) for c in x.curves]
        if not pts:
            return 1
        return 1 if float(np.mean((np.vstack(pts) - o) @ n)) >= 0 else -1

    def set_parent(self, ids, null_id):
        """Outliner (drag): put objects under the null null_id (None: top level) - one undo step."""
        sc = self.scene
        null = sc.null_by_id(null_id) if null_id is not None else None
        if null_id is not None and null is None:
            return
        objs = [o for o in (sc.object_by_id(i) for i in ids) if o is not None and hasattr(o, "parent")
                and o.__dict__.get("flipbook") is None]  # flipbook drawings belong to no null
        objs = [o for o in objs if not (null is not None and isinstance(o, NullObject) and
                                        (o is null or null in sc.descendants(o)))]
        if not objs or all(o.parent == null_id for o in objs):
            return
        sc.checkpoint()
        moved = sc.set_parent(objs, null)
        self.ws.target_cache = (None, None)
        self.notify(tr("{0} Objekt(e) ").format(len(moved)) + (tr("unter „{0}“").format(null.name) if null else tr("auf die oberste Ebene")))
        self._changed()

    def set_null_color(self, ids, rgb):
        """Outliner (right-click -> color): color strip of the selected nulls (None: none) - one undo step."""
        nulls = [n for n in (self.scene.null_by_id(i) for i in ids) if n is not None]
        rgb = tuple(int(x) for x in rgb) if rgb else None
        if not nulls or all(n.color == rgb for n in nulls):
            return
        self.scene.checkpoint()
        for n in nulls:
            n.color = rgb
        self._changed()

    def dissolve_null(self):
        """Shift+G: dissolve selected nulls - the objects below them stay where and as they are (without instances)."""
        sc = self.scene
        nulls = [o for o in self.selected_objects if isinstance(o, NullObject)]
        if not nulls:
            return self.notify(tr("Auflösen: erst ein Null, eine Symmetrie oder ein Array wählen"))
        sc.checkpoint()
        kids = []
        for n in nulls:
            kids += sc.dissolve_null(n)
        self.selection = [o.id for o in kids if sc.object_by_id(o.id) is not None]
        self.ws.target_cache = (None, None)
        self.notify(tr("{0} Gruppe(n) aufgelöst – {1} Objekt(e) eine Stufe höher").format(len(nulls), len(kids)))
        self._changed()

    def convert_generators(self):
        """Alt+C: turn selected generators (or those in selected nulls) into real geometry - one undo step."""
        from .. import convert
        sc = self.scene
        picked = [o for o in self.selected_objects if isinstance(o, NullObject)]
        gens = [o for o in picked if o.kind != "null"]
        gens += [d for o in picked if o.kind == "null" for d in sc.descendants(o)
                 if isinstance(d, NullObject) and d.kind != "null"]
        top = [g for g in dict.fromkeys(gens) if not any(a in gens for a in sc.ancestors(g))]  # the outer one does the inner one
        if not top:
            return self.notify(tr("Konvertieren: erst eine Symmetrie oder ein Array wählen"))
        sc.checkpoint()
        texts = [convert.convert(sc, g) for g in top]
        self.selection = [g.id for g in top]
        self.ws.target_cache = (None, None)
        self._changed()
        self.notify(tr("Konvertiert: ") + "; ".join(texts))

    def set_null_param(self, nid, key, value, rebuild=True):
        """Change a setting of a generator (outliner) - one undo step; continuous values (rebuild=False: sliders,
        number fields) merge quick changes and do not rebuild the outliner (it stays usable)."""
        null = self.scene.null_by_id(nid)
        if null is None or null.params.get(key) == value:
            return
        self.scene.checkpoint(burst=None if rebuild else ("null", nid, key))
        null.params[key] = value
        self.ws.target_cache = (None, None)
        if rebuild:
            self._changed()
        else:
            self.update_all()

    def assign_array_line(self, nid, key):
        """Array along a line: the selected line (edit, edge mode) becomes the path (key "path") or the up line."""
        refs = [r for r in self.edge_selection if r[0] == "line"]
        curve = edges.ref_to_curve(self.scene, refs[0]) if refs else None
        if curve is None:
            return self.notify(tr("Erst eine Linie wählen (Edit, Kantenmodus), dann hier übernehmen"))
        self.set_null_param(nid, key, curve.id)
        self.notify((tr("Pfad") if key == "path" else tr("Up-Linie")) + tr(" des Arrays gesetzt"))

    def _mirror_snap(self, pos):
        """Snap to the mirror plane (like "clamp points to axis" in Cinema 4D, but already while drawing):
        if the pen is near the plane of a symmetry the active stroke object lies in, the point lands exactly
        on it - shifted along the drawing surface, so the seam meets the mirror. Otherwise None."""
        if pos is None:
            return None
        ref = self._surface_hit(pos) if self._mirror_syms() else None
        return None if ref is None else self._mirror_snap_at(ref)

    def _active_syms(self):
        """Symmetries the active stroke object lies in (new lines land there)."""
        stroke = self.scene.active_stroke
        if stroke is None or stroke not in self.scene.strokes:
            return []
        from .. import generators
        return [n for n in self.scene.ancestors(stroke) if n.kind == "symmetry" and generators.is_on(n)]

    def _mirror_syms(self):
        return self._active_syms() if self.ws.magnet else []  # snap only with magnet

    def _mirror_snap_at(self, ref):
        """Point ref on the drawing surface -> the same point on the nearby mirror plane (END_SNAP_PX) or None."""
        from .. import generators
        syms = self._mirror_syms()
        if not syms:
            return None
        ref = np.asarray(ref, float)
        surface = self.scene.active_surface
        m = surface.normal if isinstance(surface, Plane) else None
        best = None
        for null in syms:
            n, o = generators.mirror_plane(null)
            dist = float((ref - o) @ n)
            d = n - m * float(m @ n) if m is not None else n  # along the drawing plane to the mirror plane
            if abs(float(n @ d)) < 1e-6:
                continue  # drawing plane parallel to the mirror plane: no seam on it
            point = ref - d * (dist / float(n @ d))
            screen, ok = self.project(np.array([ref, point]))
            if not ok.all():
                continue
            px = float(np.hypot(*(screen[0] - screen[1])))
            if px < END_SNAP_PX and (best is None or px < best[0]):
                best = (px, point)
        return None if best is None else best[1]

    # --- Click copies: selects the generator (like in Cinema 4D) ---
    def _instance_proxies(self):
        """Pick proxies of the surface copies; owner = the outermost generator that produces them. Only for selecting
        (not for drawing on - the original is edited)."""
        from .. import generators
        from ..geometry import Geometry
        from ..scene import PickProxy
        from .display_lists import _GEN_CACHE
        copies = generators.copies_by_object(self.scene)
        out = []
        for s in self._visible_surfaces():
            mesh = s.fill_mesh() if s.id in copies else None
            if mesh is None:
                continue
            for key, ops in copies[s.id]:
                if generators.is_original(ops):
                    continue
                gen = self.scene.null_by_id(key[-1][0])
                verts, tris = _GEN_CACHE.get((mesh[0], mesh[1]), generators.ops_key(ops),
                                             lambda ops=ops: generators.apply_mesh(mesh[0], mesh[1], ops))
                if not len(tris):
                    continue
                proxy = _GEN_CACHE.get((verts, tris), ("proxy",), lambda v=verts, t=tris: PickProxy(Geometry(v, t), None))
                proxy.owner = gen
                out.append(proxy)
        return out

    def _instance_line_under(self, pos):
        """Generator whose line copy lies under the cursor (PICK_PX), otherwise None."""
        from .. import generators
        copies = generators.copies_by_object(self.scene)
        p = np.array([pos.x(), pos.y()], float)
        best, hit = PICK_PX, None
        for st in self.scene.strokes:
            if st.id not in copies:
                continue
            for c in st.curves:
                if not self._curve_shown(st, c) or c.paint:
                    continue
                for key, ops in copies[st.id]:
                    if generators.is_original(ops):
                        continue
                    for pts, _ in generators.apply_polyline(c.points, ops):
                        screen, ok = self.project(pts)
                        if not ok.any():
                            continue
                        a, b = screen[:-1], screen[1:]
                        ab = b - a
                        t = np.clip(np.einsum("ij,ij->i", p - a, ab) / np.maximum(np.einsum("ij,ij->i", ab, ab), 1e-9), 0, 1)
                        d = np.linalg.norm(a + ab * t[:, None] - p, axis=1)
                        d[~(ok[:-1] & ok[1:])] = np.inf
                        if d.min() < best:
                            best, hit = float(d.min()), self.scene.null_by_id(key[-1][0])
        return hit

    def _instance_surface_under(self, pos):
        """(generator or None, distance) of the frontmost surface copy under the cursor - checked against real surfaces:
        if a real one lies in front, None."""
        proxies = self._instance_proxies()
        if not proxies:
            return None
        obj, _, _ = self._mesh_samples([pos], self._pickables() + proxies, exact=False)[0]
        return obj if isinstance(obj, NullObject) else None

    # --- Display and hits ---
    def _visible_nulls(self):
        if not self.planes_visible:  # axis crosses belong to the drawing aids
            return []
        # remembered while the draw lists are valid (rotating, painting): with USD hierarchies thousands of nulls per frame
        key = (getattr(self, "_lists_cache", None), self.scene, len(self.scene.nulls))
        memo = getattr(self, "_vis_nulls_memo", None)
        if memo is not None and memo[0][0] is key[0] and memo[0][1] is key[1] and memo[0][2] == key[2]                 and key[0] is not None and not getattr(self, "_lists_dirty", True):
            return memo[1]
        out = [n for n in self.scene.nulls if not self.scene.is_hidden(n)]
        self._vis_nulls_memo = (key, out)
        return out

    def _null_screen(self, null):
        """(center, [(axis end, color)]) on screen or None (behind the camera)."""
        return self._nulls_screen([null])[0]

    def _nulls_screen(self, nulls):
        """_null_screen for many nulls at once (one projection for all - USD hierarchies have dozens)."""
        if not nulls:
            return []
        eps = max(self.cam.dist, 1e-3) * 1e-3
        origins = np.array([n.origin for n in nulls], float)
        ends = np.concatenate([origins[:, None, :], origins[:, None, :] + np.array([n.axes.T for n in nulls]) * eps],
                              axis=1)  # (N, 4, 3): center + three axis ends
        screen, ok = self.project(ends.reshape(-1, 3))
        screen, ok = screen.reshape(-1, 4, 2), ok.reshape(-1, 4)
        out = []
        for s, k in zip(screen, ok):
            if not k[0]:
                out.append(None)
                continue
            c = s[0]
            axes = []
            for j, (_, _, color) in enumerate(AXES):
                d = s[j + 1] - c if k[j + 1] else np.zeros(2)
                length = float(np.hypot(*d))
                d = d / length * NULL_AXIS_PX if length > 1e-9 else np.zeros(2)
                axes.append((c + d, color))
            out.append((c, axes))
        return out

    def _null_under(self, pos):
        best, hit = NULL_PICK_PX, None
        p = np.array([pos.x(), pos.y()], float)
        nulls = self._visible_nulls()
        for null, s in zip(nulls, self._nulls_screen(nulls)):
            if s is None:
                continue
            c, axes = s
            for end, _ in [(c, None)] + axes:  # center or along an axis
                ab = end - c
                t = float(np.clip((p - c) @ ab / max(ab @ ab, 1e-9), 0, 1)) if ab @ ab > 0 else 0.0
                d = float(np.linalg.norm(c + ab * t - p))
                if d < best:
                    best, hit = d, null
        return hit

    def _draw_nulls(self, p):
        """Axis cross per null (selected: thicker, with ring); generators with a small mark in the center."""
        selected = set(self.selection) if self.select_mode else set()
        nulls = sorted(self._visible_nulls(), key=lambda n: n.id in selected)  # selected on top
        marks = [(null, s) for null, s in zip(nulls, self._nulls_screen(nulls)) if s is not None]
        reach = NULL_AXIS_PX + 4
        w, h = self.width(), self.height()
        shown = [(null, s) for null, s in marks if -reach < s[0][0] < w + reach and -reach < s[0][1] < h + reach]
        if shown:  # all in one image (one each per null costs ~10 ms per frame with USD hierarchies)
            cs = np.array([s[0] for _, s in shown])
            x0, y0 = cs.min(axis=0) - reach
            x1, y1 = cs.max(axis=0) + reach

            def draw(q):
                for null, (c, axes) in shown:
                    sel = null.id in selected
                    o = QPointF(c[0] - x0, c[1] - y0)
                    for end, color in axes:
                        q.setPen(QPen(color, 2.4 if sel else 1.4))
                        q.drawLine(o, QPointF(end[0] - x0, end[1] - y0))
                    ring = QColor(SELECTED_STROKE_COLOR if sel else theme.GRAPHITE)
                    q.setPen(QPen(ring, 1.6 if sel else 1.0))
                    q.setBrush(QColor(255, 255, 255, 200))
                    if null.kind == "symmetry":  # diamond: mirrored
                        r = 5.5
                        q.drawPolygon(QPolygonF([o + QPointF(0, -r), o + QPointF(r, 0), o + QPointF(0, r),
                                                 o + QPointF(-r, 0)]))
                    elif null.kind == "array":  # square: multiplied
                        q.drawRect(QRectF(o.x() - 4, o.y() - 4, 8, 8))
                    else:
                        q.drawEllipse(o, 3.5, 3.5)

            self._raster(p, x0, y0, x1 - x0, y1 - y0, draw)
        for null, _ in marks:
            if null.id in selected and null.kind == "symmetry" and null.params.get("on", True):
                self._draw_mirror_plane(p, null)
        if not self.select_mode and not self.notes_mode and self.planes_visible:  # drawing into a symmetry:
            for null in self._active_syms():  # show their plane subtly
                if not self.scene.is_hidden(null):
                    self._draw_mirror_plane(p, null, alpha=80)

    def _draw_mirror_plane(self, p, null, alpha=170):
        """Selected symmetry: its mirror plane as a dashed rectangle around the content (kept side: arrow)."""
        from .. import arrays, generators
        n, o = generators.mirror_plane(null)
        axis = SYMMETRY_PLANES.get(null.params.get("plane", "zy"), 0)
        u, v = (null.axes[:, k] for k in range(3) if k != axis)
        box = arrays.content_box(self.scene, null)
        if box is not None:
            pts = np.array([[x, y, z] for x in box[:, 0] for y in box[:, 1] for z in box[:, 2]]) if False else \
                np.array([[a, b, c] for a in (box[0][0], box[1][0]) for b in (box[0][1], box[1][1])
                          for c in (box[0][2], box[1][2])])
            least = 0.35 * float(np.linalg.norm(box[1] - box[0])) + 0.2  # flat content: still clearly visible
            du = max(np.abs((pts - o) @ u).max() * 1.15, least)
            dv = max(np.abs((pts - o) @ v).max() * 1.15, least)
        else:
            du = dv = 1.0
        corners = np.array([o - u * du - v * dv, o + u * du - v * dv, o + u * du + v * dv, o - u * du + v * dv,
                            o - u * du - v * dv])
        color = QColor(SELECTED_STROKE_COLOR)
        color.setAlpha(alpha)
        p.setPen(QPen(color, 1.2, Qt.DashLine))
        p.setBrush(Qt.NoBrush)
        self.draw_polyline(p, corners)
        size = 0.25 * min(du, dv)
        p.setPen(QPen(color, 1.6))
        self.draw_polyline(p, np.array([o, o + n * size]))  # points to the kept side

"""Display lists for the renderer: strokes, surfaces, planes, meshes.

Generators (symmetry, array): objects below them are multiplied here - the original cut at the mirror plane,
the copies cut and offset (generators.py). Copies are pure display: they show no selection
or active coloring (the original is edited), lines on them belong to the copy of their surface."""
from .common import *  # noqa: F401,F403
from .. import counters, lru
from .. import generators

_GEN_CACHE = generators.LRU()


DRAG_PREVIEW_RES = 0.5  # surfaces that change during a drag: shown at this resolution (full again on release)


def _preview_mesh(surface):
    """fill_mesh of the surface at drag resolution (own entry in the cache, the surface stays unchanged)."""
    old = surface.resolution
    surface.resolution = old * DRAG_PREVIEW_RES
    try:
        return surface.fill_mesh()
    finally:
        surface.resolution = old


class _MeshInstance:
    """Copy of a mesh for the renderer: same geometry, other matrix, own display id."""
    __slots__ = ("geo", "xform", "id", "missing", "hidden")

    def __init__(self, geo, xform, vid):
        self.geo, self.xform, self.id, self.missing, self.hidden = geo, xform, vid, False, False


class DisplayListMixin:
    def _note_glow(self):
        """Notes mode with a selected note: the parts it is connected to -> ({object id: strength},
        {line id: strength}); 1 = part at the end of a leader line (on a line: only this line), 0.5 = arm of the
        octopus. If an anchor point is clicked (ws.active_anchor), only its parts."""
        ws = self.ws
        if not (self.notes_active and ws.notes_visible) or ws.active_note is None or getattr(self, "_clean_frame", False):
            return {}, {}
        note = self.scene.note_by_id(ws.active_note)
        if note is None or not any(n is note for n in self.note_list()):
            return {}, {}
        focus = ws.active_anchor[1] if ws.active_anchor and ws.active_anchor[0] == note.id else None
        objs, lines = {}, {}
        for j, a in enumerate(note.anchors):
            if focus is not None and j != focus:
                continue
            if a.curve_id is not None:
                lines[a.curve_id] = 1.0
            else:
                oid = self._anchor_object(note.id, j, a.point)
                if oid is not None:
                    objs[oid] = 1.0
            for m in a.members:
                if m.curve_id is not None:
                    lines.setdefault(m.curve_id, 0.5)
                else:
                    obj = self.scene.object_by_id(m.obj_id)
                    for part in (self.scene.descendants(obj) if obj in self.scene.nulls else [obj]):
                        if part is not None:  # a null: everything in it
                            objs.setdefault(part.id, 0.5)
        return objs, lines

    def _anchor_object(self, nid, j, point):
        """id of the object at the fixed anchor point (as in the Sketch Brief: nearest surface, mesh or line) - remembered."""
        from ..brief import _locate
        key = (id(self.scene), nid, j, np.asarray(point, float).tobytes())
        cache = self.__dict__.setdefault("_anchor_hits", {})
        if key not in cache:
            lru.trim(cache, 4096)
            vis = {"surfaces": [s for s in self._visible_surfaces() if not s.aid], "meshes": self._visible_meshes(),
                   "curves": self._shown_lines()}
            hit = _locate(vis, point, max(0.005 * float(self.cam.dist), 1e-3))
            cache[key] = hit[1].id if hit is not None else None
        return cache[key]

    @staticmethod
    def _glow_surface(entry, strength, outlines):
        """Surface entry tinted magenta, with a magenta outline (selected note, connected part)."""
        glaze, mix, _, alpha = NOTE_GLOW[strength]
        line = _rgba(theme.OCTOPUS)
        entry["state"] = (*line[:3], max(glaze, entry["state"][3]))
        entry["line"] = (*line[:3], alpha)
        entry["outlines"] = outlines()
        entry["emphasis"] = 1
        return entry

    def _stroke_draw_list(self):
        """All lines plus the stroke currently being created (scene and live part together)."""
        return self._scene_stroke_list() + self._live_draw_list()

    def _scene_stroke_list(self, reuse=False):
        """All lines of the scene as (points, widths, rgba) for the ribbons - without the stroke currently being created
        (_live_draw_list): while drawing, this part stays from the last frame.
        reuse: only the highlight under the mouse has changed - the preparatory work over the whole scene (owners,
        hidden items, outer lines of surfaces, generator copies) is valid from last time.
        Highlights (selection, hover, connect) color the line itself instead of laying a second one over it
        - otherwise the graphite stroke would show through the gaps of the pencil grain."""
        selected = set(self.selection)
        tint = {}  # edge reference -> rgba
        # colors of the surface (selection, hover): opacity 2 = the stroke shader shows them at full brightness, without
        # light, shadow and tint from helper planes (harbor test 10.11.: selected lines were barely recognizable)
        ui = lambda color: (*_rgba(color)[:3], 2.0)
        if self._extrude:
            tint.update({edges.curve_to_ref(self.scene, c): ui(CONNECT_COLOR) for c in self._extrude["curves"]})
        elif self.edge_selection:
            # selected plus coupled edges = the edges the transform target moves. The selected ones themselves always
            # from the selection: with a partial edge involved the target moves it as partial edges (a ComponentGroup instead of
            # EdgeGroup) - otherwise the whole lines stayed gray but moved along (Alpaka handlebar 14.11.)
            sel = ui(SELECTED_STROKE_COLOR)
            tint.update({r: sel for r in self.edge_selection})
            target = self.transform_target
            tint.update({r: sel for g in (target.items if target else ())
                         if isinstance(g, edges.EdgeGroup) for r in g.refs})
        if self.select_mode and self._select_hover is not None:
            tint[self._select_hover[0]] = ui(CONNECT_COLOR)
        glow_objs, glow_lines = self._note_glow()
        for cid, strength in glow_lines.items():  # selected note: connected lines magenta
            curve = self.scene.curve_by_id(cid)
            owner = self.scene.owner_of(curve) if curve is not None else None
            if owner is not None:
                tint[("line", owner.id, cid)] = self._mix(_rgba(STROKE_COLOR), _rgba(theme.OCTOPUS), NOTE_GLOW[strength][1])
        tint.update({r: _rgba(c) for r, c in getattr(self, "_extra_tint", {}).items()})  # clean_image(lines=…)
        seg_tint = {}  # (stroke_id, line_id) -> {(a, b): rgba} - partial edges
        for r in self.seg_selection:
            seg_tint.setdefault(r[1:3], {})[r[3:5]] = ui(SELECTED_STROKE_COLOR)
        if self.select_mode and self._select_hover is not None and self._select_hover[0][0] == "seg":
            r = self._select_hover[0]
            seg_tint.setdefault(r[1:3], {})[r[3:5]] = ui(CONNECT_COLOR)
        paper = np.array(_rgba(theme.PAPER)[:3])
        out = []
        edge_glow = self.select_mode and self.ws.component == "edge"
        pre = self.__dict__.get("_stroke_pre") if reuse else None
        if pre is not None and pre[0] is self.scene and pre[1] == bool(self.select_mode):
            owners, hidden_ids, edge_ids, copies, keysets = pre[2:]
        else:
            owners = self._line_owners()
            hidden_ids = self._hidden_ids()
            # edit mode: outer lines of surfaces (outline, border curves, cross-sections) dark petrol - belong to the surface
            shown = {id(c) for c in self._visible_curves()} if self.select_mode else None
            edge_ids = {c.id for s in self._visible_surfaces() for c in self._edge_lines(s, shown)} if self.select_mode else set()
            copies = generators.copies_by_object(self.scene)
            keysets = {oid: {k for k, _ in seqs} for oid, seqs in copies.items()}
            self._stroke_pre = (self.scene, bool(self.select_mode), owners, hidden_ids, edge_ids, copies, keysets)
        edge_color = _rgba(theme.EDGE_LINE_COLOR)
        painted = []  # (order, entry): painting strokes, the newest last (lies on top)
        # entries remembered per line object: if nothing changed on an object (same lines in the same state,
        # same coloring and visibility), its entries from the last frame apply - during a drag only
        # what can change in this frame is assembled (harbor 10.11.: otherwise all ~2,900 lines per frame)
        memos = self.__dict__.setdefault("_owner_memo", {})
        tint_of, seg_of = {}, {}
        for r, col in tint.items():
            if r is not None:  # (line without object, e.g. a preview: belongs to none)
                tint_of.setdefault(r[1], []).append((r, col))
        for (oid, cid), parts in seg_tint.items():
            seg_of.setdefault(oid, []).append((cid, tuple(sorted(parts.items()))))
        shared = (id(self.scene), edge_color, edge_glow, tuple(paper), bool(self.gizmo.dragging), id(owners),
                  frozenset(hidden_ids), tuple(sorted(self.ws.layers_visible.items())), bool(self.select_mode),
                  theme.COLOR_COMPRESS, theme.COLOR_VIEW, theme.dark, theme.PAPER.rgba(),
                  tuple(np.asarray(pl.normal, float).tobytes() for pl in self.scene.planes))
        self._owner_memo_keep = owners  # keeps the id valid
        faint = getattr(self, "_faint", ())  # clean_image(faint=…): weakly highlighted (note octopus)
        for owner in self.scene.strokes:
            base = ui(SELECTED_STROKE_COLOR) if owner.id in selected else _rgba(STROKE_COLOR)
            if owner.id in faint and owner.id not in selected:
                base = self._mix(base, _rgba(SELECTED_STROKE_COLOR), FAINT_MIX)
            if owner.id in glow_objs and owner.id not in selected:
                base = self._mix(base, _rgba(theme.OCTOPUS), NOTE_GLOW[glow_objs[owner.id]][1])
            idle = _rgba(STROKE_COLOR)
            if edge_glow and owner.id not in selected:  # edge mode: highlight lines slightly
                base = self._mix(base, _rgba(SELECTED_STROKE_COLOR), EDIT_GLOW)
            if edge_glow:
                idle = self._mix(idle, _rgba(SELECTED_STROKE_COLOR), EDIT_GLOW)
            if owner.id not in copies:
                key = (shared, base, owner.id in selected, tuple(map(id, owner.curves)),
                       sum(c.__dict__.get("_v", 0) for c in owner.curves),
                       tuple(sorted(tint_of.get(owner.id, ()))), tuple(sorted(seg_of.get(owner.id, ()))),
                       frozenset(c.id for c in owner.curves if c.id in edge_ids) if edge_ids else None)
                memo = memos.get(owner.id)
                counters.C["strich_objekte_geprueft"] += 1
                if memo is None or memo[0] != key or memo[3] is not owner:
                    counters.C["strich_objekte"] += 1
                    mine, mine_paint = [], []
                    self._owner_lines(owner, mine, mine_paint, base, tint, seg_tint, edge_ids, edge_color, edge_glow,
                                      owners, hidden_ids, paper, selected)
                    lru.trim(memos, 4096)
                    memo = memos[owner.id] = (key, mine, mine_paint, owner, list(owner.curves))  # (holds the lines fast)
                elif self.VERIFY_LISTS:
                    self._verify_owner(owner, memo, base, tint, seg_tint, edge_ids, edge_color, edge_glow, owners,
                                       hidden_ids, paper, selected)
                out += memo[1]
                painted += memo[2]
                continue
            # under a generator: the original (cut) with its state, the copies neutral - they show
            # neither selection nor hover (the original is edited)
            mine, mine_paint, plain, plain_paint = [], [], [], []
            self._owner_lines(owner, mine, mine_paint, base, tint, seg_tint, edge_ids, edge_color, edge_glow,
                              owners, hidden_ids, paper, selected)
            self._owner_lines(owner, plain, plain_paint, idle, {}, {}, set(), edge_color, edge_glow,
                              owners, hidden_ids, paper, set())
            for key, ops in copies[owner.id]:
                # clean image (brief): copies highlighted like the original - the focus including the mirror half
                src, src_paint = ((mine, mine_paint) if generators.is_original(ops) or self._clean_copies()
                                  else (plain, plain_paint))
                out += self._instanced_lines(src, key, ops, keysets)
                painted += [(e[0], e[1], x) for e in src_paint for x in self._instanced_lines([e[2]], key, ops, keysets)]
        if painted:  # painting at the front of the buffer (own pass), depth by order
            painted.sort(key=lambda p: (p[0], p[1]))
            n = len(painted)
            out = [(*e[:5], (e[5], (k + 1) / (n + 1))) for k, (_, _, e) in enumerate(painted)] + out
        return out

    VERIFY_LISTS = False  # tests: check remembered entries of a line object against freshly assembled ones

    @staticmethod
    def _verify_stroke_list(fast, full):
        """Check mode: the stroke list from the fast path (only highlight changed) must equal the fully built one."""
        def same(a, b):
            if isinstance(a, np.ndarray) or isinstance(b, np.ndarray):
                return a is b or (np.shape(a) == np.shape(b) and np.array_equal(a, b))
            if isinstance(a, (tuple, list)) and isinstance(b, (tuple, list)):
                return len(a) == len(b) and all(same(x, y) for x, y in zip(a, b))
            return a == b
        assert len(fast) == len(full), f"Strichliste nach Hover: {len(fast)} statt {len(full)} Einträge"
        for k, (a, b) in enumerate(zip(fast, full)):
            assert same(a, b), f"Strichliste nach Hover weicht bei Eintrag {k} vom vollen Neubau ab"

    def _verify_owner(self, owner, memo, *args):
        mine, mine_paint = [], []
        self._owner_lines(owner, mine, mine_paint, *args)

        def same(a, b):
            if isinstance(a, np.ndarray) or isinstance(b, np.ndarray):
                return a is b or (np.shape(a) == np.shape(b) and np.array_equal(a, b))
            if isinstance(a, (tuple, list)) and isinstance(b, (tuple, list)):
                return len(a) == len(b) and all(same(x, y) for x, y in zip(a, b))
            return a == b
        assert same(mine, memo[1]) and same(mine_paint, memo[2]), f"gemerkte Strich-Einträge von „{owner.name}“ veraltet"

    def _live_draw_list(self):
        """What changes with every mouse movement: strokes currently being created (also in another viewport),
        preview of an extrusion, the connect line. Cheap - rebuilt in every frame."""
        out = []
        copies = keysets = None
        for vp in self.ws.viewports:  # strokes currently being created - also in another viewport
            color = _rgba(STRAIGHT_COLOR if vp._straight else DRAWING_COLOR)
            on = [s.id for s in vp._drawing_surfaces()]  # belong to the drawing surface
            if vp.ws.draw_tool == "brush" and not vp._straight:  # brush: in color and texture already while painting
                current = [(pts, vp._widths_for(pts, pressure=True), (*theme.display_rgb(vp.ws.paint_color), 1.0), 2.0, on)
                           for pts, _ in vp._finished_runs()]
            else:
                current = [(pts, vp._widths_for(pts, pressure=True), color, 1.0, on) for pts, _ in vp._finished_runs()]
            target = vp.scene.active_stroke
            # copies only if the target lies under a generator (searching the whole scene cost about 30 ms per frame
            # with large USD hierarchies - with painting, on every mouse movement)
            if current and copies is None and target is not None and \
                    any(n.kind != "null" for n in self.scene.ancestors(target)):
                copies = generators.copies_by_object(self.scene)
                keysets = {oid: {k for k, _ in seqs} for oid, seqs in copies.items()}
            if current and copies is not None and target is not None and target.id in copies and vp._mode == "draw":
                # draws into an object under a generator: the stroke is mirrored/copied already while drawing
                current = [x for key, ops in copies[target.id]
                           for x in self._instanced_lines([(np.asarray(e[0], float), *e[1:]) for e in current],
                                                          key, ops, keysets)]
            out += current
        for vp in self.ws.viewports:  # preview of an extrusion: copy and connecting lines
            out += [(pts, wid, _rgba(CONNECT_COLOR)) for pts, wid in vp._extrude_preview_lines()]
        return out

    def _clean_copies(self):
        """Clean image (clean_image): copies under generators show the state of the original."""
        return getattr(self, "_clean_frame", False)

    @staticmethod
    def _instanced_lines(entries, key, ops, keysets):
        """Stroke entries for a copy (key, ops) of a generator: cut/offset. The original keeps its
        membership; lines of a copy belong to the copy of their surface (same sequence), otherwise to none."""
        res = []
        orig = generators.is_original(ops)
        okey = generators.ops_key(ops)
        for e in entries:
            paint = len(e) > 5
            src = (e[0], e[1]) + ((e[5],) if paint else ())
            # normals of the painting right here as float32: outside the cache a new array would arise per frame,
            # and the stroke upload (fingerprint by identity) would reprocess all strokes every frame
            pieces = _GEN_CACHE.get(src, okey, lambda e=e, paint=paint: [
                (pts, (ex[0], np.ascontiguousarray(ex[1], dtype="f4")) if paint else ex)
                for pts, ex in generators.apply_polyline(
                    e[0], ops, (np.asarray(e[1], float),) + ((np.asarray(e[5], float),) if paint else ()),
                    normal_slots=(1,) if paint else ())])
            own = list(e[4]) if len(e) > 4 else []
            if not orig:
                own = [generators.vid(o, key) for o in own if key in keysets.get(o, ())]
            for pts, ex in pieces:
                item = (pts, ex[0], e[2], e[3] if len(e) > 3 else 1.0, own)
                if paint:
                    item += (ex[1],)
                res.append(item)
        return res

    def _owner_lines(self, owner, out, painted, base, tint, seg_tint, edge_ids, edge_color, edge_glow, owners,
                     hidden_ids, paper, selected):
        """Append entries of the lines of a stroke object (color by state) to out or painted."""
        for c in owner.curves:
            if c.frame is not None:  # flipbook drawings: own buffer (_flip_draw_data), frame change loads nothing anew
                continue
            if not self._curve_shown(owner, c, hidden_ids):
                continue
            if c.paint:
                color = (*theme.display_rgb(c.color), 1.0) if c.style == "brush" and c.color is not None \
                    else _rgba(STROKE_COLOR)
                painted.append((c.seq, c.id, (c.points, c.widths, color, 2.0 if c.style == "brush" else 1.0,
                                              ([c.plane_id] if c.plane_id is not None else []) + owners.get(c.id, []),
                                              self._paint_normals(c))))
                continue
            ref = ("line", owner.id, c.id)
            own = ([c.plane_id] if c.plane_id is not None else []) + owners.get(c.id, [])
            color = tint.get(ref, base)
            tinted = ref in tint  # explicitly colored (hover, edge selection, clean_image) - beats the brush color
            if c.id in edge_ids and color == base and owner.id not in selected:
                color = self._mix(color, edge_color, theme.EDGE_LINE_MIX)

            if c.generated:  # lighter instead of transparent (pencil grain needs opaque strokes)
                color = (*(np.array(color[:3]) * (1 - GENERATED_PAPER_MIX) + paper * GENERATED_PAPER_MIX), color[3])
            parts = seg_tint.get((owner.id, c.id))
            if parts:  # draw the line in pieces: selected/hovered edges colored
                for a, b in components.segments(c):
                    out.append((c.points[a:b + 1], c.widths[a:b + 1], parts.get((a, b), color), 1.0, own))
                continue
            if c.style == "brush" and c.color is not None and c.id not in edge_ids:
                if tinted:
                    pass
                elif color == base and not edge_glow:
                    color = (*theme.display_rgb(c.color), 1.0)
                elif color == base:
                    color = self._mix((*theme.display_rgb(c.color), 1.0), _rgba(SELECTED_STROKE_COLOR), EDIT_GLOW)
                out.append((c.points, c.widths, color, 2.0, own))
            else:
                out.append((c.points, c.widths, color, 1.0, own))

    def _paint_normals(self, curve):
        """Surface normal per point of a painting stroke: from its plane or drawing surface (follows deformations),
        otherwise the one remembered while painting, if need be toward the camera."""
        cache = self.__dict__.setdefault("_normals_cache", {})
        hit = cache.get(id(curve))
        dragging = self.gizmo.dragging
        if hit is not None and hit[0] is curve.points and (dragging or len(hit) < 3):
            return hit[1]
        target = self.scene.object_by_id(curve.plane_id) if curve.plane_id is not None else None
        n = len(curve.points)
        if dragging and hit is not None and len(hit[1]) == n and isinstance(target, SurfaceObject):
            # during a drag: painting follows the surface, its normals barely change - reuse the previous ones (marked
            # approximately); after release they are computed exactly (artist: snap in only afterwards)
            cache[id(curve)] = (curve.points, hit[1], "ungefähr")
            return hit[1]
        rot = None
        if hit is not None and len(hit[0]) == n and isinstance(target, SurfaceObject):
            from ..renderer import _rigid_rotation
            rot = _rigid_rotation(hit[0], curve.points)  # only moved along (group rotated): rotate normals along
        if rot is not None:
            normals = hit[1] @ rot.T.astype("f4")
        elif isinstance(target, Plane):
            normals = np.tile(target.normal, (n, 1))
        elif isinstance(target, SurfaceObject):
            fallback = curve.normals if curve.normals is not None and len(curve.normals) == n \
                else np.tile(self.cam.back, (n, 1))
            normals = self._surface_normals_at(target, curve.points, fallback)
        elif curve.normals is not None and len(curve.normals) == n:
            normals = curve.normals
        else:
            normals = np.tile(self.cam.back, (n, 1))
        normals = np.ascontiguousarray(normals, dtype="f4")
        lru.trim(cache, 16384)
        cache[id(curve)] = (curve.points, normals)
        return normals

    def _painting(self):
        """Paint mode is in effect: pen or brush, not in free mode (there real lines always arise)."""
        if self.ws.timing_mode:  # timing: painting only (on flipbook planes)
            return self.ws.draw_tool in ("pen", "brush")
        return self.ws.paint_mode and self.ws.draw_tool in ("pen", "brush") and not self._free_pen() \
            and self._free_saved is None

    def _line_owners(self):
        """Line id -> drawing surfaces the line belongs to (besides the one it was drawn on): attached
        to them, outline of a fill surface, cross-section/side line of a loft, border curve of a curve surface - also
        after splitting. On these surfaces the line stays visible, behind other surfaces not.
        Remembered as long as the surfaces' references and the set of lines are the same (do not modify): during a drag
        nothing changes there, but the query ran per frame over all surfaces."""
        scene = self.scene
        key = (id(scene), len(scene.split_map),
               tuple((len(st.curves), sum(c.id for c in st.curves)) for st in scene.strokes),
               tuple((s.id, len(s.attached), sum(s.attached), tuple(getattr(s, "patch_lines", ())),
                      tuple(i for cid, _ in s.links for i in scene.link_ids(cid)),
                      tuple(cid for cid, _ in getattr(s, "rails", ())),
                      tuple(tuple(src[1]) if src and src[0] == "lines" else None for src in getattr(s, "sources", ())))
                     for s in scene.surfaces))
        memo = self.__dict__.get("_line_owners_memo")
        if memo is not None and memo[0] == key and memo[2] is scene:
            return memo[1]
        out = {}

        def add(cid, sid):
            for i in scene.split_pieces(cid) or [cid]:
                ids = out.setdefault(i, [])
                if sid not in ids:
                    ids.append(sid)

        for s in scene.surfaces:
            for cid in s.attached:
                add(cid, s.id)
            for cid, _ in s.links:
                for i in scene.link_ids(cid):
                    add(i, s.id)
            for cid, _ in getattr(s, "rails", ()):
                add(cid, s.id)
            for src in getattr(s, "sources", ()):
                if src and src[0] == "lines":
                    for i in src[1]:
                        add(i, s.id)
            for cid in getattr(s, "patch_lines", ()):
                add(cid, s.id)
        if memo is not None and memo[2] is scene and memo[1] == out:
            out = memo[1]  # same content (e.g. just a new line somewhere): keep the same object - the stroke entries remembered per
            # line object hang on its identity and would otherwise all become invalid
        self._line_owners_memo = (key, out, scene)
        return out

    @staticmethod
    def _mix(a, b, t):
        return tuple(np.array(a) * (1 - t) + np.array(b) * t)

    def _all_extrude_previews(self):
        return [s for vp in self.ws.viewports for s in vp._extrude_preview()]

    def _visible_surfaces(self):
        """Surfaces that are displayed: not individually hidden (H), surface switch at top right on; helper surfaces
        belong to the drawing aids ("Drawing aids" switch like the planes)."""
        show = self.ws.layers_visible.get("surfaces", True)
        return [s for s in self.scene.surfaces if not self.scene.is_hidden(s) and (self.planes_visible if s.aid else show)]

    def _surface_draw_list(self):
        """Surfaces with material: dicts for renderer._upload_surfaces (shape, material, coloring, state, grid)."""
        # loft surfaces follow their cross-sections live (also in the middle of a gizmo drag), lines drawn on them
        # deform along - except with Alt (stay put)
        dragging = self._mode == "transform"
        if dragging and getattr(self, "_drag_keys", None) is None:
            # drag begins: remember the state of the surfaces - what changes during the drag is shown coarser (evenly smooth)
            self._drag_keys = {s.id: s._cache_key() for s in self.scene.surfaces if isinstance(s, LoftSurface)}
        elif not dragging:
            self._drag_keys = None
        free = self._free_move and dragging
        fresh = getattr(self, "_lofts_fresh", None)
        hold = getattr(self.ws, "sync_hold", None)
        if hold is not None and (hold is not self.scene or not any(vp._mode == "erase" for vp in self.ws.viewports)):
            hold = self.ws.sync_hold = None  # eraser drag over (or other scene): reconcile again
        if hold is not None:
            pass  # eraser removed only painting in this drag: surfaces do not change (reconcile on release)
        elif fresh is None or fresh[0] is not self.scene or fresh[1] != free:  # just reconciled in _changed: not twice
            self.scene.sync_lofts(free=free, lazy=True)
        self._lofts_fresh = None
        selected = set(self.selection) if self.select_mode else set()  # drawing mode: show no selected surfaces
        drawing = self._drawing_surfaces()
        out = []
        copies = generators.copies_by_object(self.scene)
        glow = self._note_glow()[0]
        base = getattr(self, "_drag_keys", None)
        for surface in self._visible_surfaces() + self._all_extrude_previews():
            model = getattr(surface, "_carry_model", None)
            if model is not None and getattr(surface, "_carry_base", None) is not None:
                mesh = surface._carry_base  # carried along rigidly: net from the start of the drag, the GPU moves it (position matrix)
            elif base is not None and surface.id in base and surface._cache_key() != base[surface.id]:
                mesh = _preview_mesh(surface)  # changes during the drag: half resolution (same shape, coarser net)
            else:
                mesh = surface.fill_mesh()
            if mesh is None:
                continue
            state = (any(surface is d for d in drawing), surface.id in selected)
            seqs = copies.get(surface.id)
            if seqs is not None and model is not None:  # copies (symmetry/array): as before from the moved net
                mesh, model = surface.fill_mesh(), None
            if seqs is None:
                entry = self._surface_entry(surface, mesh[0], mesh[1], state)
                if model is not None:
                    entry["model"] = model
                out.append(self._glow_surface(entry, glow[surface.id], surface.outlines)
                           if surface.id in glow else entry)
                continue
            # under a generator: original cut (with its state), copies neutral with own display id
            for key, ops in seqs:
                orig = generators.is_original(ops)
                # copy = cut original, only mirrored/offset: they share the cut and normals (the
                # copy computes nothing of its own, only the position of its points)
                cut = max((i for i, op in enumerate(ops) if op[0] == "clip"), default=-1) + 1
                head, tail = ops[:cut], ops[cut:]
                bv, bt = (_GEN_CACHE.get((mesh[0], mesh[1]), generators.ops_key(head),
                                         lambda head=head: generators.apply_mesh(mesh[0], mesh[1], head))
                          if head else (mesh[0], mesh[1]))
                verts, tris = (_GEN_CACHE.get((bv, bt), generators.ops_key(tail),
                                              lambda bv=bv, bt=bt, tail=tail: generators.apply_mesh(bv, bt, tail))
                               if tail else (bv, bt))
                if not len(tris):
                    continue
                entry = self._surface_entry(surface, verts, tris,
                                            state if orig or self._clean_copies() else (False, False),
                                            lambda ops=ops: [p for line in surface.outlines() for p, _ in
                                                             generators.apply_polyline(np.asarray(line, float), ops)])
                if surface.id in glow:  # copies are included: they light up too
                    self._glow_surface(entry, glow[surface.id], lambda ops=ops: [
                        p for line in surface.outlines() for p, _ in generators.apply_polyline(np.asarray(line, float), ops)])
                if not orig:
                    entry["id"] = generators.vid(surface.id, key)
                if tail:  # normals of the (cut) original, rotated along or mirrored
                    entry["basis"] = (bv, bt, generators.matrix_of(tail)[:3, :3], generators.flips(tail))
                out.append(entry)
        if dragging:  # what deforms during the drag gets simple lighting normals; exact after release
            for entry in out:
                entry["draft"] = True
        return out

    def _surface_entry(self, surface, verts, tris, state, outlines=None):
        """dict of a surface for the renderer (shape, material, coloring by state). outlines: () -> outline polylines
        (copies: cut/offset), otherwise those of the surface."""
        outlines = outlines or surface.outlines
        faint = not any(state) and surface.id in getattr(self, "_faint", ())  # clean_image(faint=…)
        if faint:
            entry = self._surface_entry(surface, verts, tris, (False, True), lambda: [])
            entry["state"] = (*entry["state"][:3], entry["state"][3] * FAINT_MIX)
            return entry
        if isinstance(surface, LoftSurface) and not any(state):  # loft inactive: ocher; active like any drawing surface
            fill, line = theme.LOFT_IDLE_COLORS
        else:
            fill, line = PLANE_COLORS[state] if any(state) else theme.SURFACE_IDLE_COLORS
        emphasis = 2 if state[0] else (1 if state[1] else 3)
        fill, line = _rgba(fill), _rgba(line)
        if self.select_mode and self.ws.component == "face" and not state[1]:  # surface mode: highlight slightly
            sel_fill, sel_line = PLANE_COLORS[(False, True)]
            fill, line = self._mix(fill, _rgba(sel_fill), EDIT_GLOW), self._mix(line, _rgba(sel_line), EDIT_GLOW)
        # state as a subtle tint of the material: selected clearly, active slightly, surface mode hinted
        glaze = theme.SURFACE_STATE_GLAZE[1] if state[1] else theme.SURFACE_STATE_GLAZE[0] if state[0] else (
            EDIT_GLOW * theme.SURFACE_STATE_GLAZE[1] if self.select_mode and self.ws.component == "face" else 0.0)
        tint = getattr(surface, "tint", None)
        if getattr(surface, "aid", False):  # helper surface: colored like a helper plane (state), hides nothing
            pf, pl = (_rgba(c) for c in PLANE_COLORS[state])
            return dict(verts=verts, tris=tris, id=surface.id, material=0, tint=tuple(pf[:3]),
                        seed=getattr(surface, "seed", 0.0), state=(*pl[:3], 0.0),
                        grid_step=_grid_step(verts) if state[0] else 0.0, grid_alpha=theme.SURFACE_GRID_ALPHA[2],
                        grid_color=pl[:3], outlines=outlines(), line=pl, emphasis=emphasis,
                        opacity=float(pf[3]), resolution=1.0, occlude=False)
        return dict(verts=verts, tris=tris, id=surface.id,
                    material=theme.MATERIAL_INDEX.get(getattr(surface, "material", "papier"), 0),
                    tint=tint if tint is not None else (1.0, 1.0, 1.0), seed=getattr(surface, "seed", 0.0),
                    state=(*line[:3], glaze), grid_step=_grid_step(verts) if state[0] else 0.0,
                    grid_alpha=theme.SURFACE_GRID_ALPHA[2], grid_color=line[:3],
                    outlines=outlines() if state[1] or state[0] else [], line=line, emphasis=emphasis,
                    opacity=float(getattr(surface, "opacity", 1.0)),
                    resolution=float(getattr(surface, "res", 1.0)))

    def _infinite_plane(self):
        """Infinite display only for the three base planes: if one of them is the only drawing surface, it continues
        as a subtle neutral grid (tiles in its size) beyond its rectangle. Own helper planes
        are not shown infinite - one drags them to where one needs them."""
        drawing = self._drawing_surfaces()
        if not self.planes_visible or len(drawing) != 1 or not isinstance(drawing[0], Plane) or not drawing[0].preset:
            return []
        plane = drawing[0]
        depth = abs(float((self.cam.eye - plane.origin) @ plane.normal))
        return [dict(origin=plane.origin, u=plane.axis_u, v=plane.axis_v,
                     core=(plane.size_u / 2, plane.size_v / 2), tile=(plane.size_u, plane.size_v),
                     fill=_rgba(theme.GRAPHITE), line=_rgba(theme.GRAPHITE),
                     reach=theme.INFINITE_REACH * max(depth, plane.size_u, plane.size_v, self.cam.dist),
                     strength=1.0, depth=False, id=plane.id)]

    def _plane_draw_list(self):
        """[(plane, fill color, line color, highlight)] - highlight 2: drawing happens here, 1: selected, 0: otherwise.
        In edit mode the planes look exactly as in drawing (artist 12.11.: there none counted as drawing plane -
        it vanished over the geometry but kept tinting the strokes behind it); a selected plane carries the
        selection color, even if it is the drawing plane."""
        selected = set(self.selection) if self.select_mode else set()
        drawing = self._drawing_surfaces()
        if self.select_mode and not self._free_pen() and not self.notes_mode:
            drawing = self._multi_surfaces() if self.multi_mode else [self.scene.active_surface]
        eye, view = self.cam.eye, -self.cam.back
        out = []
        for plane in sorted(self._visible_planes(), key=lambda pl: -((pl.origin - eye) @ view)):  # back to front
            chosen = plane.id in selected
            active = any(plane is s for s in drawing) and not chosen
            fill, line = PLANE_COLORS[(active, chosen)]
            out.append((plane, _rgba(fill), _rgba(line), 2 if active else int(chosen)))
        return out

    def _mesh_draw_list(self):
        selected = set(self.selection) if self.select_mode else set()
        drawing = self._drawing_surfaces()
        out = []
        copies = generators.copies_by_object(self.scene)
        faint = getattr(self, "_faint", ())  # clean_image(faint=…): weakly highlighted (note octopus)
        glow = self._note_glow()[0]
        magenta = _rgba(theme.OCTOPUS)
        for mesh in self._visible_meshes():
            state = (any(mesh is s for s in drawing), mesh.id in selected)
            weak = FAINT_MIX if not any(state) and mesh.id in faint else 1.0
            if weak < 1.0:
                state = (False, True)
            r, g, b, _ = _rgba(PLANE_COLORS[state][1])
            glowing = mesh.id in glow and not state[1]  # selected note: connected meshes (including copies) magenta
            out.append((mesh, (*magenta[:3], NOTE_GLOW[glow[mesh.id]][2]) if glowing
                        else (r, g, b, MESH_TINT_ALPHA[state] * weak)))
            for key, ops in copies.get(mesh.id, ()):  # copies under generators (meshes are not cut)
                if generators.is_original(ops):
                    continue
                cstate = state if self._clean_copies() else (False, False)
                r, g, b, _ = _rgba(PLANE_COLORS[cstate][1])
                inst = _GEN_CACHE.get((mesh.geo,), (generators.ops_key(ops), mesh.xform.tobytes(), key),
                                      lambda ops=ops, key=key: _MeshInstance(mesh.geo, generators.matrix_of(ops) @ mesh.xform,
                                                                             generators.vid(mesh.id, key)))
                out.append((inst, (*magenta[:3], NOTE_GLOW[glow[mesh.id]][2]) if glowing else
                            (r, g, b, MESH_TINT_ALPHA[cstate] * (weak if self._clean_copies() else 1.0))))
        return out

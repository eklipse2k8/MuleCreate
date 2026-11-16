"""Surfaces as objects with material (display): choose material, tint, save; surfaces cover lines."""
import os
import tempfile

import numpy as np

from tests.harness import H, Qt
from sketch_machine import network, theme
from sketch_machine.scene import Scene, StrokeObject



def _find(o, sid):
    """Entry of an object anywhere in the outliner (surfaces are under their line object)."""
    from PySide6.QtWidgets import QTreeWidgetItemIterator
    it = QTreeWidgetItemIterator(o)
    while it.value() is not None:
        if it.value().data(0, Qt.UserRole) == sid:
            return it.value()
        it += 1
    return None


def _under(root, sid):
    stack = [root.child(i) for i in range(root.childCount())]
    while stack:
        x = stack.pop()
        if x.data(0, Qt.UserRole) == sid:
            return True
        stack += [x.child(i) for i in range(x.childCount())]
    return False

def _square(h: H, y=0.0, x0=0.0, size=2.0):
    sc = h.sc
    sc.new_stroke()
    pts = [np.array(p, float) for p in ([x0, y, 0], [x0 + size, y, 0], [x0 + size, y, size], [x0, y, size])]
    lines = []
    for k in range(4):
        sc.add_curve(np.linspace(pts[k], pts[(k + 1) % 4], 12), None)
        lines.append(sc.curves[-1])
    network.sync(sc)
    for k in range(4):
        network.join(sc, lines[k], 11, lines[(k + 1) % 4], 0)
    s = sc.create_fill([(c, False) for c in lines])
    s.seed = 1.0  # fixed texture offset: spots and tone steps are the same in every run (pixel comparisons)
    h.v._changed()
    return s


def test_f_tints_the_active_surface(h: H):
    """Draw mode: F tints the active surface in the current colour, Shift+F resets; one undo step each."""
    s = _square(h)
    h.camera([1, 0, 1], 5, [0.1, 1, 0.2])
    h.draw_mode()
    h.v._activate(s)
    h.v.set_paint_color((0.8, 0.3, 0.2))
    h.key(Qt.Key_F)
    assert s.tint == (0.8, 0.3, 0.2)
    h.key(Qt.Key_F, Qt.ShiftModifier)
    assert s.tint is None
    h.key(Qt.Key_Z, Qt.ControlModifier)
    assert h.sc.surfaces[0].tint == (0.8, 0.3, 0.2), "undo brings the tint back"


def test_material_in_the_outliner(h: H):
    """The material column of the surface (painted like a dropdown, no widget per row – speed) shows its material,
    the menu sets it."""
    from sketch_machine.outliner import BRIEF_ROLE, MATERIAL
    s = _square(h)
    h.pump(0.05)
    o = h.w.outliner
    o.rebuild()
    item = _find(o, s.id)
    assert o.itemWidget(item, MATERIAL) is None, "no embedded widget per row"
    assert item.data(MATERIAL, BRIEF_ROLE)[0] == "Papier"
    o._set_material(s.id, "holz")  # what the menu calls on click
    assert h.sc.surfaces[0].material == "holz"
    h.pump(0.05)
    item = _find(o, s.id)
    assert item.data(MATERIAL, BRIEF_ROLE)[0] == "Holz"


def test_outliner_panels_only_on_expanding(h: H):
    """Surface options (sliders) are only created on expanding – not on every rebuild for all surfaces."""
    s = _square(h)
    h.pump(0.05)
    o = h.w.outliner
    o.rebuild()
    item = _find(o, s.id)
    assert o.itemWidget(item.child(0), 0) is None, "collapsed: no panel yet"
    item.setExpanded(True)
    h.pump(0.05)
    item = _find(o, s.id)
    assert o.itemWidget(item.child(0), 0) is not None, "expanded: panel there"
    assert item.child(0).isFirstColumnSpanned(), "panel across the full width"
    o.rebuild()  # stays expanded, panel is built again
    item = _find(o, s.id)
    assert item.isExpanded() and o.itemWidget(item.child(0), 0) is not None


def test_material_colour_offset_are_saved(h: H):
    s = _square(h)
    s.material, s.tint, s.seed = "stoff", (0.2, 0.4, 0.6), 123.4
    path = os.path.join(tempfile.mkdtemp(), "mat.sketch.json")
    h.sc.save(path)
    t = Scene.load(path)[0].surfaces[0]
    assert (t.material, t.tint, t.seed) == ("stoff", (0.2, 0.4, 0.6), 123.4)


def test_surface_hides_line_behind_it(h: H):
    """Surfaces cover: a line behind a surface cannot be seen, a line on it can."""
    _square(h, y=1.0, x0=-1.0, size=3.0)
    sc = h.sc
    sc.add_curve(np.linspace([0.0, 0.0, 0.5], [1.0, 0.0, 0.5], 10), None, np.full(10, 0.05))  # under the surface
    behind = sc.curves[-1]
    h.v._changed()
    h.v.set_planes_visible(False)
    try:
        h.camera([0.5, 0.5, 0.5], 5, [0.0, 1.0, 0.02])  # from above: the surface lies between camera and line
        img = h.grab()
        mid = h.scr(behind.points[5])
        r, g, b = h.pixel(img, mid)[:3]
        beside = h.pixel(img, h.scr(behind.points[5] + np.array([0.0, 0.0, 0.8])))[:3]  # next to it, no line behind
        assert abs((r + g + b) - sum(beside)) < 40, f"line behind the surface shows through: {(r, g, b)} instead of {beside}"
    finally:
        h.v.set_planes_visible(True)


def test_large_mesh_hides_small_line_close_behind_it(h: H):
    """Meshes cover independently of their size: under the top of a 60 m cube a line 0.3 m deeper
    cannot be seen (before: tolerance of 2 % of the mesh diagonal), a line drawn on it can."""
    from sketch_machine.geometry import Geometry
    from sketch_machine.scene import MeshObject
    h.new_scene()
    sc = h.sc
    v = np.array([[x, y, z] for x in (-30, 30) for y in (-60, 0) for z in (-30, 30)], float)
    f = [[0, 1, 3], [0, 3, 2], [4, 6, 7], [4, 7, 5], [0, 4, 5], [0, 5, 1], [2, 3, 7], [2, 7, 6], [1, 5, 7], [1, 7, 3],
         [0, 2, 6], [0, 6, 4]]
    mesh = MeshObject("Cube", "", Geometry(v, np.array(f)))
    sc.meshes.append(mesh)
    sc.new_stroke()
    sc.add_curve(np.linspace([0.0, -0.3, 0.5], [1.0, -0.3, 0.5], 10), None, np.full(10, 0.05))
    behind = sc.curves[-1]
    sc.add_curve(np.linspace([0.0, 0.0, -0.5], [1.0, 0.0, -0.5], 10), mesh.id, np.full(10, 0.05))
    on = sc.curves[-1]
    h.v._changed()
    h.v.set_planes_visible(False)
    try:
        h.camera([0.5, 0.0, 0.0], 5, [0.0, 1.0, 0.02])  # from above onto the top
        img = h.grab()
        lum = lambda p: sum(h.pixel(img, h.scr(p))[:3])
        hidden = abs(lum(behind.points[5]) - lum(behind.points[5] + np.array([0.0, 0.0, 0.3])))
        shown = lum(on.points[5] + np.array([0.0, 0.0, 0.3])) - lum(on.points[5])
        assert hidden < 40, f"line under the mesh top shows through ({hidden})"
        assert shown > 100, f"line drawn on the mesh is not visible ({shown})"
    finally:
        h.v.set_planes_visible(True)


def test_mesh_edges_do_not_let_the_surface_behind_show_through(h: H):
    """At depth edges of a mesh (a block stands on a plate) the plate also covers directly next to the block:
    a surface below does not show through as speckles along the edge (check opacity only at the pixel itself)."""
    from sketch_machine.geometry import Geometry
    from sketch_machine.scene import MeshObject
    h.new_scene()
    sc = h.sc

    def box(lo, hi):
        v = np.array([[x, y, z] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])], float)
        f = [[0, 1, 3], [0, 3, 2], [4, 6, 7], [4, 7, 5], [0, 4, 5], [0, 5, 1], [2, 3, 7], [2, 7, 6], [1, 5, 7],
             [1, 7, 3], [0, 2, 6], [0, 6, 4]]
        return v, np.array(f)

    (v1, f1), (v2, f2) = box((-3, -0.1, -3), (4, 0.0, 4)), box((0.2, 0.0, -2), (1.2, 0.6, 3))
    sc.meshes.append(MeshObject("Plate with block", "", Geometry(np.vstack([v1, v2]), np.vstack([f1, f2 + 8]))))
    _square(h, y=-0.4, x0=-1.0, size=3.0)  # surface under the plate
    h.v.set_planes_visible(False)
    try:
        h.camera([0.5, 0.0, 0.5], 5, [-0.35, 1.0, 0.1])  # slanted from above: the block creates a depth edge
        a = h.grab()
        sc.surfaces[0].hidden = True
        h.v._changed()
        b = h.grab()
        n = h.diff(a, b, threshold=30)
        assert n < 5, f"surface under the plate shows through at {n} pixels along the block edge"
    finally:
        sc.surfaces[0].hidden = False
        h.v.set_planes_visible(True)


def test_transparent_surface_lets_line_show_through(h: H):
    """Transparency slider: behind a half-transparent surface a line can be seen, weaker than when free."""
    s = _square(h, y=1.0, x0=-1.0, size=3.0)
    sc = h.sc
    sc.add_curve(np.linspace([0.0, 0.0, 0.5], [1.0, 0.0, 0.5], 10), None, np.full(10, 0.08))
    behind = sc.curves[-1]
    h.v._changed()
    h.v.set_planes_visible(False)
    h.camera([0.5, 0.5, 0.5], 5, [0.0, 1.0, 0.02])
    mid = h.scr(behind.points[5])
    beside = h.scr(behind.points[5] + np.array([0.0, 0.0, 0.8]))
    lum = lambda img, p: sum(h.pixel(img, p)[:3])
    img = h.grab()
    hidden = abs(lum(img, mid) - lum(img, beside))
    h.v.set_surface_opacity(s.id, 0.5)
    img = h.grab()
    half = lum(img, beside) - lum(img, mid)
    h.v.set_surface_opacity(s.id, 0.0)
    img = h.grab()
    free = lum(img, beside) - lum(img, mid)
    h.v.set_planes_visible(True)
    assert hidden < 40, f"opaque: line hidden ({hidden})"
    assert 60 < half < free - 60, f"half transparent: line visible more weakly ({half} instead of free {free})"


def test_resolution_changes_net_not_shape(h: H):
    """Resolution slider: curve surface and fill surface get a finer or coarser net, the shape stays."""
    from sketch_machine.viewport import _dist_to_triangles_fast
    sc = h.sc
    sc.new_stroke()
    t = np.linspace(0, 1, 16)
    sides = [np.stack([t * 4, 0.8 * np.sin(t * np.pi), t * 0], 1), np.stack([np.full_like(t, 4), 0.8 * np.sin(t * np.pi), t * 4], 1),
             np.stack([4 - t * 4, 0.8 * np.sin(t * np.pi), np.full_like(t, 4)], 1), np.stack([t * 0, 0.8 * np.sin(t * np.pi), 4 - t * 4], 1)]
    lines = []
    for sd in sides:
        sc.add_curve(sd, None)
        lines.append(sc.curves[-1])
    patch = sc.create_patch(lines)
    fill_s = _square(h, y=0.0, x0=6.0, size=3.0)
    h.v._changed()
    # bulged (one outline raised): a flat fill surface shows only its border, there is nothing finer
    # or coarser to set on it
    edge = next(c for c in sc.curves if any(i == c.id for cid, _ in fill_s.links for i in sc.link_ids(cid)))
    bent = edge.points.copy()
    bent[len(bent) // 2] += [0.0, 0.6, 0.0]
    edge.points = bent
    h.v._changed()
    for s in (patch, fill_s):
        v1, t1 = [np.array(x) for x in s.fill_mesh()[:2]]
        h.v.set_surface_resolution(s.id, 4.0)
        h.v._changed()
        v4, t4 = [np.array(x) for x in s.fill_mesh()[:2]]
        h.v.set_surface_resolution(s.id, 0.25)
        h.v._changed()
        vq, tq = [np.array(x) for x in s.fill_mesh()[:2]]
        assert len(t4) > 8 * len(t1) and len(tq) * 4 < len(t1), (s.name, len(tq), len(t1), len(t4))
        size = float(np.linalg.norm(np.ptp(v1, axis=0)))
        probe = v4[np.linspace(0, len(v4) - 1, 300).astype(int)]
        assert _dist_to_triangles_fast(probe, v1[t1]).max() < 0.01 * size, f"{s.name}: fine, shape stays"
        h.v.set_surface_resolution(s.id, 1.0)
        h.v._changed()
        assert len(np.array(s.fill_mesh()[1])) == len(t1)
    path = os.path.join(tempfile.mkdtemp(), "res.sketch.json")
    patch.resolution, patch.opacity = 2.0, 0.4
    sc.save(path)
    t = next(x for x in Scene.load(path)[0].surfaces if x.name == patch.name)
    assert (t.resolution, t.opacity) == (2.0, 0.4)


def test_global_resolution_multiplies_and_returns_exactly(h: H):
    """Viewport quality (global slider): multiplies the slider of every surface; when reset, the net is exactly
    the old one again – coarser and finer again leaves no corners (the shape is never built from the coarse net)."""
    from sketch_machine.scene import SurfaceObject
    sc = h.sc
    sc.new_stroke()
    t = np.linspace(0, 1, 16)
    sides = [np.stack([t * 4, 0.8 * np.sin(t * np.pi), t * 0], 1), np.stack([np.full_like(t, 4), 0.8 * np.sin(t * np.pi), t * 4], 1),
             np.stack([4 - t * 4, 0.8 * np.sin(t * np.pi), np.full_like(t, 4)], 1), np.stack([t * 0, 0.8 * np.sin(t * np.pi), 4 - t * 4], 1)]
    lines = []
    for sd in sides:
        sc.add_curve(sd, None)
        lines.append(sc.curves[-1])
    patch = sc.create_patch(lines)
    fill_s = _square(h, y=0.0, x0=6.0, size=3.0)
    h.v._changed()
    # bulged (one outline raised): a flat fill surface shows only its border, there is nothing finer
    # or coarser to set on it
    edge = next(c for c in sc.curves if any(i == c.id for cid, _ in fill_s.links for i in sc.link_ids(cid)))
    bent = edge.points.copy()
    bent[len(bent) // 2] += [0.0, 0.6, 0.0]
    edge.points = bent
    h.v._changed()
    before = {s.id: [np.array(x).copy() for x in s.fill_mesh()[:2]] for s in (patch, fill_s)}
    try:
        h.v.set_display_resolution(0.25)
        h.v._changed()
        h.grab()
        for s in (patch, fill_s):
            assert len(np.array(s.fill_mesh()[1])) * 4 < len(before[s.id][1]), f"{s.name}: coarser"
        h.v.set_surface_resolution(patch.id, 4.0)  # own slider × global: 4 × 0.25 = as before
        h.v._changed()
        assert len(np.array(patch.fill_mesh()[1])) == len(before[patch.id][1]), "sliders multiply"
        h.v.set_surface_resolution(patch.id, 1.0)
        h.v.set_display_resolution(1.0)
        h.v._changed()
        for s in (patch, fill_s):
            v, tr = [np.array(x) for x in s.fill_mesh()[:2]]
            assert np.array_equal(tr, before[s.id][1]) and np.allclose(v, before[s.id][0]), f"{s.name}: exactly back"
    finally:
        SurfaceObject.display_res = 1.0


def test_free_mode_over_surface_without_crash(h: H):
    """Free mode: mouse over a surface – the start point is looked up while moving (not while drawing the frame,
    there the GPU picking would confuse the GL context); a stroke starts on the surface."""
    from PySide6.QtCore import QPointF
    s = _square(h, y=0.0, x0=-1.0, size=3.0)
    h.camera([0.5, 0, 0.5], 6, [0.2, 1.0, 0.4])
    h.draw_mode()
    h.v.set_free_draw(True)
    try:
        start = h.scrf([0.5, 0.0, 0.5])
        for k in range(5):
            h.move(start + QPointF(k * 3, 0))
            h.pump(0.02)
        assert h.v._free_hover is not None and abs(h.v._free_hover[1]) < 1e-3, "start point on the surface"
        n = len(h.curves())
        h.stroke([start, start + QPointF(60, -40), start + QPointF(120, -60)])
        assert len(h.curves()) == n + 1, "free stroke is created"
        assert np.linalg.norm(h.curves()[-1].points[0] - [0.5, 0.0, 0.5]) < 0.05, "starts on the surface"
    finally:
        h.v.set_free_draw(False)


def test_helper_surface_hides_nothing_and_belongs_to_the_drawing_aids(h: H):
    """Surface -> helper surface: line behind it visible, drawing aids off hides it, saved; back: covers."""
    s = _square(h, y=1.0, x0=-1.0, size=3.0)
    sc = h.sc
    sc.add_curve(np.linspace([0.0, 0.0, 0.5], [1.0, 0.0, 0.5], 10), None, np.full(10, 0.08))
    behind = sc.curves[-1]
    h.v._changed()
    h.camera([0.5, 0.5, 0.5], 5, [0.0, 1.0, 0.02])
    mid, beside = h.scr(behind.points[5]), h.scr(behind.points[5] + np.array([0.0, 0.0, 0.8]))
    lum = lambda img, p: sum(h.pixel(img, p)[:3])
    h.v.set_surface_aid(s.id, True)
    img = h.grab()
    assert lum(img, beside) - lum(img, mid) > 60, "line behind the helper surface is visible"
    assert any(x is s for x in h.v._visible_surfaces())
    h.v.set_planes_visible(False)
    assert not any(x is s for x in h.v._visible_surfaces()), "drawing aids off: helper surface gone"
    h.v.set_planes_visible(True)
    path = os.path.join(tempfile.mkdtemp(), "aid.sketch.json")
    h.sc.save(path)
    assert Scene.load(path)[0].surfaces[0].aid, "helper surface stays on loading"
    h.key(Qt.Key_Z, Qt.ControlModifier)
    assert not h.sc.surfaces[0].aid, "Undo"


def test_surface_switch_top_right(h: H):
    s = _square(h)
    h.v.set_layer_visible("surfaces", False)
    try:
        assert not h.v._visible_surfaces(), "surfaces hidden"
        h.v.set_surface_aid(s.id, True)
        assert h.v._visible_surfaces(), "helper surfaces belong to the drawing aids, not to the surface switch"
    finally:
        h.v.set_layer_visible("surfaces", True)
    assert "surfaces" in h.w.layer_checks


def test_outliner_surface_options_collapsed(h: H):
    """Transparency/resolution/helper surface are under the surface, collapsed; expanded, it stays on rebuild."""
    s = _square(h)
    o = h.w.outliner
    o.rebuild()
    item = lambda: _find(o, s.id)
    assert item().childCount() == 1 and not item().isExpanded(), "options collapsed"
    item().setExpanded(True)
    o.rebuild()
    assert item().isExpanded(), "stays expanded"


def test_helper_surface_is_with_the_planes(h: H):
    s = _square(h)
    o = h.w.outliner
    planes = lambda: _under(o.planes_root, s.id)
    o.rebuild()
    assert _find(o, s.id) is not None and not planes()
    h.v.set_surface_aid(s.id, True)
    o.rebuild()
    assert planes(), "helper surface under planes"
    h.v.set_surface_aid(s.id, False)
    o.rebuild()
    assert _find(o, s.id) is not None and not planes()


def test_surface_is_under_its_line_object(h: H):
    """In the outliner, surfaces are under the line object of their border lines (fewer entries); if their border also
    belongs to foreign line objects, the info column shows ⚠ with a hint."""
    from sketch_machine.outliner import INFO
    s = _square(h)
    o = h.w.outliner
    o.rebuild()
    item = _find(o, s.id)
    parent = item.parent()
    assert parent is not None and isinstance(h.sc.object_by_id(parent.data(0, Qt.UserRole)), StrokeObject), \
        "surface hangs under its line object"
    assert item.text(INFO) == ""

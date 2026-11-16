"""Moving a surface means: moving all its lines (border, net lines, lines and painting on it). The surface results
from its lines, never the other way round – moved alone it would lie next to them and jump back at the next sync.
Duplicating takes the same net along: the copy hangs on its own lines."""
import numpy as np

from sketch_machine import network
from tests.harness import H, line
from tests.test_rigid_move import _square_with_paint


def _lines_of(sc, patch):
    return [sc.curve_by_id(i) for i in patch.patch_lines]


def test_moving_curve_surface_takes_all_lines_along(h: H):
    sc, st, patch, paint = _square_with_paint(h)
    sc.active_stroke = st
    sc.add_curve(line([0.5, 0, 1.0], [1.5, 0, 1.05], 9), patch.id)  # real line on the surface
    on = st.curves[-1]
    h.v._changed()
    before = {c.id: c.points.copy() for c in st.curves}
    mesh = patch.fill_mesh()[0].copy()
    h.v.selection, h.v.edge_selection = [patch.id], []
    h.v._changed()
    d = np.array([0.6, 0.4, -0.3])
    h.v.transform_target.translate(d)
    h.v._changed()
    for c in _lines_of(sc, patch):
        assert np.allclose(c.points, before[c.id] + d), "border line moves with the surface"
    assert np.allclose(sc.curve_by_id(on.id).points, before[on.id] + d, atol=1e-6), "line on the surface moves along"
    for c in paint:
        assert np.allclose(c.points, before[c.id] + d, atol=1e-4) and c.id in patch.attached, "painting moves along"
    assert np.allclose(patch.fill_mesh()[0], mesh + d, atol=1e-6), "surface lies on its lines again"
    # touch a border line: nothing jumps back
    c = _lines_of(sc, patch)[0]
    pts = c.points.copy()
    pts[len(pts) // 2] += [0.0, 0.0, 1e-4]
    c.points = pts
    h.v.selection = []
    h.v._changed()
    assert abs(float(patch.fill_mesh()[0][:, 1].mean()) - float((mesh + d)[:, 1].mean())) < 1e-3, "no jumping back"


def test_carried_during_drag_and_the_same_afterwards(h: H):
    sc, st, patch, paint = _square_with_paint(h)
    before = {c.id: c.points.copy() for c in st.curves}
    mesh = patch.fill_mesh()[0].copy()
    h.v.selection = [patch.id]
    h.v._changed()
    target = h.v.transform_target
    target.in_drag = True
    d = np.array([0.5, 0.2, 0.1])
    target.translate(d)
    h.v._changed()
    assert getattr(patch, "_carried", False), "surface with its lines: carried rigidly"
    target.in_drag = False
    target.end_rigid()
    h.v._changed()
    assert np.allclose(patch.fill_mesh()[0], mesh + d, atol=1e-6)
    for c in st.curves:
        assert np.allclose(c.points, before[c.id] + d, atol=1e-4)
    assert all(c.id in patch.attached and c.plane_id == patch.id for c in paint)


def _two_sharing(h):
    """Two curve surfaces side by side with a shared border line (be)."""
    h.new_scene()
    sc = h.sc
    st = sc.new_stroke()
    p = {k: np.array(v, float) for k, v in dict(a=[0, 0, 0], b=[2, 0, 0], c=[4, 0, 0], d=[0, 0, 2], e=[2, 0, 2],
                                                f=[4, 0, 2]).items()}
    names = ("ab", "bc", "de", "ef", "ad", "be", "cf")
    for x, y in names:
        sc.add_curve(line(p[x], p[y], 8), None)
    network.sync(sc)
    lines = dict(zip(names, st.curves))
    patches = []
    for group in (("ab", "be", "de", "ad"), ("bc", "cf", "ef", "be")):
        h.v.selection = []
        h.v.edge_selection = [("line", st.id, lines[n].id) for n in group]
        h.v.do_patch()
        patches.append(sc.surfaces[-1])
    h.v.selection, h.v.edge_selection = [], []
    h.v._changed()
    return sc, st, lines, patches


def test_shared_line_is_moved_only_once(h: H):
    sc, st, lines, patches = _two_sharing(h)
    before = {n: c.points.copy() for n, c in lines.items()}
    d = np.array([0.0, 1.0, 0.0])
    h.v.selection = [f.id for f in patches]  # both surfaces: the shared line belongs to both
    h.v._changed()
    h.v.transform_target.translate(d)
    h.v._changed()
    for n, c in lines.items():
        assert np.allclose(c.points, before[n] + d), f"line {n}: moved exactly once"


def test_surface_and_own_line_selected_moved_once(h: H):
    sc, st, lines, patches = _two_sharing(h)
    before = {n: c.points.copy() for n, c in lines.items()}
    d = np.array([0.0, 1.0, 0.0])
    h.edit_mode("edge")
    h.v.selection = [patches[0].id]
    h.v.edge_selection = [("line", st.id, lines["ab"].id)]
    h.v._changed()
    h.v.transform_target.translate(d)
    h.v._changed()
    for n in ("ab", "be", "de", "ad"):
        assert np.allclose(lines[n].points, before[n] + d), f"line {n}: moved exactly once"
    assert np.allclose(lines["cf"].points, before["cf"]), "far edge of the neighboring surface stays"


def test_neighboring_surface_follows_the_shared_line(h: H):
    sc, st, lines, patches = _two_sharing(h)
    d = np.array([0.0, 1.0, 0.0])
    h.v.selection = [patches[0].id]
    h.v._changed()
    h.v.transform_target.translate(d)
    h.v._changed()
    y = patches[1].fill_mesh()[0][:, 1]
    assert abs(float(y.max()) - 1.0) < 1e-3 and abs(float(y.min())) < 1e-3, "neighbor: up at the shared line, down far away"


def test_duplicating_copies_the_lines_too(h: H):
    sc, st, patch, paint = _square_with_paint(h)
    n_lines = len(sc.curves)
    h.v.selection, h.v.edge_selection = [patch.id], []
    h.v._changed()
    assert h.v.duplicate(), "surface duplicated"
    h.v._changed()
    copies = [f for f in sc.surfaces if f is not patch]
    assert len(copies) == 1
    dup = copies[0]
    assert len(dup.patch_lines) == 4 and not set(dup.patch_lines) & set(patch.patch_lines), "copy has its own border lines"
    assert all(sc.curve_by_id(i) is not None for i in dup.patch_lines)
    assert len(sc.curves) == n_lines * 2, "border and painting copied"
    # move the copy: the original stays where it is
    orig = {i: sc.curve_by_id(i).points.copy() for i in patch.patch_lines}
    mesh = patch.fill_mesh()[0].copy()
    # as after Ctrl+D: the copy is selected and still lies exactly on the original (welded only within itself)
    assert dup.id in h.v.selection or any(r[2] in dup.patch_lines for r in h.v.edge_selection), "copy is selected"
    h.v.transform_target.translate(np.array([3.0, 0.0, 0.0]))
    h.v._changed()
    assert all(np.allclose(sc.curve_by_id(i).points, p) for i, p in orig.items()), "original lines untouched"
    assert np.allclose(patch.fill_mesh()[0], mesh), "original surface untouched"
    assert np.allclose(dup.fill_mesh()[0][:, 0].min(), 3.0, atol=1e-4), "copy moved along with its lines"

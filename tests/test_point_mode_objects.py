"""Point mode with several selected line objects: clicking a point clears the object selection – the points
of the other objects remain selectable anyway (harbour test 10.11.: afterwards only the last active object was left)."""
from tests.harness import H, line


def _three(h):
    h.new_scene()
    sc = h.sc
    objs = []
    for z in (0.0, 1.0, 2.0):
        st = sc.new_stroke()
        sc.add_curve(line([0, 0, z], [1, 0, z], 8), None)
        objs.append(st)
    h.camera([0.5, 0, 1.0], 6, [0.1, 1, 0.2])
    h.v._changed()
    h.edit_mode("point")
    return sc, objs


def _shown(h):
    return {r[1] for r, _c, _k in h.v._knot_list()}


def test_points_of_both_objects_remain_after_first_click(h: H):
    sc, (a, b, c) = _three(h)
    sc.active_stroke = b
    h.v.selection = [a.id, b.id]
    h.v._changed()
    h.grab()
    assert _shown(h) == {a.id, b.id}, "selected objects: their points"
    h.click(h.scr(a.curves[0].points[0]))
    assert h.v.point_selection and h.v.point_selection[0][1] == a.id
    assert _shown(h) == {a.id, b.id}, "after clicking a point of a, the points of b are still there"
    h.click(h.scr(b.curves[0].points[0]))
    assert h.v.point_selection and h.v.point_selection[0][1] == b.id, "point of b can be selected"
    assert _shown(h) == {a.id, b.id}


def test_new_object_selection_replaces_the_set(h: H):
    sc, (a, b, c) = _three(h)
    sc.active_stroke = b
    h.v.selection = [a.id, b.id]
    h.v._changed()
    h.click(h.scr(a.curves[0].points[0]))
    h.v.point_selection = []
    h.v.selection = [c.id]
    sc.active_stroke = c
    h.v._changed()
    assert _shown(h) == {c.id}, "another object selected: only its points"


def test_leaving_edit_forgets_the_set(h: H):
    sc, (a, b, c) = _three(h)
    sc.active_stroke = b
    h.v.selection = [a.id, b.id]
    h.v._changed()
    h.click(h.scr(a.curves[0].points[0]))
    h.draw_mode()
    h.v.selection, h.v.point_selection = [], []
    sc.active_stroke = c
    h.edit_mode("point")
    assert _shown(h) == {c.id}, "after drawing and back, only the active object counts again"

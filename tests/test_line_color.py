"""Coloring in edit mode: choosing a color changes nothing; “Apply” in the color picker colors selected surfaces and brush lines,
pencil stays; convert via right-click."""
import numpy as np

from sketch_machine.i18n import tr
from tests.harness import H


def _two_lines(h: H):
    h.new_scene()
    sc = h.sc
    sc.new_stroke()
    sc.add_curve(np.linspace([0, 0, 0], [1, 0, 0], 8), None)
    brush = sc.curves[-1]
    brush.style, brush.color = "brush", (0.8, 0.1, 0.1)
    sc.add_curve(np.linspace([0, 0, 1], [1, 0, 1], 8), None)
    pencil = sc.curves[-1]
    stroke = sc.owner_of(brush)
    h.edit_mode("edge")
    h.v.edge_selection = [("line", stroke.id, brush.id), ("line", stroke.id, pencil.id)]
    return brush, pencil


def test_apply_colors_selected_brush_lines_pencil_stays(h: H):
    brush, pencil = _two_lines(h)
    msgs = []
    h.v.status_changed.connect(msgs.append)
    try:
        h.w._use_color((0.1, 0.2, 0.9), remember=False, persist=False)
        h.w._use_color((0.1, 0.3, 0.9), remember=False, persist=False)  # dragging in the color wheel
        assert brush.color == (0.8, 0.1, 0.1), "choosing a color alone recolors nothing"
        assert h.v.apply_color((0.1, 0.3, 0.9))
        assert brush.color == (0.1, 0.3, 0.9) and pencil.color is None and pencil.style == "pencil"
        assert any(tr("Bleistift").lower() in m.lower() for m in msgs), msgs
        h.sc.undo()
        brush2 = next(c for c in h.sc.curves if c.id == brush.id)
        assert brush2.color == (0.8, 0.1, 0.1), "one undo step for the recoloring"
    finally:
        h.v.status_changed.disconnect(msgs.append)


def test_apply_colors_selected_surfaces_and_lines_in_one_step(h: H):
    from tests.test_undo_speed import _two_patches
    sc, st, patches = _two_patches(h)
    line_ = st.curves[0]
    line_.style, line_.color = "brush", (0.8, 0.1, 0.1)
    patches[1].aid = False
    h.edit_mode("face")
    h.v.selection = [f.id for f in patches]
    h.v.edge_selection = [("line", st.id, line_.id), ("line", st.id, st.curves[1].id)]
    h.v._changed()
    rows = [c.color for c in patches[0].curves]
    assert h.v.apply_color((0.2, 0.5, 0.7))
    assert all(f.tint == (0.2, 0.5, 0.7) for f in patches), "both surfaces colored"
    assert line_.color == (0.2, 0.5, 0.7) and st.curves[1].color is None, "brush line yes, pencil no"
    assert [c.color for c in patches[0].curves] == rows, "the shape of the surface (grid rows) stays untouched"
    sc.undo()
    h.v._changed()
    assert all(f.tint is None for f in sc.surfaces), "one undo step for everything"
    assert sc.curve_by_id(line_.id).color == (0.8, 0.1, 0.1)
    h.v.selection = [f.id for f in sc.surfaces]
    h.v.edge_selection = []
    assert h.v.apply_color((0.2, 0.5, 0.7)) and h.v.apply_color(reset=True)
    assert all(f.tint is None for f in sc.surfaces), "Shift+click: tint back to the material"


def test_apply_without_selection_does_nothing(h: H):
    brush, pencil = _two_lines(h)
    h.v.edge_selection = []
    n = len(h.sc._undo)
    assert not h.v.apply_color((0.1, 0.2, 0.9))
    assert len(h.sc._undo) == n and brush.color == (0.8, 0.1, 0.1)


def test_button_in_color_picker_only_in_edit(h: H):
    brush, pencil = _two_lines(h)
    h.w._open_color_popup()
    pop = h.w._color_popup
    try:
        assert pop.apply_button.isVisible(), "Edit: “Apply” button under the color wheel"
        pop.wheel.set_rgb((0.1, 0.3, 0.9))
        pop.apply_button.click()
        assert max(abs(a - b) for a, b in zip(brush.color, (0.1, 0.3, 0.9))) < 0.01, "click colors the selected brush line"
    finally:
        pop.hide()
    h.draw_mode()
    h.w._open_color_popup()
    try:
        assert not pop.apply_button.isVisible(), "Draw: no button"
    finally:
        pop.hide()


def test_color_in_draw_mode_recolors_nothing(h: H):
    brush, pencil = _two_lines(h)
    h.draw_mode()
    h.w._use_color((0.1, 0.2, 0.9), remember=False, persist=False)
    assert brush.color == (0.8, 0.1, 0.1)


def test_right_click_converts_pencil_to_brush_and_back(h: H):
    brush, pencil = _two_lines(h)
    h.v.set_paint_color((0.2, 0.6, 0.3))
    pid_before = dict(pencil.pids or {})
    pts = pencil.points.copy()
    h.v.convert_lines("brush")
    assert pencil.style == "brush" and pencil.color == (0.2, 0.6, 0.3)
    assert brush.color == (0.8, 0.1, 0.1), "already brush: keeps its color"
    assert np.array_equal(pencil.points, pts) and dict(pencil.pids or {}) == pid_before, "shape and points stay"
    h.v.convert_lines("pencil")
    assert pencil.style == brush.style == "pencil" and pencil.color is None and brush.color is None
    h.sc.undo()
    assert {c.style for c in h.sc.curves} == {"brush"}

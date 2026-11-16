"""Hide/show: layer switches (lines, colour lines, paint), H / Shift+H / Alt+H, eye in the outliner."""
import numpy as np

from tests.harness import H, Qt, line


def _scene(h: H):
    sc = h.sc
    sc.new_stroke()
    for k in range(3):
        sc.add_curve(line([k, 0, 0], [k, 0, 2], 10), sc.planes[0].id)
    sc.curves[0].style, sc.curves[0].color = "brush", (0.8, 0.2, 0.1)
    h.v._changed()
    h.camera([1, 0, 1], 7, [0.1, 1, 0.3])
    return sc


def test_switches_hide_and_lock(h: H):
    sc = _scene(h)
    base = h.grab()
    for name in ("lines", "brush"):
        h.w.layer_checks[name].setChecked(False)
        h.pump(0.02)
        assert h.w.layers_action.isChecked(), "button lights up as long as something is missing"
        assert h.diff(base, h.grab()) > 0, f"{name}: image changes"
        h.w.layer_checks[name].setChecked(True)
        h.pump(0.02)
    assert h.diff(base, h.grab()) == 0 and not h.w.layers_action.isChecked()
    h.w.layer_checks["lines"].setChecked(False)
    h.edit_mode("edge")
    assert h.v._curve_under(h.scrf(sc.curves[1].points[5]), 8)[0] is None, "hidden line not selectable"
    h.w.layer_checks["lines"].setChecked(True)


def test_eraser_leaves_hidden_lines(h: H):
    sc = _scene(h)
    h.w.layer_checks["lines"].setChecked(False)
    before = [c.points.copy() for c in h.curves() if c.style != "brush"]
    h.v.set_draw_tool("eraser")
    h.stroke_world([[x, 0, 1.0] for x in np.linspace(-0.5, 2.5, 10)])
    h.w.layer_checks["lines"].setChecked(True)
    after = [c.points for c in h.curves() if c.style != "brush"]
    assert len(after) == len(before) and all(np.array_equal(a, b) for a, b in zip(after, before)), \
        "hidden lines stay"
    h.v.set_draw_tool("pen")


def test_h_shift_h_alt_h_and_eye(h: H):
    sc = _scene(h)
    h.edit_mode("edge")
    st = sc.strokes[0]
    h.v.set_selection([st.id])
    h.key(Qt.Key_H)
    assert h.sc.strokes[0].hidden and len(h.v._stroke_draw_list()) == 0
    h.key(Qt.Key_H, Qt.AltModifier)
    assert not h.sc.strokes[0].hidden
    h.v.set_selection([h.sc.strokes[0].id])
    h.key(Qt.Key_H, Qt.ShiftModifier)
    assert not h.sc.strokes[0].hidden
    h.key(Qt.Key_H, Qt.AltModifier)
    from sketch_machine.outliner import EYE
    o = h.w.outliner
    o.rebuild()
    o._on_clicked(o.strokes_root.child(0), EYE)
    assert h.sc.strokes[0].hidden, "eye hides"
    o._on_clicked(o.strokes_root.child(0), EYE)
    assert not h.sc.strokes[0].hidden

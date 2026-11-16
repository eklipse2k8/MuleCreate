"""Outliner handling from the harbour test 09.11.: after a rebuild, Shift+click selected everything from the top row;
Alt+G did nothing when the focus was in the outliner."""
import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from sketch_machine.scene import NullObject
from tests.harness import H


def _strokes(h, n=5):
    h.new_scene()
    sc = h.sc
    out = []
    for k in range(n):
        st = sc.new_stroke()
        st.name = f"S{k}"
        sc.add_curve(np.linspace([k, 0, 0], [k, 0, 1], 6), None)
        out.append(st)
    h.v._changed()
    h.pump(0.05)
    return out


def _row(o, sid):
    root = o.strokes_root
    return next(root.child(i) for i in range(root.childCount()) if root.child(i).data(0, Qt.UserRole) == sid)


def _click(o, item, mods=Qt.NoModifier):
    rect = o.visualItemRect(item)
    QTest.mouseClick(o.viewport(), Qt.LeftButton, mods, rect.center())


def test_shift_click_after_rebuild(h: H):
    sts = _strokes(h)
    o = h.w.outliner
    o.rebuild()
    o.expandAll()
    h.pump(0.05)
    _click(o, _row(o, sts[2].id))
    h.pump(0.05)
    o.rebuild()  # as after every change
    h.pump(0.05)
    _click(o, _row(o, sts[3].id), Qt.ShiftModifier)
    h.pump(0.05)
    chosen = set(h.v.selection)
    assert chosen == {sts[2].id, sts[3].id}, f"Shift+click selected {sorted(h.sc.object_by_id(i).name for i in chosen)}"


def test_alt_g_with_focus_in_the_outliner(h: H):
    sts = _strokes(h, 3)
    o = h.w.outliner
    h.v.selection = [sts[0].id, sts[1].id]
    o.setFocus()
    h.pump(0.02)
    n = len(h.sc.nulls)
    QTest.keyClick(o, Qt.Key_G, Qt.AltModifier)
    h.pump(0.05)
    assert len(h.sc.nulls) == n + 1, "Alt+G creates a null"
    null = h.sc.nulls[-1]
    assert isinstance(null, NullObject) and sts[0].parent == null.id and sts[1].parent == null.id


def _space_key(h, key):
    v = h.v
    v.setFocus()
    QTest.keyPress(v, Qt.Key_Space)
    QTest.keyClick(v, key)
    QTest.keyRelease(v, Qt.Key_Space)
    h.pump(0.05)


def test_space_b_new_stroke_object_in_the_group(h: H):
    sts = _strokes(h, 2)
    h.v.selection = [sts[0].id]
    h.v.create_null("null")
    null = h.sc.nulls[-1]
    n = len(h.sc.strokes)
    h.v.selection = [null.id]
    _space_key(h, Qt.Key_B)
    assert len(h.sc.strokes) == n + 1, "Space+B creates a stroke object"
    new = h.sc.strokes[-1]
    assert new.parent == null.id and h.sc.active_stroke is new, "in the selected null, becomes active"
    h.v.selection = []
    _space_key(h, Qt.Key_B)
    assert h.sc.strokes[-1].parent == null.id, "without selection: in the group of the active stroke object"


def test_multi_mode_frame(h: H):
    from sketch_machine.vp.free_draw import MULTI_FRAME
    _strokes(h, 1)
    h.draw_mode()
    v = h.v
    v.ws.multi_mode = True
    v.update()
    img = h.grab()
    found = any(abs(img.pixelColor(x, 2).red() - MULTI_FRAME[0]) < 30 and abs(img.pixelColor(x, 2).green() - MULTI_FRAME[1]) < 30
                for x in range(20, min(400, img.width()), 3))
    v.ws.multi_mode = False
    assert found, "multi mode: amber-coloured frame at the edge"


def test_gizmo_jumps_to_the_inserted_point(h: H):
    """Ctrl+click inserts a point: afterwards the gizmo sits on it, not on the previously selected point."""
    from sketch_machine import components
    h.new_scene()
    sc = h.sc
    st = sc.new_stroke()
    sc.add_curve(np.linspace([0, 0, 0], [4, 0, 0], 41), None)
    c = st.curves[-1]
    h.v._changed()
    h.camera([2, 0, 0], 8, [0.0, 1.0, 0.02])
    h.edit_mode("point")
    ks = components.knots(c)
    h.v._apply_selection((), (), "replace", pts=[("pt", st.id, c.id, ks[-1])])
    first = h.v.transform_target.pivot().copy()
    h.v._insert_point(h.scr([1.0, 0.0, 0.0]))
    h.v._changed()
    new = h.v.transform_target.pivot()
    assert np.linalg.norm(new - np.array([1.0, 0, 0])) < 0.2, f"gizmo at {new}, not at the new point (before {first})"

"""Selection: click, double click, selection in undo, speed of the double click on surfaces."""
import time

import numpy as np

from tests.harness import H, Qt, line


def _three_lines(h: H):
    sc = h.sc
    sc.new_stroke()
    out = []
    for k in range(3):
        sc.add_curve(line([k, 0, 0], [k, 0, 2], 10), sc.planes[0].id)
        out.append(sc.curves[-1])
    h.v._changed()
    h.camera([1, 0, 1], 6, [0, 1, 0.01])
    return out


def _edge_ids(h: H):
    return sorted(r[2] for r in h.v.edge_selection)


def test_click_and_shift_click(h: H):
    lines = _three_lines(h)
    h.edit_mode("edge")
    h.click(h.scr(lines[0].points[5]))
    assert _edge_ids(h) == [lines[0].id], _edge_ids(h)
    h.click(h.scr(lines[1].points[5]), Qt.ShiftModifier)
    assert _edge_ids(h) == sorted([lines[0].id, lines[1].id])
    h.click(h.scr(lines[0].points[5]), Qt.ControlModifier)
    assert _edge_ids(h) == [lines[1].id]


def test_selection_in_undo(h: H):
    lines = _three_lines(h)
    h.edit_mode("edge")
    h.click(h.scr(lines[0].points[5]))
    a = _edge_ids(h)
    h.click(h.scr(lines[1].points[5]))
    b = _edge_ids(h)
    h.key(Qt.Key_Z, Qt.ControlModifier)
    assert _edge_ids(h) == a, "undo restores the previous selection"
    h.key(Qt.Key_Z, Qt.ControlModifier | Qt.ShiftModifier)
    assert _edge_ids(h) == b, "redo restores the selection"


def test_undo_of_an_operation_brings_the_selection_back(h: H):
    lines = _three_lines(h)
    h.edit_mode("edge")
    h.click(h.scr(lines[1].points[5]))
    before = _edge_ids(h)
    h.key(Qt.Key_Delete)
    assert len(h.curves()) == 2
    h.key(Qt.Key_Z, Qt.ControlModifier)
    assert len(h.curves()) == 3 and _edge_ids(h) == before


def test_selection_clicks_do_not_push_out_work(h: H):
    import sketch_machine.scene as S
    lines = _three_lines(h)
    h.edit_mode("edge")
    for _ in range(5):
        h.sc.checkpoint()
    old = S.UNDO_LIMIT
    S.UNDO_LIMIT = 5
    try:
        for k in range(60):
            h.click(h.scr(lines[k % 3].points[5]))
        geo = sum(1 for e in h.sc._undo if type(e).__name__ != "_Selection")
    finally:
        S.UNDO_LIMIT = old
    assert geo == 5, geo


def test_double_click_on_surface_fast(h: H):
    """Curve surface with a dense net, plus a lot of bound net of a neighboring surface nearby (as in the
    Skyscraper, where a double click took 59 s)."""
    sc = h.sc
    sc.new_stroke()
    t = np.linspace(0, 1, 16)
    sides = [np.stack([t * 4, 0.6 * np.sin(t * np.pi), t * 0], 1),
             np.stack([np.full_like(t, 4), 0.6 * np.sin(t * np.pi), t * 4], 1),
             np.stack([4 - t * 4, 0.6 * np.sin(t * np.pi), np.full_like(t, 4)], 1),
             np.stack([t * 0, 0.6 * np.sin(t * np.pi), 4 - t * 4], 1)]
    curves = []
    for s in sides:
        sc.add_curve(s, None)
        curves.append(sc.curves[-1])
    h.v.edge_selection = [("line", sc.strokes[0].id, c.id) for c in curves]
    h.v.do_patch()
    patch = sc.surfaces[-1]
    sc.create_fill([(c, False) for c in curves])
    verts = patch.fill_mesh()[0]
    h.v._changed()
    h.frame(verts, back=[0.2, 0.9, 0.3])
    h.edit_mode("face")
    centre = verts[np.argmin(np.linalg.norm(verts - verts.mean(axis=0), axis=1))]
    t0 = time.perf_counter()
    h.v.select_loop(h.scrf(centre), "replace")
    dt = time.perf_counter() - t0
    assert dt < 1.0, f"double click took {dt:.2f} s"
    return f"{dt * 1000:.0f} ms"


def _ids(h: H):
    return {r[2] for r in h.v.edge_selection} | {r[2] for r in h.v.seg_selection}


def test_l_shift_l_only_via_point_ids(h: H):
    """L: connected within its own object; Shift+L: also across object boundaries; never via position – an end that lies
    only just next to a line on the screen (gap) does not count (before: 12 px screen proximity)."""
    sc = h.sc
    a = sc.new_stroke()
    square = [([0, 0, 0], [1, 0, 0]), ([1, 0, 0], [1, 0, 1]), ([1, 0, 1], [0, 0, 1]), ([0, 0, 1], [0, 0, 0])]
    own = []
    for p, q in square:
        sc.add_curve(line(p, q, 8), None)
        own.append(sc.curves[-1])
    h.v._changed()
    b = sc.new_stroke()
    sc.add_curve(line([1, 0, 1], [2, 0, 2], 8), None)  # other object, connected at the corner
    other = sc.curves[-1]
    sc.new_stroke()
    sc.add_curve(line([1.01, 0, 0], [2, 0, -1], 8), None)  # gap: only nearby
    near = sc.curves[-1]
    h.v._changed()
    h.camera([1, 0, 0.5], 12, [0.0, 1.0, 0.02])  # far away: the gap is < 12 px on the screen
    h.edit_mode("edge")
    start = ("line", a.id, own[0].id)
    h.v.edge_selection = [start]
    h.v.select_linked("object")
    assert _ids(h) == {c.id for c in own}, "L: exactly its own connected square"
    h.v.edge_selection = [start]
    h.v.select_linked("all")
    assert _ids(h) == {c.id for c in own} | {other.id}, "Shift+L: plus the connected line in the other object"
    assert near.id not in _ids(h) and b.id != near.id


def test_ctrl_l_loop_by_net_flow(h: H):
    """Ctrl+L: straight on at crossings (4 edges), ends at T-junctions (3)."""
    sc = h.sc
    sc.new_stroke()
    row = []
    for x in range(3):
        sc.add_curve(line([x, 0, 1], [x + 1, 0, 1], 8), None)
        row.append(sc.curves[-1])
    for x in range(4):  # vertical lines in two pieces, butting against the row
        for z0, z1 in ((0, 1), (1, 2)):
            sc.add_curve(line([x, 0, z0], [x, 0, z1], 8), None)
    h.v._changed()
    h.edit_mode("edge")
    st = sc.strokes[-1]
    h.v.edge_selection = [("line", st.id, row[1].id)]
    h.key(Qt.Key_L, Qt.ControlModifier)  # via the keyboard like the artist (used to do nothing)
    assert _ids(h) == {c.id for c in row}, f"loop: the whole row, nothing vertical ({len(_ids(h))} lines)"


def test_double_click_loop_without_screen_proximity(h: H):
    """Double-click loop takes only truly connected lines: an open square with a gap that is smaller than
    12 px on the screen gives no loop across the gap."""
    sc = h.sc
    st = sc.new_stroke()
    pts = [[0, 0, 0], [1, 0, 0], [1, 0, 1], [0, 0, 1], [0, 0, 0.01]]
    for p, q in zip(pts[:-1], pts[1:]):
        sc.add_curve(line(p, q, 8), None)
    h.v._changed()
    h.camera([0.5, 0, 0.5], 12, [0.0, 1.0, 0.02])
    h.edit_mode("edge")
    first = sc.curves[-4]
    h.v.select_loop(h.scrf(first.points[4]), "replace")
    assert _ids(h) == {first.id}, f"no loop across the gap ({len(_ids(h))} lines selected)"


def test_double_click_surface_marks_stroke_object_in_outliner(h: H):
    """Edit, edge mode: double click on a surface selects its lines – the outliner then marks the stroke object
    they belong to."""
    from sketch_machine.outliner import ID_ROLE
    from PySide6.QtWidgets import QTreeWidgetItemIterator
    sc = h.sc
    st = sc.new_stroke()
    pts = [[0, 0, 0], [2, 0, 0], [2, 0, 2], [0, 0, 2], [0, 0, 0]]
    for p, q in zip(pts[:-1], pts[1:]):
        sc.add_curve(line(p, q, 8), None)
    h.v.edge_selection = [("line", st.id, c.id) for c in st.curves]
    h.v.do_patch()
    h.v._changed()
    h.camera([1, 0, 1], 5, [0.1, 1.0, 0.1])
    h.edit_mode("edge")
    h.dclick(h.scr([1.0, 0.0, 1.0]))
    h.pump(0.05)
    assert {r[2] for r in h.v.edge_selection} == {c.id for c in st.curves}, "the four border lines selected"
    marked = set()
    it = QTreeWidgetItemIterator(h.w.outliner)
    while it.value() is not None:
        if it.value().isSelected():
            marked.add(it.value().data(0, ID_ROLE))
        it += 1
    assert st.id in marked, "outliner marks the stroke object of the selected lines"

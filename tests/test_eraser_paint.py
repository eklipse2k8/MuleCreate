"""Eraser and painting on a plane above a surface: planes do not occlude – so the depth at which erasing happens
followed the surface far behind, and the eraser could not reach the painting (harbor test 10.11.)."""
import numpy as np
from PySide6.QtCore import Qt

from tests.harness import H, line
from tests.test_rigid_move import _square_in_null


def _paint_above_surface(h):
    sc, st, patch, null = _square_in_null(h)  # curve surface 2 x 2 at y = 0
    h.v.selection = []
    plane = sc.new_plane(np.array([1.0, 3.0, 1.0]), np.array([1.0, 0, 0]), np.array([0, 0, 1.0]))
    sc.active_stroke = st
    sc.add_curve(line([0.3, 3.0, 1.0], [1.7, 3.0, 1.0], 14), plane.id)
    paint = st.curves[-1]
    paint.paint, paint.style, paint.color = True, "brush", (0.9, 0.9, 0.9)
    paint.widths = np.full(len(paint.points), 0.12)
    sc.add_curve(line([0.3, 3.0, 1.5], [1.7, 3.0, 1.5], 14), plane.id)  # real line next to it
    real = st.curves[-1]
    h.camera([1.0, 0.0, 1.0], 9, [0.05, 1.0, 0.1])
    h.v._changed()
    h.grab()
    return sc, st, paint, real


def _points(sc, flag):
    return sum(len(c.points) for c in sc.curves if c.paint == flag and c.plane_id is not None)


def test_eraser_deletes_painting_on_plane_above_surface(h: H):
    sc, st, paint, real = _paint_above_surface(h)
    length = lambda: sum(float(np.linalg.norm(np.diff(c.points, axis=0), axis=1).sum()) for c in sc.curves if c.paint)
    before = length()
    h.v.set_draw_tool("eraser")
    h.stroke_world([[1.0, 3.0, z] for z in np.linspace(0.7, 1.25, 8)])  # across the paint stroke
    assert length() < before - 0.05, "paint stroke on the plane was erased"
    assert len([c for c in sc.curves if c.paint]) == 2, "cut through in the middle"
    assert any(c is real for c in sc.curves), "the line next to it stayed whole"


def test_ctrl_erases_only_lines(h: H):
    sc, st, paint, real = _paint_above_surface(h)
    pts = paint.points.copy()
    h.v.set_draw_tool("eraser")
    h.stroke_world([[1.0, 3.0, z] for z in np.linspace(0.7, 1.7, 10)], mods=Qt.ControlModifier)  # across both
    assert any(c is paint for c in sc.curves) and np.array_equal(paint.points, pts), "Ctrl: painting stays"
    assert not any(c is real for c in sc.curves), "Ctrl: the real line was cut"

"""Radierer und Malerei auf einer Ebene über einer Fläche: Ebenen verdecken nicht – die Tiefe, in der radiert wird,
richtete sich deshalb nach der Fläche weit dahinter, und der Radierer kam an die Malerei nicht heran (Hafentest 10.11.)."""
import numpy as np
from PySide6.QtCore import Qt

from tests.harness import H, line
from tests.test_starre_bewegung import _square_in_null


def _paint_above_surface(h):
    sc, st, patch, null = _square_in_null(h)  # Kurvenfläche 2 x 2 bei y = 0
    h.v.selection = []
    plane = sc.new_plane(np.array([1.0, 3.0, 1.0]), np.array([1.0, 0, 0]), np.array([0, 0, 1.0]))
    sc.active_stroke = st
    sc.add_curve(line([0.3, 3.0, 1.0], [1.7, 3.0, 1.0], 14), plane.id)
    paint = st.curves[-1]
    paint.paint, paint.style, paint.color = True, "brush", (0.9, 0.9, 0.9)
    paint.widths = np.full(len(paint.points), 0.12)
    sc.add_curve(line([0.3, 3.0, 1.5], [1.7, 3.0, 1.5], 14), plane.id)  # echte Linie daneben
    real = st.curves[-1]
    h.camera([1.0, 0.0, 1.0], 9, [0.05, 1.0, 0.1])
    h.v._changed()
    h.grab()
    return sc, st, paint, real


def _points(sc, flag):
    return sum(len(c.points) for c in sc.curves if c.paint == flag and c.plane_id is not None)


def test_radierer_loescht_malerei_auf_ebene_ueber_flaeche(h: H):
    sc, st, paint, real = _paint_above_surface(h)
    length = lambda: sum(float(np.linalg.norm(np.diff(c.points, axis=0), axis=1).sum()) for c in sc.curves if c.paint)
    before = length()
    h.v.set_draw_tool("eraser")
    h.stroke_world([[1.0, 3.0, z] for z in np.linspace(0.7, 1.25, 8)])  # quer über den Malstrich
    assert length() < before - 0.05, "Malstrich auf der Ebene wurde radiert"
    assert len([c for c in sc.curves if c.paint]) == 2, "in der Mitte durchtrennt"
    assert any(c is real for c in sc.curves), "die Linie daneben blieb ganz"


def test_strg_radiert_nur_linien(h: H):
    sc, st, paint, real = _paint_above_surface(h)
    pts = paint.points.copy()
    h.v.set_draw_tool("eraser")
    h.stroke_world([[1.0, 3.0, z] for z in np.linspace(0.7, 1.7, 10)], mods=Qt.ControlModifier)  # über beide
    assert any(c is paint for c in sc.curves) and np.array_equal(paint.points, pts), "Strg: Malerei bleibt"
    assert not any(c is real for c in sc.curves), "Strg: die echte Linie wurde durchtrennt"

"""Druckempfindlichkeit des Radierers: der Regler war gespeichert, wirkte aber nirgends. Jetzt skaliert der Druck den
Radierkreis wie beim Stift die Strichbreite (leichteste Berührung 10 %, festeste 200 %)."""
import time

import numpy as np
from PySide6.QtCore import QPointF

from tests.harness import H, line


def _line_and_pass(h, pressure):
    """Eine Linie und ein Radierzug parallel daneben – 1,3 Radius neben der Linie."""
    h.new_scene()
    sc = h.sc
    sc.new_stroke()
    sc.add_curve(line([-1.0, 0.0, 0.0], [1.0, 0.0, 0.0], 40), None)
    h.camera([0.0, 0.0, 0.0], 6, [0.0, 0.0, 1.0])
    h.v._changed()
    h.grab()
    h.v.set_draw_tool("eraser")
    h.v.set_pressure("eraser", 1.0)
    r = h.v.eraser_px / 2
    y = h.scrf([0.0, 0.0, 0.0]).y() - 1.3 * r
    xs = np.linspace(h.scrf([-0.6, 0, 0]).x(), h.scrf([0.6, 0, 0]).x(), 12)
    h.v._pressure, h.v._pressure_at = pressure, time.monotonic() + 60  # stylus pressure, fresh during the drag
    before = sum(len(c.points) for c in sc.curves)
    h.stroke([QPointF(float(x), float(y)) for x in xs])
    h.v._pressure = None
    return before, sum(len(c.points) for c in sc.curves), len(sc.curves)


def test_fester_druck_radiert_weiter_als_der_kreis(h: H):
    before, after, n = _line_and_pass(h, 1.0)  # 200 %: reaches 2 radii
    assert n == 2 or after < before, "fester Druck: der größere Kreis erreicht die Linie und trennt sie"


def test_leichter_druck_radiert_nichts_daneben(h: H):
    before, after, n = _line_and_pass(h, 0.0)  # 10 %: reaches 0.1 radius
    assert n == 1 and after == before, "leichter Druck: der kleine Kreis bleibt von der Linie weg"


def test_maus_ohne_druck_wie_bisher(h: H):
    h.v.set_pressure("eraser", 1.0)
    assert h.v._current_pressure() is None, "ohne Tablett gibt es keinen Druck – der Radierer bleibt gleich groß"

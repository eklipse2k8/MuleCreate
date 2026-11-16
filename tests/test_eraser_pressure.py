"""Pressure sensitivity of the eraser: the slider was saved but had no effect anywhere. Now the pressure scales the
eraser circle like it scales the stroke width for the pen (lightest touch 10 %, firmest 200 %)."""
import time

import numpy as np
from PySide6.QtCore import QPointF

from tests.harness import H, line


def _line_and_pass(h, pressure):
    """A line and an eraser drag parallel next to it – 1.3 radii away from the line."""
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


def test_firm_pressure_erases_beyond_the_circle(h: H):
    before, after, n = _line_and_pass(h, 1.0)  # 200 %: reaches 2 radii
    assert n == 2 or after < before, "firm pressure: the larger circle reaches the line and cuts it"


def test_light_pressure_erases_nothing_nearby(h: H):
    before, after, n = _line_and_pass(h, 0.0)  # 10 %: reaches 0.1 radius
    assert n == 1 and after == before, "light pressure: the small circle stays clear of the line"


def test_mouse_without_pressure_as_before(h: H):
    h.v.set_pressure("eraser", 1.0)
    assert h.v._current_pressure() is None, "without a tablet there is no pressure – the eraser stays the same size"

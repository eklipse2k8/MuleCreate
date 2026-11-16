"""Helper planes tint what lies behind them (strokes, paint) – before, it showed through untinted (harbour test 09.11.).
What lies in front of the plane stays untinted."""
import numpy as np

from tests.harness import H


def _setup(h):
    h.new_scene()
    sc = h.sc
    plane = sc.new_plane(np.array([0.0, 0.0, 0.0]), np.array([1.0, 0, 0]), np.array([0, 1.0, 0]))
    plane.size_u = plane.size_v = 4.0
    sc.new_stroke()
    # dark stroke behind the plane (z = -2), one piece sticks out sideways past the plane
    sc.add_curve(np.linspace([-1.0, 0.5, -2.0], [5.0, 0.5, -2.0], 40), None, np.full(40, 0.25))
    # the same stroke in front of the plane (z = +2)
    sc.add_curve(np.linspace([-1.0, -0.8, 2.0], [5.0, -0.8, 2.0], 40), None, np.full(40, 0.25))
    h.v.selection = []
    h.v._changed()
    h.camera([0.5, 0.0, 0.0], 14, [0.0, 0.0, 1.0])
    h.pump(0.1)
    return plane


def _lum(c):
    return 0.3 * c.red() + 0.59 * c.green() + 0.11 * c.blue()


def test_stroke_behind_plane_tinted_in_front_not(h: H):
    plane = _setup(h)
    img = h.grab()
    behind_in = img.pixelColor(*map(int, (h.scr([0.0, 0.5, -2.0]).x(), h.scr([0.0, 0.5, -2.0]).y())))
    behind_out = img.pixelColor(*map(int, (h.scr([4.5, 0.5, -2.0]).x(), h.scr([4.5, 0.5, -2.0]).y())))
    front_in = img.pixelColor(*map(int, (h.scr([0.0, -0.8, 2.0]).x(), h.scr([0.0, -0.8, 2.0]).y())))
    front_out = img.pixelColor(*map(int, (h.scr([4.5, -0.8, 2.0]).x(), h.scr([4.5, -0.8, 2.0]).y())))
    assert _lum(behind_in) > _lum(behind_out) + 25, \
        f"behind the plane tinted: {behind_in.getRgb()} vs. outside {behind_out.getRgb()}"
    assert abs(_lum(front_in) - _lum(front_out)) < 25, \
        f"in front of the plane untinted: {front_in.getRgb()} vs. {front_out.getRgb()}"

"""Hilfsebenen tönen, was hinter ihnen liegt (Striche, Malerei) – vorher schien es ungetönt durch (Hafentest 09.11.).
Was vor der Ebene liegt, bleibt ungetönt."""
import numpy as np

from tests.harness import H


def _setup(h):
    h.new_scene()
    sc = h.sc
    plane = sc.new_plane(np.array([0.0, 0.0, 0.0]), np.array([1.0, 0, 0]), np.array([0, 1.0, 0]))
    plane.size_u = plane.size_v = 4.0
    sc.new_stroke()
    # dunkler Strich hinter der Ebene (z = -2), ein Stück ragt seitlich über die Ebene hinaus
    sc.add_curve(np.linspace([-1.0, 0.5, -2.0], [5.0, 0.5, -2.0], 40), None, np.full(40, 0.25))
    # derselbe Strich vor der Ebene (z = +2)
    sc.add_curve(np.linspace([-1.0, -0.8, 2.0], [5.0, -0.8, 2.0], 40), None, np.full(40, 0.25))
    h.v.selection = []
    h.v._changed()
    h.camera([0.5, 0.0, 0.0], 14, [0.0, 0.0, 1.0])
    h.pump(0.1)
    return plane


def _lum(c):
    return 0.3 * c.red() + 0.59 * c.green() + 0.11 * c.blue()


def test_strich_hinter_ebene_getoent_davor_nicht(h: H):
    plane = _setup(h)
    img = h.grab()
    behind_in = img.pixelColor(*map(int, (h.scr([0.0, 0.5, -2.0]).x(), h.scr([0.0, 0.5, -2.0]).y())))
    behind_out = img.pixelColor(*map(int, (h.scr([4.5, 0.5, -2.0]).x(), h.scr([4.5, 0.5, -2.0]).y())))
    front_in = img.pixelColor(*map(int, (h.scr([0.0, -0.8, 2.0]).x(), h.scr([0.0, -0.8, 2.0]).y())))
    front_out = img.pixelColor(*map(int, (h.scr([4.5, -0.8, 2.0]).x(), h.scr([4.5, -0.8, 2.0]).y())))
    assert _lum(behind_in) > _lum(behind_out) + 25, \
        f"hinter der Ebene getönt: {behind_in.getRgb()} vs. außerhalb {behind_out.getRgb()}"
    assert abs(_lum(front_in) - _lum(front_out)) < 25, \
        f"vor der Ebene ungetönt: {front_in.getRgb()} vs. {front_out.getRgb()}"

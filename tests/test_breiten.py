"""Strichbreite automatisch erzeugter Linien (Loft-Seitenlinien, Extrude-Kanten …): an den verbundenen Punkten die
echte, aktuelle Breite der Linien dort, dazwischen anteilig – nicht der Mittelwert aller Linien."""
import numpy as np

from tests.harness import H, line
from tests.test_extrude import _extrude, _select_lines
from tests.test_loft import _arc
from sketch_machine import network
from sketch_machine.scene import PatchSurface


def test_loft_seitenlinien_nehmen_die_breite_der_querschnitte(h: H):
    """Dünner Querschnitt vorn, dicker hinten: die Seitenlinie beginnt dünn und endet dick."""
    sc = h.new_scene()
    sc.new_stroke()
    thin, thick = 0.01, 0.05
    sc.add_curve(_arc((0, 0), 1.0, 0.6, 0.0), None, np.full(40, thin))
    a = sc.curves[-1]
    sc.add_curve(_arc((0, 0), 1.0, 0.6, 3.0), None, np.full(40, thick))
    b = sc.curves[-1]
    h.v._changed()
    network.sync(sc)
    st = sc.owner_of(a).id
    h.v.set_select_mode(True)
    h.v.ws.component = "edge"
    h.v.edge_selection = [("line", st, a.id), ("line", st, b.id)]
    h.v._pick_rank = {a.id: 0, b.id: 1}
    h.v._track_pick_order = lambda: None
    h.v.do_loft()
    del h.v._track_pick_order
    assert isinstance(sc.surfaces[-1], PatchSurface)
    rails = [c for c in sc.curves if c is not a and c is not b and abs(np.ptp(c.points[:, 2])) > 2.5]
    assert len(rails) == 2, f"{len(rails)} Seitenlinien statt 2"
    for r in rails:
        w = r.widths if r.points[0, 2] < r.points[-1, 2] else r.widths[::-1]
        assert abs(w[0] - thin) < 1e-6 and abs(w[-1] - thick) < 1e-6, f"Seitenlinie {w[0]:.3f} … {w[-1]:.3f}"
        assert np.all(np.diff(w) >= -1e-9), "Breite verläuft dazwischen anteilig"


def test_extrude_kanten_nehmen_die_breite_des_profils_dort(h: H):
    """Profil, das von dünn nach dick verläuft: jede Kante so breit wie das Profil an ihrem Ansatz."""
    sc = h.new_scene()
    sc.new_stroke()
    sc.add_curve(line([0, 0, 0], [2, 0, 0], 20), sc.planes[0].id, np.linspace(0.01, 0.05, 20))
    profile = sc.curves[-1]
    h.v._changed()
    network.sync(sc)
    _select_lines(h, [profile])
    h.v.ws.extrude_surface = False
    try:
        _extrude(h, length=1.0)
    finally:
        h.v.ws.extrude_surface = True
    edges = [c for c in sc.curves if len(c.points) == 2 and np.ptp(c.points[:, 1]) > 0.9]
    assert len(edges) == 2, f"{len(edges)} Kanten statt 2"
    for e in edges:
        x = e.points[0, 0]
        want = 0.01 if x < 1 else 0.05
        assert np.allclose(e.widths, want, atol=1e-6), f"Kante bei x={x:.1f}: {e.widths} statt {want}"

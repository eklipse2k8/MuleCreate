"""Stroke width of automatically generated lines (loft rails, extrude edges ...): at the connected points the
actual, current width of the lines there, proportional in between - not the mean of all lines."""
import numpy as np

from tests.harness import H, line
from tests.test_extrude import _extrude, _select_lines
from tests.test_loft import _arc
from sketch_machine import network
from sketch_machine.scene import PatchSurface


def test_loft_rails_take_the_width_of_the_cross_sections(h: H):
    """Thin cross-section in front, thicker behind: the rail starts thin and ends thick."""
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
    assert len(rails) == 2, f"{len(rails)} rails instead of 2"
    for r in rails:
        w = r.widths if r.points[0, 2] < r.points[-1, 2] else r.widths[::-1]
        assert abs(w[0] - thin) < 1e-6 and abs(w[-1] - thick) < 1e-6, f"rail {w[0]:.3f} ... {w[-1]:.3f}"
        assert np.all(np.diff(w) >= -1e-9), "width runs proportionally in between"


def test_extrude_edges_take_the_width_of_the_profile_there(h: H):
    """Profile that runs from thin to thick: each edge as wide as the profile at its root."""
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
    assert len(edges) == 2, f"{len(edges)} edges instead of 2"
    for e in edges:
        x = e.points[0, 0]
        want = 0.01 if x < 1 else 0.05
        assert np.allclose(e.widths, want, atol=1e-6), f"edge at x={x:.1f}: {e.widths} instead of {want}"

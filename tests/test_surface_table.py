"""Surface table (renderer.SURF_DATA): all surfaces in one draw call, the values per surface from a data texture.
Here with an artificially small table (renderer.SURF_ROWS = 4), so that the wrap into the next column group is
checked too."""
import numpy as np

from sketch_machine import counters, renderer
from tests.harness import H
from tests.test_material import _square

FARBEN = [(0.9, 0.1, 0.1), (0.1, 0.8, 0.1), (0.1, 0.1, 0.9), (0.9, 0.8, 0.1), (0.8, 0.1, 0.8), (0.1, 0.8, 0.8),
          (0.9, 0.5, 0.1), (0.5, 0.1, 0.9), (0.3, 0.3, 0.3), (0.6, 0.9, 0.3)]


def _reihe(h: H):
    h.new_scene()
    flaechen = []
    for k, farbe in enumerate(FARBEN):
        s = _square(h, x0=3.0 * k, size=2.0)
        s.tint = farbe
        flaechen.append(s)
    h.v._changed()
    h.frame(np.array([[0.0, 0.0, 0.0], [3.0 * len(FARBEN) - 1.0, 0.0, 2.0]]), back=(0.0, 1.0, 0.05), margin=1.25)
    return flaechen


def _farbe(h: H, img, k):
    return np.array(h.pixel(img, h.scr([3.0 * k + 1.0, 0.0, 1.0])), float) / 255.0


def _anders(a, b):
    return sum(abs(x - y) for x, y in zip(a, b))


def test_every_surface_gets_its_own_values(h: H):
    """Ten surfaces, each tinted differently, the table wraps after four rows: each shows its own color (not that of
    another row), and the whole image needs one draw call per pass."""
    renderer.SURF_ROWS = 4
    try:
        _reihe(h)
        with counters.measure() as got:
            img = h.grab()
    finally:
        renderer.SURF_ROWS = 4096
    assert 0 < got["zeichenaufrufe"] <= 5, f"surfaces drawn individually? {got['zeichenaufrufe']} calls"
    gesehen = [_farbe(h, img, k) for k in range(len(FARBEN))]
    for k, farbe in enumerate(FARBEN):
        c = gesehen[k]
        if max(farbe) - min(farbe) > 0.2:
            assert int(np.argmax(c)) == int(np.argmax(farbe)), f"surface {k} does not show its tint {farbe}: {c.round(2)}"
        others = [np.abs(c - gesehen[j]).max() for j in range(len(FARBEN)) if j != k]
        assert min(others) > 0.05, f"surface {k} looks like another one ({c.round(2)})"
    normal = h.grab()  # the same scene with the usual table: the same image
    assert h.diff(img, normal) == 0, "with the table wrapped the image looks different than without"


def test_carried_surface_moves_via_the_table(h: H):
    """In a rigid drag the mesh is not re-uploaded – the pose is in the table. The dragged surface (row 9,
    third column group) appears displaced, its neighbor stays."""
    renderer.SURF_ROWS = 4
    v = h.v
    try:
        flaechen = _reihe(h)
        h.edit_mode("face")
        v.selection = [flaechen[9].id]
        v.edge_selection = []
        v._changed()
        vorher = h.grab()
        h.sc.checkpoint()
        t = v.transform_target
        t.in_drag = True
        v.gizmo._drag = {"target": t}
        v._mode = "transform"
        try:
            t.translate(np.array([0.0, 0.0, 4.0]))
            im_zug = h.grab()
            mitgetragen = [s for s in v.renderer._surfaces if s.get("model") is not None]
        finally:
            v.gizmo._drag = None
            v._mode = None
            t.in_drag = False
            t.end_rigid()
            v._changed()
    finally:
        renderer.SURF_ROWS = 4096
    assert mitgetragen, "in a rigid drag the surface should be carried along (pose matrix)"
    alt = h.scr([28.0, 0.0, 1.0])
    assert _anders(h.pixel(vorher, alt), h.pixel(im_zug, alt)) > 30, "the dragged surface is still at its old place"
    nachbar = h.scr([25.0, 0.0, 1.0])
    assert _anders(h.pixel(vorher, nachbar), h.pixel(im_zug, nachbar)) < 12, "the neighboring surface changed during the drag"

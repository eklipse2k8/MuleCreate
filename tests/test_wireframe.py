"""Imported meshes: X-ray shows every layer, wireframe only the (polygon) edges."""
import numpy as np

from tests.harness import H
from sketch_machine import geometry
from sketch_machine.geometry import Geometry
from sketch_machine.scene import MeshObject


def test_polygon_edges_without_diagonals(h: H):
    counts = [4] * 6
    idx = [0, 1, 2, 3, 4, 5, 6, 7, 0, 1, 5, 4, 1, 2, 6, 5, 2, 3, 7, 6, 3, 0, 4, 7]
    pos, nxt = geometry.polygon_edges(counts, idx)
    idx = np.array(idx)
    assert len(geometry._unique_edges(idx[pos], idx[nxt])) == 12, "cube made of quads: 12 edges"
    v = np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0], [0, 0, 1], [1, 0, 1], [1, 1, 1], [0, 1, 1]], float)
    tris = geometry._fan_triangulate(counts, idx)[0]
    assert len(Geometry(v, tris).edges) == 12, "without polygon info (OBJ): diagonals in planes are dropped"


def _plates(h: H):
    """Two plates one behind the other (x 0..2 and 1..3), camera from the front."""
    h.new_scene()
    quads = []
    for x0, z in ((0.0, 0.0), (1.0, -1.0)):
        quads.append(np.array([[x0, 0, z], [x0 + 2, 0, z], [x0 + 2, 2, z], [x0, 2, z]], float))
    v = np.vstack(quads)
    f = np.array([[0, 1, 2], [0, 2, 3], [4, 5, 6], [4, 6, 7]])
    h.sc.meshes.append(MeshObject("Platten", "", Geometry(v, f)))
    h.camera([1.5, 1.0, -0.5], 7, [0.0, 0.0, 1.0])
    return h.scr(np.array([0.5, 1.0, 0.0])), h.scr(np.array([1.5, 1.0, 0.0])), h.scr(np.array([2.5, 1.0, -1.0]))


def test_xray_shows_every_layer(h: H):
    single, both, back = _plates(h)
    try:
        h.v.set_xray(True)
        img = h.grab()
        lum = lambda q: sum(h.pixel(img, q))
        assert lum(both) < lum(single) - 6, f"two layers denser than one ({lum(both)} / {lum(single)})"
        assert abs(lum(single) - lum(back)) < 12, "one layer in front as at the back"
    finally:
        h.v.set_xray(False)


def test_wireframe_is_added_like_in_blender(h: H):
    """Wireframe is an overlay for X-ray only: the meshes stay, all edges are added; without X-ray (opaque)
    it changes nothing."""
    single, both, back = _plates(h)
    hidden_edge = h.scr(np.array([1.0, 1.0, -1.0]))  # left edge of the back plate, behind the front one
    front_edge = h.scr(np.array([2.0, 1.0, 0.0]))  # right edge of the front plate (the back surface in front of it)
    from PySide6.QtCore import QPoint

    def dark(img, q):  # darkest pixel around q (the edge is 1 px wide)
        return min(sum(h.pixel(img, QPoint(q.x() + dx, q.y() + dy))) for dx in (-1, 0, 1) for dy in (-1, 0, 1))
    try:
        solid = h.grab()
        h.v.set_wireframe(True)
        wire = h.grab()
        assert h.diff(wire, solid) == 0, "without X-ray: opaque meshes without wireframe"
        h.v.set_xray(True)
        h.v.set_wireframe(False)
        xray = h.grab()
        h.v.set_wireframe(True)
        both_on = h.grab()
        assert dark(both_on, front_edge) < dark(xray, front_edge) - 10, "with X-ray: visible edge drawn"
        assert dark(both_on, hidden_edge) < dark(xray, hidden_edge) - 10, \
            "with X-ray: the edge behind too"
    finally:
        h.v.set_wireframe(False)
        h.v.set_xray(False)

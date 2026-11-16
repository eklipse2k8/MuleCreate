"""Gruppe drehen/skalieren schnell: starre Bewegungen übernehmen Normalen (mitgedreht) und Bindungen statt neu zu
rechnen – das Ergebnis muss dasselbe sein wie neu gerechnet."""
import numpy as np

from tests.harness import H
from tests.test_material import _square
from sketch_machine.camera import rot_axis
from sketch_machine.renderer import _corner_normals, _rigid_rotation


def test_starre_bewegung_erkannt_sonst_nicht(h: H):
    rng = np.random.default_rng(1)
    P = rng.random((300, 3)) * 50
    R = rot_axis(np.array([1.0, 2.0, 0.5]) / np.linalg.norm([1.0, 2.0, 0.5]), 0.7)
    assert np.allclose(_rigid_rotation(P, (P @ R.T) * 1.3 + 4), R)
    flat = P * np.array([1, 0, 1])
    assert np.allclose(_rigid_rotation(flat, flat @ R.T), R), "ebene Form"
    assert _rigid_rotation(P, P * np.array([-1, 1, 1])) is None, "gespiegelt"
    assert _rigid_rotation(P, P * np.array([1, 2, 1])) is None, "ungleichmäßig skaliert"
    Q = P @ R.T
    Q[17] += 0.01
    assert _rigid_rotation(P, Q) is None, "ein Punkt verformt"


def test_mitgedrehte_normalen_wie_neu_gerechnet(h: H):
    h.new_scene()
    s = _square(h, y=0.0, x0=-1.0, size=2.0)
    h.grab()
    rend = h.v.renderer
    verts, tris = (np.array(x) for x in s.fill_mesh()[:2])
    verts[:, 1] += 0.2 * verts[:, 0] ** 2 + 0.1 * verts[:, 2]  # gewölbt: Normalen verschieden
    rend._corner_data(verts, tris, {}, sid=999)
    R = rot_axis(np.array([0.0, 1.0, 0.0]), 0.9) @ rot_axis(np.array([1.0, 0.0, 0.0]), 0.4)
    moved = (verts - 1.0) @ R.T * 2.0 + 5.0
    corner, _calm, _rough = rend._corner_data(moved, tris, {}, sid=999)
    fresh = _corner_normals(moved, tris)[0].reshape(-1, 3)
    assert np.allclose(corner, fresh, atol=1e-6)

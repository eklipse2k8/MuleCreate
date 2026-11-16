"""Importierte Meshes: X-Ray zeigt jede Schicht, Drahtgitter nur die (Polygon-)Kanten."""
import numpy as np

from tests.harness import H
from sketch_machine import geometry
from sketch_machine.geometry import Geometry
from sketch_machine.scene import MeshObject


def test_polygonkanten_ohne_diagonalen(h: H):
    counts = [4] * 6
    idx = [0, 1, 2, 3, 4, 5, 6, 7, 0, 1, 5, 4, 1, 2, 6, 5, 2, 3, 7, 6, 3, 0, 4, 7]
    pos, nxt = geometry.polygon_edges(counts, idx)
    idx = np.array(idx)
    assert len(geometry._unique_edges(idx[pos], idx[nxt])) == 12, "Würfel aus Vierecken: 12 Kanten"
    v = np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0], [0, 0, 1], [1, 0, 1], [1, 1, 1], [0, 1, 1]], float)
    tris = geometry._fan_triangulate(counts, idx)[0]
    assert len(Geometry(v, tris).edges) == 12, "ohne Polygon-Infos (OBJ): Diagonalen in Ebenen fallen weg"


def _plates(h: H):
    """Zwei hintereinanderliegende Platten (x 0..2 bzw. 1..3), Kamera von vorn."""
    h.new_scene()
    quads = []
    for x0, z in ((0.0, 0.0), (1.0, -1.0)):
        quads.append(np.array([[x0, 0, z], [x0 + 2, 0, z], [x0 + 2, 2, z], [x0, 2, z]], float))
    v = np.vstack(quads)
    f = np.array([[0, 1, 2], [0, 2, 3], [4, 5, 6], [4, 6, 7]])
    h.sc.meshes.append(MeshObject("Platten", "", Geometry(v, f)))
    h.camera([1.5, 1.0, -0.5], 7, [0.0, 0.0, 1.0])
    return h.scr(np.array([0.5, 1.0, 0.0])), h.scr(np.array([1.5, 1.0, 0.0])), h.scr(np.array([2.5, 1.0, -1.0]))


def test_xray_zeigt_jede_schicht(h: H):
    single, both, back = _plates(h)
    try:
        h.v.set_xray(True)
        img = h.grab()
        lum = lambda q: sum(h.pixel(img, q))
        assert lum(both) < lum(single) - 6, f"zwei Schichten dichter als eine ({lum(both)} / {lum(single)})"
        assert abs(lum(single) - lum(back)) < 12, "eine Schicht vorn wie hinten"
    finally:
        h.v.set_xray(False)


def test_drahtgitter_kommt_dazu_wie_in_blender(h: H):
    """Drahtgitter ist ein Overlay nur fürs X-Ray: die Meshes bleiben, alle Kanten kommen dazu; ohne X-Ray (deckend)
    ändert es nichts."""
    single, both, back = _plates(h)
    hidden_edge = h.scr(np.array([1.0, 1.0, -1.0]))  # linke Kante der hinteren Platte, hinter der vorderen
    front_edge = h.scr(np.array([2.0, 1.0, 0.0]))  # rechte Kante der vorderen Platte (davor die hintere Fläche)
    from PySide6.QtCore import QPoint

    def dark(img, q):  # dunkelstes Pixel um q (die Kante ist 1 px breit)
        return min(sum(h.pixel(img, QPoint(q.x() + dx, q.y() + dy))) for dx in (-1, 0, 1) for dy in (-1, 0, 1))
    try:
        solid = h.grab()
        h.v.set_wireframe(True)
        wire = h.grab()
        assert h.diff(wire, solid) == 0, "ohne X-Ray: deckende Meshes ohne Drahtgitter"
        h.v.set_xray(True)
        h.v.set_wireframe(False)
        xray = h.grab()
        h.v.set_wireframe(True)
        both_on = h.grab()
        assert dark(both_on, front_edge) < dark(xray, front_edge) - 10, "mit X-Ray: sichtbare Kante gezeichnet"
        assert dark(both_on, hidden_edge) < dark(xray, hidden_edge) - 10, \
            "mit X-Ray: auch die Kante dahinter"
    finally:
        h.v.set_wireframe(False)
        h.v.set_xray(False)

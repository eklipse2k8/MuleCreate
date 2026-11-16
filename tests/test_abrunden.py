"""Abrunden (Strg+B) einer Umriss-Ecke einer Füllfläche: die Fläche folgt dem Bogen, als hätte man einen Punkt eingefügt
und die Linie von Hand gerundet. Früher blieb die Fläche mit spitzer Ecke stehen (Umriss galt als unterbrochen) und
folgte danach gar nichts mehr – der Bogen lag neben ihrem Rand."""
import numpy as np
from PySide6.QtCore import Qt, QPointF

from tests.harness import H
from tests.test_loft import _size
from tests.test_treffer import _z_fill, _bend
from sketch_machine.vp.snapping import _point_mesh_distance


def _bevel_corner(h: H, corner, px=60):
    """Ecke im Punktmodus wählen, Strg+B, Maus px nach links, Klick. -> neue Linien"""
    before = {c.id for c in h.curves()}
    h.edit_mode("point")
    h.click(h.scr(corner))
    h.key(Qt.Key_B, Qt.ControlModifier)
    p0 = h.scrf(corner)
    h.move(QPointF(p0.x() - px, p0.y()))
    h.click(QPointF(p0.x() - px, p0.y()).toPoint())
    h.sc.sync_lofts()
    h.grab()
    return [c for c in h.curves() if c.id not in before]


def _check_follows(surf, arc, corner):
    verts, tris = surf.fill_mesh()[:2]
    size = _size(verts)
    loop = surf.loop_points()
    assert min(np.linalg.norm(loop - corner, axis=1)) > 0.02 * size, "Fläche hat noch die spitze Ecke"
    on_rim = max(min(np.linalg.norm(loop - p, axis=1)) for p in arc.points)
    assert on_rim < 1e-6 * size, f"Umriss der Fläche läuft {on_rim:.3f} neben dem Bogen"
    off = max(_point_mesh_distance(p, verts, tris) for p in arc.points) / size
    assert off < 0.01, f"Bogen {off:.1%} neben der Fläche"


def test_abrunden_einer_umriss_ecke(h: H):
    for bent in (False, True):
        surf, lines = _z_fill(h)
        if bent:
            _bend(h, lines)
        corner = lines[1].points[0].copy()  # (6, 0, 0): Linie 0 trifft Linie 1
        new = _bevel_corner(h, corner)
        assert len(new) == 1, f"ein Bogen erwartet, {len(new)} neue Linien"
        arc = new[0]
        _check_follows(surf, arc, corner)
        # die Fläche folgt weiter ihrem Umriss (sie ist nicht eingefroren)
        before = surf.fill_mesh()[0].copy()
        c = lines[5]  # unterer Rand (6, 0, 6) -> (0, 0, 6)
        c.points = c.points.copy()
        c.points[:, 1] += 0.6 * np.sin(np.linspace(0, np.pi, len(c.points)))
        h.v._changed()
        h.sc.sync_lofts()
        verts = surf.fill_mesh()[0]
        assert verts.shape != before.shape or np.abs(verts - before).max() > 0.1, "Fläche folgt dem Umriss nicht mehr"
        _check_follows(surf, arc, corner)
        # Strg+Z (erst die Auswahl, dann das Abrunden): Ecke und Fläche wie vorher
        h.key(Qt.Key_Z, Qt.ControlModifier)
        h.key(Qt.Key_Z, Qt.ControlModifier)
        h.sc.sync_lofts()
        h.v._changed()
        loop = h.sc.surfaces[0].loop_points()
        assert min(np.linalg.norm(loop - corner, axis=1)) < 1e-6, "nach Rückgängig wieder spitze Ecke"

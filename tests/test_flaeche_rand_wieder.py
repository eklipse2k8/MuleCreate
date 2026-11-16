"""Kurvenflächen verlieren ihre Randlinie nicht (Alpaka-Tank 14.11.): eine geteilte oder zusammengelegte Randlinie
überlebt Speichern und Laden, und Cleanup „Flächen wieder an ihre Linien hängen“ hängt eine Kurvenfläche, der eine
Randlinie fehlt, an die Linie, die genau auf ihrem Rand liegt – nur wenn das eindeutig ist."""
import os
import tempfile

import numpy as np

from tests.harness import H
from tests.test_netz import _square_patch
from sketch_machine import cleanup, network
from sketch_machine.scene import PatchSurface, Scene


def _split_mid(sc, c):
    owner = sc.owner_of(c)
    i = len(c.points) // 2
    sc._split_in(owner, c, c.points[i].copy(), i, 0.0)
    network.sync(sc)
    sc.sync_lofts()


def _lift(sc, curves, dy=0.5):
    for c in curves:
        c.points = c.points + np.array([0, dy, 0])
    network.sync(sc)
    sc.sync_lofts()


def _edge_y(surf):
    g = surf.grid()
    return g[-1, 1:-1, 1], g[0, 1:-1, 1], g[1:-1, 0, 1], g[1:-1, -1, 1]


def test_geteilte_randlinie_uebersteht_speichern(h: H):
    sc = h.sc
    surf, border = _square_patch(h)
    _split_mid(sc, border[2])
    assert sc.curve_by_id(border[2].id) is None and sc._patch_sides(surf) is not None, "geteilt, Fläche folgt"
    path = os.path.join(tempfile.mkdtemp(), "rand.mule")
    sc.save(path)
    sc2 = Scene.load(path)[0]
    s2 = next(s for s in sc2.surfaces if isinstance(s, PatchSurface))
    assert 0 not in s2.patch_lines, f"Randlinie beim Laden verloren: {s2.patch_lines}"
    assert sc2._patch_sides(s2) is not None, "Fläche hängt nach dem Laden an allen Randlinien"


def test_cleanup_haengt_fehlende_randlinie_an(h: H):
    sc = h.sc
    surf, border = _square_patch(h)
    k = surf.patch_lines.index(border[2].id)
    surf.patch_lines[k] = 0  # id verloren (so stand es in der Alpaka-Datei)
    assert sc._patch_sides(surf) is None
    assert cleanup.relink_surfaces(sc, [surf]) == 1
    assert surf.patch_lines[k] == border[2].id and sc._patch_sides(surf) is not None
    before = [e.copy() for e in _edge_y(surf)]
    _lift(sc, [border[2]])
    moved = [float(np.abs(a - b).max()) for a, b in zip(_edge_y(surf), before)]
    assert max(moved) > 0.4, f"Fläche folgt der wieder angehängten Randlinie nicht: {moved}"


def test_cleanup_haengt_kette_aus_stuecken_an(h: H):
    sc = h.sc
    surf, border = _square_patch(h)
    k = surf.patch_lines.index(border[1].id)
    _split_mid(sc, border[1])
    pieces = sc.split_pieces(surf.patch_lines[k])
    sc.split_map.clear()
    surf.patch_lines[k] = 0
    assert cleanup.relink_surfaces(sc, [surf]) == 1
    assert sorted(sc.split_pieces(surf.patch_lines[k])) == sorted(pieces), "beide Stücke als Randseite"
    assert sc._patch_sides(surf) is not None
    g0 = surf.grid().copy()
    sc.sync_lofts()
    assert np.abs(surf.grid() - g0).max() < 1e-6, "Anhängen ändert die Form nicht"


def test_cleanup_raet_nicht(h: H):
    """Liegt die Linie nicht mehr genau auf dem Rand, bleibt die Seite offen."""
    sc = h.sc
    surf, border = _square_patch(h)
    k = surf.patch_lines.index(border[2].id)
    surf.patch_lines[k] = 0
    _lift(sc, [border[2]], dy=0.2)
    assert cleanup.relink_surfaces(sc, [surf]) == 0
    assert surf.patch_lines[k] == 0

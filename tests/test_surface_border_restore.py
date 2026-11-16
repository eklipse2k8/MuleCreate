"""Curve surfaces do not lose their border line (alpaca tank 14.11.): a split or merged border line
survives saving and loading, and the cleanup "Reattach surfaces to their lines" attaches a curve surface that is
missing a border line to the line lying exactly on its border – only if that is unambiguous."""
import os
import tempfile

import numpy as np

from tests.harness import H
from tests.test_net import _square_patch
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


def test_split_border_line_survives_saving(h: H):
    sc = h.sc
    surf, border = _square_patch(h)
    _split_mid(sc, border[2])
    assert sc.curve_by_id(border[2].id) is None and sc._patch_sides(surf) is not None, "split, surface follows"
    path = os.path.join(tempfile.mkdtemp(), "rand.mule")
    sc.save(path)
    sc2 = Scene.load(path)[0]
    s2 = next(s for s in sc2.surfaces if isinstance(s, PatchSurface))
    assert 0 not in s2.patch_lines, f"border line lost on loading: {s2.patch_lines}"
    assert sc2._patch_sides(s2) is not None, "surface is attached to all border lines after loading"


def test_cleanup_reattaches_missing_border_line(h: H):
    sc = h.sc
    surf, border = _square_patch(h)
    k = surf.patch_lines.index(border[2].id)
    surf.patch_lines[k] = 0  # id lost (this is how it was in the alpaca file)
    assert sc._patch_sides(surf) is None
    assert cleanup.relink_surfaces(sc, [surf]) == 1
    assert surf.patch_lines[k] == border[2].id and sc._patch_sides(surf) is not None
    before = [e.copy() for e in _edge_y(surf)]
    _lift(sc, [border[2]])
    moved = [float(np.abs(a - b).max()) for a, b in zip(_edge_y(surf), before)]
    assert max(moved) > 0.4, f"surface does not follow the reattached border line: {moved}"


def test_cleanup_reattaches_chain_of_pieces(h: H):
    sc = h.sc
    surf, border = _square_patch(h)
    k = surf.patch_lines.index(border[1].id)
    _split_mid(sc, border[1])
    pieces = sc.split_pieces(surf.patch_lines[k])
    sc.split_map.clear()
    surf.patch_lines[k] = 0
    assert cleanup.relink_surfaces(sc, [surf]) == 1
    assert sorted(sc.split_pieces(surf.patch_lines[k])) == sorted(pieces), "both pieces as border side"
    assert sc._patch_sides(surf) is not None
    g0 = surf.grid().copy()
    sc.sync_lofts()
    assert np.abs(surf.grid() - g0).max() < 1e-6, "attaching does not change the shape"


def test_cleanup_does_not_guess(h: H):
    """If the line no longer lies exactly on the border, the side stays open."""
    sc = h.sc
    surf, border = _square_patch(h)
    k = surf.patch_lines.index(border[2].id)
    surf.patch_lines[k] = 0
    _lift(sc, [border[2]], dy=0.2)
    assert cleanup.relink_surfaces(sc, [surf]) == 0
    assert surf.patch_lines[k] == 0

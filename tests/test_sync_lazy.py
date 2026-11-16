"""Sync before a frame without a reported change (hover, camera, preview): skipped as long as nobody touched a line
or surface – and immediately full again as soon as someone does (even without Viewport._changed)."""
import numpy as np

from tests.harness import H
from tests.test_undo_speed import _two_patches


def _count(sc):
    n = [0]
    real = sc._sync_lofts
    sc._sync_lofts = lambda free: (n.__setitem__(0, n[0] + 1), real(free))[1]
    return n


def test_redraw_without_change_does_not_sync(h: H):
    sc, st, patches = _two_patches(h)
    h.v.update()
    h.grab()
    n = _count(sc)
    for _ in range(3):
        h.v.update()
        h.grab()
    assert n[0] == 0, "nothing touched: no full sync"


def test_every_change_syncs_again(h: H):
    sc, st, patches = _two_patches(h)
    h.v.update()
    h.grab()
    n = _count(sc)
    c = sc.curve_by_id(patches[0].patch_lines[0])
    mesh = patches[0].fill_mesh()[0].copy()
    pts = c.points.copy()
    pts[len(pts) // 2] += [0.0, 0.5, 0.0]
    c.points = pts  # like a gizmo drag: no _changed, just redraw
    h.v.update()
    h.grab()
    now = patches[0].fill_mesh()[0]
    assert n[0] == 1 and not (now.shape == mesh.shape and np.allclose(now, mesh)), "line moved: surface follows in the next frame"
    patches[1].resolution = patches[1].resolution * 2  # field of a surface set
    h.v.update()
    h.grab()
    assert n[0] == 2, "field of a surface changed: full sync"
    patches[1].attached[-1] = {"uv": np.zeros((2, 2)), "on": np.ones(2, bool), "last": b""}  # extended in place
    h.v.update()
    h.grab()
    assert n[0] == 3, "reference list of a surface grew: full sync"
    h.v._changed()
    assert n[0] == 4, "a reported change always syncs fully"

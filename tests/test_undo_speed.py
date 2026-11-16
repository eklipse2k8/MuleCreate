"""Undo without a full copy of the arrays: the snapshot shares numpy arrays with the scene (read-only) and takes the
surfaces' caches along - after undo only what really changed is recomputed."""
import copy

import numpy as np

from sketch_machine import network
from tests.harness import H, line


def _two_patches(h):
    h.new_scene()
    sc = h.sc
    st = sc.new_stroke()
    patches = []
    for x0 in (0.0, 5.0):
        first = len(st.curves)
        pts = [[x0, 0, 0], [x0 + 2, 0, 0], [x0 + 2, 0, 2], [x0, 0, 2], [x0, 0, 0]]
        for p, q in zip(pts[:-1], pts[1:]):
            sc.add_curve(line(p, q, 8), None)
        network.sync(sc)
        h.v.selection = []
        h.v.edge_selection = [("line", st.id, c.id) for c in st.curves[first:]]
        h.v.do_patch()
        patches.append(sc.surfaces[-1])
    h.v.selection, h.v.edge_selection = [], []
    h.v._changed()
    return sc, st, patches


def test_snapshot_shares_arrays_read_only(h: H):
    sc, st, patches = _two_patches(h)
    c = st.curves[0]
    pts = c.points
    sc.checkpoint()
    snap_curve = sc._undo[-1][2][0].curves[0]
    assert snap_curve is not c and snap_curve.points is pts, "copy of the object, same array"
    assert not pts.flags.writeable, "shared array is read-only"
    try:
        pts[0, 0] = 99.0
    except ValueError:
        pass
    else:
        raise AssertionError("in-place modification must fail (would otherwise corrupt the history)")
    c.points = c.points + [0.0, 1.0, 0.0]  # replacing is the right way
    assert np.allclose(snap_curve.points, pts) and not np.allclose(c.points, pts)


def test_copy_outside_the_history_stays_independent(h: H):
    sc, st, patches = _two_patches(h)
    c = st.curves[0]
    dup = copy.deepcopy(c)  # clipboard, duplicate
    assert dup.points is not c.points and dup.points.flags.writeable and np.array_equal(dup.points, c.points)
    assert dup.pids is not c.pids and dup.pids == c.pids


def test_undo_recomputes_no_surface(h: H):
    """After undo/redo the carried-along caches apply: no surface reclassifies its net
    (without them every one would - harbour scene: 0.35 s per undo)."""
    from sketch_machine.scene_surfaces import SurfaceSyncMixin
    sc, st, patches = _two_patches(h)
    calls = []
    real = SurfaceSyncMixin._net_classify
    SurfaceSyncMixin._net_classify = lambda self, *a, **k: (calls.append(1), real(self, *a, **k))[1]
    try:
        h.v._changed()
        assert not calls, "nothing changed: nothing reclassified"
        sc.checkpoint()
        moved = sc.curve_by_id(patches[0].patch_lines[0])
        before = moved.points.copy()
        mesh_b = patches[1].fill_mesh()[0]
        pts = moved.points.copy()
        pts[len(pts) // 2] += [0.0, 0.4, 0.0]
        moved.points = pts
        h.v._changed()
        assert len(calls) == 1, "only the changed surface is reclassified"
        del calls[:]
        sc.undo()
        h.v._changed()
        assert not calls, f"undo: caches still apply ({len(calls)} surfaces reclassified)"
        a2, b2 = sc.surfaces[-2:]
        assert np.allclose(sc.curve_by_id(a2.patch_lines[0]).points, before), "line back at its old place"
        assert np.array_equal(b2.fill_mesh()[0], mesh_b), "untouched surface unchanged"
        sc.redo()
        h.v._changed()
        assert not calls, "redo likewise"
        assert np.allclose(sc.curve_by_id(sc.surfaces[-2].patch_lines[0]).points, pts)
    finally:
        SurfaceSyncMixin._net_classify = real


def test_undo_redo_sequence_stays_exact(h: H):
    """Several steps back and forth: every state returns bit-exactly (shared arrays must never change)."""
    sc, st, patches = _two_patches(h)
    states = []
    rng = np.random.default_rng(3)
    for step in range(5):
        states.append([c.points.copy() for c in st.curves])
        sc.checkpoint()
        c = st.curves[int(rng.integers(len(st.curves)))]
        pts = c.points.copy()
        pts[len(pts) // 2] += rng.normal(0, 0.2, 3)
        c.points = pts
        h.v._changed()
    final = [c.points.copy() for c in sc.strokes[0].curves]
    for want in reversed(states):
        sc.undo()
        h.v._changed()
        got = [c.points for c in sc.strokes[0].curves]
        assert len(got) == len(want) and all(np.array_equal(a, b) for a, b in zip(got, want)), "undo state differs"
    for _ in states:
        sc.redo()
        h.v._changed()
    got = [c.points for c in sc.strokes[0].curves]
    assert all(np.allclose(a, b, atol=1e-9) for a, b in zip(got, final)), "redo state differs"

"""Rigid movement: surfaces whose lines are all dragged along are only carried during the gizmo drag (no sync per
frame) and follow their lines again after release (harbour test 09.11.: moving the hero building took 0.5 s per frame)."""
import json
import os
import tempfile

import numpy as np

from sketch_machine import network
from tests.harness import H, line


def _square_in_null(h):
    h.new_scene()
    sc = h.sc
    st = sc.new_stroke()
    pts = [[0, 0, 0], [2, 0, 0], [2, 0, 2], [0, 0, 2], [0, 0, 0]]
    for p, q in zip(pts[:-1], pts[1:]):
        sc.add_curve(line(p, q, 8), None)
    network.sync(sc)
    h.v.edge_selection = [("line", st.id, c.id) for c in st.curves]
    h.v.do_patch()
    patch = sc.surfaces[-1]
    h.v.selection = [st.id, patch.id]
    h.v.create_null("null")
    null = sc.nulls[-1]
    h.v.selection = [null.id]
    h.v._changed()
    return sc, st, patch, null


def test_surface_is_carried_and_follows_afterwards(h: H):
    sc, st, patch, null = _square_in_null(h)
    before = patch.fill_mesh()[0].copy()
    target = h.v.transform_target
    target.in_drag = True  # like Gizmo.begin
    d = np.array([1.0, 0.5, -0.25])
    target.translate(d / 2)
    target.translate(d / 2)
    assert getattr(patch, "_carried", False) and patch.frozen is not None, "carried during the drag"
    assert np.allclose(patch.fill_mesh()[0], before + d), "net moves rigidly along"
    h.v._changed()  # sync during the drag: skips it
    assert getattr(patch, "_carried", False)
    target.in_drag = False
    target.end_rigid()  # like Gizmo.end
    h.v._changed()
    assert patch.frozen is None and not getattr(patch, "_carried", False), "free again after the drag"
    assert np.allclose(patch.fill_mesh()[0], before + d, atol=1e-6), "freshly built = carried"


def test_non_uniform_scaling_deforms_normally(h: H):
    sc, st, patch, null = _square_in_null(h)
    target = h.v.transform_target
    target.in_drag = True
    target.scale(np.array([2.0, 1.0, 1.0]), np.eye(3), np.zeros(3))
    assert patch.frozen is None, "deformed: do not carry"
    target.in_drag = False
    target.end_rigid()


def test_save_and_undo_in_the_middle_of_a_drag(h: H):
    sc, st, patch, null = _square_in_null(h)
    sc.checkpoint()
    target = h.v.transform_target
    target.in_drag = True
    target.translate(np.array([1.0, 0, 0]))
    path = os.path.join(tempfile.mkdtemp(), "drag.sketch.json")
    sc.save(path)
    data = json.load(open(path, encoding="utf-8"))
    assert not any("frozen" in f for f in data["surfaces"]), "carried is never saved as frozen"
    sc.undo()
    h.v._changed()
    assert all(s.frozen is None for s in sc.surfaces), "nothing frozen after undo"
    target.in_drag = False
    target.end_rigid()


def test_frame_during_drag_same_as_afterwards(h: H):
    """Pose matrix on the GPU (net from the start of the drag) draws the same picture as the net freshly built afterwards."""
    sc, st, patch, null = _square_in_null(h)
    h.camera([1.5, 0.0, 1.0], 7, [0.3, 0.8, 0.5])
    h.v._changed()
    target = h.v.transform_target
    target.in_drag = True
    target.translate(np.array([0.4, 0.2, 0.1]))
    rot = np.array([[np.cos(0.3), 0, np.sin(0.3)], [0, 1, 0], [-np.sin(0.3), 0, np.cos(0.3)]])
    target.rotate(rot, np.array([1.0, 0.0, 1.0]))
    assert getattr(patch, "_carry_model", None) is not None, "display via pose matrix"
    during = h.grab()
    target.in_drag = False
    target.end_rigid()
    h.v._changed()
    after = h.grab()
    n = h.diff(during, after, threshold=6)
    assert n < 200, f"frame during the drag differs from the freshly built one ({n} pixels)"


def _square_with_paint(h):
    """Curve surface made of four lines, on it two paint strokes – all in ONE line object, the surface not selected."""
    h.new_scene()
    sc = h.sc
    st = sc.new_stroke()
    pts = [[0, 0, 0], [2, 0, 0], [2, 0, 2], [0, 0, 2], [0, 0, 0]]
    for p, q in zip(pts[:-1], pts[1:]):
        sc.add_curve(line(p, q, 8), None)
    network.sync(sc)
    h.v.edge_selection = [("line", st.id, c.id) for c in st.curves]
    h.v.do_patch()
    patch = sc.surfaces[-1]
    sc.active_stroke = st
    for z in (0.6, 1.4):
        sc.add_curve(line([0.4, 0, z], [1.6, 0, z + 0.2], 10), patch.id)
        st.curves[-1].paint = True
    h.v.edge_selection = []
    h.v._changed()
    paint = [c for c in st.curves if c.paint]
    assert all(c.id in patch.attached for c in paint), "paint sticks to the surface"
    return sc, st, patch, paint


def _drag_all(h, target, patch, st):
    """Replay a drag (move + rotate); returns the total movement as a function."""
    before = {c.id: c.points.copy() for c in st.curves}
    mesh = patch.fill_mesh()[0].copy()
    target.in_drag = True
    d = np.array([0.7, 0.3, -0.4])
    rot = np.array([[np.cos(0.4), 0, np.sin(0.4)], [0, 1, 0], [-np.sin(0.4), 0, np.cos(0.4)]])
    piv = np.array([1.0, 0.0, 1.0])
    target.translate(d)
    h.v._changed()
    target.rotate(rot, piv)
    h.v._changed()
    move = lambda p: piv + (p + d - piv) @ rot.T
    return before, mesh, move


def _check_followed(h, sc, st, patch, paint, target, before, mesh, move):
    assert getattr(patch, "_carried", False), "carried during the drag although the surface is not selected"
    assert np.allclose(patch.fill_mesh()[0], move(mesh)), "net moves rigidly along"
    target.in_drag = False
    target.end_rigid()
    h.v._changed()
    assert patch.frozen is None and not getattr(patch, "_carried", False)
    assert np.allclose(patch.fill_mesh()[0], move(mesh), atol=1e-6), "freshly built = carried"
    for c in st.curves:
        assert np.allclose(c.points, move(before[c.id]), atol=1e-4), "lines and paint moved rigidly"
    assert all(c.plane_id == patch.id and c.id in patch.attached for c in paint), "paint still sticks"


def test_moving_line_object_carries_surface(h: H):
    """Talking points 10.11.: move line object (border lines + paint), surface not selected – 3.4 s per frame, because
    every paint stroke was rebound in every frame."""
    sc, st, patch, paint = _square_with_paint(h)
    h.v.selection = [st.id]
    h.v._changed()
    target = h.v.transform_target
    _check_followed(h, sc, st, patch, paint, target, *_drag_all(h, target, patch, st))


def test_all_lines_in_edge_mode_carry_surface(h: H):
    sc, st, patch, paint = _square_with_paint(h)
    h.edit_mode("edge")
    h.v.selection = []
    h.v.edge_selection = [("line", st.id, c.id) for c in st.curves]
    h.v._changed()
    target = h.v.transform_target
    _check_followed(h, sc, st, patch, paint, target, *_drag_all(h, target, patch, st))


def test_moving_only_paint_carries_nothing(h: H):
    """Only the paint strokes dragged: the surface stays put and is not carried."""
    sc, st, patch, paint = _square_with_paint(h)
    mesh = patch.fill_mesh()[0].copy()
    h.edit_mode("edge")
    h.v.selection = []
    h.v.edge_selection = [("line", st.id, c.id) for c in paint]
    h.v._changed()
    target = h.v.transform_target
    target.in_drag = True
    target.translate(np.array([0.1, 0.0, 0.1]))
    h.v._changed()
    assert getattr(patch, "_carry_model", None) is None, "surface does not travel with the paint"
    assert np.allclose(patch.fill_mesh()[0], mesh)
    target.in_drag = False
    target.end_rigid()
    h.v._changed()
    assert np.allclose(patch.fill_mesh()[0], mesh)


def test_softly_dragged_neighbour_line_prevents_holding(h: H):
    """A second surface touches the moving one only at a corner: its two border lines there are dragged softly along. It hangs
    on no selected line, but must not be held (it deforms); the first is carried."""
    sc, st, patch, paint = _square_with_paint(h)
    first = list(st.curves)
    sc.active_stroke = st
    pts = [[2, 0, 2], [4, 0, 2], [4, 0, 4], [2, 0, 4], [2, 0, 2]]
    for p, q in zip(pts[:-1], pts[1:]):
        sc.add_curve(line(p, q, 8), None)
    second = [c for c in st.curves if c not in first]
    network.sync(sc)
    h.edit_mode("edge")
    h.v.selection = []
    h.v.edge_selection = [("line", st.id, c.id) for c in second]
    h.v.do_patch()
    other = sc.surfaces[-1]
    assert other is not patch
    h.v.selection = []  # do_patch selects the new surface – here only the lines of the first are selected
    h.v.edge_selection = [("line", st.id, c.id) for c in first]
    h.v._changed()
    mesh = other.fill_mesh()[0].copy()
    target = h.v.transform_target
    target.in_drag = True
    target.translate(np.array([-0.5, 0.0, -0.5]))
    h.v._changed()
    assert getattr(patch, "_carried", False), "surface of the selected lines is carried"
    assert other.frozen is None, "neighbour surface with softly dragged border lines is not held"
    assert not np.allclose(other.fill_mesh()[0], mesh), "neighbour surface already follows its deformed corner during the drag"
    target.in_drag = False
    target.end_rigid()
    h.v._changed()
    assert patch.frozen is None and other.frozen is None


def test_uninvolved_surface_is_not_resynced_after_the_drag(h: H):
    """A surface that hangs on nothing moving is only held during the drag: its stamp still applies after release
    (before, every release resynced all surfaces of the scene)."""
    sc, st, patch, null = _square_in_null(h)
    other = sc.new_stroke()
    other.parent = None  # not in the group that is about to be moved
    pts = [[5, 0, 0], [7, 0, 0], [7, 0, 2], [5, 0, 2], [5, 0, 0]]
    for p, q in zip(pts[:-1], pts[1:]):
        sc.add_curve(line(p, q, 8), None)
    network.sync(sc)
    h.v.edge_selection = [("line", other.id, c.id) for c in other.curves]
    h.v.do_patch()
    far = sc.surfaces[-1]
    far.parent = None
    assert far not in sc.descendants(null) and other not in sc.descendants(null)
    h.v.edge_selection = []
    h.v.selection = [null.id]
    h.v._changed()
    h.v._changed()
    stamp, mesh = far.__dict__.get("_sync_ok"), far.fill_mesh()[0]
    assert stamp is not None
    target = h.v.transform_target
    target.in_drag = True
    target.translate(np.array([0.5, 0.0, 0.25]))
    h.v._changed()
    assert far.__dict__.get("_idle_hold") and not patch.__dict__.get("_idle_hold")
    assert far.frozen is not None and patch.frozen is not None, "both held during the drag"
    target.in_drag = False
    target.end_rigid()
    assert far.frozen is None and far.__dict__.get("_sync_ok") == stamp, "stamp of the uninvolved one still applies"
    assert patch.__dict__.get("_sync_ok") is not None, "the moved one is shifted along and counts as synced"
    h.v._changed()
    assert far.fill_mesh()[0] is mesh, "nothing recomputed"
    assert np.allclose(patch.fill_mesh()[0].mean(axis=0), [1.5, 0.0, 1.25]), "the moved one has followed its lines"
    # if the "uninvolved" one does hang on something that changed, it syncs
    c = other.curves[0]
    c.points = c.points + np.array([0.0, 0.3, 0.0])
    h.v._changed()
    assert far.fill_mesh()[0] is not mesh


def test_moved_surface_is_not_recomputed_after_the_drag(h: H):
    """Only moved: the finished state of the surface travels along, after release nothing is rebuilt from the lines.
    (The check mode of the tests recomputes it anyway and compares.) Rotated: recomputed as before."""
    from sketch_machine.scene import SurfaceObject
    sc, st, patch, null = _square_in_null(h)
    h.v._changed()
    rows = [c.points.copy() for c in patch.curves]
    pts = [p.copy() for p in patch._net_pts]
    target = h.v.transform_target
    target.in_drag = True
    d = np.array([0.5, 0.25, -1.0])
    target.translate(d / 2)
    target.translate(d / 2)
    target.in_drag = False
    builds = []
    real = type(patch)._build
    type(patch)._build = lambda self: (builds.append(1), real(self))[1]
    try:
        target.end_rigid()
        assert patch.frozen is None and patch.__dict__.get("_sync_ok") is not None
        mesh = patch.fill_mesh()
        assert not builds, "displayed net is shifted along, not rebuilt"
    finally:
        type(patch)._build = real
    assert all(np.allclose(c.points, r + d) for c, r in zip(patch.curves, rows)), "grid rows shifted along"
    assert all(np.allclose(p, q + d) for p, q in zip(patch._net_pts, pts)), "net geometry shifted along"
    h.v._changed()  # check mode: recomputes and compares
    assert np.allclose(patch.fill_mesh()[0].mean(axis=0), np.array([1.0, 0.0, 1.0]) + d, atol=1e-6)
    # afterwards a line deforms: the surface follows as always
    c = st.curves[0]
    p = c.points.copy()
    p[len(p) // 2] += [0.0, 0.5, 0.0]
    c.points = p
    h.v._changed()
    assert patch.fill_mesh()[0][:, 1].max() > d[1] + 0.2, "follows the deformed line"
    # rotated: no shifting along
    target = h.v.transform_target
    target.in_drag = True
    a = np.radians(30.0)
    rot = np.array([[np.cos(a), 0, np.sin(a)], [0, 1, 0], [-np.sin(a), 0, np.cos(a)]])
    target.rotate(rot, np.zeros(3))
    target.in_drag = False
    target.end_rigid()
    assert patch.__dict__.get("_sync_ok") is None, "rotated: syncs again"
    h.v._changed()

"""During a gizmo drag, what cannot be seen in motion is saved: surfaces that deform get simple
light normals (exact after release), and the occlusion of the points is read back only every fourth frame."""
import numpy as np

from sketch_machine import components
from tests.harness import H
from tests.test_undo_speed import _two_patches


def _point_drag(h):
    sc, st, patches = _two_patches(h)
    h.camera([3.5, 0.0, 1.0], 12, [0.2, 0.8, 0.5])
    c = sc.curve_by_id(patches[0].patch_lines[0])
    h.edit_mode("point")
    h.v.selection, h.v.edge_selection, h.v.seg_selection = [], [], []
    h.v.point_selection = [("pt", st.id, c.id, components.knots(c)[0])]
    h.v._changed()
    h.grab()
    target = h.v.transform_target
    target.in_drag = True
    h.v.gizmo._drag = {"target": target}
    h.v._mode = "transform"
    return sc, patches, target


def _release(h, target):
    h.v.gizmo._drag = None
    h.v._mode = None
    target.in_drag = False
    target.end_rigid()
    h.v._changed()
    h.grab()


def _rough_blocks(h):
    return [hit[3] for hit in h.v.renderer._block_cache.values()]


def test_deformed_surface_rough_during_drag_exact_afterwards(h: H):
    sc, patches, target = _point_drag(h)
    target.translate(np.array([0.0, 0.3, 0.0]))
    h.v.update()
    h.grab()
    assert any(_rough_blocks(h)), "the deformed surface has simple normals during the drag"
    assert not all(_rough_blocks(h)), "the untouched surface keeps its exact ones"
    _release(h, target)
    assert not any(_rough_blocks(h)), "after release all normals are exact"
    after = h.grab()
    h.v.renderer._block_cache, h.v.renderer._normal_cache, h.v.renderer._surface_key = {}, {}, None
    h.v.update()
    fresh = h.grab()
    assert h.diff(after, fresh, threshold=2) == 0, "image after release = freshly computed image"


def test_point_occlusion_during_drag_only_every_fourth_frame(h: H):
    sc, patches, target = _point_drag(h)
    r = h.v.renderer
    calls = []
    real = r.points_visible
    r.points_visible = lambda pts: (calls.append(len(pts)), real(pts))[1]
    try:
        for _ in range(8):
            target.translate(np.array([0.0, 0.02, 0.0]))
            h.v.update()
            h.grab()
        assert len(calls) == 2, f"read back every fourth frame during the drag ({len(calls)} of 8)"
        _release(h, target)
        n = len(calls)
        h.v.update()
        h.grab()
        h.v.update()
        h.grab()
        assert len(calls) - n >= 2, "without a drag again in every frame"
    finally:
        r.points_visible = real

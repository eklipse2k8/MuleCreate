"""Zooming (Alt + right mouse button): continuous, also far out (large planes) – never a jump."""
import math

from tests.harness import H
from sketch_machine.camera import Camera


def test_zooming_from_large_distance_does_not_jump(h: H):
    cam = Camera()
    cam.dist = 1400.0  # e.g. after framing a 1 km plane
    cam.dolly(0.05)
    assert math.isclose(cam.dist, 1400.0 * math.exp(-0.05)), f"jump to {cam.dist:.0f} m"
    cam.dolly(-0.05)
    assert math.isclose(cam.dist, 1400.0)


def test_zooming_out_to_several_kilometres_and_limits(h: H):
    cam = Camera()
    cam.dist = 10.0
    for _ in range(400):
        cam.dolly(-0.05)
    assert cam.dist == Camera.MAX_DIST, cam.dist
    for _ in range(800):
        cam.dolly(0.05)
    assert cam.dist == Camera.MIN_DIST, cam.dist


def test_clip_plane_grows_with_distance(h: H):
    """Close as always (5 cm), growing along far out: front/back ratio stays, kilometre-scale terrain does not flicker."""
    import numpy as np
    from sketch_machine.vp.common import NEAR
    h.new_scene()
    h.camera([0.0, 0.0, 0.0], 10.0, [0.3, 0.8, 0.5])
    assert h.v._near() == NEAR, "normal distance: unchanged"
    h.camera([0.0, 0.0, 0.0], 5000.0, [0.3, 0.8, 0.5])
    assert math.isclose(h.v._near(), 5.0) and h.v._far() / h.v._near() <= 1e5 + 1
    eye = h.v.cam.eye
    pts = np.array([eye - h.v.cam.back * 2.0, eye - h.v.cam.back * 50.0])  # 2 m in front of the camera: clipped
    _s, ok = h.v.project(pts)
    assert list(ok) == [False, True]


def test_maximum_stroke_width_adjustable(h: H):
    """Pen in world units grows up to the set limit (default 50 m, up to 5 km); a smaller limit takes the pen along."""
    from sketch_machine.workspace import PEN_MAX_WORLD
    v = h.v
    old = (v.pen_world_mode, v.pen_world, v.pen_max_world)
    try:
        v.pen_world_mode = True
        v.pen_world = 5.0
        v._scale_pen(10.0)
        assert math.isclose(v.pen_world, 50.0), "beyond the old 10 m limit"
        for _ in range(20):
            v._scale_pen(10.0)
        assert v.pen_world == PEN_MAX_WORLD == 50.0, "default 50 m"
        v.set_pen_max_world(5000.0)
        for _ in range(20):
            v._scale_pen(10.0)
        assert v.pen_world == 5000.0, "up to 5 km by hand"
        v.set_pen_max_world(2.0)
        assert v.pen_world == 2.0 and v.pen_max_world == 2.0
        v._scale_pen(3.0)
        assert v.pen_world == 2.0
        v.set_pen_max_world(1e9)
        assert v.pen_max_world == 5000.0, "at most 5 km"
    finally:
        v.pen_world_mode, v.pen_world, v.pen_max_world = old

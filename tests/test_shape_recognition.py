"""Rectangle shape recognition (shapes.py): fit the sides instead of a bounding box, orientation without camera
influence (harbour test 09.11.: large rectangles imprecise, orientation seemed arbitrary)."""
import math

import numpy as np

from sketch_machine import shapes
from tests.harness import H


def _hand_rect(w, h, overshoot, angle=0.0, noise=0.0, seed=1):
    """Rectangle as one stroke, overshooting each corner by `overshoot` and coming back (as drawn by hand)."""
    rng = np.random.default_rng(seed)
    c = [(0, 0), (w, 0), (w, h), (0, h)]
    pts = []
    for i in range(4):
        a, b = np.array(c[i], float), np.array(c[(i + 1) % 4], float)
        d = (b - a) / np.linalg.norm(b - a)
        for t in np.linspace(0, 1, 30):
            pts.append(a + (b - a) * t)
        pts.append(b + d * overshoot)  # beyond the corner
    pts.append(np.array(c[0], float) + np.array([0, 0.3 * overshoot]))
    pts = np.array(pts) + rng.normal(0, noise, (len(pts), 2))
    rot = np.array([[math.cos(angle), -math.sin(angle)], [math.sin(angle), math.cos(angle)]])
    return pts @ rot.T


def test_overdrawn_large_rectangle_keeps_its_size(h: H):
    shape = shapes.recognize(_hand_rect(100.0, 40.0, overshoot=8.0, noise=0.3))
    assert shape is not None and shape["kind"] == "rect", shape
    w, hh = np.abs(np.asarray(shape["p1"]) - np.asarray(shape["p0"]))
    assert abs(w - 100.0) < 2.0 and abs(hh - 40.0) < 2.0, f"size {w:.1f} x {hh:.1f} instead of 100 x 40"


def test_plane_axis_instead_of_screen(h: H):
    """With a plane axis (rotated 30° in the image) a slightly skewed rectangle lies on the axis, not on the
    screen – even if it is nearly screen-parallel."""
    axis = math.radians(30)
    shape = shapes.recognize(_hand_rect(60.0, 30.0, overshoot=2.0, angle=axis + math.radians(2), noise=0.2), [axis])
    assert shape is not None and shape["kind"] == "rect", shape
    diff = (shape["angle"] - axis + math.pi / 4) % (math.pi / 2) - math.pi / 4
    assert abs(diff) < math.radians(1), f"orientation {math.degrees(shape['angle']):.1f}° instead of the plane axis 30°"

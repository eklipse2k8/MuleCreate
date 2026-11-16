"""Partial stroke upload: if only some of the strokes change (same layout), the renderer re-prepares only those
and writes them to their place in the buffer. The harness checks every partial upload against the full preparation
(Renderer.VERIFY_STROKES) – here: that the path is taken at all and the image is the same."""
import numpy as np

from sketch_machine import renderer
from tests.harness import H, line


def _scene(h):
    h.new_scene()
    sc = h.sc
    sc.new_stroke()
    for k in range(6):
        sc.add_curve(line([0, 0, 0.3 * k], [2, 0.2, 0.3 * k], 12), None)
    h.camera([1.0, 0.0, 0.8], 5, [0.2, 0.8, 0.5])
    h.v._changed()
    h.grab()
    return sc


def test_one_stroke_moved_only_it_is_re_prepared(h: H):
    sc = _scene(h)
    r = h.v.renderer
    assert renderer.Renderer.VERIFY_STROKES, "the harness checks partial uploads"
    state = r._stroke_state
    c = sc.strokes[-1].curves[2]
    c.points = c.points + np.array([0.0, 0.3, 0.0])
    h.v.update()
    part = h.grab()
    assert r._stroke_state is state and "at" in state, "same layout: partial upload instead of a rebuild"
    r._stroke_state = None  # full rebuild of the same state
    r._stroke_list = None
    h.v.update()
    full = h.grab()
    assert h.diff(part, full, threshold=2) == 0, "partial upload shows the same image as the full one"


def test_different_layout_rebuilds(h: H):
    sc = _scene(h)
    r = h.v.renderer
    state = r._stroke_state
    sc.add_curve(line([0, 0.5, 0], [2, 0.5, 0], 9), None)
    h.v._changed()
    h.grab()
    assert r._stroke_state is not state, "one more stroke: everything new"
    state = r._stroke_state
    c = sc.strokes[-1].curves[0]
    c.points = np.vstack([c.points, c.points[-1] + [0.1, 0, 0]])
    c.widths = np.append(c.widths, c.widths[-1])
    h.v._changed()
    h.grab()
    assert r._stroke_state is not state, "different point count: everything new"


def test_nothing_changed_no_new_state(h: H):
    _scene(h)
    r = h.v.renderer
    rev = r._stroke_rev
    h.v.update()
    h.grab()
    assert r._stroke_rev == rev, "same strokes: nothing uploaded (shadow map stays)"

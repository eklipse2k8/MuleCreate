"""Point marks in edit mode shrink when they are dense in the image (artist 12.11.: zoomed out they clumped into
black blotches over the object)."""
import numpy as np

from tests.harness import H


def _gitter(h: H, n=14):
    sc = h.new_scene()
    st = sc.new_stroke()
    st.parent = None
    for i in range(n):
        sc.add_curve(np.linspace([0.0, 0.0, 0.1 * i], [1.0, 0.0, 0.1 * i], 4), None)
    h.v._changed()
    return st


def test_marks_full_size_when_near_and_smaller_when_far(h: H):
    st = _gitter(h)
    v = h.v
    pts = np.vstack([c.points for c in st.curves])
    h.edit_mode("point")
    v.selection = [st.id]
    v._changed()
    h.frame(pts, back=(0.0, 1.0, 0.05), margin=1.3)
    shared, free, rest = v._net_marks()
    alle = shared + free + rest
    assert len(alle) >= 20, "precondition of the test: points are shown"
    nah = v._mark_crowd(alle)
    assert nah == 1.0, f"zoomed in close, the marks have their full size ({nah:.2f})"
    h.frame(pts, back=(0.0, 1.0, 0.05), margin=60)
    fern = v._mark_crowd(alle)
    assert v.MARK_CROWD_MIN <= fern < 0.6, f"zoomed far out, the marks shrink clearly ({fern:.2f})"
    h.frame(pts, back=(0.0, 1.0, 0.05), margin=8)
    mitte = v._mark_crowd(alle)
    assert fern <= mitte <= nah, f"in between, the size lies in between ({fern:.2f} ≤ {mitte:.2f} ≤ {nah:.2f})"
    h.grab()  # draws with shrunken marks, without error


def test_few_points_always_stay_full_size(h: H):
    sc = h.new_scene()
    st = sc.new_stroke()
    st.parent = None
    sc.add_curve(np.linspace([0.0, 0.0, 0.0], [1.0, 0.0, 0.0], 4), None)
    h.v._changed()
    h.edit_mode("point")
    h.v.selection = [st.id]
    h.v._changed()
    h.frame(st.curves[0].points, margin=80)
    shared, free, rest = h.v._net_marks()
    assert h.v._mark_crowd(shared + free + rest) == 1.0, "a single line: its two points stay large"

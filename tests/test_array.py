"""Array: copies as instances – circle around the null, linear, along a line; rotation, randomness (fixed per copy)."""
import numpy as np

from tests.harness import H, line
from sketch_machine import arrays


def _array_with_line(h, a, b, **params):
    sc = h.sc
    st = sc.new_stroke(parent=None)
    sc.add_curve(line(a, b, 5), None)
    h.edit_mode("edge")
    h.v.set_selection([st.id])
    arr = h.v.create_null("array")
    arr.params.update(params)
    return st, arr


def _drawn(h):
    return [e[0] for e in h.v._stroke_draw_list() if len(e[0]) > 1]


def test_circle(h: H):
    st, arr = _array_with_line(h, [1, 0, 0], [2, 0, 0], mode="radial", count=4)
    lines = _drawn(h)
    assert len(lines) == 4
    ends = sorted(tuple(np.round(p[-1], 6)) for p in lines)
    assert ends == sorted([(2, 0, 0), (0, 0, -2), (-2, 0, 0), (0, 0, 2)]), ends
    assert np.allclose(st.curves[0].points[-1], [2, 0, 0]), "original stays"
    arr.params.update(angle=90.0, count=3)  # not full: first and last copy at the ends of the angle
    ends = sorted(tuple(np.round(p[-1], 6)) for p in _drawn(h))
    assert ends == sorted([(2, 0, 0), (np.round(2 * np.cos(np.pi / 4), 6), 0, np.round(-2 * np.sin(np.pi / 4), 6)),
                           (0, 0, -2)]), ends


def test_linear(h: H):
    _, arr = _array_with_line(h, [0, 0, 0], [1, 0, 0], mode="linear", count=3, offset=[0, 0, 2])
    starts = sorted(tuple(np.round(p[0], 6)) for p in _drawn(h))
    assert starts == [(0, 0, 0), (0, 0, 2), (0, 0, 4)], starts


def test_along_line_with_up(h: H):
    sc = h.sc
    path = sc.new_stroke(parent=None)
    sc.add_curve(line([0, 0, 0], [0, 0, 4], 9), None)  # path along z
    sc.add_curve(line([0, 1, 0], [0, 1, 4], 9), None)  # up line above it
    p_line, up_line = path.curves
    st, arr = _array_with_line(h, [0, 0, 0], [0, 0.5, 0], mode="line", count=3, path=p_line.id, up=up_line.id)
    arr.axes = np.column_stack([[0, 0, 1.0], [0, 1.0, 0], [-1.0, 0, 0]])  # x = direction of travel: original = first copy
    mats = arrays.matrices(sc, arr)
    assert len(mats) == 3, f"original + 2 copies (the first would lie exactly on it): {len(mats)}"
    tips = sorted(tuple(np.round(arrays.transform(m, [0, 0.5, 0]), 6)) for m in mats)
    assert tips == [(0, 0.5, 0), (0, 0.5, 2), (0, 0.5, 4)], tips
    sc.add_curve(line([0, 0, 4.0], [0, 0, 6.0], 3), None)  # uninvolved line: nothing changes
    assert len(arrays.matrices(sc, arr)) == 3


def test_rotation_and_randomness_fixed(h: H):
    sc = h.sc
    _, arr = _array_with_line(h, [1, 0, 0], [2, 0, 0], mode="linear", count=4, offset=[0, 0, 1], spin=90.0)
    m = arrays.matrices(sc, arr)
    tip = arrays.transform(m[1], [2, 0, 0])
    assert np.allclose(tip, [1.5, 0, 1.5]) or np.allclose(tip, [1.5, 0, 0.5]), f"copy 1 rotated about up: {tip}"
    arr.params.update(spin=0.0, rand_rot=0.5, rand_off=0.3, seed=7)
    a = arrays.matrices(sc, arr)
    b = arrays.matrices(sc, arr)
    assert all(np.allclose(x, y) for x, y in zip(a, b)), "same seed: same copies"
    arr.params["count"] = 6
    c = arrays.matrices(sc, arr)
    assert all(np.allclose(x, y) for x, y in zip(a, c[:4])), "more copies do not reshuffle the existing ones"
    arr.params["off_axes"] = [False, False, False]
    arr.params["rot_axes"] = [False, False, False]
    d = arrays.matrices(sc, arr)
    assert np.allclose(arrays.transform(d[2], [1, 0, 0]), [1, 0, 2]), "all axes off: no randomness"


def test_surface_in_array_with_own_id(h: H):
    sc = h.sc
    st = sc.new_stroke(parent=None)
    P = [np.array(p, float) for p in ([1, 0, 0], [2, 0, 0], [2, 0, 1], [1, 0, 1])]
    for p, q in zip(P, P[1:] + P[:1]):
        sc.add_curve(line(p, q, 5), None)
    f = sc.create_fill([(c, False) for c in st.curves])
    sc.sync_lofts()
    h.edit_mode("face")
    h.v.set_selection([st.id, f.id])
    arr = h.v.create_null("array")
    arr.params.update(mode="radial", count=3)
    ents = h.v._surface_draw_list()
    assert len(ents) == 3 and len({e["id"] for e in ents}) == 3
    ents2 = h.v._surface_draw_list()
    assert all(a["verts"] is b["verts"] for a, b in zip(ents, ents2)), "unchanged copies: the same arrays (buffers)"


def test_many_copies_stay_cached(h: H):
    """Regression (11 s per frame): more entries than the old cache held – every frame recomputed everything."""
    sc = h.sc
    st = sc.new_stroke(parent=None)
    for k in range(300):
        sc.add_curve(line([k * 0.01, 0, 0], [k * 0.01, 0.1, 0], 3), None)
    h.edit_mode("edge")
    h.v.set_selection([st.id])
    arr = h.v.create_null("array")
    arr.params.update(mode="linear", count=20, offset=[0, 0, 1])
    a = h.v._stroke_draw_list()
    b = h.v._stroke_draw_list()
    assert len(a) == 6000 and all(x[0] is y[0] for x, y in zip(a, b)), "same copies: the same arrays (no recomputation)"

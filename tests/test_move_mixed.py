"""A mixed selection (whole lines + partial edges) moves every selected point exactly once (harbor test 09.11.: shared
points moved twice as far, the lines stretched there)."""
import numpy as np

from sketch_machine import components, network
from tests.harness import H, line

D = np.array([0, 1.0, 0])


def _build(h, polys):
    sc = h.new_scene()
    sc.new_stroke()
    out = []
    for p in polys:
        sc.add_curve(np.asarray(p, float), None)
        out.append(sc.strokes[-1].curves[-1])
    network.sync(sc)
    return sc, out


def _ref(sc, c):
    return ("line", sc.owner_of(c).id, c.id)


def _move(h, sc, curves, edge=(), segs=(), steps=10):
    v = h.v
    if not v.select_mode:
        v.set_select_mode(True)
    v.ws.component = "edge"
    v.selection, v.point_selection = [], []
    v.edge_selection = [_ref(sc, c) for c in edge]
    v.seg_selection = [("seg",) + _ref(sc, c)[1:] + (a, b) for c, a, b in segs]
    v._changed()
    olds = [c.points.copy() for c in curves]
    target = v.transform_target
    for _ in range(steps):  # like the gizmo: many small steps
        target.translate(D / steps)
        network.sync(sc)
    return [(c.points - o)[:, 1] for c, o in zip(curves, olds)]


def _corner_scene(h):
    corner = np.vstack([line([1, 0, 0], [1.5, 0, 0], 6), line([1.5, 0, 0], [1.5, 0, 0.5], 6)[1:]])
    return _build(h, [line([0, 0, 0], [1, 0, 0]), corner, line([1.5, 0, 0.5], [3, 0, 0.5])])


def test_whole_line_and_partial_edges_moved_once(h: H):
    sc, cs = _corner_scene(h)
    segs = [(cs[1], a, b) for a, b in components.segments(cs[1])]
    assert len(segs) >= 2, "line with a corner has partial edges"
    d0, d1, _ = _move(h, sc, cs, edge=[cs[0]], segs=segs)
    for name, d in (("whole line", d0), ("line from partial edges", d1)):
        assert np.allclose(d, 1.0, atol=1e-6), f"{name}: displacement {d.min():.2f}..{d.max():.2f} instead of 1.00"


def test_line_selected_as_whole_and_as_partial_edge(h: H):
    sc, cs = _corner_scene(h)
    segs = [(cs[1], a, b) for a, b in components.segments(cs[1])]
    _d0, d1, _ = _move(h, sc, cs, edge=[cs[1]], segs=segs[:1])
    assert np.allclose(d1, 1.0, atol=1e-6), f"line selected twice: {d1.min():.2f}..{d1.max():.2f} instead of 1.00"


def test_only_whole_lines_unchanged(h: H):
    sc, cs = _build(h, [line([0, 0, 0], [1, 0, 0]), line([1, 0, 0], [2, 0, 0]), line([2, 0, 0], [3, 0, 0])])
    d0, d1, _ = _move(h, sc, cs, edge=cs[:2])
    assert np.allclose(d0, 1.0) and np.allclose(d1, 1.0)


def test_whole_lines_stay_tinted_next_to_partial_edge(h: H):
    """Alpaca handlebar 14.11.: ring selection of whole lines plus one partial edge – the gizmo moves all of them, but only
    the partial edge was drawn in selection color (the tinting read only whole lines from the transform target)."""
    from sketch_machine.vp.display_lists import SELECTED_STROKE_COLOR, _rgba
    sc, cs = _corner_scene(h)
    segs = [(cs[1], a, b) for a, b in components.segments(cs[1])]
    v = h.v
    if not v.select_mode:
        v.set_select_mode(True)
    v.ws.component = "edge"
    v.selection, v.point_selection = [], []
    v.edge_selection = [_ref(sc, cs[0]), _ref(sc, cs[2])]
    v.seg_selection = [("seg",) + _ref(sc, cs[1])[1:] + segs[0][1:]]
    v._changed()
    assert v.seg_selection and v.edge_selection, "mixed selection is set"
    sel = _rgba(SELECTED_STROKE_COLOR)[:3]
    entries = v._scene_stroke_list()
    for name, c in (("first line", cs[0]), ("last line", cs[2])):
        hit = [e for e in entries if len(e[0]) == len(c.points) and np.allclose(e[0], c.points)]
        assert hit, f"{name}: not in the stroke list"
        assert np.allclose(hit[0][2][:3], sel), f"{name}: selected, but not drawn in selection color"

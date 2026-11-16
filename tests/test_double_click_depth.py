"""Double-click/click in edit mode selects only what is visible: an edge that shows through behind the front surface no
longer wins just because it is closer to the cursor (harbour test 09.11.: double-click hit the surface behind)."""
from tests.harness import H, line


def _square(h, sc, x0, y, x1):
    st = sc.new_stroke()
    pts = [[x0, y, 0], [x1, y, 0], [x1, y, 2], [x0, y, 2], [x0, y, 0]]
    for p, q in zip(pts[:-1], pts[1:]):
        sc.add_curve(line(p, q, 8), None)
    h.v.edge_selection = [("line", st.id, c.id) for c in st.curves]
    h.v.do_patch()
    return st, sc.surfaces[-1]


def _setup(h, comp):
    sc = h.new_scene()
    front, fs = _square(h, sc, 0, 0.0, 2)
    back, bs = _square(h, sc, 1, -1.0, 3)
    h.v._changed()
    h.camera([1.5, 0, 1], 8, [0.0, 1.0, 0.03])
    h.edit_mode(comp)
    h.v._apply_selection([fs.id, front.id], [], "replace")
    h.v._changed()
    h.grab()
    # centre of the front surface; 1 m behind it runs the left edge of the back one
    return h.scr([1.0, -1.0, 1.0]), front, fs, back, bs


def test_double_click_stays_on_the_front_surface(h: H):
    for comp in ("face", "edge"):
        p, front, fs, back, bs = _setup(h, comp)
        assert h.v._mesh_under(p)[0] is fs, "cursor is over the front surface"
        h.dclick(p)
        h.pump(0.05)
        owners = {r[1] for r in h.v.edge_selection} | {r[1] for r in h.v.seg_selection}
        assert back.id not in owners and bs.id not in h.v.selection, \
            f"{comp}: double-click selected lines/surface behind"


def test_edge_behind_not_under_the_cursor(h: H):
    p, front, fs, back, bs = _setup(h, "edge")
    hit = h.v._edge_under(p, tolerance=3, visible=True)
    assert hit is None or hit[0][1] != back.id, "occluded edge does not count"
    h.v.set_xray(True)
    hit = h.v._edge_under(p, tolerance=3, visible=True)
    h.v.set_xray(False)
    assert hit is not None and hit[0][1] == back.id, "X-ray: occluded things are selectable too"

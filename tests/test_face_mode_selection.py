"""Switching to surface mode: every surface whose describing lines are all selected is selected too
(recording 10.11. 22:10: select all lines of an object, surface mode – the surfaces should be included)."""
from sketch_machine import network
from tests.harness import H, line


def _two_squares(h):
    h.new_scene()
    sc = h.sc
    out = []
    for x in (0, 5):
        st = sc.new_stroke()
        pts = [[x, 0, 0], [x + 2, 0, 0], [x + 2, 0, 2], [x, 0, 2], [x, 0, 0]]
        for p, q in zip(pts[:-1], pts[1:]):
            sc.add_curve(line(p, q, 8), None)
        network.sync(sc)
        h.v.edge_selection = [("line", st.id, c.id) for c in st.curves]
        h.v.do_patch()
        out.append((st, sc.surfaces[-1]))
    h.v.selection, h.v.edge_selection = [], []
    h.edit_mode("edge")
    return sc, out


def test_all_lines_selected_surface_joins_in_surface_mode(h: H):
    sc, ((st_a, face_a), (st_b, face_b)) = _two_squares(h)
    h.v.edge_selection = [("line", st_a.id, c.id) for c in st_a.curves]
    h.v.set_component("face")
    assert face_a.id in h.v.selection and face_b.id not in h.v.selection
    assert len(h.v.edge_selection) == len(st_a.curves), "the lines stay selected"


def test_only_some_of_the_lines_selects_no_surface(h: H):
    sc, ((st_a, face_a), (st_b, face_b)) = _two_squares(h)
    h.v.edge_selection = [("line", st_a.id, c.id) for c in st_a.curves[:3]]
    h.v.set_component("face")
    assert face_a.id not in h.v.selection and face_b.id not in h.v.selection


def test_hidden_surface_stays_out(h: H):
    sc, ((st_a, face_a), (st_b, face_b)) = _two_squares(h)
    face_a.hidden = True
    h.v.edge_selection = [("line", st.id, c.id) for st in (st_a, st_b) for c in st.curves]
    h.v.set_component("face")
    assert face_a.id not in h.v.selection and face_b.id in h.v.selection

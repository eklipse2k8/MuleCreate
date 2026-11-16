"""Ctrl+G and surfaces: surfaces follow their lines. If ALL lines of a surface move into the new object, it belongs
to it afterwards (with its painting); if only some move, it stays. Merging whole line objects: all their surfaces
are under the one object afterwards – even if the surfaces were selected too (this used to abort)."""
import numpy as np

from sketch_machine import network
from tests.harness import H, line


def _quad(h, st, x0, z0):
    """Quad from four lines in st, as a curve surface: (lines, surface)."""
    sc = h.sc
    sc.active_stroke = st
    first = len(st.curves)
    pts = [[x0, 0, z0], [x0 + 1, 0, z0], [x0 + 1, 0, z0 + 1], [x0, 0, z0 + 1], [x0, 0, z0]]
    for p, q in zip(pts[:-1], pts[1:]):
        sc.add_curve(line(p, q, 6), None)
    lines = st.curves[first:]
    network.sync(sc)
    h.v.selection = []
    h.v.edge_selection = [("line", st.id, c.id) for c in lines]
    h.v.do_patch()
    return lines, sc.surfaces[-1]


def _two_objects(h):
    """Two line objects, each with two separate quads including a surface."""
    h.new_scene()
    sc = h.sc
    a, b = sc.new_stroke(), sc.new_stroke()
    a.name, b.name = "A", "B"
    h.edit_mode("edge")
    qa1, qa2 = _quad(h, a, 0, 0), _quad(h, a, 3, 0)
    qb1, qb2 = _quad(h, b, 0, 5), _quad(h, b, 3, 5)
    h.v.selection, h.v.edge_selection = [], []
    h.v._changed()
    assert [f.owner for f in (qa1[1], qa2[1], qb1[1], qb2[1])] == [a.id, a.id, b.id, b.id]
    return sc, a, b, qa1, qa2, qb1, qb2


def _refs(sc, lines):
    return [("line", sc.owner_of(c).id, c.id) for c in lines]


def test_one_quad_each_from_two_objects_into_a_third(h: H):
    sc, a, b, qa1, qa2, qb1, qb2 = _two_objects(h)
    nulls = len(sc.nulls)
    h.v.edge_selection = _refs(sc, qa1[0] + qb1[0])
    h.v.selection = [qa1[1].id, qb1[1].id]  # the surfaces selected too
    h.v.group_selection()
    new = sc.strokes[-1]
    assert new not in (a, b) and len(new.curves) == 8, "third object with the lines of both quads"
    assert qa1[1].owner == new.id and qb1[1].owner == new.id, "both fully described surfaces belong to the new object"
    assert qa1[1].parent == new.parent and qb1[1].parent == new.parent
    assert qa2[1].owner == a.id and qb2[1].owner == b.id, "the other surfaces stay"
    assert a in sc.strokes and b in sc.strokes and len(a.curves) == 4 and len(b.curves) == 4, "the originals remain"
    assert len(sc.nulls) == nulls, "surfaces in the selection do not create a null"
    h.v.undo()
    assert len(h.sc.strokes) == 2, "one undo step"


def test_surface_moves_even_without_being_selected(h: H):
    sc, a, b, qa1, qa2, qb1, qb2 = _two_objects(h)
    h.v.edge_selection = _refs(sc, qa1[0])
    h.v.selection = []
    h.v.group_selection()
    new = sc.strokes[-1]
    assert qa1[1].owner == new.id, "all four lines moved: the surface belongs to the new object"
    assert qa2[1].owner == a.id


def test_partially_selected_the_surface_stays(h: H):
    sc, a, b, qa1, qa2, qb1, qb2 = _two_objects(h)
    h.v.edge_selection = _refs(sc, qa1[0][:3])  # three of four lines
    h.v.selection = [qa1[1].id]
    h.v.group_selection()
    new = sc.strokes[-1]
    assert len(new.curves) == 3 and qa1[1].owner == a.id, "only some of the lines: the surface stays with A"
    h.v._changed()
    assert qa1[1].owner == a.id, "also after the sync"


def test_painting_of_the_surface_moves_along(h: H):
    sc, a, b, qa1, qa2, qb1, qb2 = _two_objects(h)
    sc.active_stroke = a
    sc.add_curve(line([0.2, 0, 0.5], [0.8, 0, 0.5], 6), qa1[1].id)
    paint = a.curves[-1]
    paint.paint = True
    h.v._changed()
    h.v.edge_selection = _refs(sc, qa1[0])
    h.v.group_selection()
    new = sc.strokes[-1]
    assert sc.owner_of(paint) is new and paint.plane_id == qa1[1].id, "painting on the surface moves into the new object too"


def test_merge_whole_objects_also_with_selected_surfaces(h: H):
    sc, a, b, qa1, qa2, qb1, qb2 = _two_objects(h)
    faces = [q[1] for q in (qa1, qa2, qb1, qb2)]
    h.v.edge_selection = []
    h.v.selection = [a.id, b.id] + [f.id for f in faces]
    h.v.group_selection()
    assert a in sc.strokes and b not in sc.strokes and len(a.curves) == 16, "one object with all lines"
    assert all(f.owner == a.id and f.parent == a.parent for f in faces), "all surfaces are under the one object"
    assert len(sc.surfaces) == 4, "no surface lost"
    assert all(np.isfinite(f.fill_mesh()[0]).all() for f in faces)

"""Dragging edges with softly co-dragged neighbouring lines: the groups for it are built once per drag (with one shared
knot index), not anew per frame and per neighbour – in a large scene that cost seconds per frame
(harbour, import_silos, 10.11.). The result of the drag stays the same."""
import numpy as np

from sketch_machine import components
from tests.harness import H
from tests.test_group_surfaces import _two_objects


def test_knot_index_only_once_per_drag(h: H):
    from tests.test_surface_move import _two_sharing
    sc, st, lines, patches = _two_sharing(h)
    h.edit_mode("edge")
    h.v.selection = []
    h.v.edge_selection = [("line", st.id, lines[n].id) for n in ("ab", "be", "de", "ad")]  # bc, ef hang on the ends
    h.v._changed()
    target = h.v.transform_target
    built = []
    real = components.KnotIndex.__init__
    components.KnotIndex.__init__ = lambda self, scene: (built.append(1), real(self, scene))[1]
    try:
        before = {n: c.points.copy() for n, c in lines.items()}
        d = np.array([0.0, 0.25, 0.0])
        for _ in range(4):
            target.translate(d)
            h.v.update()
            h.grab()
        assert len(built) == 1, f"one knot index for the whole drag ({len(built)} built)"
    finally:
        components.KnotIndex.__init__ = real
    assert np.allclose(lines["ab"].points, before["ab"] + 4 * d), "selected lines moved fully"
    assert np.allclose(lines["cf"].points, before["cf"]), "distant line stays"
    hub = lines["bc"].points[:, 1] - before["bc"][:, 1]
    assert abs(float(hub.max()) - 1.0) < 1e-6 and abs(float(hub.min())) < 1e-6, "neighbouring line tapers off softly (1 to 0)"


def test_entries_per_line_object_stay_when_nothing_happens(h: H):
    sc, a, b, qa1, qa2, qb1, qb2 = _two_objects(h)
    h.v._changed()
    h.grab()
    calls = []
    real = type(h.v)._owner_lines
    type(h.v)._owner_lines = lambda self, owner, *args: (calls.append(owner.id), real(self, owner, *args))[1]
    try:
        verify = type(h.v).VERIFY_LISTS
        type(h.v).VERIFY_LISTS = False  # (the check itself reassembles)
        c = a.curves[0]
        c.points = c.points + [0.0, 0.1, 0.0]
        h.v.update()
        h.grab()
        assert calls == [a.id], f"only the changed line object is reassembled ({calls})"
    finally:
        type(h.v)._owner_lines = real
        type(h.v).VERIFY_LISTS = verify

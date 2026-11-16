"""Report book of the surface sync (scene._touch, scene_surfaces._sync_asked): A surface whose stamp has changed
must look again - even if the change bypassed it. Both cases come from the independent
review of v0.99.195 (12.11.); they need no window, only the scene."""
import numpy as np

import sketch_machine.scene as S
from sketch_machine import network

LEVEL = "core"


def _linie(a, b, n=8):
    return np.linspace(np.asarray(a, float), np.asarray(b, float), n)


def _flaeche(sc, ecken):
    st = sc.new_stroke()
    st.parent = None
    for p, q in zip(ecken, ecken[1:] + ecken[:1]):
        sc.add_curve(_linie(p, q), None)
    network.sync(sc)
    patch = sc.create_patch(list(st.curves))
    assert patch is not None
    return st, patch


def _stempel_gilt(sc, f):
    return f.__dict__.get("_sync_ok") == sc._surface_stamp(f, sc._sync_world(False), network.refs_by_pid(sc), count=False)


def _ruhe(sc, n=4):
    for _ in range(n):
        sc.sync_lofts()


def test_held_surface_looks_again_after_the_drag(h=None):
    """A line M hangs on the corner of surface A and belongs to an object that is dragged rigidly. A itself is
    uninvolved and is held during the drag; a second surface deforms meanwhile (so the sync runs every frame).
    After release, A must be recomputed once: its neighbouring line has moved."""
    sc = S.Scene()
    _st, a = _flaeche(sc, [[0, 0, 0], [2, 0, 0], [2, 0, 2], [0, 0, 2]])
    st_c = sc.new_stroke()
    st_c.parent = None
    q = [[10, 0, 0], [12, 0, 0], [12, 0, 2], [10, 0, 2]]
    for i, j in ((0, 1), (1, 2), (2, 3)):
        sc.add_curve(_linie(q[i], q[j]), None)
    st_b = sc.new_stroke()
    st_b.parent = None
    sc.add_curve(_linie(q[3], q[0]), None)
    network.sync(sc)
    b = sc.create_patch(list(st_c.curves) + [st_b.curves[-1]])
    assert b is not None
    sc.active_stroke = st_b
    sc.add_curve(_linie([0, 0, 0], [-1, 0, -1]), None)  # M: at the corner of A, in the dragged object
    m = st_b.curves[-1]
    _ruhe(sc)
    assert any(c is m for c in a._dep_curves) and _stempel_gilt(sc, a)
    t = S.TransformSet([st_b], scene=sc)
    t.in_drag = True
    held = False
    for _ in range(3):
        t.translate(np.array([-0.5, 0.0, 0.0]))
        sc.sync_lofts()
        held |= bool(a.__dict__.get("_idle_hold"))
    t.in_drag = False
    t.end_rigid()
    assert held, "precondition of the test: the uninvolved surface is held during the drag"
    assert not _stempel_gilt(sc, a), "precondition of the test: the drag has changed the stamp of the surface"
    sc.sync_lofts()  # (with VERIFY_SYNC the check would trip here if the surface were trusted)
    assert _stempel_gilt(sc, a), "not recomputed after release: the stamp of the surface is stale"


def test_deleted_line_two_steps_away_is_noticed(h=None):
    """At the corner of the surface hangs M, on it M2, on it M3. M3 is not one of the lines the surface depends on,
    but its end counts in the stamp (how many lines hang on the points of M2). If M3 is deleted, nobody
    reports - the surface must notice it through the number of lines at the point."""
    for kette in (2, 3):
        sc = S.Scene()
        _st, a = _flaeche(sc, [[0, 0, 0], [2, 0, 0], [2, 0, 2], [0, 0, 2]])
        st_b = sc.new_stroke()
        st_b.parent = None
        enden = [[0, 0, 0], [-1, 0, -1], [-2, 0, -1], [-3, 0, -1]]
        for p, q in zip(enden[:kette], enden[1:kette + 1]):
            sc.add_curve(_linie(p, q), None)
        _ruhe(sc)
        assert _stempel_gilt(sc, a)
        st_b.curves.remove(st_b.curves[-1])  # the last line of the chain disappears without any field being set
        if _stempel_gilt(sc, a):
            continue  # (at this chain length the line does not count in the stamp: nothing to check)
        sc.sync_lofts()
        assert _stempel_gilt(sc, a), f"chain of {kette} lines: deleting the last one was not noticed"

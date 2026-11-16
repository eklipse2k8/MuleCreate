"""Directories of the scene (Scene.object_by_id, Scene.curve_by_id): look up instead of search, "does not exist" is
remembered. The check mode Scene.VERIFY_INDEX (on in all tests) compares every answer with a search over all lists –
here the ways are played through in which a remembered "does not exist" could become wrong."""
import numpy as np

import sketch_machine.scene as S
from sketch_machine import counters

LEVEL = "core"


def _linie(x):
    return np.linspace([x, 0.0, 0.0], [x + 1.0, 0.0, 1.0], 6)


def _szene(n=3):
    sc = S.Scene()
    for k in range(n):
        st = sc.new_stroke()
        st.parent = None
        sc.add_curve(_linie(2.0 * k), None)
        sc.add_curve(_linie(2.0 * k + 0.5), None)
    return sc


def test_line_comes_back_after_undo_and_redo(h=None):
    assert S.Scene.VERIFY_INDEX, "the check mode of the directories must be on in the tests"
    sc = _szene()
    sc.checkpoint()
    weg = sc.strokes[1].curves[0]
    cid = weg.id
    assert sc.curve_by_id(cid) is weg
    sc.strokes[1].curves.remove(weg)
    assert sc.curve_by_id(cid) is None and sc.curve_by_id(cid) is None  # (second query: from the remembered answer)
    sc.undo()
    assert sc.curve_by_id(cid) is not None and sc.curve_by_id(cid).id == cid, "after undo the line is back"
    sc.redo()
    assert sc.curve_by_id(cid) is None, "after redo it is gone again"


def test_remembered_does_not_exist_costs_nothing(h=None):
    sc = _szene(6)
    assert sc.curve_by_id(10 ** 9) is None
    with counters.measure() as got:
        for _ in range(50):
            assert sc.curve_by_id(10 ** 9) is None
            assert sc.object_by_id(10 ** 9) is None
    assert got["linien_index"] == 0, f"every query for a missing line rebuilds the directory ({got['linien_index']})"
    assert got["suche_objekt"] <= 1, f"every query for a missing object searches the lists ({got['suche_objekt']})"


def test_objects_added_removed_and_reordered(h=None):
    sc = _szene()
    a, b, c = sc.strokes
    assert sc.object_by_id(a.id) is a and sc.object_by_id(c.id) is c
    assert sc.object_by_id(None) is None
    sc.strokes.remove(b)
    assert sc.object_by_id(b.id) is None and sc.object_by_id(c.id) is c, "after removal the remembered position is no longer correct"
    sc.strokes.insert(0, b)
    assert sc.object_by_id(b.id) is b and sc.object_by_id(a.id) is a
    neu = sc.new_stroke()
    assert sc.object_by_id(neu.id) is neu
    null = sc.new_null()
    assert sc.object_by_id(null.id) is null
    sc.delete([null])
    assert sc.object_by_id(null.id) is None


def test_line_moves_to_another_object(h=None):
    sc = _szene()
    a, b, _c = sc.strokes
    linie = a.curves[0]
    assert sc.curve_by_id(linie.id) is linie
    a.curves.remove(linie)
    b.curves.append(linie)
    assert sc.curve_by_id(linie.id) is linie, "the moved line is no longer found"
    assert sc.owner_of(linie) is b

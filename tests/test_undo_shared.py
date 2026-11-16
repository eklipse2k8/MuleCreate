"""Undo copy only for what changed: unchanged lines and surfaces share their image with the previous step; when
restoring they stay in place as live objects. No history step may ever change because of this."""
import numpy as np

from sketch_machine.scene import Scene
from tests.harness import H
from tests.test_undo_speed import _two_patches


def _twin(sc, obj):
    return sc._twins[id(obj)][3]


def test_unchanged_is_shared_changed_is_copied_anew(h: H):
    sc, st, patches = _two_patches(h)
    sc.checkpoint()
    a, b = st.curves[0], st.curves[5]
    twins = {id(c): _twin(sc, c) for c in st.curves}
    faces = [_twin(sc, p) for p in patches]
    a.points = a.points + np.array([0.0, 0.2, 0.0])
    h.v._changed()
    sc.checkpoint()
    assert _twin(sc, a) is not twins[id(a)], "changed line: new image"
    assert _twin(sc, b) is twins[id(b)], "unchanged line: same image"
    assert _twin(sc, patches[0]) is not faces[0] and _twin(sc, patches[1]) is faces[1]
    assert np.allclose(twins[id(a)].points[:, 1], 0.0), "the old image stays as it was"


def test_in_place_changes_are_detected(h: H):
    sc, st, patches = _two_patches(h)
    sc.checkpoint()
    c = st.curves[0]
    old = _twin(sc, c)
    k = next(iter(c.pids))
    c.pids[k] = c.pids[k] + 100000  # (netedit changes point IDs in place)
    sc.checkpoint()
    assert _twin(sc, c) is not old and old.pids[k] == c.pids[k] - 100000
    face = patches[1]
    old = _twin(sc, face)
    face.attached[987654] = {"uv": np.zeros((2, 2))}  # (surfaces change their dictionaries in place)
    sc.checkpoint()
    assert _twin(sc, face) is not old and 987654 not in old.attached
    del face.attached[987654]


def test_history_stays_untouched_when_work_continues_after_undo(h: H):
    sc, st, patches = _two_patches(h)
    line_ids = [c.id for c in st.curves]
    states = []
    for k in range(4):  # four steps: move a different line each time
        sc.checkpoint()
        c = sc.curve_by_id(line_ids[k])
        c.points = c.points + np.array([0.0, 0.1 * (k + 1), 0.0])
        h.v._changed()
        states.append([sc.curve_by_id(i).points.copy() for i in line_ids])
    for _ in range(3):
        sc.undo()
        h.v._changed()
    assert all(np.allclose(sc.curve_by_id(i).points, p) for i, p in zip(line_ids, states[0]))
    kept = sc.curve_by_id(line_ids[6])
    # change live objects – also one that had stayed unchanged; the redo steps stay intact
    for i in (line_ids[6], line_ids[1]):
        c = sc.curve_by_id(i)
        c.points = c.points + np.array([0.3, 0.0, 0.0])
    h.v._changed()
    edited = [sc.curve_by_id(i).points.copy() for i in line_ids]  # this state moves into the history on redo
    for k in (1, 2, 3):
        sc.redo()
        h.v._changed()
        assert all(np.allclose(sc.curve_by_id(i).points, p) for i, p in zip(line_ids, states[k])), f"step {k}"
    assert sc.curve_by_id(line_ids[6]) is not kept or np.allclose(kept.points, states[3][6])
    for k in (2, 1):
        sc.undo()
        h.v._changed()
        assert all(np.allclose(sc.curve_by_id(i).points, p) for i, p in zip(line_ids, states[k])), f"back {k}"
    sc.undo()
    h.v._changed()
    assert all(np.allclose(sc.curve_by_id(i).points, p) for i, p in zip(line_ids, edited)), "the edited state"
    sc.undo()
    assert all(np.allclose(sc.curve_by_id(i).points[:, 1], 0.0) for i in line_ids), "at the very beginning"


def test_after_undo_unchanged_objects_stay_the_same(h: H):
    sc, st, patches = _two_patches(h)
    sc.checkpoint()
    a, b, face_b, mesh_b = st.curves[0], st.curves[5], patches[1], patches[1].fill_mesh()[0]
    a.points = a.points + np.array([0.0, 0.2, 0.0])
    h.v._changed()
    sc.undo()
    h.v._changed()
    lines = [c for s in sc.strokes for c in s.curves]
    assert b in lines and a not in lines, "unchanged: same object; changed: from the snapshot"
    assert face_b in sc.surfaces and face_b.fill_mesh()[0] is mesh_b, "untouched surface stays in place with its mesh"
    assert all(c is not _twin(sc, c) for c in lines), "never an object of the history in the live scene"


def test_check_mode_notices_a_wrongly_shared_image(h: H):
    """The check mode all tests run with raises an alarm if a change would go unnoticed."""
    sc, st, patches = _two_patches(h)
    sc.checkpoint()
    real = Scene._twin_memo
    Scene._twin_memo = lambda self: ({i: r[3] for i, r in self._twins.items()}, dict(self._twins))  # "everything unchanged"
    try:
        c = st.curves[0]
        c.points = c.points + np.array([0.0, 0.2, 0.0])
        try:
            sc.checkpoint()
        except AssertionError as exc:
            assert "Undo-Kopie" in str(exc) or "undo copy" in str(exc).lower()
        else:
            raise AssertionError("wrongly shared image not noticed")
    finally:
        Scene._twin_memo = real

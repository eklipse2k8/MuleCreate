"""Undo-Kopie nur für Geändertes: unveränderte Linien und Flächen teilen ihr Abbild mit dem vorigen Schritt, beim
Zurückholen bleiben sie als lebende Objekte stehen. Kein Schritt der Historie darf sich dadurch je ändern."""
import numpy as np

from sketch_machine.scene import Scene
from tests.harness import H
from tests.test_undo_tempo import _two_patches


def _twin(sc, obj):
    return sc._twins[id(obj)][3]


def test_unveraendertes_wird_geteilt_geaendertes_neu_kopiert(h: H):
    sc, st, patches = _two_patches(h)
    sc.checkpoint()
    a, b = st.curves[0], st.curves[5]
    twins = {id(c): _twin(sc, c) for c in st.curves}
    faces = [_twin(sc, p) for p in patches]
    a.points = a.points + np.array([0.0, 0.2, 0.0])
    h.v._changed()
    sc.checkpoint()
    assert _twin(sc, a) is not twins[id(a)], "geänderte Linie: neues Abbild"
    assert _twin(sc, b) is twins[id(b)], "unveränderte Linie: dasselbe Abbild"
    assert _twin(sc, patches[0]) is not faces[0] and _twin(sc, patches[1]) is faces[1]
    assert np.allclose(twins[id(a)].points[:, 1], 0.0), "das alte Abbild bleibt, wie es war"


def test_aenderungen_an_ort_und_stelle_werden_erkannt(h: H):
    sc, st, patches = _two_patches(h)
    sc.checkpoint()
    c = st.curves[0]
    old = _twin(sc, c)
    k = next(iter(c.pids))
    c.pids[k] = c.pids[k] + 100000  # (netedit ändert Punkt-IDs an Ort und Stelle)
    sc.checkpoint()
    assert _twin(sc, c) is not old and old.pids[k] == c.pids[k] - 100000
    face = patches[1]
    old = _twin(sc, face)
    face.attached[987654] = {"uv": np.zeros((2, 2))}  # (Flächen ändern ihre Wörterbücher an Ort und Stelle)
    sc.checkpoint()
    assert _twin(sc, face) is not old and 987654 not in old.attached
    del face.attached[987654]


def test_historie_bleibt_unberuehrt_wenn_nach_undo_weitergearbeitet_wird(h: H):
    sc, st, patches = _two_patches(h)
    line_ids = [c.id for c in st.curves]
    states = []
    for k in range(4):  # vier Schritte: je eine andere Linie bewegen
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
    # lebende Objekte ändern – auch eines, das unverändert stehen geblieben war; die Wiederholen-Schritte bleiben heil
    for i in (line_ids[6], line_ids[1]):
        c = sc.curve_by_id(i)
        c.points = c.points + np.array([0.3, 0.0, 0.0])
    h.v._changed()
    edited = [sc.curve_by_id(i).points.copy() for i in line_ids]  # dieser Stand wandert beim Wiederholen in die Historie
    for k in (1, 2, 3):
        sc.redo()
        h.v._changed()
        assert all(np.allclose(sc.curve_by_id(i).points, p) for i, p in zip(line_ids, states[k])), f"Schritt {k}"
    assert sc.curve_by_id(line_ids[6]) is not kept or np.allclose(kept.points, states[3][6])
    for k in (2, 1):
        sc.undo()
        h.v._changed()
        assert all(np.allclose(sc.curve_by_id(i).points, p) for i, p in zip(line_ids, states[k])), f"zurück {k}"
    sc.undo()
    h.v._changed()
    assert all(np.allclose(sc.curve_by_id(i).points, p) for i, p in zip(line_ids, edited)), "der bearbeitete Stand"
    sc.undo()
    assert all(np.allclose(sc.curve_by_id(i).points[:, 1], 0.0) for i in line_ids), "ganz am Anfang"


def test_nach_undo_bleiben_unveraenderte_objekte_dieselben(h: H):
    sc, st, patches = _two_patches(h)
    sc.checkpoint()
    a, b, face_b, mesh_b = st.curves[0], st.curves[5], patches[1], patches[1].fill_mesh()[0]
    a.points = a.points + np.array([0.0, 0.2, 0.0])
    h.v._changed()
    sc.undo()
    h.v._changed()
    lines = [c for s in sc.strokes for c in s.curves]
    assert b in lines and a not in lines, "unverändert: dasselbe Objekt; geändert: aus dem Schnappschuss"
    assert face_b in sc.surfaces and face_b.fill_mesh()[0] is mesh_b, "unberührte Fläche bleibt samt Netz stehen"
    assert all(c is not _twin(sc, c) for c in lines), "nie ein Objekt der Historie in der lebenden Szene"


def test_pruefmodus_bemerkt_ein_falsch_geteiltes_abbild(h: H):
    """Der Prüfmodus, mit dem alle Tests laufen, schlägt an, wenn eine Änderung unbemerkt bliebe."""
    sc, st, patches = _two_patches(h)
    sc.checkpoint()
    real = Scene._twin_memo
    Scene._twin_memo = lambda self: ({i: r[3] for i, r in self._twins.items()}, dict(self._twins))  # „alles unverändert“
    try:
        c = st.curves[0]
        c.points = c.points + np.array([0.0, 0.2, 0.0])
        try:
            sc.checkpoint()
        except AssertionError as exc:
            assert "Undo-Kopie" in str(exc)
        else:
            raise AssertionError("falsch geteiltes Abbild nicht bemerkt")
    finally:
        Scene._twin_memo = real

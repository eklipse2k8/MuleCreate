"""Verzeichnisse der Szene (Scene.object_by_id, Scene.curve_by_id): Nachschlagen statt Suchen, „gibt es nicht“ wird
gemerkt. Der Prüfmodus Scene.VERIFY_INDEX (in allen Tests an) vergleicht jede Antwort mit der Suche über alle Listen –
hier werden die Wege durchgespielt, auf denen ein gemerktes „gibt es nicht“ falsch werden könnte."""
import numpy as np

import sketch_machine.scene as S
from sketch_machine import counters

STUFE = "kern"


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


def test_linie_kommt_nach_undo_und_redo_wieder(h=None):
    assert S.Scene.VERIFY_INDEX, "der Prüfmodus der Verzeichnisse muss in den Tests an sein"
    sc = _szene()
    sc.checkpoint()
    weg = sc.strokes[1].curves[0]
    cid = weg.id
    assert sc.curve_by_id(cid) is weg
    sc.strokes[1].curves.remove(weg)
    assert sc.curve_by_id(cid) is None and sc.curve_by_id(cid) is None  # (zweite Frage: aus dem Gemerkten)
    sc.undo()
    assert sc.curve_by_id(cid) is not None and sc.curve_by_id(cid).id == cid, "nach Undo ist die Linie wieder da"
    sc.redo()
    assert sc.curve_by_id(cid) is None, "nach Redo ist sie wieder weg"


def test_gemerktes_gibt_es_nicht_kostet_nichts(h=None):
    sc = _szene(6)
    assert sc.curve_by_id(10 ** 9) is None
    with counters.measure() as got:
        for _ in range(50):
            assert sc.curve_by_id(10 ** 9) is None
            assert sc.object_by_id(10 ** 9) is None
    assert got["linien_index"] == 0, f"jede Frage nach einer fehlenden Linie baut das Verzeichnis neu ({got['linien_index']})"
    assert got["suche_objekt"] <= 1, f"jede Frage nach einem fehlenden Objekt durchsucht die Listen ({got['suche_objekt']})"


def test_objekte_dazu_weg_und_umsortiert(h=None):
    sc = _szene()
    a, b, c = sc.strokes
    assert sc.object_by_id(a.id) is a and sc.object_by_id(c.id) is c
    assert sc.object_by_id(None) is None
    sc.strokes.remove(b)
    assert sc.object_by_id(b.id) is None and sc.object_by_id(c.id) is c, "nach dem Entfernen stimmt der gemerkte Platz nicht mehr"
    sc.strokes.insert(0, b)
    assert sc.object_by_id(b.id) is b and sc.object_by_id(a.id) is a
    neu = sc.new_stroke()
    assert sc.object_by_id(neu.id) is neu
    null = sc.new_null()
    assert sc.object_by_id(null.id) is null
    sc.delete([null])
    assert sc.object_by_id(null.id) is None


def test_linie_zieht_in_ein_anderes_objekt(h=None):
    sc = _szene()
    a, b, _c = sc.strokes
    linie = a.curves[0]
    assert sc.curve_by_id(linie.id) is linie
    a.curves.remove(linie)
    b.curves.append(linie)
    assert sc.curve_by_id(linie.id) is linie, "die umgezogene Linie wird nicht mehr gefunden"
    assert sc.owner_of(linie) is b

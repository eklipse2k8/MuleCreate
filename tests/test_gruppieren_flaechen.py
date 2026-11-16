"""Strg+G und Flächen: Flächen folgen ihren Linien. Ziehen ALLE Linien einer Fläche in das neue Objekt um, gehört sie
danach ihm (samt Malerei); zieht nur ein Teil um, bleibt sie. Ganze Linienobjekte zusammenlegen: alle ihre Flächen
stehen danach unter dem einen Objekt – auch wenn die Flächen mitgewählt waren (das brach vorher ab)."""
import numpy as np

from sketch_machine import network
from tests.harness import H, line


def _quad(h, st, x0, z0):
    """Viereck aus vier Linien in st, als Kurvenfläche: (Linien, Fläche)."""
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
    """Zwei Linienobjekte mit je zwei getrennten Vierecken samt Fläche."""
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


def test_je_ein_viereck_aus_zwei_objekten_in_ein_drittes(h: H):
    sc, a, b, qa1, qa2, qb1, qb2 = _two_objects(h)
    nulls = len(sc.nulls)
    h.v.edge_selection = _refs(sc, qa1[0] + qb1[0])
    h.v.selection = [qa1[1].id, qb1[1].id]  # die Flächen mitgewählt
    h.v.group_selection()
    new = sc.strokes[-1]
    assert new not in (a, b) and len(new.curves) == 8, "drittes Objekt mit den Linien beider Vierecke"
    assert qa1[1].owner == new.id and qb1[1].owner == new.id, "beide ganz beschriebenen Flächen gehören dem neuen Objekt"
    assert qa1[1].parent == new.parent and qb1[1].parent == new.parent
    assert qa2[1].owner == a.id and qb2[1].owner == b.id, "die anderen Flächen bleiben"
    assert a in sc.strokes and b in sc.strokes and len(a.curves) == 4 and len(b.curves) == 4, "die Originale bestehen weiter"
    assert len(sc.nulls) == nulls, "Flächen in der Auswahl legen kein Null an"
    h.v.undo()
    assert len(h.sc.strokes) == 2, "ein Undo-Schritt"


def test_flaeche_zieht_auch_ohne_mitwahl_um(h: H):
    sc, a, b, qa1, qa2, qb1, qb2 = _two_objects(h)
    h.v.edge_selection = _refs(sc, qa1[0])
    h.v.selection = []
    h.v.group_selection()
    new = sc.strokes[-1]
    assert qa1[1].owner == new.id, "alle vier Linien umgezogen: die Fläche gehört dem neuen Objekt"
    assert qa2[1].owner == a.id


def test_teilweise_gewaehlt_bleibt_die_flaeche(h: H):
    sc, a, b, qa1, qa2, qb1, qb2 = _two_objects(h)
    h.v.edge_selection = _refs(sc, qa1[0][:3])  # drei von vier Linien
    h.v.selection = [qa1[1].id]
    h.v.group_selection()
    new = sc.strokes[-1]
    assert len(new.curves) == 3 and qa1[1].owner == a.id, "nur ein Teil der Linien: die Fläche bleibt bei A"
    h.v._changed()
    assert qa1[1].owner == a.id, "auch nach dem Abgleich"


def test_malerei_der_flaeche_zieht_mit_um(h: H):
    sc, a, b, qa1, qa2, qb1, qb2 = _two_objects(h)
    sc.active_stroke = a
    sc.add_curve(line([0.2, 0, 0.5], [0.8, 0, 0.5], 6), qa1[1].id)
    paint = a.curves[-1]
    paint.paint = True
    h.v._changed()
    h.v.edge_selection = _refs(sc, qa1[0])
    h.v.group_selection()
    new = sc.strokes[-1]
    assert sc.owner_of(paint) is new and paint.plane_id == qa1[1].id, "Malerei auf der Fläche zieht mit ins neue Objekt"


def test_ganze_objekte_zusammenlegen_auch_mit_gewaehlten_flaechen(h: H):
    sc, a, b, qa1, qa2, qb1, qb2 = _two_objects(h)
    faces = [q[1] for q in (qa1, qa2, qb1, qb2)]
    h.v.edge_selection = []
    h.v.selection = [a.id, b.id] + [f.id for f in faces]
    h.v.group_selection()
    assert a in sc.strokes and b not in sc.strokes and len(a.curves) == 16, "ein Objekt mit allen Linien"
    assert all(f.owner == a.id and f.parent == a.parent for f in faces), "alle Flächen stehen unter dem einen Objekt"
    assert len(sc.surfaces) == 4, "keine Fläche verloren"
    assert all(np.isfinite(f.fill_mesh()[0]).all() for f in faces)

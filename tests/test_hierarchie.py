"""Null-Objekte und Hierarchie: gruppieren, mitbewegen, Achsenmodus, Speichern/Laden, Undo, Löschen/Auflösen,
Ausblenden, Kopieren, Outliner."""
import json
import os
import tempfile

import numpy as np

from tests.harness import H, Qt, line
from sketch_machine.clipboard import Clipboard, paste
from sketch_machine.scene import NullObject, Scene


def _two_strokes(sc):
    a = sc.new_stroke(parent=None)
    sc.add_curve(line([1, 0, 0], [2, 0, 0]), None)
    b = sc.new_stroke(parent=None)
    sc.add_curve(line([1, 0, 1], [2, 1, 1]), None)
    return a, b


def _edit(h, ids):
    h.edit_mode("edge")
    h.v.set_selection(ids)


def test_gruppieren_unter_null(h: H):
    sc = h.sc
    a, b = _two_strokes(sc)
    _edit(h, [a.id, b.id])
    h.key(Qt.Key_G, Qt.AltModifier)
    null = sc.nulls[-1]
    assert null.kind == "null" and a.parent == null.id and b.parent == null.id
    assert np.allclose(null.origin, [1.5, 0.5, 0.5]), f"Null in der Mitte der Auswahl: {null.origin}"
    assert h.v.selection == [null.id]
    h.pump(0.05)
    out = h.w.outliner
    assert out.groups_root.childCount() == 1 and out.groups_root.child(0).childCount() == 2, "Outliner zeigt die Gruppe"
    assert out.strokes_root.childCount() == 0, "Kinder stehen nicht mehr unter Strokes"


def test_null_bewegt_kinder(h: H):
    sc = h.sc
    a, b = _two_strokes(sc)
    _edit(h, [a.id, b.id])
    null = h.v.create_null("null")
    before = [c.points.copy() for c in sc.curves]
    target = h.v.transform_target
    assert np.allclose(target.pivot(), null.origin), "Pivot ist das Achsenkreuz des Nulls"
    target.translate(np.array([0.0, 2.0, 0.0]))
    for c, p in zip(sc.curves, before):
        assert np.allclose(c.points, p + [0, 2, 0]), "Kinder wandern mit"
    assert np.allclose(null.origin, [1.5, 2.5, 0.5])
    rot = np.array([[0, -1, 0], [1, 0, 0], [0, 0, 1.0]])
    h.v.ws.target_cache = (None, None)
    target = h.v.transform_target
    target.rotate(rot, target.pivot())
    assert np.allclose(null.axes, rot), "Achsen drehen mit"


def test_achsenmodus_bewegt_nur_null(h: H):
    sc = h.sc
    a, _ = _two_strokes(sc)
    _edit(h, [a.id])
    null = h.v.create_null("null")
    before = a.curves[0].points.copy()
    h.v.set_axis_mode(True)
    try:
        target = h.v.transform_target
        target.translate(np.array([1.0, 0, 0]))
        assert np.allclose(a.curves[0].points, before), "Objekte bleiben stehen"
        assert np.allclose(null.origin, [2.5, 0, 0]), f"nur das Null wandert: {null.origin}"
    finally:
        h.v.set_axis_mode(False)


def test_speichern_laden(h: H):
    sc = h.sc
    a, b = _two_strokes(sc)
    _edit(h, [a.id])
    outer = h.v.create_null("null")
    _edit(h, [b.id])
    sym = h.v.create_null("symmetry")
    sc.set_parent([sym], outer)
    sym.params["plane"] = "xy"
    path = os.path.join(tempfile.mkdtemp(), "h.sketch.json")
    sc.save(path)
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    assert len(data["nulls"]) == 2
    loaded, _ = Scene.load(path)
    nulls = {n.name: n for n in loaded.nulls}
    o2, s2 = nulls[outer.name], nulls[sym.name]
    assert s2.parent == o2.id and s2.kind == "symmetry" and s2.params["plane"] == "xy"
    kids = {o.name for o in loaded.children(o2)}
    assert kids == {a.name, sym.name}, kids
    assert [o.name for o in loaded.children(s2)] == [b.name]


def test_undo_hierarchie(h: H):
    sc = h.sc
    a, b = _two_strokes(sc)
    _edit(h, [a.id, b.id])
    h.v.create_null("null")
    assert a.parent is not None
    h.v.undo()
    sc = h.sc
    assert not sc.nulls and all(s.parent is None for s in sc.strokes), "Undo nimmt Null und Hierarchie zurück"
    h.v.redo()
    assert len(h.sc.nulls) == 1 and all(s.parent == h.sc.nulls[0].id for s in h.sc.strokes)


def test_loeschen_und_aufloesen(h: H):
    sc = h.sc
    a, b = _two_strokes(sc)
    _edit(h, [a.id])
    null = h.v.create_null("null")
    h.v.set_selection([null.id])
    h.key(Qt.Key_G, Qt.ShiftModifier)
    assert not sc.nulls and a in sc.strokes and a.parent is None, "Auflösen behält die Kinder"
    _edit(h, [a.id, b.id])
    null = h.v.create_null("null")
    h.v.set_selection([null.id])
    h.key(Qt.Key_Delete)
    assert not sc.nulls and not sc.strokes, "Löschen nimmt alles darunter mit"


def test_ausblenden_vererbt(h: H):
    sc = h.sc
    a, b = _two_strokes(sc)
    _edit(h, [a.id])
    null = h.v.create_null("null")
    h.v.set_hidden(null.id, True)
    assert sc.is_hidden(a) and not sc.is_hidden(b)
    shown = {id(c) for c in h.v._visible_curves()}
    assert id(a.curves[0]) not in shown and id(b.curves[0]) in shown
    h.v.unhide_all()
    assert not sc.is_hidden(a)


def test_kopieren_mit_teilbaum(h: H):
    sc = h.sc
    a, b = _two_strokes(sc)
    _edit(h, [a.id, b.id])
    null = h.v.create_null("symmetry")
    clip = Clipboard()
    clip.copy(sc, [null])
    objs, _ = paste(sc, clip, "elements")
    new_null = next(o for o in objs if isinstance(o, NullObject))
    kids = sc.children(new_null)
    assert len(kids) == 2 and all(k not in (a, b) for k in kids), "Kopie hat eigene Kinder"
    assert new_null.kind == "symmetry" and new_null.params is not null.params
    assert len(sc.children(null)) == 2, "Original unverändert"


def test_kein_kreis(h: H):
    sc = h.sc
    outer = sc.new_null()
    inner = sc.new_null(parent=outer.id)
    assert not sc.set_parent([outer], inner), "Null nicht unter sein eigenes Kind"
    assert outer.parent is None
    h.v.set_parent([outer.id], inner.id)
    assert outer.parent is None


def test_flaeche_im_null_der_linien(h: H):
    sc = h.sc
    st = sc.new_stroke(parent=None)
    P = [np.array(p, float) for p in ([0, 0, 0], [2, 0, 0], [2, 0, 2], [0, 0, 2])]
    for p, q in zip(P, P[1:] + P[:1]):
        sc.add_curve(line(p, q), None)
    _edit(h, [st.id])
    null = h.v.create_null("symmetry")
    f = sc.create_fill([(c, False) for c in st.curves])
    assert f.parent == null.id, "Fläche aus Linien unter der Symmetrie liegt mit darunter"
    s2 = sc.new_stroke()
    assert s2.parent is None or s2.parent == null.id


def test_outliner_ziehen(h: H):
    sc = h.sc
    a, b = _two_strokes(sc)
    null = sc.new_null()
    h.v._changed()
    h.v.set_parent([a.id], null.id)
    assert a.parent == null.id
    h.v.set_parent([a.id], None)
    assert a.parent is None
    h.v.undo()
    assert h.sc.strokes[0].parent is not None, "Umhängen ist ein Undo-Schritt"


def _outliner_select(h: H, ids):
    from PySide6.QtWidgets import QTreeWidgetItemIterator
    from sketch_machine.outliner import ID_ROLE
    out = h.w.outliner
    out.rebuild()
    out.clearSelection()
    it = QTreeWidgetItemIterator(out)
    while it.value() is not None:
        if it.value().data(0, ID_ROLE) in ids:
            it.value().setSelected(True)
        it += 1
    return out


def test_outliner_duplizieren_und_loeschen(h: H):
    """Outliner, Rechtsklick: Duplizieren kopiert ein Null samt allem darunter (Kopie hat eigene Linien), Löschen
    entfernt es samt allem darunter."""
    sc = h.sc
    a, b = _two_strokes(sc)
    _edit(h, [a.id, b.id])
    h.key(Qt.Key_G, Qt.AltModifier)
    null = sc.nulls[-1]
    n_lines = sum(len(s.curves) for s in sc.strokes)
    out = _outliner_select(h, [null.id])
    out._duplicate()
    copy = next(n for n in sc.nulls if n is not null)
    kids = sc.children(copy)
    assert len(kids) == 2 and all(k not in (a, b) for k in kids), "Kopie hat eigene Kinder"
    assert sum(len(s.curves) for s in sc.strokes) == 2 * n_lines, "Linien mitkopiert"
    out = _outliner_select(h, [copy.id])
    out._delete()
    assert copy not in sc.nulls and all(k not in sc.strokes for k in kids), "Null samt Kindern gelöscht"
    assert sc.children(null) and sum(len(s.curves) for s in sc.strokes) == n_lines, "Original bleibt"
    h.key(Qt.Key_Z, Qt.ControlModifier)
    assert any(n.id == copy.id for n in sc.nulls), "Löschen ist ein Undo-Schritt"


def _rows(item):
    from sketch_machine.outliner import ID_ROLE
    return [item.child(k) for k in range(item.childCount()) if item.child(k).data(0, ID_ROLE) is not None]


def test_outliner_sortiert_nach_namen_zaehlt_und_vererbt_farbe(h: H):
    """Unter einem Null: Typen gemischt, natürlich nach Namen; Info zeigt die Anzahl; Farbe des Nulls gilt darunter,
    bis ein Null mit eigener Farbe sie überschreibt – gespeichert mit der Szene."""
    from sketch_machine.outliner import COLOR_ROLE, INFO
    sc = h.sc
    top = sc.new_null()
    names = ["Teil 10", "002_ygelenk_root", "Teil 2", "001_xgelenk"]
    for n in names:
        if n == "002_ygelenk_root":
            inner = sc.new_null(parent=top.id)
            inner.name = n
        else:
            st = sc.new_stroke(parent=top.id)
            sc.add_curve(line([0, 0, 0], [1, 0, 0]), None)
            st.name = n
    blue = sc.new_null(parent=inner.id)
    top.color, blue.color = (200, 90, 80), (90, 130, 205)
    h.v._changed()
    out = h.w.outliner
    out.rebuild()
    row = out.groups_root.child(0)
    assert [r.text(0) for r in _rows(row)] == ["001_xgelenk", "002_ygelenk_root", "Teil 2", "Teil 10"]
    assert row.text(INFO) == "Null · 4"
    inner_row = _rows(row)[1]
    assert inner_row.data(0, COLOR_ROLE).getRgb()[:3] == (200, 90, 80), "Kind-Null ohne Farbe erbt"
    assert _rows(inner_row)[0].data(0, COLOR_ROLE).getRgb()[:3] == (90, 130, 205), "eigene Farbe überschreibt"
    path = os.path.join(tempfile.mkdtemp(), "farbe.sketch.json")
    sc.save(path)
    loaded = Scene.load(path)[0]
    assert sorted(n.color for n in loaded.nulls if n.color) == [(90, 130, 205), (200, 90, 80)]


def test_strg_g_linien_mit_objekt_in_gruppe_am_herkunftsort(h: H):
    """Strg+G mit gewählten Linien und einem weiteren gewählten Objekt: neues Stroke-Objekt und das Objekt kommen in
    ein neues Null – im Null, in dem das Objekt der Linien lag. Eine nur mitgewählte Fläche, die nicht von den Linien
    beschrieben wird, bleibt dagegen, wo sie ist (Flächen folgen ihren Linien, nie der Auswahl)."""
    sc = h.sc
    home = sc.new_null()
    st = sc.new_stroke(parent=home.id)
    for p, q in (([0, 0, 0], [1, 0, 0]), ([1, 0, 0], [1, 1, 0]), ([5, 0, 0], [6, 0, 0])):
        sc.add_curve(line(p, q), None)
    other = sc.new_stroke(parent=None)
    P = [np.array(p, float) for p in ([0, 0, 3], [2, 0, 3], [2, 0, 5], [0, 0, 5])]
    for p, q in zip(P, P[1:] + P[:1]):
        sc.add_curve(line(p, q), None)
    f = sc.create_fill([(c, False) for c in other.curves])
    h.v._changed()
    h.edit_mode("edge")
    h.v.edge_selection = [("line", st.id, c.id) for c in st.curves[:2]]
    h.v.selection = [f.id]
    h.v.group_selection()
    new = sc.strokes[-1]
    assert len(sc.nulls) == 1 and new.parent == home.id and len(new.curves) == 2, "nur Fläche mitgewählt: kein Null"
    assert f.owner == other.id and f.parent is None, "die fremde Fläche bleibt bei ihrem Linienobjekt"
    h.v.undo()
    sc = h.sc
    st, other = (next(s for s in sc.strokes if s.id == i) for i in (st.id, other.id))
    h.v.edge_selection = [("line", st.id, c.id) for c in st.curves[:2]]
    h.v.selection = [other.id]
    h.v.group_selection()
    group = sc.nulls[-1]
    new = sc.strokes[-1]
    assert group.id != home.id and group.parent == home.id, "Gruppe sitzt, wo das Objekt der Linien lag"
    assert new.parent == group.id and other.parent == group.id and len(new.curves) == 2
    assert len(st.curves) == 1 and st.parent == home.id, "der Rest bleibt im alten Objekt"
    h.v.undo()
    assert len(h.sc.nulls) == 1, "ein Undo-Schritt"


def test_strg_g_legt_gewaehlte_stroke_objekte_zusammen(h: H):
    """Strg+G ohne Linienauswahl, mit mehreren gewählten Stroke-Objekten: alle Linien ins erste (Name, Gruppe bleiben),
    die anderen verschwinden; Flächen bleiben, wo sie sind; ein Undo-Schritt."""
    sc = h.sc
    home = sc.new_null()
    a = sc.new_stroke(parent=home.id)
    a.name = "Hero"
    sc.add_curve(line([0, 0, 0], [1, 0, 0]), None)
    b = sc.new_stroke(parent=home.id)
    sc.add_curve(line([0, 1, 0], [1, 1, 0]), None)
    sc.add_curve(line([0, 2, 0], [1, 2, 0]), None)
    c = sc.new_stroke(parent=None)
    sc.add_curve(line([0, 3, 0], [1, 3, 0]), None)
    h.v._changed()
    n_strokes = len(sc.strokes)
    h.v.selection = [a.id, b.id, c.id]
    h.v.group_selection()
    assert len(sc.strokes) == n_strokes - 2 and a in sc.strokes and b not in sc.strokes and c not in sc.strokes
    assert len(a.curves) == 4 and a.name == "Hero" and a.parent == home.id
    assert h.v.selection == [a.id]
    h.v.undo()
    assert len(h.sc.strokes) == n_strokes, "ein Undo-Schritt"


def test_outliner_suche_scroll_und_mitscrollen(h: H):
    """Suchfeld zeigt Treffer samt Gruppe; Klick im Outliner lässt die Lage stehen, Auswahl im Viewport scrollt hin."""
    sc = h.sc
    grp = sc.new_null()
    grp.name = "Flügel"
    strokes = []
    for k in range(60):
        st = sc.new_stroke(parent=grp.id if k == 59 else None)
        sc.add_curve(line([k, 0, 0], [k, 1, 0]), None)
        st.name = f"Linie {k:02d}"
        strokes.append(st)
    h.v._changed()
    out = h.w.outliner
    out.rebuild()
    h.pump(0.05)
    out.set_filter("linie 59")
    shown = [r.text(0) for r in _rows(out.groups_root) if not r.isHidden()]
    assert shown == ["Flügel"], shown
    assert [r.text(0) for r in _rows(_rows(out.groups_root)[0]) if not r.isHidden()] == ["Linie 59"]
    assert out.strokes_root.isHidden(), "keine Treffer unter Strokes"
    out.set_filter("")
    assert not out.strokes_root.isHidden()
    bar = out.verticalScrollBar()
    assert bar.maximum() > 0, "Liste länger als der Outliner"
    bar.setValue(bar.maximum() // 2)
    mid = bar.value()
    _outliner_select(h, [strokes[30].id])
    out._from_outliner = True
    h.v.set_selection([strokes[30].id])
    h.pump(0.05)
    assert bar.value() == mid, "Klick im Outliner: die Liste springt nicht"
    bar.setValue(0)
    h.v.set_selection([strokes[59].id])
    h.pump(0.05)
    item = out.selectedItems()[0]
    assert out.visualItemRect(item).intersects(out.viewport().rect()), "Auswahl im Viewport: hingescrollt"


def test_outliner_spalten_ziehbar_und_material_fuer_alle_gewaehlten(h: H):
    """Name, Material und Info sind ziehbare Spalten; das Material-Dropdown einer gewählten Fläche setzt alle gewählten
    Flächen (ein Undo-Schritt), eine nicht gewählte nur sich selbst."""
    from PySide6.QtWidgets import QHeaderView
    from sketch_machine import theme
    from sketch_machine.outliner import BRIEF, EYE, INFO, MATERIAL, NAME
    sc = h.sc
    fills = []
    for z in (0, 3, 6):
        st = sc.new_stroke(parent=None)
        P = [np.array(p, float) for p in ([0, 0, z], [2, 0, z], [2, 0, z + 2], [0, 0, z + 2])]
        for p, q in zip(P, P[1:] + P[:1]):
            sc.add_curve(line(p, q), None)
        fills.append(sc.create_fill([(c, False) for c in st.curves]))
    h.v._changed()
    out = h.w.outliner
    head = out.header()
    assert all(head.sectionResizeMode(c) == QHeaderView.Interactive for c in (NAME, MATERIAL, BRIEF, INFO))
    assert head.sectionResizeMode(EYE) == QHeaderView.Fixed and not head.stretchLastSection()
    key = [k for k, _ in theme.MATERIALS if k != fills[0].material][0]
    _outliner_select(h, [fills[0].id, fills[1].id])
    out._set_material(fills[0].id, key)
    assert [f.material == key for f in fills] == [True, True, False], "gewählte Flächen zusammen"
    h.v.undo()
    assert all(f.material != key for f in h.sc.surfaces), "ein Undo-Schritt"
    out = _outliner_select(h, [h.sc.surfaces[0].id])
    out._set_material(h.sc.surfaces[2].id, key)
    assert [f.material == key for f in h.sc.surfaces] == [False, False, True], "nicht gewählte Fläche: nur sie"

"""Punktmodus mit mehreren gewählten Linienobjekten: der Klick auf einen Punkt hebt die Objekt-Auswahl auf – die Punkte
der anderen Objekte bleiben trotzdem wählbar (Hafentest 10.11.: danach war nur noch das zuletzt aktive Objekt dran)."""
from tests.harness import H, line


def _three(h):
    h.new_scene()
    sc = h.sc
    objs = []
    for z in (0.0, 1.0, 2.0):
        st = sc.new_stroke()
        sc.add_curve(line([0, 0, z], [1, 0, z], 8), None)
        objs.append(st)
    h.camera([0.5, 0, 1.0], 6, [0.1, 1, 0.2])
    h.v._changed()
    h.edit_mode("point")
    return sc, objs


def _shown(h):
    return {r[1] for r, _c, _k in h.v._knot_list()}


def test_punkte_beider_objekte_bleiben_nach_dem_ersten_klick(h: H):
    sc, (a, b, c) = _three(h)
    sc.active_stroke = b
    h.v.selection = [a.id, b.id]
    h.v._changed()
    h.grab()
    assert _shown(h) == {a.id, b.id}, "gewählte Objekte: ihre Punkte"
    h.click(h.scr(a.curves[0].points[0]))
    assert h.v.point_selection and h.v.point_selection[0][1] == a.id
    assert _shown(h) == {a.id, b.id}, "nach dem Klick auf einen Punkt von a sind die Punkte von b noch da"
    h.click(h.scr(b.curves[0].points[0]))
    assert h.v.point_selection and h.v.point_selection[0][1] == b.id, "Punkt von b lässt sich wählen"
    assert _shown(h) == {a.id, b.id}


def test_neue_objektauswahl_ersetzt_den_satz(h: H):
    sc, (a, b, c) = _three(h)
    sc.active_stroke = b
    h.v.selection = [a.id, b.id]
    h.v._changed()
    h.click(h.scr(a.curves[0].points[0]))
    h.v.point_selection = []
    h.v.selection = [c.id]
    sc.active_stroke = c
    h.v._changed()
    assert _shown(h) == {c.id}, "anderes Objekt gewählt: nur noch seine Punkte"


def test_edit_verlassen_vergisst_den_satz(h: H):
    sc, (a, b, c) = _three(h)
    sc.active_stroke = b
    h.v.selection = [a.id, b.id]
    h.v._changed()
    h.click(h.scr(a.curves[0].points[0]))
    h.draw_mode()
    h.v.selection, h.v.point_selection = [], []
    sc.active_stroke = c
    h.edit_mode("point")
    assert _shown(h) == {c.id}, "nach Zeichnen und zurück gilt wieder nur das aktive Objekt"

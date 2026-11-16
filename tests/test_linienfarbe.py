"""Färben im Edit: Farbe wählen ändert nichts; „Anwenden“ in der Farbwahl färbt gewählte Flächen und Pinsellinien,
Bleistift bleibt; per Rechtsklick umwandeln."""
import numpy as np

from sketch_machine.i18n import tr
from tests.harness import H


def _two_lines(h: H):
    h.new_scene()
    sc = h.sc
    sc.new_stroke()
    sc.add_curve(np.linspace([0, 0, 0], [1, 0, 0], 8), None)
    brush = sc.curves[-1]
    brush.style, brush.color = "brush", (0.8, 0.1, 0.1)
    sc.add_curve(np.linspace([0, 0, 1], [1, 0, 1], 8), None)
    pencil = sc.curves[-1]
    stroke = sc.owner_of(brush)
    h.edit_mode("edge")
    h.v.edge_selection = [("line", stroke.id, brush.id), ("line", stroke.id, pencil.id)]
    return brush, pencil


def test_anwenden_faerbt_gewaehlte_pinsellinien_bleistift_bleibt(h: H):
    brush, pencil = _two_lines(h)
    msgs = []
    h.v.status_changed.connect(msgs.append)
    try:
        h.w._use_color((0.1, 0.2, 0.9), remember=False, persist=False)
        h.w._use_color((0.1, 0.3, 0.9), remember=False, persist=False)  # Ziehen im Farbrad
        assert brush.color == (0.8, 0.1, 0.1), "Farbe wählen allein färbt nichts um"
        assert h.v.apply_color((0.1, 0.3, 0.9))
        assert brush.color == (0.1, 0.3, 0.9) and pencil.color is None and pencil.style == "pencil"
        assert any(tr("Bleistift").lower() in m.lower() for m in msgs), msgs
        h.sc.undo()
        brush2 = next(c for c in h.sc.curves if c.id == brush.id)
        assert brush2.color == (0.8, 0.1, 0.1), "ein Undo-Schritt für das Umfärben"
    finally:
        h.v.status_changed.disconnect(msgs.append)


def test_anwenden_faerbt_gewaehlte_flaechen_und_linien_in_einem_schritt(h: H):
    from tests.test_undo_tempo import _two_patches
    sc, st, patches = _two_patches(h)
    line_ = st.curves[0]
    line_.style, line_.color = "brush", (0.8, 0.1, 0.1)
    patches[1].aid = False
    h.edit_mode("face")
    h.v.selection = [f.id for f in patches]
    h.v.edge_selection = [("line", st.id, line_.id), ("line", st.id, st.curves[1].id)]
    h.v._changed()
    rows = [c.color for c in patches[0].curves]
    assert h.v.apply_color((0.2, 0.5, 0.7))
    assert all(f.tint == (0.2, 0.5, 0.7) for f in patches), "beide Flächen gefärbt"
    assert line_.color == (0.2, 0.5, 0.7) and st.curves[1].color is None, "Pinsellinie ja, Bleistift nein"
    assert [c.color for c in patches[0].curves] == rows, "die Form der Fläche (Gitterreihen) bleibt unberührt"
    sc.undo()
    h.v._changed()
    assert all(f.tint is None for f in sc.surfaces), "ein Undo-Schritt für alles"
    assert sc.curve_by_id(line_.id).color == (0.8, 0.1, 0.1)
    h.v.selection = [f.id for f in sc.surfaces]
    h.v.edge_selection = []
    assert h.v.apply_color((0.2, 0.5, 0.7)) and h.v.apply_color(reset=True)
    assert all(f.tint is None for f in sc.surfaces), "Shift+Klick: Färbung zurück auf das Material"


def test_anwenden_ohne_auswahl_tut_nichts(h: H):
    brush, pencil = _two_lines(h)
    h.v.edge_selection = []
    n = len(h.sc._undo)
    assert not h.v.apply_color((0.1, 0.2, 0.9))
    assert len(h.sc._undo) == n and brush.color == (0.8, 0.1, 0.1)


def test_knopf_in_der_farbwahl_nur_im_edit(h: H):
    brush, pencil = _two_lines(h)
    h.w._open_color_popup()
    pop = h.w._color_popup
    try:
        assert pop.apply_button.isVisible(), "Edit: Knopf „Anwenden“ unter dem Farbrad"
        pop.wheel.set_rgb((0.1, 0.3, 0.9))
        pop.apply_button.click()
        assert max(abs(a - b) for a, b in zip(brush.color, (0.1, 0.3, 0.9))) < 0.01, "Klick färbt die gewählte Pinsellinie"
    finally:
        pop.hide()
    h.draw_mode()
    h.w._open_color_popup()
    try:
        assert not pop.apply_button.isVisible(), "Zeichnen: kein Knopf"
    finally:
        pop.hide()


def test_farbe_im_zeichenmodus_faerbt_nichts_um(h: H):
    brush, pencil = _two_lines(h)
    h.draw_mode()
    h.w._use_color((0.1, 0.2, 0.9), remember=False, persist=False)
    assert brush.color == (0.8, 0.1, 0.1)


def test_rechtsklick_wandelt_bleistift_in_pinsel_und_zurueck(h: H):
    brush, pencil = _two_lines(h)
    h.v.set_paint_color((0.2, 0.6, 0.3))
    pid_before = dict(pencil.pids or {})
    pts = pencil.points.copy()
    h.v.convert_lines("brush")
    assert pencil.style == "brush" and pencil.color == (0.2, 0.6, 0.3)
    assert brush.color == (0.8, 0.1, 0.1), "schon Pinsel: bleibt in seiner Farbe"
    assert np.array_equal(pencil.points, pts) and dict(pencil.pids or {}) == pid_before, "Form und Punkte bleiben"
    h.v.convert_lines("pencil")
    assert pencil.style == brush.style == "pencil" and pencil.color is None and brush.color is None
    h.sc.undo()
    assert {c.style for c in h.sc.curves} == {"brush"}

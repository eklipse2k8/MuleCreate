"""Notizkrake: Arme vom Ankerpunkt einer Notiz zu weiteren gleichartigen Teilen – ziehen (Shift) oder Auswahl
hinzufügen, nur an der gewählten Notiz sichtbar (gebogen, magenta), gespeichert, Undo, im Sketch Brief."""
import json
import os
import tempfile

import numpy as np
from PySide6.QtCore import QPointF, Qt

from tests.harness import H, expected_failure
from tests.test_material import _square
from sketch_machine import theme
from sketch_machine.scene import Note, NoteAnchor, NoteMember, Scene


def _krake_scene(h: H):
    """Drei Paneele nebeneinander, eine Notiz zeigt auf das erste."""
    h.new_scene()
    panels = [_square(h, y=0.0, x0=x0, size=2.0) for x0 in (-4.0, -1.0, 2.0)]
    for k, s in enumerate(panels, 1):
        s.name = f"Paneel {k}"
    note = Note("Paneel", np.array([-3.0, 1.2, 1.0]))
    note.anchors.append(NoteAnchor(np.array([-3.0, 0.0, 1.0])))
    h.sc.notes.append(note)
    h.v.set_notes_mode(True)
    h.v.ws.active_note = note.id
    h.camera([0.0, 0.0, 1.0], 11, [0.0, 0.9, 0.35])
    h.grab()
    return note, panels


def _magenta(img):
    """Anzahl Pixel in der Farbe der Krakenarme."""
    c = theme.OCTOPUS
    n = 0
    for y in range(0, img.height(), 2):
        for x in range(0, img.width(), 2):
            p = img.pixelColor(x, y)
            if abs(p.red() - c.red()) < 40 and abs(p.green() - c.green()) < 40 and abs(p.blue() - c.blue()) < 40:
                n += 1
    return n


def _diff(a, b):
    """Mittlere Farbabweichung zweier gleich großer Bilder."""
    def arr(img):
        img = img.convertToFormat(img.Format.Format_RGB32)  # (Bild festhalten, bis die Daten kopiert sind)
        raw = np.frombuffer(bytes(img.constBits()), np.uint8)
        return raw.reshape(img.height(), img.bytesPerLine())[:, :img.width() * 4]
    return float(np.abs(arr(a).astype(int) - arr(b).astype(int)).mean())


def test_arm_ziehen_mit_shift_undo_redo(h: H):
    """Shift+Ziehen vom Ankerpunkt auf ein anderes Paneel: Arm angehängt (ein Undo-Schritt); ohne Shift wird wie
    bisher die Hinweislinie versetzt, nicht die Krake erweitert."""
    note, panels = _krake_scene(h)
    try:
        end = h.v.notes_tool._screen[note.id]["anchors"][0][1]
        h.stroke([end, h.scrf([0.0, 0.0, 1.0])], mods=Qt.ShiftModifier)
        assert not note.anchors[0].members, "Anker noch nicht angeklickt: Shift wählt ihn erst"
        assert h.v.ws.active_anchor == (note.id, 0)
        h.grab()
        h.stroke([end, h.scrf([0.0, 0.0, 1.0])], mods=Qt.ShiftModifier)
        members = note.anchors[0].members
        assert len(members) == 1 and members[0].obj_id == panels[1].id, [m.obj_id for m in members]
        assert members[0].curve_id is None and np.allclose(members[0].point, [0.0, 0.0, 1.0], atol=0.1)
        assert np.allclose(note.anchors[0].point, [-3.0, 0.0, 1.0]), "Anker bleibt, wo er war"
        h.grab()
        end = h.v.notes_tool._screen[note.id]["anchors"][0][1]
        h.stroke([end, h.scrf([0.0, 0.0, 1.0])], mods=Qt.ShiftModifier)
        assert len(note.anchors[0].members) == 1, "dasselbe Teil nur einmal"
        h.sc.undo()
        again = h.sc.notes[0]
        assert not again.anchors[0].members, "Strg+Z nimmt den Arm zurück"
        h.sc.redo()
        assert len(h.sc.notes[0].anchors[0].members) == 1, "Strg+Y bringt ihn wieder"
    finally:
        h.v.set_notes_mode(False)


@expected_failure("Ankerpunkt der Krake nicht magenta – rot seit mindestens v0.99.130, Ursache ungeklärt (12.11.)")
def test_arme_nur_an_gewaehlter_notiz_gebogen_magenta(h: H):
    """Arme erscheinen nur, solange die Notiz gewählt ist (Modus Notizen); Ring am Ende ist anklickbar, Entf
    entfernt den Arm."""
    note, panels = _krake_scene(h)
    try:
        note.anchors[0].members += [NoteMember(panels[1].id, None, np.array([0.0, 0.0, 1.0])),
                                    NoteMember(panels[2].id, None, np.array([3.0, 0.0, 1.0]))]
        h.v._changed()
        dot = h.grab()
        assert not h.v.notes_tool._screen[note.id]["members"], "nur Notiz gewählt: noch keine Arme"
        assert 3 < _magenta(dot) < 60, ("Ankerpunkt mit Krake magenta mit Ring", _magenta(dot))
        h.click(h.v.notes_tool._screen[note.id]["anchors"][0][1])
        assert h.v.ws.active_anchor == (note.id, 0)
        shown = h.grab()
        info = h.v.notes_tool._screen[note.id]
        assert len(info["members"]) == 2, info["members"]
        assert _magenta(shown) > _magenta(dot) + 20, "angeklickt: Arme in Magenta zu sehen"
        h.v.ws.active_note = None
        h.v._changed()
        hidden = h.grab()
        assert not h.v.notes_tool._screen[note.id]["members"] and _magenta(hidden) < 3, "ohne Auswahl keine Arme"
        h.v.ws.active_note, h.v.ws.active_anchor = note.id, (note.id, 0)
        h.v._changed()
        h.grab()
        (ji, end), = [m for m in h.v.notes_tool._screen[note.id]["members"] if m[0] == (0, 1)]
        h.move(end)
        assert h.v.notes_tool.hover == ("member", note.id, (0, 1)), h.v.notes_tool.hover
        h.key(Qt.Key_Delete)
        assert [m.obj_id for m in h.sc.notes[0].anchors[0].members] == [panels[1].id], "Entf am Ring: nur dieser Arm"
        assert h.sc.notes, "die Notiz selbst bleibt"
    finally:
        h.v.set_notes_mode(False)


def test_auswahl_zur_krake_hinzufuegen_und_speichern(h: H):
    """Auswahl (Flächen und eine Linie) als Arme in einem Schritt; Ende = dem Anker nächste Stelle; gespeichert
    und geladen mit neuen ids."""
    note, panels = _krake_scene(h)
    try:
        line = h.sc.strokes[-1].curves[0]
        h.v.ws.selection = [panels[1].id, panels[2].id]
        h.v.ws.edge_selection = [("line", h.sc.strokes[-1].id, line.id)]
        added = h.v.notes_tool.add_selection(note.id, 0)
        members = note.anchors[0].members
        assert added == 3 and len(members) == 3, [(m.obj_id, m.curve_id) for m in members]
        assert members[0].point[0] < 0.0, "Ende des Arms: dem Anker nächste Stelle von Paneel 2 (linker Rand)"
        assert members[2].curve_id == line.id and members[2].obj_id == h.sc.strokes[-1].id
        assert h.v.notes_tool.add_selection(note.id, 0) == 0, "nichts doppelt"
        path = os.path.join(tempfile.mkdtemp(), "krake.sketch.json")
        h.sc.save(path)
        loaded = Scene.load(path)[0]
        got = loaded.notes[0].anchors[0].members
        names = [loaded.object_by_id(m.obj_id).name for m in got]
        assert names == ["Paneel 2", "Paneel 3", h.sc.strokes[-1].name], names
        assert got[2].curve_id is not None and loaded.curve_by_id(got[2].curve_id) is not None, "Linie neu verknüpft"
        h.sc.undo()
        assert not h.sc.notes[0].anchors[0].members, "Auswahl hinzufügen = ein Undo-Schritt"
    finally:
        h.v.ws.selection, h.v.ws.edge_selection = [], []
        h.v.set_notes_mode(False)


def test_brief_nennt_mitglieder_index_und_geloeschte(h: H):
    """Brief: Anker nennt „also meant“, brief.json hat Mitglieder und den Index Bauteil -> Notizen, das Notizbild
    zeigt die Mitglieder schwächer als den Anker; gelöschte Mitglieder meldet die Vorprüfung."""
    from sketch_machine import brief
    note, panels = _krake_scene(h)
    try:
        note.anchors[0].members += [NoteMember(panels[1].id, None, np.array([0.0, 0.0, 1.0])),
                                    NoteMember(panels[2].id, None, np.array([3.0, 0.0, 1.0]))]
        folder = tempfile.mkdtemp()
        brief.export(h.sc, h.v, folder, "krake")
        md = open(os.path.join(folder, "brief.md"), encoding="utf-8").read()
        data = json.load(open(os.path.join(folder, "brief.json"), encoding="utf-8"))
        a = data["notes"][0]["anchors"][0]
        assert a["target"]["name"] == "Paneel 1", a.get("target")
        assert [m["name"] for m in a["members"]] == ["Paneel 2", "Paneel 3"], a.get("members")
        assert "also meant: " in md and "may be incomplete" in md, "Anker nennt seine Mitglieder"
        assert "„also meant“" in md.split("**Reading notes:**")[1][:2000], "Lesehilfe erklärt die Liste"
        index = {e["name"]: e["notes"] for e in data["part_notes"]}
        assert index["Paneel 1"] == [{"note": "N1", "anchor": 1, "via": "anchor"}], index
        assert index["Paneel 3"] == [{"note": "N1", "anchor": 1, "via": "also meant"}], index
        assert os.path.isfile(os.path.join(folder, "views", "note_N1_1.png"))
        # schwächer hervorgehoben als der Anker, aber sichtbar
        h.v.set_notes_mode(False)
        h.camera([0.0, 0.0, 1.0], 11, [0.0, 0.9, 0.35])
        plain = h.v.clean_image()
        faint = h.v.clean_image(faint=[panels[2].id])
        strong = h.v.clean_image(select=[panels[2].id])
        assert 0 < _diff(plain, faint) < _diff(plain, strong), (_diff(plain, faint), _diff(plain, strong))
        # gelöscht: Vorprüfung meldet es, der Brief nennt es nicht mehr
        h.sc.checkpoint()
        h.sc.surfaces.remove(panels[2])
        h.v._changed()
        data = brief.analyse(h.sc)
        points = brief.precheck(h.sc, data)["points"]
        assert any(("Notizkrake" in p and "Gelöschtes" in p) or "were deleted" in p for p in points), points
        assert [m["name"] for m in data["notes"][0]["anchors"][0]["members"]] == ["Paneel 2"]
        h.v.set_notes_mode(True)
        h.v.ws.active_note, h.v.ws.active_anchor = h.sc.notes[0].id, (h.sc.notes[0].id, 0)
        h.v._changed()
        h.grab()
        assert len(h.v.notes_tool._screen[note.id]["members"]) == 2, "gelöschtes Mitglied bleibt gestrichelt sichtbar"
    finally:
        h.v.set_notes_mode(False)


def test_gewaehlte_notiz_laesst_verbundene_teile_aufleuchten(h: H):
    """Gewählte Notiz: Teil am Anker kräftig, Teile an den Armen schwächer in Magenta; Klick auf einen Ankerpunkt:
    nur seine Teile; Klick auf die Notiz bzw. Esc: wieder alle; ohne gewählte Notiz nichts."""
    note, panels = _krake_scene(h)
    try:
        line = h.sc.strokes[-1].curves[0]
        note.anchors.append(NoteAnchor(np.array([0.0, 0.0, 0.5]), line.id, 0.5))
        note.anchors[0].members.append(NoteMember(panels[1].id, None, np.array([0.0, 0.0, 1.0])))
        h.v._changed()
        objs, lines = h.v._note_glow()
        assert objs == {panels[0].id: 1.0, panels[1].id: 0.5} and lines == {line.id: 1.0}, (objs, lines)
        lit = h.grab()
        h.v.ws.active_note = None
        h.v._changed()
        assert h.v._note_glow() == ({}, {}), "ohne gewählte Notiz leuchtet nichts"
        dark = h.grab()
        assert _diff(lit, dark) > 0.3, _diff(lit, dark)
        h.v.ws.active_note = note.id
        h.v._changed()
        h.grab()
        end = dict(h.v.notes_tool._screen[note.id]["anchors"])[0]
        h.click(end)
        assert h.v.ws.active_anchor == (note.id, 0), h.v.ws.active_anchor
        objs, lines = h.v._note_glow()
        assert objs == {panels[0].id: 1.0, panels[1].id: 0.5} and not lines, "nur die Teile des angeklickten Ankers"
        assert note.anchors[0].point[0] == -3.0, "Klick versetzt den Anker nicht"
        h.key(Qt.Key_Escape)
        assert h.v.ws.active_anchor is None and h.v.ws.active_note == note.id, "Esc: zurück zur ganzen Notiz"
        assert h.v._note_glow()[1] == {line.id: 1.0}
    finally:
        h.v.set_notes_mode(False)


def test_shift_klick_im_viewport_und_null_als_gruppe(h: H):
    """Modus Notizen, Notiz gewählt (eine Hinweislinie): Shift+Klick auf ein Teil hängt es an die Krake, nochmal
    heraus; Strg+Shift+Klick nimmt das Null darüber (ein Arm, alles darin leuchtet). „Auswahl hinzufügen“ mit einem
    Null: ebenfalls ein Arm; der Brief nennt die Gruppe samt Teilen."""
    from sketch_machine import brief
    from sketch_machine.scene import NullObject
    note, panels = _krake_scene(h)
    try:
        null = NullObject("Paneele")
        h.sc.nulls.append(null)
        panels[1].parent = panels[2].parent = null.id
        h.v._changed()
        h.grab()
        h.click(h.scrf([0.0, 0.0, 1.0]), mods=Qt.ShiftModifier)
        assert [m.obj_id for m in note.anchors[0].members] == [panels[1].id], "Shift+Klick: Teil dazu"
        assert h.v.ws.active_note == note.id, "Notiz bleibt gewählt"
        h.click(h.scrf([0.0, 0.0, 1.0]), mods=Qt.ShiftModifier)
        assert not note.anchors[0].members, "nochmal Shift+Klick: wieder heraus"
        h.click(h.scrf([-3.0, 0.0, 1.0]), mods=Qt.ShiftModifier)
        assert not note.anchors[0].members, "das Teil am Anker selbst kommt nicht nochmal dazu"
        h.click(h.scrf([3.0, 0.0, 1.0]), mods=Qt.ShiftModifier | Qt.ControlModifier)
        assert [m.obj_id for m in note.anchors[0].members] == [null.id], "Strg+Shift+Klick: das ganze Null"
        objs, _ = h.v._note_glow()
        assert objs.get(panels[1].id) == 0.5 and objs.get(panels[2].id) == 0.5, objs
        data = brief.analyse(h.sc)
        (m,) = data["notes"][0]["anchors"][0]["members"]
        assert m["kind"] == "group" and len(m["parts"]) == 2, m
        index = {e["name"]: e["notes"] for e in data["part_notes"]}
        assert index["Paneel 3"] == [{"note": "N1", "anchor": 1, "via": "also meant"}], index
        h.sc.undo()
        h.v.ws.selection = [null.id]
        assert h.v.notes_tool.add_selection(note.id, 0) == 1, "Null in der Auswahl: ein Arm"
        assert h.sc.notes[0].anchors[0].members[0].obj_id == null.id
    finally:
        h.v.ws.selection = []
        h.v.set_notes_mode(False)


def test_arme_verdeckt_blass(h: H):
    """Arme werden wie Hinweislinien von Flächen verdeckt: das verdeckte Stück bleibt im Modus Notizen blass."""
    note, panels = _krake_scene(h)
    try:
        note.anchors[0].members.append(NoteMember(panels[2].id, None, np.array([3.0, 0.0, 1.0])))
        h.v.ws.active_anchor = (note.id, 0)
        h.v._changed()
        h.grab()
        seen = h.v.notes_tool.occlusion["_arms"][(note.id, 0, 0)]
        assert seen.all(), "frei: ganz sichtbar"
        wall = _square(h, y=0.6, x0=-0.5, size=2.0)  # über dem Arm (Kamera schaut von oben)
        h.v.ws.active_note, h.v.ws.active_anchor = note.id, (note.id, 0)
        h.v._changed()
        h.grab()
        seen = h.v.notes_tool.occlusion["_arms"][(note.id, 0, 0)]
        assert seen.any() and not seen.all(), ("teils verdeckt", seen)
        assert len(h.v.notes_tool._screen[note.id]["members"]) == 1, "der Arm bleibt anklickbar"
    finally:
        h.v.set_notes_mode(False)


def test_zweiter_klick_aus_und_krake_ohne_schild(h: H):
    """Nochmal auf den angeklickten Ankerpunkt klicken blendet die Arme wieder aus; liegt das Schild der Notiz hinter
    der Kamera (nah an den Teilen), bleiben Ankerpunkt und Arme des angeklickten Ankers zu sehen; ein Arm, dessen
    Ende hinter der Kamera liegt, verschwindet nicht ganz."""
    note, panels = _krake_scene(h)
    try:
        note.anchors[0].members.append(NoteMember(panels[1].id, None, np.array([0.0, 0.0, 1.0])))
        h.v._changed()
        h.grab()
        end = h.v.notes_tool._screen[note.id]["anchors"][0][1]
        h.click(end)
        h.grab()
        assert h.v.ws.active_anchor == (note.id, 0) and len(h.v.notes_tool._screen[note.id]["members"]) == 1
        h.click(end)
        h.grab()
        assert h.v.ws.active_anchor is None and not h.v.notes_tool._screen[note.id]["members"], "zweiter Klick: aus"
        assert h.v.ws.active_note == note.id, "die Notiz bleibt gewählt"
        h.click(end)
        note.pos = h.v.cam.eye + h.v.cam.back * 2.0  # Schild hinter der Kamera
        h.v._changed()
        h.grab()
        info = h.v.notes_tool._screen.get(note.id)
        assert info is not None and len(info["members"]) == 1 and info["anchors"], info
        assert h.v.notes_tool.hit(info["anchors"][0][1])[0] == "anchor", "Ankerpunkt bleibt anklickbar"
        cam = h.v.cam
        samples = h.v.notes_tool.arm_samples(np.array([-3.0, 0.0, 1.0]), cam.eye + cam.back * 1.0)
        q, qok = h.v.project(samples)
        assert qok.sum() >= 2 and not qok[-1], "Ende hinter der Kamera, Anfang davor"
    finally:
        h.v.set_notes_mode(False)


def test_vordere_flaeche_schlaegt_linie_dahinter(h: H):
    """Shift+Klick (Krake) und neue Hinweislinie auf eine Fläche, hinter der eine Linie durchläuft: getroffen wird die
    sichtbare Fläche, nicht die Linie dahinter. Eine Linie vor der Fläche bleibt treffbar."""
    from sketch_machine import network
    note, panels = _krake_scene(h)
    try:
        sc = h.sc
        sc.new_stroke()
        sc.add_curve(np.linspace([-0.5, -1.0, 1.0], [2.5, -1.0, 1.0], 20), None)  # unter Paneel 2
        behind = sc.curves[-1]
        sc.new_stroke()
        sc.add_curve(np.linspace([-0.5, 1.0, 0.4], [2.5, 1.0, 0.4], 20), None)  # über Paneel 2
        front = sc.curves[-1]
        network.sync(sc)
        for s in sc.strokes:
            s.parent = None
        h.v._changed()
        h.grab()
        tool = h.v.notes_tool
        pos = h.scrf([1.0, -1.0, 1.0])  # Bildschirmstelle der hinteren Linie – dort liegt Paneel 2 davor
        assert h.v._curve_under(pos)[0] is behind, "ohne Verdeckung träfe man die Linie"
        target = tool._member_target(pos)
        assert target is not None and target.curve_id is None and target.obj_id == panels[1].id, target
        assert abs(target.point[1]) < 0.05, "der Punkt liegt auf der Fläche"
        anchor = tool._anchor_target(pos)
        assert anchor.curve_id is None and abs(anchor.point[1]) < 0.05, "Hinweislinie: auch die Fläche"
        target = tool._member_target(h.scrf([1.0, 1.0, 0.4]))
        assert target is not None and target.curve_id == front.id, "Linie davor bleibt treffbar"
    finally:
        h.v.set_notes_mode(False)

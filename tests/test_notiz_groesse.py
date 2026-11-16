"""Notizen in großen Szenen (Artist 12.11., Hafenszene): im Modus Notizen bleibt die Schrift lesbar und greifbar, und die
Szene hat einen Faktor für die Notizgröße (Rechtsklickmenü), der mitgespeichert wird."""
import os
import tempfile

import numpy as np

from sketch_machine import note_tool
from sketch_machine.scene import Scene
from tests.harness import H, Qt


def _notiz_weit_weg(h: H):
    sc = h.new_scene()
    sc.add_curve(np.linspace([0.0, 0.0, 0.0], [3000.0, 0.0, 2000.0], 12), None)  # Szene von Kilometern
    h.v._changed()
    h.camera([1500.0, 0.0, 1000.0], 2500, [0.4, 0.6, 0.7])
    if not h.v.notes_mode:
        h.key(Qt.Key_N)
    assert h.v.notes_mode
    note = h.v.notes_tool.create(np.array([1500.0, 0.0, 1000.0])) if hasattr(h.v.notes_tool, "create") else None
    if note is None:
        from sketch_machine.scene import Note
        note = Note("Kai", np.array([1500.0, 0.0, 1000.0]))
        sc.notes.append(note)
    note.title = "Kai"
    h.v._changed()
    h.grab()
    return note


def _zeile_px(h: H, note):
    g = h.v.notes_tool.geometry(note)
    return g["k"] * g["h"] / h.v.notes_tool._wpp(note.pos)


def test_im_notizmodus_lesbar_ausserhalb_klein(h: H):
    note = _notiz_weit_weg(h)
    assert _zeile_px(h, note) >= note_tool.MIN_LINE_PX_NOTES[note.size] - 0.5, \
        f"im Modus Notizen ist die Schrift nur {_zeile_px(h, note):.1f} px hoch"
    h.key(Qt.Key_N)  # Modus verlassen: wieder die sehr kleine Grenze
    assert not h.v.notes_mode
    assert _zeile_px(h, note) < 5.0, "außerhalb des Modus darf die ferne Notiz sehr klein werden"


def test_notizgroesse_der_szene_wirkt_und_wird_gespeichert(h: H):
    note = _notiz_weit_weg(h)
    h.key(Qt.Key_N)  # außerhalb des Modus: die wahre Größe in Welteinheiten zählt
    h.camera(note.pos, 30, [0.4, 0.6, 0.7])  # nah heran: keine Mindestgröße im Spiel
    vorher = h.v.notes_tool.geometry(note)["k"]
    h.v.notes_tool.set_scene_scale(10)
    assert abs(h.v.notes_tool.geometry(note)["k"] / vorher - 10) < 1e-6, "der Faktor wirkt nicht auf die Schriftgröße"
    assert h.sc.dirty
    path = os.path.join(tempfile.mkdtemp(prefix="mule_notiz_"), "n.mule")
    h.sc.save(path)
    assert Scene.load(path)[0].note_scale == 10
    h.v.notes_tool.set_scene_scale(1)
    h.sc.save(path)
    assert Scene.load(path)[0].note_scale == 1.0
    h.sc.dirty = False

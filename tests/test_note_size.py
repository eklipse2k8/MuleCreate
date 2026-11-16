"""Notes in large scenes (artist 12.11., harbour scene): in notes mode the text stays readable and graspable, and the
scene has a factor for the note size (right-click menu) that is saved with it."""
import os
import tempfile

import numpy as np

from sketch_machine import note_tool
from sketch_machine.scene import Scene
from tests.harness import H, Qt


def _notiz_weit_weg(h: H):
    sc = h.new_scene()
    sc.add_curve(np.linspace([0.0, 0.0, 0.0], [3000.0, 0.0, 2000.0], 12), None)  # scene of kilometres
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


def test_readable_in_notes_mode_small_outside(h: H):
    note = _notiz_weit_weg(h)
    assert _zeile_px(h, note) >= note_tool.MIN_LINE_PX_NOTES[note.size] - 0.5, \
        f"in notes mode the text is only {_zeile_px(h, note):.1f} px high"
    h.key(Qt.Key_N)  # leave the mode: the very small limit again
    assert not h.v.notes_mode
    assert _zeile_px(h, note) < 5.0, "outside the mode the distant note may become very small"


def test_scene_note_size_takes_effect_and_is_saved(h: H):
    note = _notiz_weit_weg(h)
    h.key(Qt.Key_N)  # outside the mode: the true size in world units counts
    h.camera(note.pos, 30, [0.4, 0.6, 0.7])  # close up: no minimum size in play
    vorher = h.v.notes_tool.geometry(note)["k"]
    h.v.notes_tool.set_scene_scale(10)
    assert abs(h.v.notes_tool.geometry(note)["k"] / vorher - 10) < 1e-6, "the factor does not affect the font size"
    assert h.sc.dirty
    path = os.path.join(tempfile.mkdtemp(prefix="mule_notiz_"), "n.mule")
    h.sc.save(path)
    assert Scene.load(path)[0].note_scale == 10
    h.v.notes_tool.set_scene_scale(1)
    h.sc.save(path)
    assert Scene.load(path)[0].note_scale == 1.0
    h.sc.dirty = False

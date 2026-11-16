"""Ansicht → Arbeitsbereich zurücksetzen: ein abgekoppeltes oder geschlossenes Panel kommt wieder an seinen Platz."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDockWidget

from tests.harness import H


def test_geschlossener_outliner_kommt_zurueck(h: H):
    h.new_scene()
    w = h.v.window()
    dock = w.findChild(QDockWidget, "outliner_dock")
    assert dock.isVisible()
    dock.setFloating(True)
    dock.close()
    h.pump(0.02)
    assert not dock.isVisible(), "abgekoppelt und geschlossen"
    w.reset_workspace()
    h.pump(0.02)
    assert dock.isVisible() and not dock.isFloating(), "Outliner wieder da und angedockt"
    assert w.dockWidgetArea(dock) == Qt.RightDockWidgetArea, "rechts, wie ab Werk"


def test_notiz_und_shots_bleiben_modusabhaengig(h: H):
    h.new_scene()
    w = h.v.window()
    pinned = w._note_pinned
    try:
        w.set_note_pinned(False)
        w.note_dock.setFloating(True)
        w.reset_workspace()
        h.pump(0.02)
        assert not w.note_dock.isFloating()
        assert not w.note_dock.isVisible(), "Notiz: nur im Modus Notizen oder angeheftet"
        assert not w.timing_dock.isVisible() and not w.timeline_dock.isVisible(), "Shots und Timeline: nur im Modus Shots"
        w.set_note_pinned(True)
        w.note_dock.setFloating(True)
        w.note_dock.close()
        w.reset_workspace()
        h.pump(0.02)
        assert w.note_dock.isVisible() and not w.note_dock.isFloating(), "angeheftet: Notiz wieder da und angedockt"
        assert w.dockWidgetArea(w.note_dock) == Qt.RightDockWidgetArea
    finally:
        w.set_note_pinned(pinned)

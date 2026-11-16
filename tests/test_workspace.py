"""View → Reset workspace: a detached or closed panel returns to its place."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDockWidget

from tests.harness import H


def test_closed_outliner_comes_back(h: H):
    h.new_scene()
    w = h.v.window()
    dock = w.findChild(QDockWidget, "outliner_dock")
    assert dock.isVisible()
    dock.setFloating(True)
    dock.close()
    h.pump(0.02)
    assert not dock.isVisible(), "detached and closed"
    w.reset_workspace()
    h.pump(0.02)
    assert dock.isVisible() and not dock.isFloating(), "outliner back and docked"
    assert w.dockWidgetArea(dock) == Qt.RightDockWidgetArea, "on the right, as by default"


def test_note_and_shots_stay_mode_dependent(h: H):
    h.new_scene()
    w = h.v.window()
    pinned = w._note_pinned
    try:
        w.set_note_pinned(False)
        w.note_dock.setFloating(True)
        w.reset_workspace()
        h.pump(0.02)
        assert not w.note_dock.isFloating()
        assert not w.note_dock.isVisible(), "note: only in notes mode or when pinned"
        assert not w.timing_dock.isVisible() and not w.timeline_dock.isVisible(), "Shots and timeline: only in Shots mode"
        w.set_note_pinned(True)
        w.note_dock.setFloating(True)
        w.note_dock.close()
        w.reset_workspace()
        h.pump(0.02)
        assert w.note_dock.isVisible() and not w.note_dock.isFloating(), "pinned: note back and docked"
        assert w.dockWidgetArea(w.note_dock) == Qt.RightDockWidgetArea
    finally:
        w.set_note_pinned(pinned)

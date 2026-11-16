"""Introduction in pictures inside the program: at the very top of the manual (F1) the button for the slideshow and the
way to the AI handbook, the same entries in the Help menu, the slideshow pages with the arrow keys, and the question at
first start does not come back after "Nicht mehr fragen"."""
from PySide6.QtCore import QSettings, Qt
from PySide6.QtTest import QTest

from tests.harness import H
from sketch_machine import intro


def test_manual_starts_with_the_introduction(h: H):
    h.w.show_manual()
    h.pump(0.1)
    man = h.w._manual
    try:
        assert man.intro_button.isVisible() and man.ai_button.isVisible(), "both buttons at the top of the manual"
        assert man.intro_button.mapTo(man, man.intro_button.rect().topLeft()).y() < man.tabs.mapTo(man, man.tabs.rect().topLeft()).y(), \
            "above the tabs: the first thing one sees"
        man.intro_button.click()
        h.pump(0.2)
        win = h.w._intro
        assert win.isVisible() and len(win.items) >= 18, len(win.items)
        first = win.title.text()
        QTest.keyClick(win, Qt.Key_Right)
        assert win.k == 1 and win.title.text() != first, "arrow right: next picture"
        QTest.keyClick(win, Qt.Key_Left)
        QTest.keyClick(win, Qt.Key_Left)
        assert win.k == len(win.items) - 1, "from the first back: the last"
        assert not win._pixmap.isNull(), "picture loaded"
        QTest.keyClick(win, Qt.Key_Escape)
        assert not win.isVisible(), "Esc closes"
    finally:
        man.close()


def test_help_menu_has_introduction_and_ai_handbook(h: H):
    help_menu = next(m for m in h.w.menuBar().actions() if m.menu() and ("&Hilf" in m.text() or "&Help" in m.text()))
    texts = [a.text() for a in help_menu.menu().actions()]
    assert any("Einführung" in t or "Introduction" in t for t in texts), texts
    assert any("AI_HANDBOOK.md" in t for t in texts), texts


def test_question_at_first_start_does_not_come_back(h: H):
    QSettings("SketchMachine", "SketchMachine").setValue(intro.ASKED_KEY, True)
    try:
        intro.ask_at_first_start(h.w)  # would block with a dialog if it asked
        assert QSettings("SketchMachine", "SketchMachine").value(intro.ASKED_KEY, False, type=bool)
    finally:
        QSettings("SketchMachine", "SketchMachine").remove(intro.ASKED_KEY)

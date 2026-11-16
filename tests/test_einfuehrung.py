"""Einführung in Bildern im Programm: ganz oben im Handbuch (F1) der Knopf zur Diashow und der Weg zum KI-Handbuch,
dieselben Einträge im Menü Hilfe, die Diashow blättert mit den Pfeiltasten, die Frage beim ersten Start kommt nach
„Nicht mehr fragen“ nicht wieder."""
from PySide6.QtCore import QSettings, Qt
from PySide6.QtTest import QTest

from tests.harness import H
from sketch_machine import intro


def test_handbuch_beginnt_mit_der_einfuehrung(h: H):
    h.w.show_manual()
    h.pump(0.1)
    man = h.w._manual
    try:
        assert man.intro_button.isVisible() and man.ai_button.isVisible(), "beide Knöpfe oben im Handbuch"
        assert man.intro_button.mapTo(man, man.intro_button.rect().topLeft()).y() < man.tabs.mapTo(man, man.tabs.rect().topLeft()).y(), \
            "über den Reitern: das Erste, was man sieht"
        man.intro_button.click()
        h.pump(0.2)
        win = h.w._intro
        assert win.isVisible() and len(win.items) >= 18, len(win.items)
        first = win.title.text()
        QTest.keyClick(win, Qt.Key_Right)
        assert win.k == 1 and win.title.text() != first, "Pfeil rechts: nächstes Bild"
        QTest.keyClick(win, Qt.Key_Left)
        QTest.keyClick(win, Qt.Key_Left)
        assert win.k == len(win.items) - 1, "vom ersten zurück: das letzte"
        assert not win._pixmap.isNull(), "Bild geladen"
        QTest.keyClick(win, Qt.Key_Escape)
        assert not win.isVisible(), "Esc schließt"
    finally:
        man.close()


def test_menue_hilfe_hat_einfuehrung_und_ki_handbuch(h: H):
    help_menu = next(m for m in h.w.menuBar().actions() if m.menu() and ("&Hilf" in m.text() or "&Help" in m.text()))
    texts = [a.text() for a in help_menu.menu().actions()]
    assert any("Einführung" in t or "Introduction" in t for t in texts), texts
    assert any("AI_HANDBOOK.md" in t for t in texts), texts


def test_frage_beim_ersten_start_nicht_wieder(h: H):
    QSettings("SketchMachine", "SketchMachine").setValue(intro.ASKED_KEY, True)
    try:
        intro.ask_at_first_start(h.w)  # would block with a dialog if it asked
        assert QSettings("SketchMachine", "SketchMachine").value(intro.ASKED_KEY, False, type=bool)
    finally:
        QSettings("SketchMachine", "SketchMachine").remove(intro.ASKED_KEY)

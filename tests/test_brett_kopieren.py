"""Elemente von Brett zu Brett: mehrere Bilder (und Texte, Striche) kopieren oder ausschneiden und in einem anderen
Brett einfügen – Global ↔ Lokal, Lokal ↔ Lokal. Anordnung bleibt, das Eingefügte ist gewählt, je ein Undo-Schritt."""
import numpy as np
from PySide6.QtCore import QBuffer, QIODevice, QPointF, Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

from sketch_machine.note_board import BOARD_MIME, ImageItem, TextBlock, board_for
from sketch_machine.scene import Note
from tests.harness import H
from tests.test_notizen import _close, _note_scene


def _png(color):
    img, buf = QImage(120, 80, QImage.Format_RGB32), QBuffer()
    img.fill(QColor(*color))
    buf.open(QIODevice.WriteOnly)
    img.save(buf, "PNG")
    return bytes(buf.data())


def _filled_board(h):
    """Lokale Notiz mit zwei Bildern (das zweite Hero-Kamera) und einem Text; dazu eine zweite lokale Notiz."""
    note = _note_scene(h)
    other = Note("Lager", np.array([-0.5, 0.8, 0.0]))
    h.sc.notes.append(other)
    board = board_for(h.v)
    board.open(h.v, note.id)
    h.pump(0.05)
    a = board.add_image(_png((200, 60, 60)), ".png", QPointF(0, 0))
    b = board.add_image(_png((60, 60, 200)), ".png", QPointF(300, 150))
    b.view = {"target": [0.0, 0.0, 0.0], "dist": 5.0, "rot": [[1, 0, 0], [0, 1, 0], [0, 0, 1]]}  # Screenshot
    b.hero, b.hero_name = True, "Totale"
    board.add_text(QPointF(0, 300), "Kran")
    board.commit()
    return note, other, board, (a, b)


def _images(board):
    return [i for i in board.gscene.items(Qt.AscendingOrder) if isinstance(i, ImageItem)]


def test_mehrere_bilder_lokal_nach_global_kopieren(h: H):
    note, other, board, (a, b) = _filled_board(h)
    try:
        board.gscene.clearSelection()
        a.setSelected(True)
        b.setSelected(True)
        assert board.copy_selection()
        assert QApplication.clipboard().mimeData().hasFormat(BOARD_MIME)
        assert len(_images(board)) == 2, "Kopieren lässt das Brett, wie es ist"
        board.open(h.v, h.sc.global_note.id)  # Panel „Global“ ist dasselbe Brett mit der Projekt-Notiz
        h.pump(0.05)
        assert not _images(board)
        undo = len(h.sc._undo)
        board.insert_mime(QApplication.clipboard().mimeData(), QPointF(1000, 500))
        got = _images(board)
        assert len(got) == 2 and {i.file for i in got} == {a.file, b.file}, "beide Bilder im globalen Brett"
        pos = sorted((i.x(), i.y()) for i in got)
        assert pos[0] == (1000.0, 500.0) and pos[1] == (1300.0, 650.0), "Anordnung bleibt, obere linke Ecke am Ziel"
        assert all(i.isSelected() for i in got), "das Eingefügte ist gewählt"
        assert not any(i.hero for i in got), "eine Kopie ist keine zweite Hero-Kamera"
        assert len(h.sc._undo) == undo + 1, "ein Undo-Schritt"
        assert len([e for e in h.sc.global_note.board["items"] if e["kind"] == "image"]) == 2, "in der Notiz gespeichert"
        assert len([e for e in h.sc.note_by_id(note.id).board["items"] if e["kind"] == "image"]) == 2, "Quelle unberührt"
    finally:
        _close(h, board)


def test_ausschneiden_und_in_anderer_lokaler_notiz_einfuegen(h: H):
    note, other, board, (a, b) = _filled_board(h)
    try:
        board.gscene.clearSelection()
        for item in board.gscene.items():
            if isinstance(item, (ImageItem, TextBlock)):
                item.setSelected(True)
        assert board.copy_selection(cut=True)
        assert not h.sc.note_by_id(note.id).board, "ausgeschnitten: die Quelle ist leer"
        board.open(h.v, other.id)
        h.pump(0.05)
        board.insert_mime(QApplication.clipboard().mimeData(), QPointF(0, 0))
        items = h.sc.note_by_id(other.id).board["items"]
        assert sorted(e["kind"] for e in items) == ["image", "image", "text"], "Bilder und Text angekommen"
        assert any(e.get("hero") and e.get("hero_name") == "Totale" for e in items), "ausgeschnitten: Hero-Kamera zieht mit um"
        board.insert_mime(QApplication.clipboard().mimeData(), QPointF(900, 0))  # nochmal einfügen = Kopie
        items = h.sc.note_by_id(other.id).board["items"]
        assert len(items) == 6 and sum(1 for e in items if e.get("hero")) == 1, "zweites Einfügen: Kopie ohne Hero"
        h.sc.undo()
        h.sc.undo()
        h.sc.undo()
        assert len(h.sc.note_by_id(note.id).board["items"]) == 3, "Undo holt das Ausgeschnittene zurück"
    finally:
        _close(h, board)


def test_tastenkuerzel_im_brett(h: H):
    from PySide6.QtTest import QTest
    note, other, board, (a, b) = _filled_board(h)
    try:
        board.gscene.clearSelection()
        a.setSelected(True)
        board.view.setFocus()
        QTest.keyClick(board.view, Qt.Key_C, Qt.ControlModifier)
        mime = QApplication.clipboard().mimeData()
        assert mime.hasFormat(BOARD_MIME) and mime.hasImage(), "ein Bild: auch als Bild für andere Programme"
        board.open(h.v, other.id)
        h.pump(0.05)
        board.view.setFocus()
        QTest.keyClick(board.view, Qt.Key_V, Qt.ControlModifier)
        assert len(_images(board)) == 1, "Strg+V fügt das kopierte Bild ein"
    finally:
        _close(h, board)

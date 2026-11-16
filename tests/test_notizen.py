"""Notizen: Kamera-Knopf (Ansicht als Bild ins Notizbrett, mit Rückflug) und Malen im Brett."""
import json
import math
import os
import tempfile

import numpy as np
from PySide6.QtCore import QPointF
from PySide6.QtGui import QImage

from tests.harness import H
from tests.test_material import _square
from sketch_machine.scene import Note, Scene


def _note_scene(h: H):
    h.new_scene()
    _square(h, y=0.0, x0=-1.0, size=2.0)
    note = Note("Sitz", np.array([0.5, 0.8, 0.0]))
    h.sc.notes.append(note)
    h.v.set_notes_mode(True)
    h.v.ws.active_note = note.id
    h.camera([0.0, 0.0, 0.5], 6, [0.3, 0.8, 0.5])
    return note


def test_kamera_knopf_fuegt_saubere_ansicht_mit_kamera_ein(h: H):
    """Klick aufs Kamera-Symbol der Notiz: Bild der Ansicht im Brett (ohne Bedienelemente), mit der Kamera;
    ein Undo-Schritt, wird gespeichert."""
    note = _note_scene(h)
    try:
        h.grab()
        icons = h.v.notes_tool._screen[note.id]["icons"]
        assert "cam" in icons, f"kein Kamera-Knopf an der Notiz ({sorted(icons)})"
        state = h.v.cam.state()
        h.click(icons["cam"])
        items = [it for it in note.board.get("items", []) if it.get("kind") == "image"]
        assert len(items) == 1, f"{len(items)} Bilder im Brett statt 1"
        item = items[0]
        data = h.sc.asset_bytes(item["file"])
        img = QImage.fromData(data)
        assert not img.isNull() and img.width() > 100, "Bild lesbar"
        assert np.allclose(item["view"]["target"], state[0], atol=1e-4) and abs(item["view"]["dist"] - state[1]) < 1e-4
        assert not getattr(h.v, "_clean_frame", False) and h.v.notes_mode, "Ansicht danach wie vorher"
        # sauber: dasselbe Bild wie die Ansicht ohne Notizen/Modus (Notiz-Überschrift nicht im Bild)
        clean = h.v.clean_image()
        shown = h.grab()
        assert h.diff(clean, shown) > 0, "im Bild fehlen die Bedienelemente (Notiz, Achsenkreuz)"
        h.v.ws.planes_visible = False
        try:
            assert h.diff(clean, h.v.clean_image()) == 0, "Zeichenhilfen (Ebenen, Achsenkreuz) nie im Bild"
        finally:
            h.v.ws.planes_visible = True
        path = os.path.join(tempfile.mkdtemp(), "notiz.sketch.json")
        h.sc.save(path)
        loaded = Scene.load(path)[0]
        again = [it for it in loaded.notes[0].board["items"] if it.get("kind") == "image"][0]
        assert again.get("view") == item["view"], "Kamera am Bild wird gespeichert"
        assert loaded.asset_bytes(again["file"]), "Bild wird gespeichert"
        h.sc.undo()
        note2 = h.sc.note_by_id(note.id)
        assert not note2.board.get("items"), "Strg+Z nimmt das Bild wieder heraus"
    finally:
        h.v.set_notes_mode(False)


def test_doppelklick_aufs_bild_fliegt_in_die_ansicht_zurueck(h: H):
    from sketch_machine.note_board import camera_view, fly_to_view
    _note_scene(h)
    try:
        view = camera_view(h.v)
        h.camera([3.0, 1.0, -2.0], 12, [-0.6, 0.3, 0.7])
        fly_to_view(h.v, view)
        h.pump(0.6)
        target, dist, rot = h.v.cam.state()
        assert np.allclose(target, view["target"], atol=1e-4) and abs(dist - view["dist"]) < 1e-4
        assert np.allclose(rot, view["rot"], atol=1e-4)
    finally:
        h.v.set_notes_mode(False)


def _board_send(h: H, board, kind, scene_pt, buttons, button=None, mods=None):
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QMouseEvent
    pos = QPointF(board.view.mapFromScene(scene_pt))
    if button is None:
        button = Qt.LeftButton if kind != QEvent.MouseMove else Qt.NoButton
    h.app.sendEvent(board.view.viewport(), QMouseEvent(kind, pos, board.view.mapToGlobal(pos.toPoint()), button,
                                                       buttons, mods if mods is not None else Qt.NoModifier))


def _board_drag(h: H, board, a, b, steps=12, path=None, mods=None, release=True):
    """Linke Maustaste im Brett von a nach b ziehen (Brett-Koordinaten); path: Zwischenpunkte statt der Geraden."""
    from PySide6.QtCore import QEvent, Qt
    _board_send(h, board, QEvent.MouseButtonPress, a, Qt.LeftButton, mods=mods)
    pts = path if path is not None else [a + (b - a) * float(t) for t in np.linspace(0, 1, steps)[1:]]
    for p in pts:
        _board_send(h, board, QEvent.MouseMove, p, Qt.LeftButton, mods=mods)
    if release:
        _board_send(h, board, QEvent.MouseButtonRelease, b, Qt.NoButton, mods=mods)
        _settle(board)


def _settle(board):
    """Pause nach dem Malen abwarten (SETTLE_MS): wartende Striche in die Notiz, Verbindung zeigen."""
    if board._settle_timer.isActive():
        board._settle_timer.stop()
        board._settle()


def _open_board(h: H):
    from sketch_machine.note_board import board_for
    note = _note_scene(h)
    board = board_for(h.v)
    board.open(h.v, note.id)
    h.pump(0.05)
    return note, board


def _close(h: H, board):
    if board.isVisible():
        board.close_board()
    h.v.set_notes_mode(False)


def test_schreibschrift_im_brett_folgt_fluessig(h: H):
    """Beim Malen liegt die Tinte auf einer eigenen Ebene: sichtbar schon während des Strichs, Bruchteile von Pixeln
    bleiben erhalten, je Punkt kostet es unabhängig von der Länge gleich viel; danach ist es ein normaler Strich.
    Echte Ecken (Rechteck) bleiben im fertigen Strich scharf."""
    import time
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QImage, QMouseEvent, QPainter, QPainterPath
    from PySide6.QtWidgets import QApplication
    from sketch_machine.note_board import StrokeItem, _ink_paths
    note, board = _open_board(h)
    view = board.view
    vp = view.viewport()

    def send(kind, x, y, button=Qt.LeftButton, buttons=Qt.LeftButton):
        pos = QPointF(x, y)
        QApplication.sendEvent(vp, QMouseEvent(kind, pos, vp.mapToGlobal(pos), button, buttons, Qt.NoModifier))

    try:
        board.set_paint_tool("pen")
        h.pump(0.05)
        send(QEvent.MouseButtonPress, 80.25, 120.5)
        stroke = view._stroke
        assert stroke is not None and stroke.live and not stroke.isVisible(), "beim Malen: Tinte statt Element"
        times = []
        for i in range(1, 900):
            x, y = 80.25 + i * 0.5, 120.5 + 40 * math.sin(i * 0.05)
            t0 = time.perf_counter()
            send(QEvent.MouseMove, x, y)
            QApplication.processEvents()
            times.append(time.perf_counter() - t0)
        early, late = sorted(times[20:220])[100], sorted(times[-200:])[100]
        assert late < early * 3 + 0.002, f"Kosten hängen an der Strichlänge: {early * 1e3:.2f} -> {late * 1e3:.2f} ms"
        assert any(abs(p.x() - round(p.x())) > 0.01 for p in stroke.pts), "Stiftlage auf ganze Pixel gerundet"
        image = vp.grab().toImage()
        ink = view.mapFromScene(stroke.pts[len(stroke.pts) // 2])
        found = any(image.pixelColor(ink.x() + dx, ink.y() + dy) != image.pixelColor(5, 5)
                    for dx in (-1, 0, 1) for dy in (-1, 0, 1))
        assert found, "Tinte ist während des Strichs zu sehen"
        send(QEvent.MouseButtonRelease, 80.25 + 450, 120.5, buttons=Qt.NoButton)
        h.pump(0.05)
        assert view._stroke is None and view._ink is None and stroke.isVisible() and not stroke.live
        assert stroke.boundingRect().width() > 400, "Rahmen stimmt nach dem Strich"
        assert not note.board.get("items"), "Loslassen bleibt leicht: erst nach der Pause in die Notiz"
        assert board._settle_timer.isActive()
        h.pump(0.6)
        assert len(note.board.get("items", [])) >= 1, "nach der Pause in der Notiz"
        # Rechteck-Ecke: der Pfad läuft durch den Eckpunkt, Schreibschrift dagegen als Bogen vorbei
        square = [QPointF(0, 0), QPointF(100, 0), QPointF(100, 100)]
        path = _ink_paths(square, [2.0] * 3)[0][0]
        assert path.intersects(QPainterPath(QPointF(100, 0)).boundingRect().adjusted(-0.5, -0.5, 0.5, 0.5)), \
            "Ecke bleibt scharf"
    finally:
        board.set_paint_tool(None)
        if board.isVisible():
            board.close_board()
        h.v.set_notes_mode(False)


def test_im_brett_malen_radieren_und_als_bild_exportieren(h: H):
    """A: Stift malt im Brett (gespeichert in der Notiz), D: Radierer teilt den Strich, eigene Stiftfarbe des
    Bretts; das Brett lässt sich als ein Bild rendern (Brief)."""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from sketch_machine.note_board import StrokeItem, render_board
    note, board = _open_board(h)
    try:
        QTest.keyClick(board.view, Qt.Key_A)
        assert board.paint_tool == "pen", board.paint_tool
        _board_drag(h, board, QPointF(-200, 0), QPointF(200, 0))
        strokes = [i for i in board.gscene.items() if isinstance(i, StrokeItem)]
        assert len(strokes) == 1 and len(strokes[0].pts) > 5, "ein Strich mit Punkten"
        assert strokes[0].style == "pen" and strokes[0].color is None, "ohne Farbwahl: Tinte"
        assert len(note.board.get("items", [])) == 1, "jeder Strich landet sofort in der Notiz"
        QTest.keyClick(board.view, Qt.Key_D)
        assert board.paint_tool == "eraser"
        _board_drag(h, board, QPointF(0, -40), QPointF(0, 40), steps=6)
        strokes = [i for i in board.gscene.items() if isinstance(i, StrokeItem)]
        assert len(strokes) == 2, f"Radierer teilt den Strich in zwei ({len(strokes)})"
        h.v.ws.paint_color = (0.1, 0.1, 0.9)  # die Farbe des 3D-Views gilt im Brett nicht
        board.set_pen_color((0.8, 0.2, 0.1))
        assert board.paint_tool == "pen", "Farbe wählen schaltet den Stift ein"
        _board_drag(h, board, QPointF(-100, 120), QPointF(100, 160))
        QTest.keyClick(board.view, Qt.Key_Escape)
        assert board.paint_tool is None, "Esc: Malen aus (Brett bleibt offen)"
        assert board.isVisible()
        board.close_board()
        items = [it for it in note.board["items"] if it["kind"] == "stroke"]
        assert len(items) == 3, f"{len(items)} Striche in der Notiz"
        colored = [it for it in items if it.get("color")]
        assert len(colored) == 1 and colored[0]["color"] == [0.8, 0.2, 0.1] and colored[0]["style"] == "pen"
        img = render_board(h.sc, note.board)
        assert img is not None and img.width() > 100
        path = os.path.join(tempfile.mkdtemp(), "malen.sketch.json")
        h.sc.save(path)
        again = Scene.load(path)[0].notes[0].board["items"]
        assert [it for it in again if it["kind"] == "stroke"] == items, "Striche werden gespeichert"
    finally:
        h.v.ws.board_color = None
        _close(h, board)


def test_notiz_und_hinweislinie_werden_von_flaechen_verdeckt(h: H):
    """Notizen und ihre Hinweislinien: von Flächen verdeckte Teile fehlen wie bei Linien; X-Ray zeigt alles."""
    from sketch_machine.scene import NoteAnchor
    h.new_scene()
    _square(h, y=0.0, x0=-3.0, size=6.0)
    note = Note("Sitz", np.array([0.0, 0.8, 3.0]))
    note.anchors.append(NoteAnchor(np.array([0.5, 0.0, 3.5])))
    h.sc.notes.append(note)
    try:
        h.camera([0.0, 0.4, 3.0], 9, [0.2, 0.9, 0.3])  # von oben
        h.grab()
        box, leads = h.v.notes_tool.occlusion[note.id]
        assert box.mean() > 0.95 and leads[0].mean() > 0.9 and leads[0][-1], (box.mean(), leads[0].mean())
        assert box.all(), box.mean()
        # ganz sichtbar: genau wie ohne Verdeckung gezeichnet (Klammern nicht beschnitten)
        seen = h.grab()
        tool = h.v.notes_tool
        tool.visibility = lambda _fn: {}
        try:
            plain = h.grab()
        finally:
            del tool.visibility
        assert h.diff(seen, plain, step=1, threshold=0) == 0, "Schild wird beschnitten, obwohl alles sichtbar ist"
        h.camera([0.0, 0.4, 3.0], 9, [0.2, -0.9, 0.3])  # von unten: das Quadrat liegt davor
        h.grab()
        box, leads = h.v.notes_tool.occlusion[note.id]
        assert box.mean() < 0.2 and leads[0].mean() < 0.2, (box.mean(), leads[0].mean())
        shown = h.grab()
        h.v.set_xray(True)
        xray = h.grab()
        assert h.v.notes_tool.occlusion is None, "X-Ray: nichts verdeckt"
        assert h.diff(shown, xray) > 0
    finally:
        h.v.set_xray(False)


def test_bilder_liegen_hinter_den_strichen(h: H):
    """Ein später eingefügtes Bild liegt trotzdem unter den Strichen (darauf wird gezeichnet); gespeichert in
    dieser Reihenfolge."""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from sketch_machine.note_board import ImageItem, StrokeItem
    note, board = _open_board(h)
    try:
        QTest.keyClick(board.view, Qt.Key_A)
        _board_drag(h, board, QPointF(-50, 40), QPointF(250, 40))
        board.set_paint_tool(None)
        board.add_snapshot()
        img = [i for i in board.gscene.items() if isinstance(i, ImageItem)][0]
        stroke = [i for i in board.gscene.items() if isinstance(i, StrokeItem)][0]
        assert img.zValue() < stroke.zValue()
        assert [it["kind"] for it in note.board["items"]] == ["image", "stroke"]
    finally:
        _close(h, board)


def test_fehlende_screenshots_neu_aufnehmen(h: H):
    """Bilddatei verloren: Screenshots mit Kamera werden aus ihr neu aufgenommen – Lage, Größe und die eigene
    Kamera bleiben; ein Undo-Schritt."""
    from sketch_machine.note_board import ImageItem, board_for, camera_view
    note = _note_scene(h)
    board = board_for(h.v)
    try:
        view = camera_view(h.v)
        note.board = {"items": [{"kind": "image", "x": 10.0, "y": 20.0, "scale": 0.4, "file": "weg.jpg", "view": view},
                                {"kind": "image", "x": 600.0, "y": 20.0, "scale": 1.0, "file": "ref.png"}]}
        h.camera([3.0, 1.0, -2.0], 12, [-0.6, 0.3, 0.7])
        state = h.v.cam.state()
        board.open(h.v, note.id)
        h.pump(0.05)
        assert board.retake_button.isVisibleTo(board), "Knopf erscheint, wenn Screenshots fehlen"
        board.retake_missing()
        shot, ref = sorted((i for i in board.gscene.items() if isinstance(i, ImageItem)), key=lambda i: i.x())
        assert not shot.missing and ref.missing, "nur der Screenshot (mit Kamera) lässt sich neu aufnehmen"
        assert shot.pixmap().width() > 200 and h.sc.asset_bytes(shot.file)
        item = note.board["items"][0]
        assert (item["x"], item["y"], item["scale"]) == (10.0, 20.0, 0.4) and item["file"] == shot.file
        assert np.allclose(h.v.cam.state()[0], state[0]) and abs(h.v.cam.state()[1] - state[1]) < 1e-9
        assert board.retake_button.isVisibleTo(board), "bleibt: nimmt dann alle Screenshots neu auf"
        h.sc.undo()
        assert h.sc.note_by_id(note.id).board["items"][0]["file"] == "weg.jpg"
    finally:
        _close(h, board)


def test_screenshot_neu_im_alten_format(h: H):
    """↻ an einem Screenshot: gleiche Kamera im Seitenverhältnis des alten Bilds (breiter und schmaler als der
    Viewport), Bild bleibt gleich breit an derselben Stelle; X-Ray wie eingestellt, nichts am Bild gemerkt."""
    from PySide6.QtCore import QBuffer, QIODevice
    from PySide6.QtGui import QImage
    from sketch_machine.note_board import ImageItem, board_for, camera_view
    note = _note_scene(h)
    board = board_for(h.v)
    try:
        def jpg(w, hgt):
            img, buf = QImage(w, hgt, QImage.Format_RGB32), QBuffer()
            img.fill(0x808080)
            buf.open(QIODevice.WriteOnly)
            img.save(buf, "JPG")
            return bytes(buf.data())
        view = camera_view(h.v)
        h.sc.assets["breit.jpg"], h.sc.assets["hoch.jpg"] = jpg(1600, 500), jpg(400, 800)
        note.board = {"items": [{"kind": "image", "x": 0.0, "y": 0.0, "scale": 0.5, "file": "breit.jpg", "view": view},
                                {"kind": "image", "x": 0.0, "y": 600.0, "scale": 1.0, "file": "hoch.jpg",
                                 "view": view}]}
        board.open(h.v, note.id)
        h.pump(0.05)
        shots = sorted((i for i in board.gscene.items() if isinstance(i, ImageItem)), key=lambda i: i.y())
        before = [i.sceneBoundingRect() for i in shots]
        xray = h.v.ws.xray
        for item in shots:
            board.retake_item(item)
        for item, rect, aspect in zip(shots, before, (3.2, 0.5)):
            pm = item.pixmap()
            assert abs(pm.width() / pm.height() - aspect) < 0.02, (pm.width(), pm.height())
            now = item.sceneBoundingRect()
            assert abs(now.left() - rect.left()) < 0.5 and abs(now.top() - rect.top()) < 0.5
            assert abs(now.width() / rect.width() - 1) < 0.01, (now, rect)
        assert h.v.ws.xray == xray and h.v._fov_zoom == 1.0
        assert "xray" not in note.board["items"][0]["view"]
    finally:
        _close(h, board)


def test_geloeschte_bilder_verschwinden_aus_der_datei(h: H):
    import json
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from sketch_machine.note_board import ImageItem
    note, board = _open_board(h)
    try:
        board.add_snapshot()
        board.add_snapshot()
        path = os.path.join(tempfile.mkdtemp(), "bilder.sketch.json")
        h.sc.save(path)
        with open(path, encoding="utf-8") as f:
            assert len(json.load(f)["assets"]) >= 1
        for i in board.gscene.items():
            i.setSelected(isinstance(i, ImageItem))
        QTest.keyClick(board.view, Qt.Key_Delete)
        h.sc.save(path)
        with open(path, encoding="utf-8") as f:
            assert json.load(f)["assets"] == {}, "gelöschte Bilder werden nicht mehr gespeichert"
    finally:
        _close(h, board)


def test_brett_strg_shift_radiert_ganze_striche(h: H):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from sketch_machine.note_board import StrokeItem
    note, board = _open_board(h)
    try:
        QTest.keyClick(board.view, Qt.Key_A)
        _board_drag(h, board, QPointF(-200, 0), QPointF(200, 0))
        _board_drag(h, board, QPointF(-200, 100), QPointF(200, 100))
        QTest.keyClick(board.view, Qt.Key_D)
        _board_drag(h, board, QPointF(0, -20), QPointF(0, 20), steps=4, mods=Qt.ControlModifier | Qt.ShiftModifier)
        strokes = [i for i in board.gscene.items() if isinstance(i, StrokeItem)]
        assert len(strokes) == 1 and strokes[0].pts[0].y() > 50, "der getroffene Strich ist ganz weg, der andere bleibt"
    finally:
        _close(h, board)


def test_brett_undo_redo_in_derselben_history(h: H):
    """Strg+Z/Strg+Y im Brett: Schritt für Schritt, gemeinsam mit dem 3D-View; das Brett zeigt den Stand."""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from sketch_machine.note_board import StrokeItem
    note, board = _open_board(h)
    try:
        QTest.keyClick(board.view, Qt.Key_A)
        _board_drag(h, board, QPointF(-200, 0), QPointF(200, 0))
        _board_drag(h, board, QPointF(-200, 100), QPointF(200, 100))
        count = lambda: len([i for i in board.gscene.items() if isinstance(i, StrokeItem)])
        assert count() == 2
        board.view.scale(1.7, 1.7)
        zoom = board.view.transform().m11()
        QTest.keyClick(board.view, Qt.Key_Z, Qt.ControlModifier)
        assert count() == 1 and len(h.sc.note_by_id(note.id).board["items"]) == 1, "Strg+Z nimmt den letzten Strich"
        assert abs(board.view.transform().m11() - zoom) < 1e-6, "Ansicht bleibt beim Undo"
        assert board.isVisible(), "Strg+Z schließt das Brett nicht"
        QTest.keyClick(board.view, Qt.Key_Y, Qt.ControlModifier)
        assert count() == 2, "Strg+Y holt ihn zurück"
        QTest.keyClick(board.view, Qt.Key_Z, Qt.ControlModifier | Qt.ShiftModifier)
        QTest.keyClick(board.view, Qt.Key_Z, Qt.ControlModifier | Qt.ShiftModifier)
        assert count() == 2, "Strg+Shift+Z = Wiederholen (nichts mehr da)"
        QTest.keyClick(board.view, Qt.Key_Z, Qt.ControlModifier)
        QTest.keyClick(board.view, Qt.Key_Z, Qt.ControlModifier)
        assert count() == 0
    finally:
        _close(h, board)


def test_brett_undo_beim_schreiben_verliert_nichts(h: H):
    """Text wird gerade geschrieben, dann Undo (Knopf/Menü): der Text ist ein eigener Schritt, das Leeren des
    Bretts schreibt keinen halben Stand in die Notiz."""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from sketch_machine.note_board import TextBlock
    note, board = _open_board(h)
    try:
        QTest.keyClick(board.view, Qt.Key_A)
        _board_drag(h, board, QPointF(-200, 0), QPointF(200, 0))
        board.set_paint_tool(None)
        block = board.add_text(QPointF(0, 200), edit=True)
        QTest.keyClicks(board.view, "Sitz 45")  # nur ASCII: QTest.keyClicks stuerzt bei Umlauten ab
        assert "Sitz 45" in block.toPlainText()
        board.undo()
        items = h.sc.note_by_id(note.id).board["items"]
        assert [it["kind"] for it in items] == ["stroke"], items
        assert not [i for i in board.gscene.items() if isinstance(i, TextBlock)]
        board.undo(redo=True)
        assert [it.get("text") for it in h.sc.note_by_id(note.id).board["items"]] == [None, "Sitz 45"]
    finally:
        _close(h, board)


def test_strg_v_im_brett_fuegt_bild_ein_nicht_die_3d_zwischenablage(h: H):
    """Strg+V auf dem Brett: das Bild aus der Zwischenablage (vorher griff das Einfügen des Hauptfensters)."""
    from PySide6.QtCore import QMimeData, Qt
    from PySide6.QtGui import QColor
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from sketch_machine.note_board import ImageItem
    clip = QApplication.clipboard()
    saved = QMimeData()  # Zwischenablage hinterher wiederherstellen
    for f in clip.mimeData().formats():
        saved.setData(f, clip.mimeData().data(f))
    note, board = _open_board(h)
    try:
        img = QImage(64, 48, QImage.Format_RGB32)
        img.fill(QColor(200, 80, 40))
        clip.setImage(img)
        h.pump(0.05)
        curves = len(h.curves())
        QTest.keyClick(board.view, Qt.Key_V, Qt.ControlModifier)
        images = [i for i in board.gscene.items() if isinstance(i, ImageItem)]
        assert len(images) == 1, f"{len(images)} Bilder im Brett"
        assert len(h.curves()) == curves, "keine Linien in die Szene eingefügt"
        item = note.board["items"][0]
        assert item["kind"] == "image" and item["file"].endswith(".jpg"), "ohne Transparenz als JPEG gespeichert"
    finally:
        clip.setMimeData(saved)
        _close(h, board)


def test_bild_link_aus_dem_web_wird_geladen(h: H):
    """Liegt nur ein Link (HTML mit <img>) in der Zwischenablage, lädt das Brett das Bild."""
    import functools
    import http.server
    import threading
    from PySide6.QtCore import QMimeData
    from PySide6.QtGui import QColor
    from sketch_machine.note_board import ImageItem
    folder = tempfile.mkdtemp()
    img = QImage(40, 30, QImage.Format_ARGB32)
    img.fill(QColor(20, 120, 220, 128))
    img.save(os.path.join(folder, "bild.png"))
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=folder)
    handler.log_message = lambda *a: None
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    note, board = _open_board(h)
    try:
        mime = QMimeData()
        mime.setHtml(f'<html><body><img src="http://127.0.0.1:{server.server_port}/bild.png"/></body></html>')
        board.insert_mime(mime, QPointF(0, 0))
        images = [i for i in board.gscene.items() if isinstance(i, ImageItem)]
        assert len(images) == 1 and images[0].pixmap().width() == 40
        assert note.board["items"][0]["file"].endswith(".png"), "Transparenz bleibt (PNG)"
    finally:
        server.shutdown()
        _close(h, board)


def test_brett_formerkennung_kreis_und_gerade(h: H):
    """Wie im 3D-View: am Strichende stillhalten -> Kreis (Größe folgt der Maus) bzw. Gerade."""
    import math
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtTest import QTest
    from sketch_machine.note_board import StrokeItem
    note, board = _open_board(h)
    try:
        QTest.keyClick(board.view, Qt.Key_A)
        ring = [QPointF(100 * math.cos(a), 100 * math.sin(a) * 0.95) for a in np.linspace(0, 2 * math.pi * 0.97, 40)]
        _board_drag(h, board, ring[0], ring[-1], path=ring[1:], release=False)
        board.view._recognize()  # Stillhalten
        assert board.view._shape is not None and board.view._shape["kind"] == "circle", board.view._shape
        _board_send(h, board, QEvent.MouseMove, QPointF(150, 0), Qt.LeftButton)
        _board_send(h, board, QEvent.MouseButtonRelease, QPointF(150, 0), Qt.NoButton)
        stroke = [i for i in board.gscene.items() if isinstance(i, StrokeItem)][0]
        r = [math.hypot(p.x(), p.y()) for p in stroke.pts]
        assert abs(min(r) - 150) < 3 and abs(max(r) - 150) < 3, f"Kreis mit Radius 150 ({min(r):.1f}…{max(r):.1f})"
        wobble = [QPointF(x, 200 + 8 * math.sin(x / 20)) for x in np.linspace(-200, 200, 30)]
        _board_drag(h, board, wobble[0], wobble[-1], path=wobble[1:], release=False)
        board.view._recognize()
        _board_send(h, board, QEvent.MouseMove, QPointF(250, 240), Qt.LeftButton)
        _board_send(h, board, QEvent.MouseButtonRelease, QPointF(250, 240), Qt.NoButton)
        line = [i for i in board.gscene.items() if isinstance(i, StrokeItem) and i is not stroke][0]
        assert len(line.pts) == 2 and line.pts[-1] == QPointF(250, 240), "Gerade bis zum Cursor"
    finally:
        _close(h, board)


def test_brett_griffe_skalieren_bild_und_text(h: H):
    """Gewähltes Bild an der Ecke ziehen: skaliert, die gegenüberliegende Ecke bleibt stehen (wie PureRef)."""
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QColor
    note, board = _open_board(h)
    try:
        img = QImage(200, 100, QImage.Format_RGB32)
        img.fill(QColor(90, 90, 90))
        from PySide6.QtCore import QBuffer, QIODevice
        buf = QBuffer()
        buf.open(QIODevice.WriteOnly)
        img.save(buf, "PNG")
        for item in (board.add_image(bytes(buf.data()), ".png", QPointF(0, 0)),
                     board.add_text(QPointF(0, 300), "Hallo")):
            board.gscene.clearSelection()
            item.setSelected(True)
            rect = item.sceneBoundingRect()
            fixed, corner = rect.topLeft(), rect.bottomRight()
            target = fixed + (corner - fixed) * 2.0
            _board_drag(h, board, corner, target, steps=8)
            new = item.sceneBoundingRect()
            assert abs(item.scale() - 2.0) < 0.05, f"Faktor 2 ({item.scale():.3f})"
            assert (new.topLeft() - fixed).manhattanLength() < 1.0, "die gegenüberliegende Ecke bleibt"
        items = note.board["items"]
        assert [round(it.get("scale", 1.0), 1) for it in items] == [2.0, 2.0], items
    finally:
        _close(h, board)


def test_brett_alt_rechte_maustaste_zoomt(h: H):
    from PySide6.QtCore import QEvent, Qt
    note, board = _open_board(h)
    try:
        start = board.view.mapToScene(board.view.viewport().rect().center())
        zoom = board.view.transform().m11()
        alt = Qt.AltModifier
        _board_send(h, board, QEvent.MouseButtonPress, start, Qt.RightButton, Qt.RightButton, alt)
        view_pt = board.view.mapFromScene(start)
        for dx in range(10, 110, 10):
            pos = QPointF(view_pt.x() + dx, view_pt.y())
            h.app.sendEvent(board.view.viewport(), __import__("PySide6.QtGui", fromlist=["QMouseEvent"]).QMouseEvent(
                QEvent.MouseMove, pos, board.view.mapToGlobal(pos.toPoint()), Qt.NoButton, Qt.RightButton, alt))
        _board_send(h, board, QEvent.MouseButtonRelease, start, Qt.NoButton, Qt.RightButton, alt)
        assert board.view.transform().m11() > zoom * 1.5, "nach rechts ziehen zoomt hinein"
        back = board.view.mapToScene(view_pt)
        assert (back - start).manhattanLength() < 2.0, "der Ansatzpunkt bleibt unter dem Cursor"
    finally:
        _close(h, board)


def test_bilder_stehen_in_der_szenendatei(h: H):
    """Bilder der Bretter werden in der Szenendatei gespeichert (kein Ordner daneben); ältere Szenen mit Ordner
    laden weiter und betten die Bilder beim Speichern ein."""
    import json
    import shutil
    note = _note_scene(h)
    try:
        img = QImage(30, 20, QImage.Format_RGB32)
        img.fill(0xff336699)
        from PySide6.QtCore import QBuffer, QIODevice
        buf = QBuffer()
        buf.open(QIODevice.WriteOnly)
        img.save(buf, "PNG")
        data = bytes(buf.data())
        h.sc.assets["bild.png"] = data
        note.board = {"items": [{"kind": "image", "x": 0, "y": 0, "scale": 1.0, "file": "bild.png"}]}
        folder = tempfile.mkdtemp()
        path = os.path.join(folder, "eingebettet.sketch.json")
        h.sc.save(path)
        assert not os.path.exists(Scene.assets_dir_for(path)), "kein Bilder-Ordner neben der Szene"
        moved = os.path.join(tempfile.mkdtemp(), "verschoben.sketch.json")
        shutil.move(path, moved)
        assert Scene.load(moved)[0].asset_bytes("bild.png") == data, "Bild steckt in der Datei"
        # ältere Szene: Bild im Ordner daneben, nicht in der Datei
        with open(moved, encoding="utf-8") as f:
            raw = json.load(f)
        raw.pop("assets")
        old = os.path.join(folder, "alt.sketch.json")
        with open(old, "w", encoding="utf-8") as f:
            json.dump(raw, f)
        os.makedirs(Scene.assets_dir_for(old))
        with open(os.path.join(Scene.assets_dir_for(old), "bild.png"), "wb") as f:
            f.write(data)
        scene = Scene.load(old)[0]
        assert scene.asset_bytes("bild.png") == data, "ältere Szene liest den Ordner"
        again = os.path.join(tempfile.mkdtemp(), "neu.sketch.json")
        scene.save(again)
        assert Scene.load(again)[0].asset_bytes("bild.png") == data, "beim Speichern eingebettet"
    finally:
        h.v.set_notes_mode(False)


def test_brief_nennt_screenshot_kamera_und_brett_bild(h: H):
    """Brief-Export: Screenshot mit Kamera, gemalte Striche gezählt, das ganze Brett als Bild."""
    from sketch_machine import brief
    note = _note_scene(h)
    try:
        h.grab()
        h.click(h.v.notes_tool._screen[note.id]["icons"]["cam"])
        note.board["items"].append({"kind": "stroke", "style": "pen", "pts": [[0, 600], [300, 640]], "w": [3, 3]})
        folder = tempfile.mkdtemp()
        files = brief.export(h.sc, h.v, folder, "notiz")
        md = open(os.path.join(folder, "brief.md"), encoding="utf-8").read()
        assert "viewport screenshot" in md and "camera at" not in md, "Screenshot im Brief, Kamera nur im JSON"
        data = json.load(open(os.path.join(folder, "brief.json"), encoding="utf-8"))
        assert data["notes"][0]["screenshots"][0]["camera"]["eye"], "Kamera des Screenshots in brief.json"
        assert "notes/board_N1.png" in files and os.path.isfile(os.path.join(folder, "notes", "board_N1.png"))
        assert "1 hand-drawn marks on the images" in md or "1 hand-drawn strokes not clearly connected" in md, md
    finally:
        h.v.set_notes_mode(False)


def _png(w, h_, color=0x6080a0):
    from PySide6.QtCore import QBuffer, QIODevice
    img, buf = QImage(w, h_, QImage.Format_RGB32), QBuffer()
    img.fill(color)
    buf.open(QIODevice.WriteOnly)
    img.save(buf, "PNG")
    return bytes(buf.data())


def test_bildunterschrift_im_brett_und_brief(h: H):
    """Bildunterschrift: graue Zeile unter dem Bild (Rahmen und Pfeilspitze beziehen sich weiter aufs Bild), gespeichert
    in der Notiz, gilt für dasselbe Bild in allen Notizen (ein Undo-Schritt); der Brief zeigt sie hinter dem Bild und
    nennt Referenzbilder ohne Unterschrift als offenen Punkt – Screenshots nicht."""
    from sketch_machine import brief
    from sketch_machine.note_board import set_image_captions
    note, board = _open_board(h)
    try:
        ref = board.add_image(_png(300, 200), ".png", QPointF(0, 0))
        board.add_snapshot()
        board.commit()
        other = Note("Hülle", np.array([0.0, 0.0, 0.0]))
        other.board = {"items": [{"kind": "image", "x": 0, "y": 0, "scale": 1.0, "file": ref.file}]}
        h.sc.notes.append(other)
        folder = tempfile.mkdtemp()
        brief.export(h.sc, h.v, folder, "notiz")
        md = open(os.path.join(folder, "brief.md"), encoding="utf-8").read()
        assert "N1 Sitz: 1 reference picture(s) without a caption" in md, "Screenshot zählt nicht mit"
        assert "N2 Hülle: 1 reference picture(s) without a caption" in md
        project = open(os.path.join(folder, "project.md"), encoding="utf-8").read()  # erste Runde (Paket v4)
        assert "the hero pictures `views/hero_*.png`" in project and "**Picture list**" in project
        assert "one line per reference picture once you opened it in full: the part ids it is about" in project
        assert "2 reference picture(s) have none: propose one each" in project
        tall = ref.boundingRect().height()
        assert set_image_captions(h.v, {f"notes/{ref.file}": " Sitz mit Gurten ", "gibts.png": "x"}) == ["gibts.png"]
        assert ref.caption == "Sitz mit Gurten" and ref.boundingRect().height() > tall + 5
        assert ref.image_rect().height() == 200, "das Bild selbst bleibt, die Zeile kommt darunter"
        assert [i.get("caption") for i in note.board["items"] if i["file"] == ref.file] == ["Sitz mit Gurten"]
        assert other.board["items"][0]["caption"] == "Sitz mit Gurten", "gilt für dasselbe Bild überall"
        brief.export(h.sc, h.v, folder, "notiz")
        md = open(os.path.join(folder, "brief.md"), encoding="utf-8").read()
        assert f"`notes/{ref.file}` – „Sitz mit Gurten“" in md and "picture(s) without a caption" not in md
        data = json.load(open(os.path.join(folder, "brief.json"), encoding="utf-8"))
        assert data["notes"][0]["captions"] == {f"notes/{ref.file}": "Sitz mit Gurten"}
        h.v.undo()
        h.pump(0.05)
        boards = lambda: json.dumps([n.board for n in h.sc.notes])  # Undo tauscht die Notiz-Objekte aus
        assert "caption" not in boards(), "ein Undo-Schritt für alle Notizen"
        h.v.redo()
        h.pump(0.05)
        base = tempfile.mkdtemp()
        again = Scene.from_dict(h.sc.to_dict(base), base)
        assert again.notes[1].board["items"][0]["caption"] == "Sitz mit Gurten"
        set_image_captions(h.v, {ref.file: ""})
        assert "caption" not in boards(), "leer entfernt sie"
    finally:
        _close(h, board)


def test_bildunterschrift_mit_teilen(h: H):
    """Unterschrift mit Teilen (harte Verbindung Bild ↔ Bauteil): gespeichert als Objekt-ids am Bild (offenes Brett
    und Szenendatei), Text ändern behält sie, leer entfernt sie mit; der Brief nennt sie hinter dem Bild
    („→ parts S1“) und part_notes das Bild am Teil."""
    from sketch_machine import brief
    from sketch_machine.note_board import set_image_captions
    note, board = _open_board(h)
    try:
        ref = board.add_image(_png(300, 200), ".png", QPointF(0, 0))
        board.commit()
        sid = next(iter(brief.index(h.sc)[1]["sid"].items()))
        set_image_captions(h.v, {ref.file: "Sitzschale"}, {ref.file: [sid[0]]})
        assert ref.caption_parts == [sid[0]]
        assert [i.get("caption_parts") for i in note.board["items"] if i["file"] == ref.file] == [[sid[0]]]
        set_image_captions(h.v, {ref.file: "Sitzschale von vorn"})
        assert ref.caption_parts == [sid[0]], "ohne parts bleiben die Teile"
        folder = tempfile.mkdtemp()
        brief.export(h.sc, h.v, folder, "notiz")
        md = open(os.path.join(folder, "brief.md"), encoding="utf-8").read()
        assert f"`notes/{ref.file}` – „Sitzschale von vorn“ → parts {sid[1]}" in md
        data = json.load(open(os.path.join(folder, "brief.json"), encoding="utf-8"))
        assert data["notes"][0]["caption_parts"] == {f"notes/{ref.file}": [sid[1]]}
        pn = next(e for e in data["part_notes"] if e["part"] == sid[1])
        assert pn["pictures"] == [f"notes/{ref.file}"]
        base = tempfile.mkdtemp()
        again = Scene.from_dict(h.sc.to_dict(base), base)
        assert again.notes[0].board["items"][-1]["caption_parts"] == [sid[0]]
        set_image_captions(h.v, {ref.file: ""})
        assert ref.caption_parts == [] and "caption_parts" not in json.dumps(note.board), "leer entfernt die Teile mit"
    finally:
        _close(h, board)


def test_pfeil_im_brett_verbindet_beschriftung_und_screenshot(h: H):
    """Ein Strich von einer Beschriftung auf einen Screenshot ist eine Verbindung (Spitze: Stelle im Bild); das Brett
    zeigt sie nach dem Malen kurz an. Kreis auf dem Bild: Markierung; Bild -> Bild; kurze Striche zählen nicht."""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from sketch_machine import board_links
    from sketch_machine.note_board import StrokeItem
    note, board = _open_board(h)
    try:
        label = board.add_text(QPointF(0, 0), "Pilotensitz\nmit Gurten")
        img = board.add_snapshot()
        r, t = img.sceneBoundingRect(), label.sceneBoundingRect()
        QTest.keyClick(board.view, Qt.Key_A)
        start, tip = QPointF(t.right() - 5, t.center().y()), r.center()
        _board_drag(h, board, start, tip)
        stroke = [i for i in board.gscene.items() if isinstance(i, StrokeItem)][0]
        assert board.view._flash is stroke, "eben gemalter Strich zeigt seine Verbindung"
        link = board_links.stroke_link(board.gscene, stroke)
        assert link["kind"] == "link" and link["source"] is label and link["target"] is img, link
        assert abs(link["uv"][0] - 0.5) < 0.05 and abs(link["uv"][1] - 0.5) < 0.05, link["uv"]
        assert board_links.label_of(label) == "Pilotensitz"
        board.view._end_flash()
        assert board.view._flash is None
        c = r.center()  # Kreis auf dem Bild
        ring = [c + QPointF(40 * np.cos(a), 40 * np.sin(a)) for a in np.linspace(0, 2 * np.pi, 24)]
        _board_drag(h, board, ring[0], ring[-1], path=ring[1:])
        circle = board.view._flash
        mark = board_links.stroke_link(board.gscene, circle)
        assert mark["kind"] == "mark" and mark["target"] is img and mark["source"] is None, mark
        board.view._end_flash()
        _board_drag(h, board, c, c + QPointF(8, 3))  # Häkchen: keine Verbindung, keine Meldung
        assert board.view._flash is None
        far = QPointF(r.right() + 600, r.top())  # Schreiben/Kritzeln im Freien: still (Artist, 2026-11-07)
        _board_drag(h, board, far, far + QPointF(120, 10), path=[far + QPointF(60, 40)])
        loop = [far + QPointF(300 + 30 * np.cos(a), 30 * np.sin(a)) for a in np.linspace(0, 2 * np.pi, 16)]
        _board_drag(h, board, loop[0], loop[-1], path=loop[1:])
        assert board.view._flash is None, "nichts gefunden: keine Meldung „unklar“"
    finally:
        board.set_paint_tool(None)
        _close(h, board)


def test_brief_zerlegt_brett_in_abschnitte_mit_pfeilen(h: H):
    """Brief: Texte/Bilder, die nah beieinander liegen, bilden einen Abschnitt (eigenes Bild); Pfeile von einer
    Beschriftung auf ein Bild stehen nummeriert (P#) mit der Stelle im Bild darin; weit Entferntes ist ein eigener
    Abschnitt."""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from sketch_machine import brief
    note, board = _open_board(h)
    try:
        label = board.add_text(QPointF(0, 0), "Sitz")
        img = board.add_snapshot()
        img.setPos(label.sceneBoundingRect().right() + 40, 0)
        board.add_text(QPointF(0, 3000), "Ganz woanders")
        t, r = label.sceneBoundingRect(), img.sceneBoundingRect()
        QTest.keyClick(board.view, Qt.Key_A)
        _board_drag(h, board, QPointF(t.left() + 20, t.center().y()), r.center())
        board.set_paint_tool(None)
        board.commit()
        folder = tempfile.mkdtemp()
        files = brief.export(h.sc, h.v, folder, "abschnitte")
        md = open(os.path.join(folder, "brief.md"), encoding="utf-8").read()
        assert "**Section 1** – `notes/board_N1_1.png`" in md and "**Section 2**" in md, md
        assert "notes/board_N1_1.png" in files and os.path.isfile(os.path.join(folder, "notes", "board_N1_1.png"))
        assert "arrow **P1** „Sitz“ → screenshot" in md and "where exactly" not in md, md
        assert "- whole board: `notes/board_N1.png`" in md and "the section picture shows exactly where" in md
        assert brief._arrow_md({"id": "P2", "from": {"text": "Release Hebel: Wenn der Copilot an diesen Hebeln "
                                                             "zieht"}, "to": None}) == \
            "**P2** „Release Hebel: Wenn der Copilot an …“ → an empty spot", "lange Beschriftung an Wortgrenze gekürzt"
        data = json.load(open(os.path.join(folder, "brief.json"), encoding="utf-8"))
        arrow = data["notes"][0]["sections"][0]["arrows"][0]
        assert np.allclose(arrow["at"], [0.5, 0.5], atol=0.05), "Stelle im Bild steht im JSON (im md nur P# im Bild)"
        assert md.index("> Sitz") < md.index("> Ganz woanders")
    finally:
        board.set_paint_tool(None)
        _close(h, board)


def test_backdrop_fasst_zusammen_und_ist_im_brief_ein_abschnitt(h: H):
    """B / ▭: Backdrop um die Auswahl, Titel gleich schreibbar; verschieben nimmt den Inhalt mit, Ecke ziehen ändert
    die Größe; gespeichert und wieder geladen; im Brief ein Abschnitt mit dem Titel."""
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtTest import QTest
    from sketch_machine import brief
    from sketch_machine.note_board import BackdropItem
    note, board = _open_board(h)
    try:
        label = board.add_text(QPointF(0, 0), "Sitz")
        img = board.add_snapshot()
        img.setPos(label.sceneBoundingRect().right() + 300, 0)  # weit weg: nach Nähe wären es zwei Abschnitte
        board.add_text(QPointF(0, 3000), "Draussen")
        label.setSelected(True)
        img.setSelected(True)
        QTest.keyClick(board.view, Qt.Key_B)
        drop = [i for i in board.gscene.items() if isinstance(i, BackdropItem)][0]
        assert board.view.editing(), "Titel ist gleich zum Schreiben bereit"
        QTest.keyClicks(board.view.viewport(), "Sitze")
        board.view.setFocus()
        drop.title.clearFocus()
        h.pump(0.05)
        saved = [it for it in note.board["items"] if it["kind"] == "backdrop"]
        assert saved and saved[0]["title"] == "Sitze", note.board
        r = drop.sceneBoundingRect()
        assert r.contains(label.sceneBoundingRect()) and r.contains(img.sceneBoundingRect())
        before = (label.pos(), img.pos())
        grip = QPointF(r.right() - 12, r.top() + 6)  # Titelleiste (Reiter), rechts neben dem Titel
        _board_drag(h, board, grip, grip + QPointF(100, 50))
        assert label.pos() - before[0] == QPointF(100, 50) and img.pos() - before[1] == QPointF(100, 50), \
            (label.pos(), img.pos())
        drop.setSelected(True)
        r = drop.sceneBoundingRect()
        _board_drag(h, board, r.bottomRight(), r.bottomRight() + QPointF(200, 0))
        assert abs(drop.sceneBoundingRect().width() - (r.width() + 200)) < 1, "Ecke ziehen: breiter"
        board._load(note)
        drop = [i for i in board.gscene.items() if isinstance(i, BackdropItem)][0]
        assert drop.title.toPlainText() == "Sitze", "geladen"
        folder = tempfile.mkdtemp()
        brief.export(h.sc, h.v, folder, "backdrop")
        md = open(os.path.join(folder, "brief.md"), encoding="utf-8").read()
        assert "**Section 1 – Sitze**" in md and "> Draussen" in md, md
        sec = md[md.index("**Section 1 – Sitze**"):md.index("> Draussen")]
        assert "> Sitz" in sec and "viewport screenshot" in sec, sec
    finally:
        _close(h, board)


def test_auto_backdrops_nach_naehe(h: H):
    """Shift+B: Backdrops um Gruppen (nah beieinander, mindestens zwei Elemente, noch in keinem Backdrop), Titel =
    erster Text; ein zweiter Lauf legt nichts Neues an; einzelne Elemente bleiben frei."""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from sketch_machine.note_board import BackdropItem
    note, board = _open_board(h)
    try:
        a = board.add_text(QPointF(0, 0), "Sitze")
        img = board.add_snapshot()
        img.setPos(0, a.sceneBoundingRect().bottom() + 20)
        board.add_text(QPointF(0, 3000), "Gurt")
        board.add_text(QPointF(0, 3080), "Schnalle")
        board.add_text(QPointF(5000, 0), "Allein")
        board.view.setFocus()
        QTest.keyClick(board.view, Qt.Key_B, Qt.ShiftModifier)
        drops = sorted((i for i in board.gscene.items() if isinstance(i, BackdropItem)), key=lambda d: d.y())
        assert [d.title.toPlainText() for d in drops] == ["Sitze", "Gurt"], [d.title.toPlainText() for d in drops]
        assert drops[0].sceneBoundingRect().contains(img.sceneBoundingRect())
        assert sum(it["kind"] == "backdrop" for it in note.board["items"]) == 2, "gespeichert (ein Undo-Schritt)"
        assert board.auto_backdrops() == [], "zweiter Lauf: nichts Neues"
    finally:
        _close(h, board)


def _ink_in(board, rect):
    """Anteil dunkler Pixel (Schrift) im Brett-Rechteck, so wie die Ansicht es gerade zeigt."""
    img = board.view.viewport().grab().toImage()
    q = board.view.mapFromScene(rect).boundingRect()
    vals = [img.pixelColor(x, y).lightness() for x in range(max(q.left(), 0), min(q.right(), img.width() - 1), 2)
            for y in range(max(q.top(), 0), min(q.bottom(), img.height() - 1), 2)]
    if not vals:
        return 0.0
    ref = float(np.median(vals))
    return sum(abs(v - ref) > 40 for v in vals) / len(vals)


def test_backdrop_nur_am_reiter_verschiebbar_inhalt_sichtbar(h: H):
    """Backdrop: Ziehen an der Titelleiste verschiebt ihn samt Inhalt (der Inhalt bleibt dabei sichtbar); im Rahmen
    zieht man eine Box auf, die die Elemente darin wählt – der Backdrop bleibt liegen."""
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtTest import QTest
    from sketch_machine.note_board import BackdropItem
    note, board = _open_board(h)
    try:
        a = board.add_text(QPointF(0, 0), "Erster Text hier")
        b = board.add_text(QPointF(0, 120), "Zweiter Text hier")
        a.setSelected(True)
        b.setSelected(True)
        QTest.keyClick(board.view, Qt.Key_B)
        drop = [i for i in board.gscene.items() if isinstance(i, BackdropItem)][0]
        board.view.setFocus()
        drop.title.clearFocus()
        board.gscene.clearSelection()
        h.pump(0.05)
        r, pos0 = drop.sceneBoundingRect(), drop.pos()
        # Box im Rahmen (unterhalb des Reiters) um beide Texte: wählt sie, Backdrop bleibt liegen und ungewählt
        box = a.sceneBoundingRect().united(b.sceneBoundingRect()).adjusted(-10, -10, 10, 10)
        _board_drag(h, board, box.topLeft(), box.bottomRight())
        assert drop.pos() == pos0, "im Rahmen ziehen verschiebt den Backdrop nicht"
        assert a.isSelected() and b.isSelected() and not drop.isSelected(), board.gscene.selectedItems()
        board.gscene.clearSelection()
        # am Reiter ziehen: samt Inhalt, der dabei sichtbar bleibt
        ink0 = _ink_in(board, a.sceneBoundingRect())
        assert ink0 > 0.01, ink0
        grip = QPointF(r.right() - 10, r.top() + 6)
        before = a.pos()
        _board_drag(h, board, grip, grip + QPointF(60, 40), release=False)
        h.pump(0.05)
        assert a.pos() - before == QPointF(60, 40), a.pos()
        assert _ink_in(board, a.sceneBoundingRect()) > ink0 * 0.5, "Inhalt beim Ziehen sichtbar"
        _board_send(h, board, QEvent.MouseButtonRelease, grip + QPointF(60, 40), Qt.NoButton)
        assert drop.pos() - pos0 == QPointF(60, 40)
        # aus der Notiz geladen (keine Python-Referenzen auf die Elemente): Anklicken lässt den Inhalt stehen
        board.commit()
        board._load(note)
        del a, b
        n0 = len(board.gscene.items())
        drop = [i for i in board.gscene.items() if isinstance(i, BackdropItem)][0]
        r = drop.sceneBoundingRect()
        grip = QPointF(r.right() - 10, r.top() + 6)
        _board_drag(h, board, grip, grip + QPointF(30, 0))
        h.pump(0.05)
        assert len(board.gscene.items()) == n0, (n0, len(board.gscene.items()))
        assert sum(it["kind"] == "text" for it in note.board["items"]) == 2, note.board
    finally:
        _close(h, board)


def test_brett_pinselbreite_unabhaengig_vom_zoom_und_strg_shift(h: H):
    """Pinselbreite des Bretts in Brett-Einheiten: gleich bei jedem Zoom; wie im 3D-View skaliert Strg+Mausrad sie
    (gemerkt), Strg+Shift+Mausrad die Dicke der Striche."""
    from PySide6.QtCore import QEvent, QPoint, Qt
    from PySide6.QtGui import QWheelEvent
    from PySide6.QtWidgets import QApplication
    from sketch_machine import note_board
    from sketch_machine.note_board import StrokeItem
    old = note_board.board_pen()
    note, board = _open_board(h)
    try:
        board.set_paint_tool("pen")
        note_board.set_board_pen(5.0)
        _board_drag(h, board, QPointF(0, 0), QPointF(60, 20))
        board.view._zoom_by(3.0)
        _board_drag(h, board, QPointF(0, 40), QPointF(60, 60))
        widths = [max(s.widths) for s in board.gscene.items() if isinstance(s, StrokeItem)]
        assert len(widths) == 2 and all(abs(w - 5.0) < 1e-6 for w in widths), widths
        vp = board.view.viewport()
        pos = QPointF(vp.width() / 2, vp.height() / 2)
        def wheel(mods):
            QApplication.sendEvent(vp, QWheelEvent(pos, vp.mapToGlobal(pos), QPoint(), QPoint(0, 120), Qt.NoButton,
                                                   mods, Qt.NoScrollPhase, False))
        wheel(Qt.ControlModifier)  # wie im 3D-View: Strg = Pinselbreite
        assert abs(note_board.board_pen() - 5.0 * 1.15) < 1e-6, note_board.board_pen()
        assert abs(board.view.transform().m11() - 3.0) < 1e-3, "Strg+Rad zoomt nicht"
        wheel(Qt.ControlModifier | Qt.ShiftModifier)  # Strg+Shift = Dicke aller Striche
        widths = [max(s.widths) for s in board.gscene.items() if isinstance(s, StrokeItem)]
        assert all(abs(w - 5.0 * 1.1) < 1e-6 for w in widths), widths
        assert abs(note_board.board_pen() - 5.0 * 1.15) < 1e-6, "Pinsel bleibt"
        assert all(abs(max(w) - 5.5) < 1e-6 for w in [i["w"] for i in note.board["items"] if i["kind"] == "stroke"]),             "in der Notiz"
    finally:
        note_board.set_board_pen(old)
        _close(h, board)


def test_brett_schnelle_striche_ein_schritt_und_notizwechsel(h: H):
    """Schnell hintereinander gemalte Striche: erst nach der Pause in die Notiz, als ein Undo-Schritt, ohne den 3D-View
    neu aufzubauen. Wechselt die Notiz vorher, landen die Striche trotzdem in ihrer eigenen Notiz."""
    from PySide6.QtCore import QEvent, Qt
    from sketch_machine.scene import Note
    note, board = _open_board(h)
    try:
        board.set_paint_tool("pen")
        rebuilt = []
        orig = h.v._changed
        h.v._changed = lambda *a, **k: (rebuilt.append(1), orig(*a, **k))
        for k in range(3):
            _board_drag(h, board, QPointF(0, 30 * k), QPointF(50, 30 * k + 10), release=False)
            _board_send(h, board, QEvent.MouseButtonRelease, QPointF(50, 30 * k + 10), Qt.NoButton)
        assert not note.board.get("items"), "noch nichts übernommen"
        _settle(board)
        h.v._changed = orig
        assert len(note.board["items"]) == 3 and not rebuilt, (len(note.board.get("items", [])), rebuilt)
        h.sc.undo()
        assert not h.sc.note_by_id(note.id).board.get("items"), "ein Undo-Schritt für alle drei"
        h.sc.redo()
        other = Note("Andere", np.array([2.0, 0.0, 0.0]))
        h.sc.notes.append(other)
        _board_drag(h, board, QPointF(0, 120), QPointF(50, 130), release=False)
        _board_send(h, board, QEvent.MouseButtonRelease, QPointF(50, 130), Qt.NoButton)
        board.show_note(h.v, other.id)
        assert len(h.sc.note_by_id(note.id).board["items"]) == 4, "wartender Strich bleibt in seiner Notiz"
        assert not other.board.get("items")
    finally:
        _close(h, board)


def test_hero_namensfeld_bleibt_nie_haengen(h: H):
    """Hafen-Aufnahme 13.11.: Haken an, Namensfeld offen, ohne Änderung weggeklickt – das Feld blieb stehen (Qt 6 meldet
    editingFinished dann nicht); nach Strg+Z stand es ohne sein Bild im Brett und das Brett zeichnete nicht mehr.
    Jetzt: Wegklicken, Esc, Haken aus und Neuladen schließen es; Bearbeiten geht danach weiter."""
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QFocusEvent
    from PySide6.QtWidgets import QApplication, QLineEdit
    from sketch_machine.note_board import ImageItem
    note, board = _open_board(h)
    view = board.view

    def shown():
        return [e for e in view.viewport().findChildren(QLineEdit) if e.isVisible()]

    try:
        board.add_snapshot()
        h.pump(0.05)
        shot = next(i for i in board.gscene.items() if isinstance(i, ImageItem))
        view.toggle_hero(shot)
        assert len(shown()) == 1
        QApplication.sendEvent(shown()[0], QFocusEvent(QEvent.FocusOut, Qt.MouseFocusReason))  # weggeklickt
        h.pump(0.05)
        assert not shown() and view._hero_edit is None, "Wegklicken ohne Änderung schließt das Feld"
        assert shot.hero and shot.hero_name, "Haken und Vorgabe-Name bleiben"
        view.edit_hero_name(shot)
        view.toggle_hero(shot)  # Haken aus
        h.pump(0.05)
        assert not shown() and view._hero_edit is None, "Haken aus schließt das Feld"
        view.toggle_hero(shot)
        old = shot.hero_name
        shown()[0].setText("Halb getippt")
        from PySide6.QtTest import QTest
        QTest.keyClick(shown()[0], Qt.Key_Escape)
        h.pump(0.05)
        assert not shown() and shot.hero_name == old, "Esc: Feld zu, Name wie vorher"
        view.edit_hero_name(shot)
        board.undo()  # Brett lädt neu: das Bild des Felds verschwindet
        h.pump(0.05)
        assert not shown() and view._hero_edit is None, "kein Feld ohne Bild"
        view.viewport().grab()  # Brett zeichnet weiter
        again = next(i for i in board.gscene.items() if isinstance(i, ImageItem))
        view.edit_hero_name(again)
        shown()[0].setText("Corner")
        view._end_hero_edit()
        assert again.hero_name == "Corner", "Bearbeiten geht weiter"
    finally:
        _close(h, board)

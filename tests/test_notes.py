"""Notes: camera button (view as a picture into the note board, with fly-back) and painting on the board."""
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
    note = Note("Seat", np.array([0.5, 0.8, 0.0]))
    h.sc.notes.append(note)
    h.v.set_notes_mode(True)
    h.v.ws.active_note = note.id
    h.camera([0.0, 0.0, 0.5], 6, [0.3, 0.8, 0.5])
    return note


def test_camera_button_inserts_clean_view_with_camera(h: H):
    """Click on the camera symbol of the note: picture of the view on the board (without controls), with the camera;
    one undo step, is saved."""
    note = _note_scene(h)
    try:
        h.grab()
        icons = h.v.notes_tool._screen[note.id]["icons"]
        assert "cam" in icons, f"no camera button on the note ({sorted(icons)})"
        state = h.v.cam.state()
        h.click(icons["cam"])
        items = [it for it in note.board.get("items", []) if it.get("kind") == "image"]
        assert len(items) == 1, f"{len(items)} pictures on the board instead of 1"
        item = items[0]
        data = h.sc.asset_bytes(item["file"])
        img = QImage.fromData(data)
        assert not img.isNull() and img.width() > 100, "picture readable"
        assert np.allclose(item["view"]["target"], state[0], atol=1e-4) and abs(item["view"]["dist"] - state[1]) < 1e-4
        assert not getattr(h.v, "_clean_frame", False) and h.v.notes_mode, "view afterwards as before"
        # clean: the same picture as the view without notes/mode (note heading not in the picture)
        clean = h.v.clean_image()
        shown = h.grab()
        assert h.diff(clean, shown) > 0, "the controls (note, axis cross) are missing from the picture"
        h.v.ws.planes_visible = False
        try:
            assert h.diff(clean, h.v.clean_image()) == 0, "drawing aids (planes, axis cross) never in the picture"
        finally:
            h.v.ws.planes_visible = True
        path = os.path.join(tempfile.mkdtemp(), "note.sketch.json")
        h.sc.save(path)
        loaded = Scene.load(path)[0]
        again = [it for it in loaded.notes[0].board["items"] if it.get("kind") == "image"][0]
        assert again.get("view") == item["view"], "camera on the picture is saved"
        assert loaded.asset_bytes(again["file"]), "picture is saved"
        h.sc.undo()
        note2 = h.sc.note_by_id(note.id)
        assert not note2.board.get("items"), "Ctrl+Z takes the picture out again"
    finally:
        h.v.set_notes_mode(False)


def test_double_click_on_the_picture_flies_back_to_the_view(h: H):
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
    """Drag the left mouse button on the board from a to b (board coordinates); path: intermediate points instead of the straight line."""
    from PySide6.QtCore import QEvent, Qt
    _board_send(h, board, QEvent.MouseButtonPress, a, Qt.LeftButton, mods=mods)
    pts = path if path is not None else [a + (b - a) * float(t) for t in np.linspace(0, 1, steps)[1:]]
    for p in pts:
        _board_send(h, board, QEvent.MouseMove, p, Qt.LeftButton, mods=mods)
    if release:
        _board_send(h, board, QEvent.MouseButtonRelease, b, Qt.NoButton, mods=mods)
        _settle(board)


def _settle(board):
    """Wait for the pause after painting (SETTLE_MS): pending strokes into the note, show connection."""
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


def test_handwriting_on_the_board_follows_smoothly(h: H):
    """While painting, the ink lies on its own layer: visible already during the stroke, fractions of pixels
    are kept, each point costs the same regardless of the length; afterwards it is a normal stroke.
    Real corners (rectangle) stay sharp in the finished stroke."""
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
        assert stroke is not None and stroke.live and not stroke.isVisible(), "while painting: ink instead of element"
        times = []
        for i in range(1, 900):
            x, y = 80.25 + i * 0.5, 120.5 + 40 * math.sin(i * 0.05)
            t0 = time.perf_counter()
            send(QEvent.MouseMove, x, y)
            QApplication.processEvents()
            times.append(time.perf_counter() - t0)
        early, late = sorted(times[20:220])[100], sorted(times[-200:])[100]
        assert late < early * 3 + 0.002, f"costs depend on the stroke length: {early * 1e3:.2f} -> {late * 1e3:.2f} ms"
        assert any(abs(p.x() - round(p.x())) > 0.01 for p in stroke.pts), "pen position rounded to whole pixels"
        image = vp.grab().toImage()
        ink = view.mapFromScene(stroke.pts[len(stroke.pts) // 2])
        found = any(image.pixelColor(ink.x() + dx, ink.y() + dy) != image.pixelColor(5, 5)
                    for dx in (-1, 0, 1) for dy in (-1, 0, 1))
        assert found, "ink is visible during the stroke"
        send(QEvent.MouseButtonRelease, 80.25 + 450, 120.5, buttons=Qt.NoButton)
        h.pump(0.05)
        assert view._stroke is None and view._ink is None and stroke.isVisible() and not stroke.live
        assert stroke.boundingRect().width() > 400, "frame is right after the stroke"
        assert not note.board.get("items"), "releasing stays light: only after the pause into the note"
        assert board._settle_timer.isActive()
        h.pump(0.6)
        assert len(note.board.get("items", [])) >= 1, "after the pause in the note"
        # rectangle corner: the path runs through the corner point, handwriting instead passes as an arc
        square = [QPointF(0, 0), QPointF(100, 0), QPointF(100, 100)]
        path = _ink_paths(square, [2.0] * 3)[0][0]
        assert path.intersects(QPainterPath(QPointF(100, 0)).boundingRect().adjusted(-0.5, -0.5, 0.5, 0.5)), \
            "corner stays sharp"
    finally:
        board.set_paint_tool(None)
        if board.isVisible():
            board.close_board()
        h.v.set_notes_mode(False)


def test_paint_erase_on_the_board_and_export_as_picture(h: H):
    """A: pen paints on the board (saved in the note), D: eraser splits the stroke, own pen colour of the
    board; the board can be rendered as one picture (brief)."""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from sketch_machine.note_board import StrokeItem, render_board
    note, board = _open_board(h)
    try:
        QTest.keyClick(board.view, Qt.Key_A)
        assert board.paint_tool == "pen", board.paint_tool
        _board_drag(h, board, QPointF(-200, 0), QPointF(200, 0))
        strokes = [i for i in board.gscene.items() if isinstance(i, StrokeItem)]
        assert len(strokes) == 1 and len(strokes[0].pts) > 5, "one stroke with points"
        assert strokes[0].style == "pen" and strokes[0].color is None, "without colour choice: ink"
        assert len(note.board.get("items", [])) == 1, "every stroke lands in the note immediately"
        QTest.keyClick(board.view, Qt.Key_D)
        assert board.paint_tool == "eraser"
        _board_drag(h, board, QPointF(0, -40), QPointF(0, 40), steps=6)
        strokes = [i for i in board.gscene.items() if isinstance(i, StrokeItem)]
        assert len(strokes) == 2, f"eraser splits the stroke in two ({len(strokes)})"
        h.v.ws.paint_color = (0.1, 0.1, 0.9)  # the colour of the 3D view does not apply on the board
        board.set_pen_color((0.8, 0.2, 0.1))
        assert board.paint_tool == "pen", "choosing a colour switches the pen on"
        _board_drag(h, board, QPointF(-100, 120), QPointF(100, 160))
        QTest.keyClick(board.view, Qt.Key_Escape)
        assert board.paint_tool is None, "Esc: painting off (board stays open)"
        assert board.isVisible()
        board.close_board()
        items = [it for it in note.board["items"] if it["kind"] == "stroke"]
        assert len(items) == 3, f"{len(items)} strokes in the note"
        colored = [it for it in items if it.get("color")]
        assert len(colored) == 1 and colored[0]["color"] == [0.8, 0.2, 0.1] and colored[0]["style"] == "pen"
        img = render_board(h.sc, note.board)
        assert img is not None and img.width() > 100
        path = os.path.join(tempfile.mkdtemp(), "paint.sketch.json")
        h.sc.save(path)
        again = Scene.load(path)[0].notes[0].board["items"]
        assert [it for it in again if it["kind"] == "stroke"] == items, "strokes are saved"
    finally:
        h.v.ws.board_color = None
        _close(h, board)


def test_note_and_leader_line_are_covered_by_surfaces(h: H):
    """Notes and their leader lines: parts covered by surfaces are missing as with lines; X-ray shows everything."""
    from sketch_machine.scene import NoteAnchor
    h.new_scene()
    _square(h, y=0.0, x0=-3.0, size=6.0)
    note = Note("Seat", np.array([0.0, 0.8, 3.0]))
    note.anchors.append(NoteAnchor(np.array([0.5, 0.0, 3.5])))
    h.sc.notes.append(note)
    try:
        h.camera([0.0, 0.4, 3.0], 9, [0.2, 0.9, 0.3])  # from above
        h.grab()
        box, leads = h.v.notes_tool.occlusion[note.id]
        assert box.mean() > 0.95 and leads[0].mean() > 0.9 and leads[0][-1], (box.mean(), leads[0].mean())
        assert box.all(), box.mean()
        # fully visible: drawn exactly as without occlusion (brackets not clipped)
        seen = h.grab()
        tool = h.v.notes_tool
        tool.visibility = lambda _fn: {}
        try:
            plain = h.grab()
        finally:
            del tool.visibility
        assert h.diff(seen, plain, step=1, threshold=0) == 0, "sign is clipped although everything is visible"
        h.camera([0.0, 0.4, 3.0], 9, [0.2, -0.9, 0.3])  # from below: the square lies in front
        h.grab()
        box, leads = h.v.notes_tool.occlusion[note.id]
        assert box.mean() < 0.2 and leads[0].mean() < 0.2, (box.mean(), leads[0].mean())
        shown = h.grab()
        h.v.set_xray(True)
        xray = h.grab()
        assert h.v.notes_tool.occlusion is None, "X-ray: nothing covered"
        assert h.diff(shown, xray) > 0
    finally:
        h.v.set_xray(False)


def test_pictures_lie_behind_the_strokes(h: H):
    """A picture inserted later still lies under the strokes (one draws on it); saved in
    this order."""
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


def test_missing_screenshots_are_retaken(h: H):
    """Picture file lost: screenshots with a camera are retaken from it – position, size and own
    camera stay; one undo step."""
    from sketch_machine.note_board import ImageItem, board_for, camera_view
    note = _note_scene(h)
    board = board_for(h.v)
    try:
        view = camera_view(h.v)
        note.board = {"items": [{"kind": "image", "x": 10.0, "y": 20.0, "scale": 0.4, "file": "gone.jpg", "view": view},
                                {"kind": "image", "x": 600.0, "y": 20.0, "scale": 1.0, "file": "ref.png"}]}
        h.camera([3.0, 1.0, -2.0], 12, [-0.6, 0.3, 0.7])
        state = h.v.cam.state()
        board.open(h.v, note.id)
        h.pump(0.05)
        assert board.retake_button.isVisibleTo(board), "button appears when screenshots are missing"
        board.retake_missing()
        shot, ref = sorted((i for i in board.gscene.items() if isinstance(i, ImageItem)), key=lambda i: i.x())
        assert not shot.missing and ref.missing, "only the screenshot (with camera) can be retaken"
        assert shot.pixmap().width() > 200 and h.sc.asset_bytes(shot.file)
        item = note.board["items"][0]
        assert (item["x"], item["y"], item["scale"]) == (10.0, 20.0, 0.4) and item["file"] == shot.file
        assert np.allclose(h.v.cam.state()[0], state[0]) and abs(h.v.cam.state()[1] - state[1]) < 1e-9
        assert board.retake_button.isVisibleTo(board), "stays: then retakes all screenshots"
        h.sc.undo()
        assert h.sc.note_by_id(note.id).board["items"][0]["file"] == "gone.jpg"
    finally:
        _close(h, board)


def test_screenshot_retaken_in_the_old_format(h: H):
    """↻ on a screenshot: same camera in the aspect ratio of the old picture (wider and narrower than the
    viewport), picture stays the same width at the same place; X-ray as set, nothing noted on the picture."""
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
        h.sc.assets["wide.jpg"], h.sc.assets["tall.jpg"] = jpg(1600, 500), jpg(400, 800)
        note.board = {"items": [{"kind": "image", "x": 0.0, "y": 0.0, "scale": 0.5, "file": "wide.jpg", "view": view},
                                {"kind": "image", "x": 0.0, "y": 600.0, "scale": 1.0, "file": "tall.jpg",
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


def test_deleted_pictures_disappear_from_the_file(h: H):
    import json
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from sketch_machine.note_board import ImageItem
    note, board = _open_board(h)
    try:
        board.add_snapshot()
        board.add_snapshot()
        path = os.path.join(tempfile.mkdtemp(), "pictures.sketch.json")
        h.sc.save(path)
        with open(path, encoding="utf-8") as f:
            assert len(json.load(f)["assets"]) >= 1
        for i in board.gscene.items():
            i.setSelected(isinstance(i, ImageItem))
        QTest.keyClick(board.view, Qt.Key_Delete)
        h.sc.save(path)
        with open(path, encoding="utf-8") as f:
            assert json.load(f)["assets"] == {}, "deleted pictures are no longer saved"
    finally:
        _close(h, board)


def test_board_ctrl_shift_erases_whole_strokes(h: H):
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
        assert len(strokes) == 1 and strokes[0].pts[0].y() > 50, "the stroke that was hit is gone entirely, the other stays"
    finally:
        _close(h, board)


def test_board_undo_redo_in_the_same_history(h: H):
    """Ctrl+Z/Ctrl+Y on the board: step by step, together with the 3D view; the board shows the state."""
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
        assert count() == 1 and len(h.sc.note_by_id(note.id).board["items"]) == 1, "Ctrl+Z takes the last stroke"
        assert abs(board.view.transform().m11() - zoom) < 1e-6, "view stays on undo"
        assert board.isVisible(), "Ctrl+Z does not close the board"
        QTest.keyClick(board.view, Qt.Key_Y, Qt.ControlModifier)
        assert count() == 2, "Ctrl+Y brings it back"
        QTest.keyClick(board.view, Qt.Key_Z, Qt.ControlModifier | Qt.ShiftModifier)
        QTest.keyClick(board.view, Qt.Key_Z, Qt.ControlModifier | Qt.ShiftModifier)
        assert count() == 2, "Ctrl+Shift+Z = redo (nothing left)"
        QTest.keyClick(board.view, Qt.Key_Z, Qt.ControlModifier)
        QTest.keyClick(board.view, Qt.Key_Z, Qt.ControlModifier)
        assert count() == 0
    finally:
        _close(h, board)


def test_board_undo_while_writing_loses_nothing(h: H):
    """Text is being written, then undo (button/menu): the text is a step of its own, clearing the
    board writes no half state into the note."""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from sketch_machine.note_board import TextBlock
    note, board = _open_board(h)
    try:
        QTest.keyClick(board.view, Qt.Key_A)
        _board_drag(h, board, QPointF(-200, 0), QPointF(200, 0))
        board.set_paint_tool(None)
        block = board.add_text(QPointF(0, 200), edit=True)
        QTest.keyClicks(board.view, "Seat 45")  # ASCII only: QTest.keyClicks crashes on umlauts
        assert "Seat 45" in block.toPlainText()
        board.undo()
        items = h.sc.note_by_id(note.id).board["items"]
        assert [it["kind"] for it in items] == ["stroke"], items
        assert not [i for i in board.gscene.items() if isinstance(i, TextBlock)]
        board.undo(redo=True)
        assert [it.get("text") for it in h.sc.note_by_id(note.id).board["items"]] == [None, "Seat 45"]
    finally:
        _close(h, board)


def test_ctrl_v_on_the_board_inserts_picture_not_the_3d_clipboard(h: H):
    """Ctrl+V on the board: the picture from the clipboard (before, the main window's paste took over)."""
    from PySide6.QtCore import QMimeData, Qt
    from PySide6.QtGui import QColor
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from sketch_machine.note_board import ImageItem
    clip = QApplication.clipboard()
    saved = QMimeData()  # restore the clipboard afterwards
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
        assert len(images) == 1, f"{len(images)} pictures on the board"
        assert len(h.curves()) == curves, "no lines pasted into the scene"
        item = note.board["items"][0]
        assert item["kind"] == "image" and item["file"].endswith(".jpg"), "saved as JPEG without transparency"
    finally:
        clip.setMimeData(saved)
        _close(h, board)


def test_picture_link_from_the_web_is_loaded(h: H):
    """If only a link (HTML with <img>) is in the clipboard, the board loads the picture."""
    import functools
    import http.server
    import threading
    from PySide6.QtCore import QMimeData
    from PySide6.QtGui import QColor
    from sketch_machine.note_board import ImageItem
    folder = tempfile.mkdtemp()
    img = QImage(40, 30, QImage.Format_ARGB32)
    img.fill(QColor(20, 120, 220, 128))
    img.save(os.path.join(folder, "picture.png"))
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=folder)
    handler.log_message = lambda *a: None
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    note, board = _open_board(h)
    try:
        mime = QMimeData()
        mime.setHtml(f'<html><body><img src="http://127.0.0.1:{server.server_port}/picture.png"/></body></html>')
        board.insert_mime(mime, QPointF(0, 0))
        images = [i for i in board.gscene.items() if isinstance(i, ImageItem)]
        assert len(images) == 1 and images[0].pixmap().width() == 40
        assert note.board["items"][0]["file"].endswith(".png"), "transparency stays (PNG)"
    finally:
        server.shutdown()
        _close(h, board)


def test_board_shape_recognition_circle_and_line(h: H):
    """As in the 3D view: hold still at the end of the stroke -> circle (size follows the mouse) or line."""
    import math
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtTest import QTest
    from sketch_machine.note_board import StrokeItem
    note, board = _open_board(h)
    try:
        QTest.keyClick(board.view, Qt.Key_A)
        ring = [QPointF(100 * math.cos(a), 100 * math.sin(a) * 0.95) for a in np.linspace(0, 2 * math.pi * 0.97, 40)]
        _board_drag(h, board, ring[0], ring[-1], path=ring[1:], release=False)
        board.view._recognize()  # hold still
        assert board.view._shape is not None and board.view._shape["kind"] == "circle", board.view._shape
        _board_send(h, board, QEvent.MouseMove, QPointF(150, 0), Qt.LeftButton)
        _board_send(h, board, QEvent.MouseButtonRelease, QPointF(150, 0), Qt.NoButton)
        stroke = [i for i in board.gscene.items() if isinstance(i, StrokeItem)][0]
        r = [math.hypot(p.x(), p.y()) for p in stroke.pts]
        assert abs(min(r) - 150) < 3 and abs(max(r) - 150) < 3, f"circle with radius 150 ({min(r):.1f}…{max(r):.1f})"
        wobble = [QPointF(x, 200 + 8 * math.sin(x / 20)) for x in np.linspace(-200, 200, 30)]
        _board_drag(h, board, wobble[0], wobble[-1], path=wobble[1:], release=False)
        board.view._recognize()
        _board_send(h, board, QEvent.MouseMove, QPointF(250, 240), Qt.LeftButton)
        _board_send(h, board, QEvent.MouseButtonRelease, QPointF(250, 240), Qt.NoButton)
        line = [i for i in board.gscene.items() if isinstance(i, StrokeItem) and i is not stroke][0]
        assert len(line.pts) == 2 and line.pts[-1] == QPointF(250, 240), "line up to the cursor"
    finally:
        _close(h, board)


def test_board_handles_scale_picture_and_text(h: H):
    """Drag the selected picture at the corner: scales, the opposite corner stays put (like PureRef)."""
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
                     board.add_text(QPointF(0, 300), "Hello")):
            board.gscene.clearSelection()
            item.setSelected(True)
            rect = item.sceneBoundingRect()
            fixed, corner = rect.topLeft(), rect.bottomRight()
            target = fixed + (corner - fixed) * 2.0
            _board_drag(h, board, corner, target, steps=8)
            new = item.sceneBoundingRect()
            assert abs(item.scale() - 2.0) < 0.05, f"factor 2 ({item.scale():.3f})"
            assert (new.topLeft() - fixed).manhattanLength() < 1.0, "the opposite corner stays"
        items = note.board["items"]
        assert [round(it.get("scale", 1.0), 1) for it in items] == [2.0, 2.0], items
    finally:
        _close(h, board)


def test_board_alt_right_mouse_button_zooms(h: H):
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
        assert board.view.transform().m11() > zoom * 1.5, "dragging to the right zooms in"
        back = board.view.mapToScene(view_pt)
        assert (back - start).manhattanLength() < 2.0, "the anchor point stays under the cursor"
    finally:
        _close(h, board)


def test_pictures_are_in_the_scene_file(h: H):
    """Pictures of the boards are saved in the scene file (no folder next to it); older scenes with a folder
    keep loading and embed the pictures on saving."""
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
        h.sc.assets["picture.png"] = data
        note.board = {"items": [{"kind": "image", "x": 0, "y": 0, "scale": 1.0, "file": "picture.png"}]}
        folder = tempfile.mkdtemp()
        path = os.path.join(folder, "embedded.sketch.json")
        h.sc.save(path)
        assert not os.path.exists(Scene.assets_dir_for(path)), "no pictures folder next to the scene"
        moved = os.path.join(tempfile.mkdtemp(), "moved.sketch.json")
        shutil.move(path, moved)
        assert Scene.load(moved)[0].asset_bytes("picture.png") == data, "picture is in the file"
        # older scene: picture in the folder next to it, not in the file
        with open(moved, encoding="utf-8") as f:
            raw = json.load(f)
        raw.pop("assets")
        old = os.path.join(folder, "old.sketch.json")
        with open(old, "w", encoding="utf-8") as f:
            json.dump(raw, f)
        os.makedirs(Scene.assets_dir_for(old))
        with open(os.path.join(Scene.assets_dir_for(old), "picture.png"), "wb") as f:
            f.write(data)
        scene = Scene.load(old)[0]
        assert scene.asset_bytes("picture.png") == data, "older scene reads the folder"
        again = os.path.join(tempfile.mkdtemp(), "new.sketch.json")
        scene.save(again)
        assert Scene.load(again)[0].asset_bytes("picture.png") == data, "embedded on saving"
    finally:
        h.v.set_notes_mode(False)


def test_brief_names_screenshot_camera_and_board_picture(h: H):
    """Brief export: screenshot with camera, painted strokes counted, the whole board as a picture."""
    from sketch_machine import brief
    note = _note_scene(h)
    try:
        h.grab()
        h.click(h.v.notes_tool._screen[note.id]["icons"]["cam"])
        note.board["items"].append({"kind": "stroke", "style": "pen", "pts": [[0, 600], [300, 640]], "w": [3, 3]})
        folder = tempfile.mkdtemp()
        files = brief.export(h.sc, h.v, folder, "note")
        md = open(os.path.join(folder, "brief.md"), encoding="utf-8").read()
        assert "viewport screenshot" in md and "camera at" not in md, "screenshot in the brief, camera only in the JSON"
        data = json.load(open(os.path.join(folder, "brief.json"), encoding="utf-8"))
        assert data["notes"][0]["screenshots"][0]["camera"]["eye"], "camera of the screenshot in brief.json"
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


def test_picture_caption_on_the_board_and_in_the_brief(h: H):
    """Picture caption: grey line under the picture (frame and arrow tip still refer to the picture), saved
    in the note, applies to the same picture in all notes (one undo step); the brief shows it behind the picture and
    names reference pictures without a caption as an open point – screenshots not."""
    from sketch_machine import brief
    from sketch_machine.note_board import set_image_captions
    note, board = _open_board(h)
    try:
        ref = board.add_image(_png(300, 200), ".png", QPointF(0, 0))
        board.add_snapshot()
        board.commit()
        other = Note("Shell", np.array([0.0, 0.0, 0.0]))
        other.board = {"items": [{"kind": "image", "x": 0, "y": 0, "scale": 1.0, "file": ref.file}]}
        h.sc.notes.append(other)
        folder = tempfile.mkdtemp()
        brief.export(h.sc, h.v, folder, "note")
        md = open(os.path.join(folder, "brief.md"), encoding="utf-8").read()
        assert "N1 Seat: 1 reference picture(s) without a caption" in md, "screenshot does not count"
        assert "N2 Shell: 1 reference picture(s) without a caption" in md
        project = open(os.path.join(folder, "project.md"), encoding="utf-8").read()  # first round (package v4)
        assert "the hero pictures `views/hero_*.png`" in project and "**Picture list**" in project
        assert "one line per reference picture once you opened it in full: the part ids it is about" in project
        assert "2 reference picture(s) have none: propose one each" in project
        tall = ref.boundingRect().height()
        assert set_image_captions(h.v, {f"notes/{ref.file}": " Seat with straps ", "nonexistent.png": "x"}) == ["nonexistent.png"]
        assert ref.caption == "Seat with straps" and ref.boundingRect().height() > tall + 5
        assert ref.image_rect().height() == 200, "the picture itself stays, the line comes below it"
        assert [i.get("caption") for i in note.board["items"] if i["file"] == ref.file] == ["Seat with straps"]
        assert other.board["items"][0]["caption"] == "Seat with straps", "applies to the same picture everywhere"
        brief.export(h.sc, h.v, folder, "note")
        md = open(os.path.join(folder, "brief.md"), encoding="utf-8").read()
        assert f"`notes/{ref.file}` – „Seat with straps“" in md and "picture(s) without a caption" not in md
        data = json.load(open(os.path.join(folder, "brief.json"), encoding="utf-8"))
        assert data["notes"][0]["captions"] == {f"notes/{ref.file}": "Seat with straps"}
        h.v.undo()
        h.pump(0.05)
        boards = lambda: json.dumps([n.board for n in h.sc.notes])  # undo replaces the note objects
        assert "caption" not in boards(), "one undo step for all notes"
        h.v.redo()
        h.pump(0.05)
        base = tempfile.mkdtemp()
        again = Scene.from_dict(h.sc.to_dict(base), base)
        assert again.notes[1].board["items"][0]["caption"] == "Seat with straps"
        set_image_captions(h.v, {ref.file: ""})
        assert "caption" not in boards(), "empty removes it"
    finally:
        _close(h, board)


def test_picture_caption_with_parts(h: H):
    """Caption with parts (hard link picture ↔ component): saved as object ids on the picture (open board
    and scene file), changing the text keeps them, empty removes them too; the brief names them behind the picture
    ("→ parts S1") and part_notes names the picture at the part."""
    from sketch_machine import brief
    from sketch_machine.note_board import set_image_captions
    note, board = _open_board(h)
    try:
        ref = board.add_image(_png(300, 200), ".png", QPointF(0, 0))
        board.commit()
        sid = next(iter(brief.index(h.sc)[1]["sid"].items()))
        set_image_captions(h.v, {ref.file: "Seat shell"}, {ref.file: [sid[0]]})
        assert ref.caption_parts == [sid[0]]
        assert [i.get("caption_parts") for i in note.board["items"] if i["file"] == ref.file] == [[sid[0]]]
        set_image_captions(h.v, {ref.file: "Seat shell from the front"})
        assert ref.caption_parts == [sid[0]], "without parts the parts stay"
        folder = tempfile.mkdtemp()
        brief.export(h.sc, h.v, folder, "note")
        md = open(os.path.join(folder, "brief.md"), encoding="utf-8").read()
        assert f"`notes/{ref.file}` – „Seat shell from the front“ → parts {sid[1]}" in md
        data = json.load(open(os.path.join(folder, "brief.json"), encoding="utf-8"))
        assert data["notes"][0]["caption_parts"] == {f"notes/{ref.file}": [sid[1]]}
        pn = next(e for e in data["part_notes"] if e["part"] == sid[1])
        assert pn["pictures"] == [f"notes/{ref.file}"]
        base = tempfile.mkdtemp()
        again = Scene.from_dict(h.sc.to_dict(base), base)
        assert again.notes[0].board["items"][-1]["caption_parts"] == [sid[0]]
        set_image_captions(h.v, {ref.file: ""})
        assert ref.caption_parts == [] and "caption_parts" not in json.dumps(note.board), "empty removes the parts too"
    finally:
        _close(h, board)


def test_arrow_on_the_board_connects_label_and_screenshot(h: H):
    """A stroke from a label onto a screenshot is a connection (tip: spot in the picture); the board
    shows it briefly after painting. Circle on the picture: marking; picture -> picture; short strokes do not count."""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from sketch_machine import board_links
    from sketch_machine.note_board import StrokeItem
    note, board = _open_board(h)
    try:
        label = board.add_text(QPointF(0, 0), "Pilot seat\nwith straps")
        img = board.add_snapshot()
        r, t = img.sceneBoundingRect(), label.sceneBoundingRect()
        QTest.keyClick(board.view, Qt.Key_A)
        start, tip = QPointF(t.right() - 5, t.center().y()), r.center()
        _board_drag(h, board, start, tip)
        stroke = [i for i in board.gscene.items() if isinstance(i, StrokeItem)][0]
        assert board.view._flash is stroke, "a stroke just painted shows its connection"
        link = board_links.stroke_link(board.gscene, stroke)
        assert link["kind"] == "link" and link["source"] is label and link["target"] is img, link
        assert abs(link["uv"][0] - 0.5) < 0.05 and abs(link["uv"][1] - 0.5) < 0.05, link["uv"]
        assert board_links.label_of(label) == "Pilot seat"
        board.view._end_flash()
        assert board.view._flash is None
        c = r.center()  # circle on the picture
        ring = [c + QPointF(40 * np.cos(a), 40 * np.sin(a)) for a in np.linspace(0, 2 * np.pi, 24)]
        _board_drag(h, board, ring[0], ring[-1], path=ring[1:])
        circle = board.view._flash
        mark = board_links.stroke_link(board.gscene, circle)
        assert mark["kind"] == "mark" and mark["target"] is img and mark["source"] is None, mark
        board.view._end_flash()
        _board_drag(h, board, c, c + QPointF(8, 3))  # tick: no connection, no message
        assert board.view._flash is None
        far = QPointF(r.right() + 600, r.top())  # writing/scribbling in the open: silent (artist, 2026-11-07)
        _board_drag(h, board, far, far + QPointF(120, 10), path=[far + QPointF(60, 40)])
        loop = [far + QPointF(300 + 30 * np.cos(a), 30 * np.sin(a)) for a in np.linspace(0, 2 * np.pi, 16)]
        _board_drag(h, board, loop[0], loop[-1], path=loop[1:])
        assert board.view._flash is None, "nothing found: no 'unclear' message"
    finally:
        board.set_paint_tool(None)
        _close(h, board)


def test_brief_splits_board_into_sections_with_arrows(h: H):
    """Brief: texts/pictures that lie close together form a section (own picture); arrows from a
    label onto a picture are numbered (P#) with the spot in the picture in them; things far away are a section
    of their own."""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from sketch_machine import brief
    note, board = _open_board(h)
    try:
        label = board.add_text(QPointF(0, 0), "Seat")
        img = board.add_snapshot()
        img.setPos(label.sceneBoundingRect().right() + 40, 0)
        board.add_text(QPointF(0, 3000), "Far away")
        t, r = label.sceneBoundingRect(), img.sceneBoundingRect()
        QTest.keyClick(board.view, Qt.Key_A)
        _board_drag(h, board, QPointF(t.left() + 20, t.center().y()), r.center())
        board.set_paint_tool(None)
        board.commit()
        folder = tempfile.mkdtemp()
        files = brief.export(h.sc, h.v, folder, "sections")
        md = open(os.path.join(folder, "brief.md"), encoding="utf-8").read()
        assert "**Section 1** – `notes/board_N1_1.png`" in md and "**Section 2**" in md, md
        assert "notes/board_N1_1.png" in files and os.path.isfile(os.path.join(folder, "notes", "board_N1_1.png"))
        assert "arrow **P1** „Seat“ → screenshot" in md and "where exactly" not in md, md
        assert "- whole board: `notes/board_N1.png`" in md and "the section picture shows exactly where" in md
        assert brief._arrow_md({"id": "P2", "from": {"text": "Release lever: When the copilot pulls on these "
                                                             "levers"}, "to": None}) == \
            "**P2** „Release lever: When the copilot pulls …“ → an empty spot", "long label shortened at a word boundary"
        data = json.load(open(os.path.join(folder, "brief.json"), encoding="utf-8"))
        arrow = data["notes"][0]["sections"][0]["arrows"][0]
        assert np.allclose(arrow["at"], [0.5, 0.5], atol=0.05), "spot in the picture is in the JSON (in the md only P# in the picture)"
        assert md.index("> Seat") < md.index("> Far away")
    finally:
        board.set_paint_tool(None)
        _close(h, board)


def test_backdrop_groups_and_is_a_section_in_the_brief(h: H):
    """B / ▭: backdrop around the selection, title can be typed right away; moving takes the content along, dragging a corner changes
    the size; saved and loaded again; in the brief a section with the title."""
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtTest import QTest
    from sketch_machine import brief
    from sketch_machine.note_board import BackdropItem
    note, board = _open_board(h)
    try:
        label = board.add_text(QPointF(0, 0), "Seat")
        img = board.add_snapshot()
        img.setPos(label.sceneBoundingRect().right() + 300, 0)  # far away: by proximity it would be two sections
        board.add_text(QPointF(0, 3000), "Outside")
        label.setSelected(True)
        img.setSelected(True)
        QTest.keyClick(board.view, Qt.Key_B)
        drop = [i for i in board.gscene.items() if isinstance(i, BackdropItem)][0]
        assert board.view.editing(), "title is ready for typing right away"
        QTest.keyClicks(board.view.viewport(), "Seats")
        board.view.setFocus()
        drop.title.clearFocus()
        h.pump(0.05)
        saved = [it for it in note.board["items"] if it["kind"] == "backdrop"]
        assert saved and saved[0]["title"] == "Seats", note.board
        r = drop.sceneBoundingRect()
        assert r.contains(label.sceneBoundingRect()) and r.contains(img.sceneBoundingRect())
        before = (label.pos(), img.pos())
        grip = QPointF(r.right() - 12, r.top() + 6)  # title bar (tab), right of the title
        _board_drag(h, board, grip, grip + QPointF(100, 50))
        assert label.pos() - before[0] == QPointF(100, 50) and img.pos() - before[1] == QPointF(100, 50), \
            (label.pos(), img.pos())
        drop.setSelected(True)
        r = drop.sceneBoundingRect()
        _board_drag(h, board, r.bottomRight(), r.bottomRight() + QPointF(200, 0))
        assert abs(drop.sceneBoundingRect().width() - (r.width() + 200)) < 1, "dragging a corner: wider"
        board._load(note)
        drop = [i for i in board.gscene.items() if isinstance(i, BackdropItem)][0]
        assert drop.title.toPlainText() == "Seats", "loaded"
        folder = tempfile.mkdtemp()
        brief.export(h.sc, h.v, folder, "backdrop")
        md = open(os.path.join(folder, "brief.md"), encoding="utf-8").read()
        assert "**Section 1 – Seats**" in md and "> Outside" in md, md
        sec = md[md.index("**Section 1 – Seats**"):md.index("> Outside")]
        assert "> Seat" in sec and "viewport screenshot" in sec, sec
    finally:
        _close(h, board)


def test_auto_backdrops_by_proximity(h: H):
    """Shift+B: backdrops around groups (close together, at least two elements, not yet in any backdrop), title =
    first text; a second run creates nothing new; single elements stay free."""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from sketch_machine.note_board import BackdropItem
    note, board = _open_board(h)
    try:
        a = board.add_text(QPointF(0, 0), "Seats")
        img = board.add_snapshot()
        img.setPos(0, a.sceneBoundingRect().bottom() + 20)
        board.add_text(QPointF(0, 3000), "Strap")
        board.add_text(QPointF(0, 3080), "Buckle")
        board.add_text(QPointF(5000, 0), "Alone")
        board.view.setFocus()
        QTest.keyClick(board.view, Qt.Key_B, Qt.ShiftModifier)
        drops = sorted((i for i in board.gscene.items() if isinstance(i, BackdropItem)), key=lambda d: d.y())
        assert [d.title.toPlainText() for d in drops] == ["Seats", "Strap"], [d.title.toPlainText() for d in drops]
        assert drops[0].sceneBoundingRect().contains(img.sceneBoundingRect())
        assert sum(it["kind"] == "backdrop" for it in note.board["items"]) == 2, "saved (one undo step)"
        assert board.auto_backdrops() == [], "second run: nothing new"
    finally:
        _close(h, board)


def _ink_in(board, rect):
    """Share of dark pixels (writing) in the board rectangle, as the view currently shows it."""
    img = board.view.viewport().grab().toImage()
    q = board.view.mapFromScene(rect).boundingRect()
    vals = [img.pixelColor(x, y).lightness() for x in range(max(q.left(), 0), min(q.right(), img.width() - 1), 2)
            for y in range(max(q.top(), 0), min(q.bottom(), img.height() - 1), 2)]
    if not vals:
        return 0.0
    ref = float(np.median(vals))
    return sum(abs(v - ref) > 40 for v in vals) / len(vals)


def test_backdrop_movable_only_by_the_tab_content_visible(h: H):
    """Backdrop: dragging the title bar moves it together with its content (the content stays visible); inside the frame
    one drags a box that selects the elements in it – the backdrop stays put."""
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtTest import QTest
    from sketch_machine.note_board import BackdropItem
    note, board = _open_board(h)
    try:
        a = board.add_text(QPointF(0, 0), "First text here")
        b = board.add_text(QPointF(0, 120), "Second text here")
        a.setSelected(True)
        b.setSelected(True)
        QTest.keyClick(board.view, Qt.Key_B)
        drop = [i for i in board.gscene.items() if isinstance(i, BackdropItem)][0]
        board.view.setFocus()
        drop.title.clearFocus()
        board.gscene.clearSelection()
        h.pump(0.05)
        r, pos0 = drop.sceneBoundingRect(), drop.pos()
        # box inside the frame (below the tab) around both texts: selects them, backdrop stays put and unselected
        box = a.sceneBoundingRect().united(b.sceneBoundingRect()).adjusted(-10, -10, 10, 10)
        _board_drag(h, board, box.topLeft(), box.bottomRight())
        assert drop.pos() == pos0, "dragging inside the frame does not move the backdrop"
        assert a.isSelected() and b.isSelected() and not drop.isSelected(), board.gscene.selectedItems()
        board.gscene.clearSelection()
        # drag at the tab: together with the content, which stays visible
        ink0 = _ink_in(board, a.sceneBoundingRect())
        assert ink0 > 0.01, ink0
        grip = QPointF(r.right() - 10, r.top() + 6)
        before = a.pos()
        _board_drag(h, board, grip, grip + QPointF(60, 40), release=False)
        h.pump(0.05)
        assert a.pos() - before == QPointF(60, 40), a.pos()
        assert _ink_in(board, a.sceneBoundingRect()) > ink0 * 0.5, "content visible while dragging"
        _board_send(h, board, QEvent.MouseButtonRelease, grip + QPointF(60, 40), Qt.NoButton)
        assert drop.pos() - pos0 == QPointF(60, 40)
        # loaded from the note (no Python references to the elements): clicking leaves the content in place
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


def test_board_brush_width_independent_of_zoom_and_ctrl_shift(h: H):
    """Brush width of the board in board units: the same at every zoom; as in the 3D view, Ctrl+mouse wheel scales it
    (remembered), Ctrl+Shift+mouse wheel the thickness of the strokes."""
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
        wheel(Qt.ControlModifier)  # as in the 3D view: Ctrl = brush width
        assert abs(note_board.board_pen() - 5.0 * 1.15) < 1e-6, note_board.board_pen()
        assert abs(board.view.transform().m11() - 3.0) < 1e-3, "Ctrl+wheel does not zoom"
        wheel(Qt.ControlModifier | Qt.ShiftModifier)  # Ctrl+Shift = thickness of all strokes
        widths = [max(s.widths) for s in board.gscene.items() if isinstance(s, StrokeItem)]
        assert all(abs(w - 5.0 * 1.1) < 1e-6 for w in widths), widths
        assert abs(note_board.board_pen() - 5.0 * 1.15) < 1e-6, "brush stays"
        assert all(abs(max(w) - 5.5) < 1e-6 for w in [i["w"] for i in note.board["items"] if i["kind"] == "stroke"]),             "in the note"
    finally:
        note_board.set_board_pen(old)
        _close(h, board)


def test_board_fast_strokes_one_step_and_note_switch(h: H):
    """Strokes painted quickly one after another: into the note only after the pause, as one undo step, without the 3D view
    being rebuilt. If the note changes before that, the strokes still land in their own note."""
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
        assert not note.board.get("items"), "nothing taken over yet"
        _settle(board)
        h.v._changed = orig
        assert len(note.board["items"]) == 3 and not rebuilt, (len(note.board.get("items", [])), rebuilt)
        h.sc.undo()
        assert not h.sc.note_by_id(note.id).board.get("items"), "one undo step for all three"
        h.sc.redo()
        other = Note("Other", np.array([2.0, 0.0, 0.0]))
        h.sc.notes.append(other)
        _board_drag(h, board, QPointF(0, 120), QPointF(50, 130), release=False)
        _board_send(h, board, QEvent.MouseButtonRelease, QPointF(50, 130), Qt.NoButton)
        board.show_note(h.v, other.id)
        assert len(h.sc.note_by_id(note.id).board["items"]) == 4, "pending stroke stays in its note"
        assert not other.board.get("items")
    finally:
        _close(h, board)


def test_hero_name_field_never_gets_stuck(h: H):
    """Harbour recording 13.11.: tick on, name field open, clicked away without a change – the field stayed (Qt 6 then does not
    report editingFinished); after Ctrl+Z it stood on the board without its picture and the board no longer painted.
    Now: clicking away, Esc, tick off and reloading close it; editing continues afterwards."""
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
        QApplication.sendEvent(shown()[0], QFocusEvent(QEvent.FocusOut, Qt.MouseFocusReason))  # clicked away
        h.pump(0.05)
        assert not shown() and view._hero_edit is None, "clicking away without a change closes the field"
        assert shot.hero and shot.hero_name, "tick and default name stay"
        view.edit_hero_name(shot)
        view.toggle_hero(shot)  # tick off
        h.pump(0.05)
        assert not shown() and view._hero_edit is None, "tick off closes the field"
        view.toggle_hero(shot)
        old = shot.hero_name
        shown()[0].setText("Half typed")
        from PySide6.QtTest import QTest
        QTest.keyClick(shown()[0], Qt.Key_Escape)
        h.pump(0.05)
        assert not shown() and shot.hero_name == old, "Esc: field closed, name as before"
        view.edit_hero_name(shot)
        board.undo()  # board reloads: the picture of the field disappears
        h.pump(0.05)
        assert not shown() and view._hero_edit is None, "no field without a picture"
        view.viewport().grab()  # board keeps painting
        again = next(i for i in board.gscene.items() if isinstance(i, ImageItem))
        view.edit_hero_name(again)
        shown()[0].setText("Corner")
        view._end_hero_edit()
        assert again.hero_name == "Corner", "editing continues"
    finally:
        _close(h, board)

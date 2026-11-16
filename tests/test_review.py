"""Review mode (review.py): recording of camera, cursor, targets and "Here!" marks; Claude reads them via MCP
(review_read, review_moment) and creates draft notes (review_note) – with an image from the camera of the time, arrow to
the cursor spot, anchor at the part shown, original sentence; accept or discard in the board."""
import json
import os
import shutil
import tempfile
import time
import wave

import numpy as np
from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QGraphicsScene

from tests.harness import H
from tests.test_mcp_server import _call
from tests.test_brief_content import _scene
from sketch_machine import mcp_server, review
from sketch_machine.scene import Scene


class _SilentAudio:
    """Instead of a microphone: one second of silence as ton.wav (tests never really record)."""

    def __init__(self, path, parent=None):
        with wave.open(path, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(16000)
            w.writeframes(b"\0\0" * 16000)
        self.ok, self.error, self.frames, self.device_name = True, "", 16000, "Test"

    def stop(self):
        pass


def _setup(h):
    base = tempfile.mkdtemp()
    old = review.reviews_dir, review.AudioWriter, h.w.path, h
    review.reviews_dir = lambda: base
    review.AudioWriter = _SilentAudio
    h.w.path = None  # the tests share the window: no path from an earlier test
    return base, old


def _restore(old):
    review.reviews_dir, review.AudioWriter, path, h = old
    h.w.path = path


def _record(h, sc):
    """Record a review: cursor rests on the line, "Here!", then camera rotated and cursor into empty space."""
    line = sc.strokes[0].curves[0]
    h.frame(np.vstack([line.points, [[0, 1, 0]]]))
    session = review.ReviewSession(h.w)
    on_line = h.scr(line.points[2])
    pos = {"p": h.v.mapToGlobal(on_line)}
    session.cursor = lambda: pos["p"]
    folder = session.start()
    h.pump(0.6)  # cursor rests -> target
    t_mark = session.elapsed()
    assert session.mark() == 1
    pins = h.v.ws.review_pins
    assert len(pins) == 1 and pins[0]["point"] is not None and session.last_mark["hit"], "pin on the line"
    h.grab()  # draws the pin (must not interfere)
    h.pump(0.2)
    from sketch_machine.scene import Note  # own changes during the review: create a note, draw a line
    sc.notes.append(Note("My note", np.array([0.0, 1.0, 0.0]),
                         board={"items": [{"kind": "text", "x": 0, "y": 0, "w": 200, "text": "mine"}]}))
    sc.add_curve(np.array([[0.0, 0.5, 0.0], [1.0, 0.5, 0.0]]), None)
    h.pump(0.7)
    h.camera([0.5, 0, 0], 3.0, (0.0, 1.0, 0.2))  # different view
    pos["p"] = h.v.mapToGlobal(QPoint(5, 5))
    h.pump(0.5)
    t_end = session.elapsed()
    session.stop(transcribe=False)
    assert h.v.ws.review_pins == [], "pins only during the review"
    with open(os.path.join(folder, review.TRANSCRIPT), "w", encoding="utf-8") as f:
        json.dump({"language": "de", "model": "test", "segments": [
            {"start": 0.0, "end": round(t_mark + 0.2, 2), "text": "Die Kante hier ist mir zu weich."},
            {"start": round(t_mark + 0.3, 2), "end": round(t_end, 2), "text": "Insgesamt passt die Richtung."}]}, f)
    return folder, line, t_mark


def test_recording_log(h: H):
    """Log: camera on change, mouse, target under the resting cursor, mark with image, review.json."""
    base, old = _setup(h)
    try:
        sc = _scene(h)
        folder, line, t_mark = _record(h, sc)
        events = review.read_log(folder)
        kinds = [e["typ"] for e in events]
        assert kinds[0] == "start" and kinds[-1] == "ende", kinds
        assert kinds.count("kamera") >= 2, "camera changes recorded"
        target = next(e for e in events if e["typ"] == "ziel")
        assert target["curve"] == line.id and target["obj"] == sc.strokes[0].id, target
        mark = next(e for e in events if e["typ"] == "marke")
        assert mark["curve"] == line.id and os.path.isfile(os.path.join(folder, mark["bild"])), mark
        assert any(e["typ"] == "notiz_neu" for e in events) and any(e["typ"] == "linien" for e in events), kinds
        meta = json.load(open(os.path.join(folder, review.META), encoding="utf-8"))
        assert meta["marken"] == 1 and meta["ton"]
        m = review.moment(events, t_mark)
        assert m["ziel"]["curve"] == line.id and m["kamera"]["w"] == h.v.width()
        assert review.find_review() == folder and review.find_review(os.path.basename(folder)[:8]) == folder
    finally:
        _restore(old)
        shutil.rmtree(base, ignore_errors=True)


def test_mcp_review_to_draft(h: H):
    """review_read names text, target (L#) and mark; review_moment renders the view of the time; review_note creates a
    draft (anchor at the line, image with camera, arrow to the cursor spot, original sentence); survives saving;
    the project note gets general points; discard only for drafts; the brief names drafts as open."""
    from sketch_machine import board_links, brief
    from sketch_machine.note_board import StrokeItem, TextBlock, _populate
    base, old = _setup(h)
    server = mcp_server.Server(h.w, port=0).start()
    try:
        sc = _scene(h)
        folder, line, t_mark = _record(h, sc)
        text = _call(h, server, "review_read")["content"][0]["text"]
        assert "Die Kante hier ist mir zu weich." in text and "cursor on L1" in text and "MARK 1" in text, text
        assert "created note N2 „My note“" in text and "drew 1 line(s)" in text, text
        r = _call(h, server, "review_moment", times=[t_mark])
        assert not r["isError"] and r["content"][1]["type"] == "image" and "L1" in r["content"][0]["text"], r
        import base64
        from PySide6.QtGui import QImage
        small = QImage.fromData(base64.b64decode(r["content"][1]["data"]))
        assert max(small.width(), small.height()) <= mcp_server.MOMENT_MAX, "small for checking"
        big = _call(h, server, "review_moment", times=[t_mark], detail=True)["content"][1]["data"]
        big = QImage.fromData(base64.b64decode(big))
        assert max(big.width(), big.height()) > mcp_server.MOMENT_MAX or max(big.width(), big.height()) == max(
            h.v.width(), h.v.height()), "detail: full size"
        r = _call(h, server, "review_note", t=t_mark, text="Kante zu weich\n- deutlich härter", title="Kante",
                  quote="Die Kante hier ist mir zu weich.")
        assert not r["isError"], r
        note = sc.notes[-1]
        assert note.title == "Kante" and note.review["quote"].startswith("Die Kante") and note.review["t_end"] > t_mark
        assert note.anchors and note.anchors[0].curve_id == line.id, "anchor at the line shown"
        img = next(i for i in note.board["items"] if i["kind"] == "image")
        assert img.get("view") and sc.asset_bytes(img["file"]), "image with camera (double click flies there)"
        g = QGraphicsScene()
        _populate(g, sc, note.board)
        links = [l for l in (board_links.stroke_link(g, s) for s in g.items() if isinstance(s, StrokeItem)) if l]
        assert len(links) == 1 and isinstance(links[0]["source"], TextBlock), links
        _arrow_follows(g)
        g.clear()
        # survives saving
        path = os.path.join(base, "s.sketch.json")
        sc.save(path)
        loaded, _ = Scene.load(path)
        assert loaded.notes[-1].review == note.review
        # brief: draft as open
        data = brief.analyse(sc)
        assert any("Review-Entwurf" in str(p) for p in brief._open_points(data, "de"))
        # project note, without image
        n0 = len(sc.global_note.board.get("items", []))
        r = _call(h, server, "review_note", t=t_mark + 0.4, note="project", text="Richtung passt", images=[])
        assert not r["isError"] and len(sc.global_note.board["items"]) == n0 + 1, r
        assert "draft" in sc.global_note.board["items"][-1]["text"]
        # discard: only drafts
        assert _call(h, server, "review_note", note="N1", discard=True)["isError"], "N1 is not a draft"
        key = brief.index(sc)[1]["nid"][note.id]
        assert not _call(h, server, "review_note", note=key, discard=True)["isError"]
        assert note not in sc.notes
        h.sc.undo()
        assert any(n.review for n in sc.notes), "Ctrl+Z brings it back"
    finally:
        server.stop()
        _restore(old)
        shutil.rmtree(base, ignore_errors=True)


def _arrow_follows(g):
    """Mule arrow in board g: move and enlarge the image, move the text – the tip stays at the same
    spot in the image, the start at the text; saved and reloaded likewise."""
    from PySide6.QtCore import QPointF
    from sketch_machine import board_links
    from sketch_machine.note_board import ArrowItem, ImageItem, TextBlock, _populate, follow_arrows
    arrow = next(i for i in g.items() if isinstance(i, ArrowItem))
    img, text = arrow.dst, arrow.src
    assert isinstance(img, ImageItem) and isinstance(text, TextBlock), "arrow knows image and text"

    def spot():
        r = img.mapRectToScene(img.image_rect())
        return QPointF(r.left() + r.width() * arrow.uv[0], r.top() + r.height() * arrow.uv[1])
    before = arrow.pts[-1]
    assert abs(before.x() - spot().x()) < 0.2 and abs(before.y() - spot().y()) < 0.2
    img.setPos(img.pos() + QPointF(-300, 450))
    img.setScale(img.scale() * 1.5)
    text.setPos(text.pos() + QPointF(900, -200))
    assert follow_arrows(g) == 1 and follow_arrows(g) == 0, "once anew, then quiet"
    tip, start = arrow.pts[-1] + arrow.pos(), arrow.pts[0] + arrow.pos()
    assert abs(tip.x() - spot().x()) < 0.2 and abs(tip.y() - spot().y()) < 0.2, (tip, spot())
    from sketch_machine.note_board import _rect_gap
    assert _rect_gap(text.sceneBoundingRect(), start) < 20, "start at the text"
    link = board_links.stroke_link(g, arrow)
    assert link["source"] is text and link["target"] is img, "the brief still reads it as an arrow from the text to the image"
    # saved and reloaded: finds text and image again
    items = [i.data() if isinstance(i, ArrowItem) else None for i in g.items()]
    entry = next(e for e in items if e)
    assert entry["arrow"]["to"] == img.file and len(entry["pts"]) == 2
    g2 = QGraphicsScene()
    board = {"items": [{"kind": "image", "x": img.x(), "y": img.y(), "scale": img.scale(), "file": img.file},
                       {"kind": "text", "x": text.x(), "y": text.y(), "text": text.toPlainText()}, entry]}
    _populate(g2, type("S", (), {"asset_bytes": lambda self, f: None})(), board)
    a2 = next(i for i in g2.items() if isinstance(i, ArrowItem))
    assert isinstance(a2.dst, ImageItem) and isinstance(a2.src, TextBlock)
    g2.clear()


def test_board_accept(h: H):
    """In the board: bar with original sentence for drafts, ✓ Accept makes a normal note (one undo step)."""
    from tests.test_notes import _open_board, _close
    note, board = _open_board(h)
    try:
        note.review = {"review": "x", "t": 3.0, "t_end": 5.0, "quote": "Das Fenster ist zu klein."}
        board._load(note)
        h.pump(0.05)
        assert board.review_bar.isVisible() and "Fenster" in board.review_label.text()
        assert not board.review_play.isEnabled(), "without an audio recording nothing to play"
        board._review_accept()
        assert note.review is None and not board.review_bar.isVisible()
        h.sc.undo()
        assert h.sc.note_by_id(note.id).review is not None
    finally:
        _close(h, board)


def test_send_review_toolbar_button(h: H):
    """Menu "Review" next to Shots: only in Notes mode – and while a review runs in every mode (red, with time)."""
    base, old = _setup(h)
    try:
        h.new_scene()
        h.v.set_notes_mode(True)
        h.pump(0.05)
        assert h.w.review_item.isVisible(), "visible in Notes mode"
        h.v.set_notes_mode(False)
        h.pump(0.05)
        assert not h.w.review_item.isVisible(), "not while drawing"
        from PySide6.QtCore import QSettings
        QSettings("SketchMachine", "SketchMachine").setValue("whisper_ask_off", True)  # no prompt in the test
        h.w.toggle_review()
        h.pump(0.05)
        assert h.w.review_item.isVisible() and "●" in h.w.review_button.text(), "running: always visible"
        h.w.toggle_review()
        h.pump(0.05)
        assert not h.w.review_item.isVisible() and h.w.review_button.text() == "Review"
        h.w._fill_review_menu()
        texts = [a.text() for a in h.w.review_menu.actions()]
        assert h.w.review_action in h.w.review_menu.actions() and any("Review-Ordner" in t for t in texts), texts
    finally:
        _restore(old)
        shutil.rmtree(base, ignore_errors=True)


def test_backup_and_live_in_the_scene(h: H):
    """Before the first draft of a review a backup in review_backups/ (once per review); the drafts go live into
    the open scene, the path stays, nothing is saved; per scene the newest review_keep() stay."""
    from sketch_machine import backup
    base, old = _setup(h)
    server = mcp_server.Server(h.w, port=0).start()
    try:
        sc = _scene(h)
        original = os.path.join(base, "hafen_v006.mule")
        h.w.path = original
        h.w.save_scene()
        before = open(original, "rb").read()
        folder, line, t_mark = _record(h, sc)
        r = _call(h, server, "review_note", t=t_mark, text="Kante zu weich", quote="zu weich")
        assert not r["isError"] and "review_backups" in r["content"][0]["text"], r
        assert h.w.path == original and open(original, "rb").read() == before, "live, not saved"
        found = backup.backups(original, backup.REVIEW_FOLDER)
        assert len(found) == 1 and not any(n.review for n in Scene.load(found[0])[0].notes), "state before the review"
        _call(h, server, "review_note", t=t_mark, text="Noch ein Punkt", quote="noch")
        assert len(backup.backups(original, backup.REVIEW_FOLDER)) == 1, "once per review"
        for k in range(4):  # limit per scene
            backup.write(sc, original, folder=backup.REVIEW_FOLDER, keep=2, now=1_000_000 + k)
        assert len(backup.backups(original, backup.REVIEW_FOLDER)) == 2
    finally:
        server.stop()
        _restore(old)
        shutil.rmtree(base, ignore_errors=True)


def test_all_drafts_at_once(h: H):
    """review_notes: several drafts in one call, one undo step; a faulty one is named, the others
    come through anyway."""
    base, old = _setup(h)
    server = mcp_server.Server(h.w, port=0).start()
    try:
        sc = _scene(h)
        folder, line, t_mark = _record(h, sc)
        n0 = len(sc.notes)
        r = _call(h, server, "review_notes", notes=[
            {"mark": 1, "text": "Kante\n- härter", "quote": "zu weich"},
            {"t": t_mark, "text": "Linie\n- dicker", "quote": "dicker", "anchor": "L1"},
            {"mark": 9, "text": "gibt es nicht"}])
        text = r["content"][0]["text"]
        assert not r["isError"] and text.startswith("2 of 3") and "FAILED" in text, text
        assert len(sc.notes) == n0 + 2 and all(n.review for n in sc.notes[n0:])
        h.sc.undo()
        assert len(sc.notes) == n0, "one Ctrl+Z takes all back"
    finally:
        server.stop()
        _restore(old)
        shutil.rmtree(base, ignore_errors=True)


def test_send_review(h: H):
    """"Send Review": stop recording, backup, sentence to the clipboard, button "Ready"; when Claude reads the
    review, "Claude is working" spins; after review_notes "Send Review" again and a message."""
    from PySide6.QtWidgets import QApplication
    from sketch_machine import backup
    base, old = _setup(h)
    server = mcp_server.Server(h.w, port=0).start()
    keep_mcp = getattr(h.w, "mcp", None)
    try:
        sc = _scene(h)
        h.w.path = os.path.join(base, "szene.mule")
        h.w.save_scene()
        folder, line, t_mark = _record(h, sc)
        sender = h.w.review_sender
        sender.stop_waiting()  # the tests share the window
        sender._done_at = -1e9
        got = []
        sender.done.connect(lambda name, made: got.append((name, made)))
        h.w.send_review()
        name = os.path.basename(folder)
        assert sender.phase == "ready" and name in QApplication.clipboard().text()
        assert "Bereit" in h.w.review_send_button.text() and h.w.review_send_item.isVisible()
        assert len(backup.backups(h.w.path, backup.REVIEW_FOLDER)) == 1
        _call(h, server, "review_read")
        assert sender.phase == "working"
        h.pump(0.2)
        assert "Claude arbeitet" in h.w.review_send_button.text()
        _call(h, server, "review_notes", notes=[{"mark": 1, "text": "Kante", "quote": "zu weich"}])
        assert sender.phase == "idle" and got == [(name, 1)], got
        assert h.w.review_send_button.text() == "Review absenden"
        assert len(backup.backups(h.w.path, backup.REVIEW_FOLDER)) == 1, "no second backup when creating"
        # re-reading shortly after "done": display stays off
        _call(h, server, "review_read")
        assert sender.phase == "idle", "re-reading does not switch Claude-is-working on again"
        # single drafts (without review_notes): if nothing comes for a while, it is done
        _call(h, server, "review_note", mark=1, text="Einzeln", quote="zu weich")
        assert sender.phase == "working", "a new draft counts"
        _call(h, server, "scene_brief")
        assert time.monotonic() - sender._last_call < 1, "every Mule call keeps the display awake"
        sender._last_call -= review.DRAFT_SETTLE_S + 1
        sender._check_idle()
        assert sender.phase == "idle" and got[-1] == (name, 1), got
        # only read, then nothing more (Claude asks in the chat): off after IDLE_RESET_S, without a message
        sender._done_at -= review.RECHECK_S + 1
        _call(h, server, "review_read")
        assert sender.phase == "working"
        sender._last_call -= review.IDLE_RESET_S + 1
        sender._check_idle()
        assert sender.phase == "idle" and len(got) == 2
        # click on "Claude is working": display off
        sender._done_at -= review.RECHECK_S + 1
        _call(h, server, "review_read")
        h.w.send_review()
        assert sender.phase == "idle" and h.w.review_send_button.text() == "Review absenden"
    finally:
        server.stop()
        _restore(old)
        shutil.rmtree(base, ignore_errors=True)

def test_without_pointing_no_arrow(h: H):
    """review_note moves t to the nearest mark or cursor rest; if nothing was pointed at nearby, there is neither an arrow
    nor an anchor at the cursor (better none than a wrong one) – with a part id still a leader line."""
    from sketch_machine import board_links
    from sketch_machine.note_board import StrokeItem, _populate
    base, old = _setup(h)
    server = mcp_server.Server(h.w, port=0).start()
    keep = h.w.path
    try:
        sc = _scene(h)
        folder, line, t_mark = _record(h, sc)
        events = review.read_log(folder)
        cam = [e for e in events if e["typ"] == "kamera"][-1]
        with open(os.path.join(folder, review.LOG), "a", encoding="utf-8") as f:  # later: only navigated
            f.write(json.dumps({**cam, "t": 30.0}) + "\n")
            f.write(json.dumps({"t": 30.2, "typ": "maus", "vp": 0, "x": 0.5, "y": 0.5}) + "\n")
        assert review.pointing_near(review.read_log(folder), 30.5) is None
        assert review.pointing_near(events, t_mark + 3)["typ"] == "marke"
        r = _call(h, server, "review_note", t=30.5, text="Allgemein zu hell", quote="zu hell")
        assert not r["isError"] and "No pointing" in r["content"][0]["text"], r
        note = sc.notes[-1]
        assert not note.anchors, "no anchor at the cursor"
        g = QGraphicsScene()
        _populate(g, sc, note.board)
        assert not any(board_links.stroke_link(g, s) for s in g.items() if isinstance(s, StrokeItem)), "no arrow"
        g.clear()
        r = _call(h, server, "review_note", t=30.5, text="Linie zu dünn", quote="dünn", anchor="L1")
        assert sc.notes[-1].anchors[0].curve_id == line.id
        r = _call(h, server, "review_note", mark=1, text="An der Marke", quote="hier")
        assert "mark 1" in r["content"][0]["text"] and sc.notes[-1].anchors[0].curve_id == line.id, r
    finally:
        h.w.path = keep
        server.stop()
        _restore(old)
        shutil.rmtree(base, ignore_errors=True)


def _click(widget, local, mods=None):
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import QApplication
    lp = QPointF(local)
    for kind in (QEvent.MouseButtonPress, QEvent.MouseButtonRelease):
        QApplication.sendEvent(widget, QMouseEvent(kind, lp, widget.mapToGlobal(lp), Qt.LeftButton,
                                                   Qt.LeftButton if kind == QEvent.MouseButtonPress else Qt.NoButton,
                                                   mods if mods is not None else Qt.NoModifier))


def test_mark_tool(h: H):
    """Tool "Mark" (instead of holding F8, 14.11.): on at the start, preview ring at the cursor; every simple click into
    the view sets a mark and does not go to the tool; Alt+click (navigating) passes through; Ctrl+Z takes the
    last mark back, not the scene undo; off: clicks go to the tool; F8/F9 do nothing anymore."""
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent
    from PySide6.QtWidgets import QApplication
    base, old = _setup(h)
    try:
        sc = _scene(h)
        line = sc.strokes[0].curves[0]
        h.frame(np.vstack([line.points, [[0, 1, 0]]]))
        session = review.ReviewSession(h.w)
        on_line = h.scr(line.points[2])
        session.cursor = lambda: h.v.mapToGlobal(on_line)
        folder = session.start()
        assert session.marking, "Mark is on at the start"
        h.pump(0.15)
        aim = h.v.ws.review_aim
        assert aim is not None and aim["hit"], "preview ring hits the line"
        n_curves = len(h.curves())
        _click(h.v, on_line)
        h.pump(0.1)
        assert len(h.v.ws.review_pins) == 1, "click sets exactly one mark"
        assert len(h.curves()) == n_curves, "the click draws nothing"
        _click(h.v, on_line, Qt.AltModifier)
        assert len(h.v.ws.review_pins) == 1, "Alt+click navigates, sets no mark"
        for k in (Qt.Key_F8, Qt.Key_F9):
            QApplication.sendEvent(h.v, QKeyEvent(QEvent.KeyPress, k, Qt.NoModifier))
            QApplication.sendEvent(h.v, QKeyEvent(QEvent.KeyRelease, k, Qt.NoModifier))
        assert session.active and len(h.v.ws.review_pins) == 1, "F8/F9 do nothing anymore"
        _click(h.v, on_line)
        assert len(h.v.ws.review_pins) == 2
        undo_before = len(sc._undo)
        for kind in (QEvent.ShortcutOverride, QEvent.KeyPress, QEvent.KeyRelease):
            QApplication.sendEvent(h.v, QKeyEvent(kind, Qt.Key_Z, Qt.ControlModifier))
        assert [p["n"] for p in h.v.ws.review_pins] == [1], "Ctrl+Z takes the last mark back"
        assert len(sc._undo) == undo_before and len(h.curves()) == n_curves, "not the scene undo"
        session.set_marking(False)
        assert h.v.ws.review_aim is None, "off: no ring"
        _click(h.v, on_line)
        assert len(h.v.ws.review_pins) == 1, "off: clicks go to the tool"
        session.set_marking(True)
        session.stop(transcribe=False)
        assert not session.marking
        marks = [e for e in review.read_log(folder) if e["typ"] == "marke"]
        assert [e["n"] for e in marks] == [1] and marks[0]["curve"] == line.id, marks
    finally:
        _restore(old)
        shutil.rmtree(base, ignore_errors=True)


def test_spoken_hier_points(h: H):
    """The German word "hier" ("here") in the transcript (camera and cursor still) counts as pointing: review_note moves there,
    arrow and anchor at the spot under the cursor; spoken while navigating it does not count."""
    base, old = _setup(h)
    server = mcp_server.Server(h.w, port=0).start()
    try:
        sc = _scene(h)
        folder, line, t_mark = _record(h, sc)
        events = review.read_log(folder)
        cam = [e for e in events if e["typ"] == "kamera"][0]
        on = next(e for e in events if e["typ"] == "ziel")
        with open(os.path.join(folder, review.LOG), "a", encoding="utf-8") as f:  # later: back on the line
            f.write(json.dumps({**cam, "t": 40.0}) + "\n")
            f.write(json.dumps({"t": 40.1, "typ": "maus", "vp": 0, "x": on["x"], "y": on["y"]}) + "\n")
            f.write(json.dumps({**cam, "t": 50.0, "dist": cam["dist"] * 1.1}) + "\n")
        tr_ = {"segments": [{"start": 41.0, "end": 43.0, "text": "Die Kante hier.",
                             "words": [["Die", 41.0, 41.2], ["Kante", 41.2, 41.6], ["hier.", 41.7, 42.0]]},
                            {"start": 49.8, "end": 50.4, "text": "hier", "words": [["hier", 49.9, 50.1]]}]}
        with open(os.path.join(folder, review.TRANSCRIPT), "w", encoding="utf-8") as f:
            json.dump(tr_, f)
        words = review.word_pointings(review.read_log(folder), tr_)
        assert [w["t"] for w in words] == [41.85], "spoken while navigating does not count"
        h.camera([5, 5, 5], 9.0, (1.0, 0.2, 0.0))  # now a completely different view
        r = _call(h, server, "review_note", t=42.5, text="Kante", quote="Die Kante hier.")
        assert not r["isError"] and "spoken „hier“" in r["content"][0]["text"], r
        assert sc.notes[-1].anchors and sc.notes[-1].anchors[0].curve_id == line.id, "anchor under the cursor at the word"
        assert "said „hier“" in _call(h, server, "review_read")["content"][0]["text"]
    finally:
        server.stop()
        _restore(old)
        shutil.rmtree(base, ignore_errors=True)


def test_images_from_folders(h: H):
    """insert_images: image files (absolute or relative to the scene) onto the board, with caption and arrow from the text;
    the same file not twice; missing and unreadable ones are named; one undo step."""
    from PySide6.QtGui import QImage, QColor
    from sketch_machine import board_links
    from sketch_machine.note_board import StrokeItem, _populate
    base = tempfile.mkdtemp()
    server = mcp_server.Server(h.w, port=0).start()
    keep = h.w.path
    try:
        sc = _scene(h)
        h.w.path = os.path.join(base, "szene.mule")
        os.makedirs(os.path.join(base, "referenz"))
        img = QImage(120, 80, QImage.Format_RGB32)
        img.fill(QColor(90, 120, 60))
        img.save(os.path.join(base, "referenz", "fels.png"))
        open(os.path.join(base, "kaputt.png"), "wb").write(b"kein Bild")
        r = _call(h, server, "insert_images", note="N1", text="Felswand wie hier",
                  files=[{"path": "referenz/fels.png", "caption": "Abgesprengter Fels", "at": [0.3, 0.6]},
                         {"path": "gibtsnicht.jpg"}, {"path": os.path.join(base, "kaputt.png")}])
        text = r["content"][0]["text"]
        assert not r["isError"] and "1 picture(s)" in text and "gibtsnicht.jpg" in text and "kaputt.png" in text, text
        items = sc.notes[0].board["items"]
        pic = next(i for i in items if i["kind"] == "image")
        assert pic["file"].endswith(".png") and pic["caption"] == "Abgesprengter Fels" and "view" not in pic
        g = QGraphicsScene()
        _populate(g, sc, sc.notes[0].board)
        links = [l for l in (board_links.stroke_link(g, s) for s in g.items() if isinstance(s, StrokeItem)) if l]
        assert len(links) == 1 and abs(links[0]["uv"][0] - 0.3) < 0.03, links
        g.clear()
        r = _call(h, server, "insert_images", note="N1", files=[{"path": "referenz/fels.png"}])
        assert "Already on that board" in r["content"][0]["text"], r
        h.sc.undo()
        assert not any(i["kind"] == "image" for i in sc.notes[0].board.get("items", [])), "one undo step"
    finally:
        h.w.path = keep
        server.stop()
        shutil.rmtree(base, ignore_errors=True)


def test_set_up_whisper(h: H):
    """Set up transcription: the steps run one after another as separate processes, at the end Mule knows the Python
    (setting whisper_python); a failing step stops; without Python the dialog explains python.org."""
    import sys
    from PySide6.QtCore import QSettings
    from sketch_machine import whisper_setup
    ok_plan = [("eins", [sys.executable, "-c", "print('a')"]), ("zwei", [sys.executable, "-c", "print('b')"])]
    dlg = whisper_setup.SetupDialog(h.w, python=sys.executable, plan=ok_plan)
    dlg.show()
    dlg._start()
    for _ in range(300):
        h.pump(0.02)
        if dlg.setup is None:
            break
    assert dlg.ok and "b" in dlg.log.toPlainText(), dlg.step.text()
    assert QSettings("SketchMachine", "SketchMachine").value("whisper_python") == whisper_setup.venv_python()
    dlg.close()
    bad = whisper_setup.SetupDialog(h.w, python=sys.executable,
                                    plan=[("kaputt", [sys.executable, "-c", "import sys; sys.exit(3)"]), ok_plan[0]])
    bad._start()
    for _ in range(300):
        h.pump(0.02)
        if bad.setup is None:
            break
    assert not bad.ok and "kaputt" in bad.step.text() and bad.go.isEnabled(), bad.step.text()
    bad.close()
    none = whisper_setup.SetupDialog(h.w, python="")
    assert "python.org" in none.info.text() and not none.go.isEnabled() and not none.again.isHidden()
    none.close()
    gpu = whisper_setup.steps(sys.executable, gpu=True)[1][1]
    assert len(gpu) > len(whisper_setup.steps(sys.executable, gpu=False)[1][1])


def test_board_mark_image_into_the_note(h: H):
    """Mark: click on an image in the open board (project note as a reference board): board mark with image and spot in the
    image; review_read names it; review_note with refs puts the image into the note for the part, arrow to the spot –
    the same image (no second one in the file), it also stays on the project note."""
    import hashlib
    from PySide6.QtCore import QBuffer, QEvent, QIODevice, QPointF, Qt
    from PySide6.QtGui import QColor, QImage, QKeyEvent, QMouseEvent
    from PySide6.QtWidgets import QApplication
    from sketch_machine import board_links
    from sketch_machine.note_board import ImageItem, StrokeItem, _populate, board_for
    base, old = _setup(h)
    server = mcp_server.Server(h.w, port=0).start()
    board = None
    try:
        sc = _scene(h)
        pic = QImage(200, 100, QImage.Format_RGB32)
        pic.fill(QColor(200, 40, 40))
        buf = QBuffer()
        buf.open(QIODevice.WriteOnly)
        pic.save(buf, "PNG")
        data = bytes(buf.data())
        name = hashlib.sha1(data).hexdigest()[:16] + ".png"
        sc.assets[name] = data
        sc.global_note.board = {"items": [{"kind": "image", "x": 0, "y": 0, "scale": 1.0, "file": name,
                                           "caption": "Tank reference"}]}
        line = sc.strokes[0].curves[0]
        h.frame(np.vstack([line.points, [[0, 1, 0]]]))
        session = review.ReviewSession(h.w)
        on_line = h.scr(line.points[2])
        pos = {"p": h.v.mapToGlobal(on_line)}
        session.cursor = lambda: pos["p"]
        folder = session.start()
        h.pump(0.3)
        assert session.mark() == 1, "mark at the tank (line)"
        board = board_for(h.v)
        board.open(h.v, sc.global_note.id)
        h.pump(0.2)
        item = next(i for i in board.gscene.items() if isinstance(i, ImageItem))
        r = item.image_rect()
        at = item.mapToScene(QPointF(r.left() + 0.25 * r.width(), r.top() + 0.75 * r.height()))
        port = board.view.viewport()
        local = board.view.mapFromScene(at)
        pos["p"] = port.mapToGlobal(local)
        h.pump(0.1)
        _click(port, local)  # tool "Mark" is on
        h.pump(0.1)
        assert len(sc.global_note.board["items"]) == 1, "the marking click moves and paints nothing on the board"
        t_end = session.elapsed()
        session.stop(transcribe=False)
        board.close_board()
        h.v.set_notes_mode(False)
        bm = [e for e in review.read_log(folder) if e["typ"] == "brettmarke"]
        assert len(bm) == 1 and bm[0]["n"] == 2 and bm[0]["datei"] == name, bm
        u, v = bm[0]["uv"]
        assert abs(u - 0.25) < 0.03 and abs(v - 0.75) < 0.03, f"spot in the image {u}, {v}"
        assert bm[0]["brett"] == sc.global_note.id and os.path.isfile(os.path.join(folder, bm[0]["bild"]))
        with open(os.path.join(folder, review.TRANSCRIPT), "w", encoding="utf-8") as f:
            json.dump({"language": "de", "model": "test", "segments": [
                {"start": 0.0, "end": round(t_end, 2), "text": "Der Tank soll so aussehen wie hier."}]}, f)
        text = _call(h, server, "review_read")["content"][0]["text"]
        assert "BOARD MARK 2" in text and "Tank reference" in text and "project note" in text, text
        assert _call(h, server, "review_note", mark=2, text="x")["isError"], "board mark is not a t"
        n_assets = len(sc.assets)
        r = _call(h, server, "review_note", mark=1, refs=[2], title="Tank",
                  text="Tank\n- Form wie auf dem Referenzfoto")
        assert not r["isError"], r
        note = sc.notes[-1]
        imgs = [i for i in note.board["items"] if i["kind"] == "image"]
        assert len(imgs) == 2 and imgs[1]["file"] == name, imgs
        assert len(sc.assets) == n_assets + 1, "only the 3D image is new, the reference image already exists"
        assert len(sc.global_note.board["items"]) == 1, "stays on the project note"
        g = QGraphicsScene()
        _populate(g, sc, note.board)
        links = [l for l in (board_links.stroke_link(g, s) for s in g.items() if isinstance(s, StrokeItem)) if l]
        assert len(links) == 2, f"arrow to each image: {len(links)}"
        g.clear()
    finally:
        if board is not None and board.isVisible():
            board.close_board()
        server.stop()
        _restore(old)
        shutil.rmtree(base, ignore_errors=True)


def test_chat_sentence_in_the_language_of_mule(h: H):
    """"Send Review" puts a sentence for the chat on the clipboard – in English if Mule speaks English
    (otherwise Claude answers in German)."""
    from sketch_machine import i18n
    sender = review.ReviewSender(h.w, review.ReviewSession(h.w))
    old = i18n.LANG
    try:
        i18n.LANG = "en"
        assert sender.prompt("x/Hafen_2026") == "Review is ready: „Hafen_2026“ – please make drafts from it."
        i18n.LANG = "de"
        assert sender.prompt("x/Hafen_2026").startswith("Review ist da: „Hafen_2026“")
    finally:
        i18n.LANG = old


def test_arrow_follows_in_the_open_board(h: H):
    """Open board: dictated text with an arrow to the image; move the image – the arrow follows without further action
    (gscene.changed) and is stored that way in the note; a painted stroke stays where it is."""
    from PySide6.QtCore import QPointF
    from tests.test_notes import _png, _open_board, _close
    from sketch_machine.note_board import ArrowItem, ImageItem, StrokeItem, add_dictated_text
    note, board = _open_board(h)
    try:
        h.v.scene.assets["ref.png"] = _png(200, 100)
        board.gscene.clear()
        from sketch_machine.note_board import _populate
        _populate(board.gscene, h.v.scene, {"items": [
            {"kind": "image", "x": 0, "y": 0, "scale": 1.0, "file": "ref.png"},
            {"kind": "stroke", "pts": [[0, 300], [100, 300]], "w": [2, 2]}]})
        board.commit()
        add_dictated_text(h.v, note, "Ecke hier", [("ref.png", (0.75, 0.25))])
        h.pump(0.05)
        arrow = next(i for i in board.gscene.items() if isinstance(i, ArrowItem))
        img = next(i for i in board.gscene.items() if isinstance(i, ImageItem))
        drawn = next(i for i in board.gscene.items() if type(i) is StrokeItem)
        img.setPos(400, 600)
        h.pump(0.05)
        tip = arrow.pts[-1] + arrow.pos()
        assert abs(tip.x() - 550) < 0.5 and abs(tip.y() - 625) < 0.5, tip
        assert drawn.pts[0] == QPointF(0, 300), "painted stroke stays"
        board.commit()
        entry = next(e for e in note.board["items"] if e.get("arrow"))
        assert entry["pts"][-1] == [550.0, 625.0] and entry["arrow"] == {"to": "ref.png", "uv": [0.75, 0.25]}
    finally:
        _close(h, board)

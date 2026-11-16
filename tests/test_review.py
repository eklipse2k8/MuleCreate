"""Review-Modus (review.py): Aufnahme von Kamera, Cursor, Zielen und „Hier!“-Marken; Claude liest sie über MCP
(review_read, review_moment) und legt Entwurfs-Notizen an (review_note) – mit Bild aus der damaligen Kamera, Pfeil auf
die Cursorstelle, Anker am gezeigten Teil, Originalsatz; im Brett übernehmen bzw. verwerfen."""
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
from tests.test_brief_inhalt import _scene
from sketch_machine import mcp_server, review
from sketch_machine.scene import Scene


class _SilentAudio:
    """Statt Mikrofon: eine Sekunde Stille als ton.wav (Tests nehmen nie echt auf)."""

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
    h.w.path = None  # die Tests teilen sich das Fenster: kein Pfad aus einem früheren Test
    return base, old


def _restore(old):
    review.reviews_dir, review.AudioWriter, path, h = old
    h.w.path = path


def _record(h, sc):
    """Review aufnehmen: Cursor ruht auf der Linie, „Hier!“, dann Kamera gedreht und Cursor ins Leere."""
    line = sc.strokes[0].curves[0]
    h.frame(np.vstack([line.points, [[0, 1, 0]]]))
    session = review.ReviewSession(h.w)
    on_line = h.scr(line.points[2])
    pos = {"p": h.v.mapToGlobal(on_line)}
    session.cursor = lambda: pos["p"]
    folder = session.start()
    h.pump(0.6)  # Cursor ruht -> Ziel
    t_mark = session.elapsed()
    assert session.mark() == 1
    pins = h.v.ws.review_pins
    assert len(pins) == 1 and pins[0]["point"] is not None and session.last_mark["hit"], "Stecknadel an der Linie"
    h.grab()  # zeichnet die Stecknadel (darf nicht stören)
    h.pump(0.2)
    from sketch_machine.scene import Note  # eigene Änderungen während des Reviews: Notiz anlegen, Linie zeichnen
    sc.notes.append(Note("Meine Notiz", np.array([0.0, 1.0, 0.0]),
                         board={"items": [{"kind": "text", "x": 0, "y": 0, "w": 200, "text": "selbst"}]}))
    sc.add_curve(np.array([[0.0, 0.5, 0.0], [1.0, 0.5, 0.0]]), None)
    h.pump(0.7)
    h.camera([0.5, 0, 0], 3.0, (0.0, 1.0, 0.2))  # andere Ansicht
    pos["p"] = h.v.mapToGlobal(QPoint(5, 5))
    h.pump(0.5)
    t_end = session.elapsed()
    session.stop(transcribe=False)
    assert h.v.ws.review_pins == [], "Stecknadeln nur während des Reviews"
    with open(os.path.join(folder, review.TRANSCRIPT), "w", encoding="utf-8") as f:
        json.dump({"language": "de", "model": "test", "segments": [
            {"start": 0.0, "end": round(t_mark + 0.2, 2), "text": "Die Kante hier ist mir zu weich."},
            {"start": round(t_mark + 0.3, 2), "end": round(t_end, 2), "text": "Insgesamt passt die Richtung."}]}, f)
    return folder, line, t_mark


def test_aufnahme_protokoll(h: H):
    """Protokoll: Kamera bei Änderung, Maus, Ziel unter dem ruhenden Cursor, Marke mit Bild, review.json."""
    base, old = _setup(h)
    try:
        sc = _scene(h)
        folder, line, t_mark = _record(h, sc)
        events = review.read_log(folder)
        kinds = [e["typ"] for e in events]
        assert kinds[0] == "start" and kinds[-1] == "ende", kinds
        assert kinds.count("kamera") >= 2, "Kamerawechsel mitgeschrieben"
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


def test_mcp_review_zu_entwurf(h: H):
    """review_read nennt Text, Ziel (L#) und Marke; review_moment rendert die damalige Ansicht; review_note legt einen
    Entwurf an (Anker an der Linie, Bild mit Kamera, Pfeil auf die Cursorstelle, Originalsatz); bleibt beim Speichern;
    Projekt-Notiz bekommt allgemeine Punkte; discard nur für Entwürfe; Brief nennt Entwürfe als offen."""
    from sketch_machine import board_links, brief
    from sketch_machine.note_board import StrokeItem, TextBlock, _populate
    base, old = _setup(h)
    server = mcp_server.Server(h.w, port=0).start()
    try:
        sc = _scene(h)
        folder, line, t_mark = _record(h, sc)
        text = _call(h, server, "review_read")["content"][0]["text"]
        assert "Die Kante hier ist mir zu weich." in text and "cursor on L1" in text and "MARK 1" in text, text
        assert "created note N2 „Meine Notiz“" in text and "drew 1 line(s)" in text, text
        r = _call(h, server, "review_moment", times=[t_mark])
        assert not r["isError"] and r["content"][1]["type"] == "image" and "L1" in r["content"][0]["text"], r
        import base64
        from PySide6.QtGui import QImage
        small = QImage.fromData(base64.b64decode(r["content"][1]["data"]))
        assert max(small.width(), small.height()) <= mcp_server.MOMENT_MAX, "zum Prüfen klein"
        big = _call(h, server, "review_moment", times=[t_mark], detail=True)["content"][1]["data"]
        big = QImage.fromData(base64.b64decode(big))
        assert max(big.width(), big.height()) > mcp_server.MOMENT_MAX or max(big.width(), big.height()) == max(
            h.v.width(), h.v.height()), "detail: volle Größe"
        r = _call(h, server, "review_note", t=t_mark, text="Kante zu weich\n- deutlich härter", title="Kante",
                  quote="Die Kante hier ist mir zu weich.")
        assert not r["isError"], r
        note = sc.notes[-1]
        assert note.title == "Kante" and note.review["quote"].startswith("Die Kante") and note.review["t_end"] > t_mark
        assert note.anchors and note.anchors[0].curve_id == line.id, "Anker an der gezeigten Linie"
        img = next(i for i in note.board["items"] if i["kind"] == "image")
        assert img.get("view") and sc.asset_bytes(img["file"]), "Bild mit Kamera (Doppelklick fliegt hin)"
        g = QGraphicsScene()
        _populate(g, sc, note.board)
        links = [l for l in (board_links.stroke_link(g, s) for s in g.items() if isinstance(s, StrokeItem)) if l]
        assert len(links) == 1 and isinstance(links[0]["source"], TextBlock), links
        _pfeil_folgt(g)
        g.clear()
        # bleibt beim Speichern
        path = os.path.join(base, "s.sketch.json")
        sc.save(path)
        loaded, _ = Scene.load(path)
        assert loaded.notes[-1].review == note.review
        # Brief: Entwurf als offen
        data = brief.analyse(sc)
        assert any("Review-Entwurf" in str(p) for p in brief._open_points(data, "de"))
        # Projekt-Notiz, ohne Bild
        n0 = len(sc.global_note.board.get("items", []))
        r = _call(h, server, "review_note", t=t_mark + 0.4, note="project", text="Richtung passt", images=[])
        assert not r["isError"] and len(sc.global_note.board["items"]) == n0 + 1, r
        assert "draft" in sc.global_note.board["items"][-1]["text"]
        # verwerfen: nur Entwürfe
        assert _call(h, server, "review_note", note="N1", discard=True)["isError"], "N1 ist kein Entwurf"
        key = brief.index(sc)[1]["nid"][note.id]
        assert not _call(h, server, "review_note", note=key, discard=True)["isError"]
        assert note not in sc.notes
        h.sc.undo()
        assert any(n.review for n in sc.notes), "Strg+Z holt ihn zurück"
    finally:
        server.stop()
        _restore(old)
        shutil.rmtree(base, ignore_errors=True)


def _pfeil_folgt(g):
    """Mule-Pfeil im Brett g: Bild verschieben und vergrößern, Text verschieben – Spitze bleibt an derselben
    Bildstelle, Anfang am Text; gespeichert und neu geladen ebenso."""
    from PySide6.QtCore import QPointF
    from sketch_machine import board_links
    from sketch_machine.note_board import ArrowItem, ImageItem, TextBlock, _populate, follow_arrows
    arrow = next(i for i in g.items() if isinstance(i, ArrowItem))
    img, text = arrow.dst, arrow.src
    assert isinstance(img, ImageItem) and isinstance(text, TextBlock), "Pfeil kennt Bild und Text"

    def spot():
        r = img.mapRectToScene(img.image_rect())
        return QPointF(r.left() + r.width() * arrow.uv[0], r.top() + r.height() * arrow.uv[1])
    before = arrow.pts[-1]
    assert abs(before.x() - spot().x()) < 0.2 and abs(before.y() - spot().y()) < 0.2
    img.setPos(img.pos() + QPointF(-300, 450))
    img.setScale(img.scale() * 1.5)
    text.setPos(text.pos() + QPointF(900, -200))
    assert follow_arrows(g) == 1 and follow_arrows(g) == 0, "einmal neu, dann ruhig"
    tip, start = arrow.pts[-1] + arrow.pos(), arrow.pts[0] + arrow.pos()
    assert abs(tip.x() - spot().x()) < 0.2 and abs(tip.y() - spot().y()) < 0.2, (tip, spot())
    from sketch_machine.note_board import _rect_gap
    assert _rect_gap(text.sceneBoundingRect(), start) < 20, "Anfang am Text"
    link = board_links.stroke_link(g, arrow)
    assert link["source"] is text and link["target"] is img, "Brief liest ihn weiter als Pfeil vom Text aufs Bild"
    # gespeichert und neu geladen: findet Text und Bild wieder
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


def test_brett_uebernehmen(h: H):
    """Im Brett: Leiste mit Originalsatz bei Entwürfen, ✓ Übernehmen macht eine normale Notiz (ein Undo-Schritt)."""
    from tests.test_notizen import _open_board, _close
    note, board = _open_board(h)
    try:
        note.review = {"review": "x", "t": 3.0, "t_end": 5.0, "quote": "Das Fenster ist zu klein."}
        board._load(note)
        h.pump(0.05)
        assert board.review_bar.isVisible() and "Fenster" in board.review_label.text()
        assert not board.review_play.isEnabled(), "ohne Tonaufnahme nichts abzuspielen"
        board._review_accept()
        assert note.review is None and not board.review_bar.isVisible()
        h.sc.undo()
        assert h.sc.note_by_id(note.id).review is not None
    finally:
        _close(h, board)


def test_review_knopf_in_der_leiste(h: H):
    """Menü „Review“ neben Shots: nur im Notizmodus – und solange ein Review läuft in jedem Modus (rot, mit Zeit)."""
    base, old = _setup(h)
    try:
        h.new_scene()
        h.v.set_notes_mode(True)
        h.pump(0.05)
        assert h.w.review_item.isVisible(), "im Notizmodus sichtbar"
        h.v.set_notes_mode(False)
        h.pump(0.05)
        assert not h.w.review_item.isVisible(), "beim Zeichnen nicht"
        from PySide6.QtCore import QSettings
        QSettings("SketchMachine", "SketchMachine").setValue("whisper_ask_off", True)  # keine Rückfrage im Test
        h.w.toggle_review()
        h.pump(0.05)
        assert h.w.review_item.isVisible() and "●" in h.w.review_button.text(), "läuft: immer sichtbar"
        h.w.toggle_review()
        h.pump(0.05)
        assert not h.w.review_item.isVisible() and h.w.review_button.text() == "Review"
        h.w._fill_review_menu()
        texts = [a.text() for a in h.w.review_menu.actions()]
        assert h.w.review_action in h.w.review_menu.actions() and any("Review-Ordner" in t for t in texts), texts
    finally:
        _restore(old)
        shutil.rmtree(base, ignore_errors=True)


def test_backup_und_live_in_der_szene(h: H):
    """Vor dem ersten Entwurf eines Reviews ein Backup in review_backups/ (einmal je Review); die Entwürfe gehen live in
    die offene Szene, der Pfad bleibt, nichts wird gespeichert; je Szene bleiben die neuesten review_keep()."""
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
        assert h.w.path == original and open(original, "rb").read() == before, "live, nicht gespeichert"
        found = backup.backups(original, backup.REVIEW_FOLDER)
        assert len(found) == 1 and not any(n.review for n in Scene.load(found[0])[0].notes), "Stand vor dem Review"
        _call(h, server, "review_note", t=t_mark, text="Noch ein Punkt", quote="noch")
        assert len(backup.backups(original, backup.REVIEW_FOLDER)) == 1, "einmal je Review"
        for k in range(4):  # Grenze je Szene
            backup.write(sc, original, folder=backup.REVIEW_FOLDER, keep=2, now=1_000_000 + k)
        assert len(backup.backups(original, backup.REVIEW_FOLDER)) == 2
    finally:
        server.stop()
        _restore(old)
        shutil.rmtree(base, ignore_errors=True)


def test_alle_entwuerfe_auf_einmal(h: H):
    """review_notes: mehrere Entwürfe in einem Aufruf, ein Undo-Schritt; ein fehlerhafter wird genannt, die anderen
    kommen trotzdem."""
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
        assert len(sc.notes) == n0, "ein Strg+Z nimmt alle zurück"
    finally:
        server.stop()
        _restore(old)
        shutil.rmtree(base, ignore_errors=True)


def test_review_absenden(h: H):
    """„Review absenden“: Aufnahme beenden, Backup, Satz in die Zwischenablage, Knopf „Bereit“; liest Claude das
    Review, dreht sich „Claude arbeitet“; nach review_notes wieder „Review absenden“ und eine Meldung."""
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
        sender.stop_waiting()  # die Tests teilen sich das Fenster
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
        assert len(backup.backups(h.w.path, backup.REVIEW_FOLDER)) == 1, "kein zweites Backup beim Anlegen"
        # Nachlesen kurz nach „fertig“: Anzeige bleibt aus
        _call(h, server, "review_read")
        assert sender.phase == "idle", "Nachlesen schaltet „Claude arbeitet“ nicht wieder an"
        # einzelne Entwürfe (ohne review_notes): kommt eine Weile nichts mehr, ist es fertig
        _call(h, server, "review_note", mark=1, text="Einzeln", quote="zu weich")
        assert sender.phase == "working", "ein neuer Entwurf zählt"
        _call(h, server, "scene_brief")
        assert time.monotonic() - sender._last_call < 1, "jeder Mule-Aufruf hält die Anzeige wach"
        sender._last_call -= review.DRAFT_SETTLE_S + 1
        sender._check_idle()
        assert sender.phase == "idle" and got[-1] == (name, 1), got
        # nur gelesen, dann nichts mehr (Claude fragt im Chat nach): nach IDLE_RESET_S aus, ohne Meldung
        sender._done_at -= review.RECHECK_S + 1
        _call(h, server, "review_read")
        assert sender.phase == "working"
        sender._last_call -= review.IDLE_RESET_S + 1
        sender._check_idle()
        assert sender.phase == "idle" and len(got) == 2
        # Klick auf „Claude arbeitet“: Anzeige aus
        sender._done_at -= review.RECHECK_S + 1
        _call(h, server, "review_read")
        h.w.send_review()
        assert sender.phase == "idle" and h.w.review_send_button.text() == "Review absenden"
    finally:
        server.stop()
        _restore(old)
        shutil.rmtree(base, ignore_errors=True)

def test_ohne_zeigen_kein_pfeil(h: H):
    """review_note rückt t auf die nächste Marke bzw. Cursor-Ruhe; wurde in der Nähe nicht gezeigt, gibt es weder Pfeil
    noch Anker am Cursor (lieber keiner als ein falscher) – mit Teil-Kennung trotzdem eine Hinweislinie."""
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
        with open(os.path.join(folder, review.LOG), "a", encoding="utf-8") as f:  # später: nur navigiert
            f.write(json.dumps({**cam, "t": 30.0}) + "\n")
            f.write(json.dumps({"t": 30.2, "typ": "maus", "vp": 0, "x": 0.5, "y": 0.5}) + "\n")
        assert review.pointing_near(review.read_log(folder), 30.5) is None
        assert review.pointing_near(events, t_mark + 3)["typ"] == "marke"
        r = _call(h, server, "review_note", t=30.5, text="Allgemein zu hell", quote="zu hell")
        assert not r["isError"] and "No pointing" in r["content"][0]["text"], r
        note = sc.notes[-1]
        assert not note.anchors, "kein Anker am Cursor"
        g = QGraphicsScene()
        _populate(g, sc, note.board)
        assert not any(board_links.stroke_link(g, s) for s in g.items() if isinstance(s, StrokeItem)), "kein Pfeil"
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


def test_markieren_werkzeug(h: H):
    """Werkzeug „Markieren“ (statt F8 halten, 14.11.): beim Start an, Vorschau-Ring am Cursor; jeder einfache Klick in
    die Ansicht setzt eine Marke und geht nicht ans Werkzeug; Alt+Klick (Navigieren) geht durch; Strg+Z nimmt die
    letzte Marke zurück, nicht das Undo der Szene; aus: Klicks gehen ans Werkzeug; F8/F9 tun nichts mehr."""
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
        assert session.marking, "Markieren ist beim Start an"
        h.pump(0.15)
        aim = h.v.ws.review_aim
        assert aim is not None and aim["hit"], "Vorschau-Ring trifft die Linie"
        n_curves = len(h.curves())
        _click(h.v, on_line)
        h.pump(0.1)
        assert len(h.v.ws.review_pins) == 1, "Klick setzt genau eine Marke"
        assert len(h.curves()) == n_curves, "der Klick zeichnet nichts"
        _click(h.v, on_line, Qt.AltModifier)
        assert len(h.v.ws.review_pins) == 1, "Alt+Klick navigiert, setzt keine Marke"
        for k in (Qt.Key_F8, Qt.Key_F9):
            QApplication.sendEvent(h.v, QKeyEvent(QEvent.KeyPress, k, Qt.NoModifier))
            QApplication.sendEvent(h.v, QKeyEvent(QEvent.KeyRelease, k, Qt.NoModifier))
        assert session.active and len(h.v.ws.review_pins) == 1, "F8/F9 tun nichts mehr"
        _click(h.v, on_line)
        assert len(h.v.ws.review_pins) == 2
        undo_before = len(sc._undo)
        for kind in (QEvent.ShortcutOverride, QEvent.KeyPress, QEvent.KeyRelease):
            QApplication.sendEvent(h.v, QKeyEvent(kind, Qt.Key_Z, Qt.ControlModifier))
        assert [p["n"] for p in h.v.ws.review_pins] == [1], "Strg+Z nimmt die letzte Marke zurück"
        assert len(sc._undo) == undo_before and len(h.curves()) == n_curves, "nicht das Undo der Szene"
        session.set_marking(False)
        assert h.v.ws.review_aim is None, "aus: kein Ring"
        _click(h.v, on_line)
        assert len(h.v.ws.review_pins) == 1, "aus: Klicks gehen ans Werkzeug"
        session.set_marking(True)
        session.stop(transcribe=False)
        assert not session.marking
        marks = [e for e in review.read_log(folder) if e["typ"] == "marke"]
        assert [e["n"] for e in marks] == [1] and marks[0]["curve"] == line.id, marks
    finally:
        _restore(old)
        shutil.rmtree(base, ignore_errors=True)


def test_gesprochenes_hier_zeigt(h: H):
    """„hier“ im Transkript (Kamera und Cursor still) zählt als Zeigen: review_note rückt dorthin, Pfeil und Anker an
    der Stelle unter dem Cursor; beim Navigieren gesprochen zählt es nicht."""
    base, old = _setup(h)
    server = mcp_server.Server(h.w, port=0).start()
    try:
        sc = _scene(h)
        folder, line, t_mark = _record(h, sc)
        events = review.read_log(folder)
        cam = [e for e in events if e["typ"] == "kamera"][0]
        on = next(e for e in events if e["typ"] == "ziel")
        with open(os.path.join(folder, review.LOG), "a", encoding="utf-8") as f:  # später: wieder auf die Linie
            f.write(json.dumps({**cam, "t": 40.0}) + "\n")
            f.write(json.dumps({"t": 40.1, "typ": "maus", "vp": 0, "x": on["x"], "y": on["y"]}) + "\n")
            f.write(json.dumps({**cam, "t": 50.0, "dist": cam["dist"] * 1.1}) + "\n")
        tr_ = {"segments": [{"start": 41.0, "end": 43.0, "text": "Die Kante hier.",
                             "words": [["Die", 41.0, 41.2], ["Kante", 41.2, 41.6], ["hier.", 41.7, 42.0]]},
                            {"start": 49.8, "end": 50.4, "text": "hier", "words": [["hier", 49.9, 50.1]]}]}
        with open(os.path.join(folder, review.TRANSCRIPT), "w", encoding="utf-8") as f:
            json.dump(tr_, f)
        words = review.word_pointings(review.read_log(folder), tr_)
        assert [w["t"] for w in words] == [41.85], "beim Navigieren gesprochen zählt nicht"
        h.camera([5, 5, 5], 9.0, (1.0, 0.2, 0.0))  # jetzt eine ganz andere Ansicht
        r = _call(h, server, "review_note", t=42.5, text="Kante", quote="Die Kante hier.")
        assert not r["isError"] and "spoken „hier“" in r["content"][0]["text"], r
        assert sc.notes[-1].anchors and sc.notes[-1].anchors[0].curve_id == line.id, "Anker unter dem Cursor beim Wort"
        assert "said „hier“" in _call(h, server, "review_read")["content"][0]["text"]
    finally:
        server.stop()
        _restore(old)
        shutil.rmtree(base, ignore_errors=True)


def test_bilder_aus_ordnern(h: H):
    """insert_images: Bilddateien (absolut oder relativ zur Szene) aufs Brett, mit Unterschrift und Pfeil vom Text;
    dieselbe Datei nicht doppelt; Fehlendes und Unlesbares werden genannt; ein Undo-Schritt."""
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
        assert not any(i["kind"] == "image" for i in sc.notes[0].board.get("items", [])), "ein Undo-Schritt"
    finally:
        h.w.path = keep
        server.stop()
        shutil.rmtree(base, ignore_errors=True)


def test_whisper_einrichten(h: H):
    """Transkription einrichten: die Schritte laufen nacheinander als eigene Prozesse, am Ende kennt Mule das Python
    (Einstellung whisper_python); ein fehlschlagender Schritt hält an; ohne Python erklärt der Dialog python.org."""
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


def test_brettmarke_bild_in_die_notiz(h: H):
    """Markieren: Klick auf ein Bild im offenen Brett (Projekt-Notiz als Referenzbrett): Brett-Marke mit Bild und Stelle im
    Bild; review_read nennt sie; review_note mit refs legt das Bild in die Notiz zum Teil, Pfeil auf die Stelle –
    dasselbe Bild (kein zweites in der Datei), es bleibt auch auf der Projekt-Notiz."""
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
                                           "caption": "Tank Referenz"}]}
        line = sc.strokes[0].curves[0]
        h.frame(np.vstack([line.points, [[0, 1, 0]]]))
        session = review.ReviewSession(h.w)
        on_line = h.scr(line.points[2])
        pos = {"p": h.v.mapToGlobal(on_line)}
        session.cursor = lambda: pos["p"]
        folder = session.start()
        h.pump(0.3)
        assert session.mark() == 1, "Marke am Tank (Linie)"
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
        _click(port, local)  # Werkzeug „Markieren“ ist an
        h.pump(0.1)
        assert len(sc.global_note.board["items"]) == 1, "der Markier-Klick verschiebt und malt nichts aufs Brett"
        t_end = session.elapsed()
        session.stop(transcribe=False)
        board.close_board()
        h.v.set_notes_mode(False)
        bm = [e for e in review.read_log(folder) if e["typ"] == "brettmarke"]
        assert len(bm) == 1 and bm[0]["n"] == 2 and bm[0]["datei"] == name, bm
        u, v = bm[0]["uv"]
        assert abs(u - 0.25) < 0.03 and abs(v - 0.75) < 0.03, f"Stelle im Bild {u}, {v}"
        assert bm[0]["brett"] == sc.global_note.id and os.path.isfile(os.path.join(folder, bm[0]["bild"]))
        with open(os.path.join(folder, review.TRANSCRIPT), "w", encoding="utf-8") as f:
            json.dump({"language": "de", "model": "test", "segments": [
                {"start": 0.0, "end": round(t_end, 2), "text": "Der Tank soll so aussehen wie hier."}]}, f)
        text = _call(h, server, "review_read")["content"][0]["text"]
        assert "BOARD MARK 2" in text and "Tank Referenz" in text and "project note" in text, text
        assert _call(h, server, "review_note", mark=2, text="x")["isError"], "Brett-Marke ist kein t"
        n_assets = len(sc.assets)
        r = _call(h, server, "review_note", mark=1, refs=[2], title="Tank",
                  text="Tank\n- Form wie auf dem Referenzfoto")
        assert not r["isError"], r
        note = sc.notes[-1]
        imgs = [i for i in note.board["items"] if i["kind"] == "image"]
        assert len(imgs) == 2 and imgs[1]["file"] == name, imgs
        assert len(sc.assets) == n_assets + 1, "nur das 3D-Bild ist neu, das Referenzbild gibt es schon"
        assert len(sc.global_note.board["items"]) == 1, "bleibt auf der Projekt-Notiz"
        g = QGraphicsScene()
        _populate(g, sc, note.board)
        links = [l for l in (board_links.stroke_link(g, s) for s in g.items() if isinstance(s, StrokeItem)) if l]
        assert len(links) == 2, f"Pfeil auf jedes Bild: {len(links)}"
        g.clear()
    finally:
        if board is not None and board.isVisible():
            board.close_board()
        server.stop()
        _restore(old)
        shutil.rmtree(base, ignore_errors=True)


def test_chat_satz_in_der_sprache_von_mule(h: H):
    """„Review absenden“ legt einen Satz für den Chat in die Zwischenablage – auf Englisch, wenn Mule Englisch spricht
    (sonst antwortet Claude auf Deutsch)."""
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


def test_pfeil_folgt_im_offenen_brett(h: H):
    """Offenes Brett: diktierter Text mit Pfeil aufs Bild; Bild verschieben – der Pfeil zieht ohne weiteres Zutun mit
    (gscene.changed) und steht so auch in der Notiz; ein gemalter Strich bleibt, wo er ist."""
    from PySide6.QtCore import QPointF
    from tests.test_notizen import _png, _open_board, _close
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
        assert drawn.pts[0] == QPointF(0, 300), "gemalter Strich bleibt"
        board.commit()
        entry = next(e for e in note.board["items"] if e.get("arrow"))
        assert entry["pts"][-1] == [550.0, 625.0] and entry["arrow"] == {"to": "ref.png", "uv": [0.75, 0.25]}
    finally:
        _close(h, board)

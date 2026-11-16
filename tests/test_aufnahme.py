"""Aufnahme (recorder) und angeheftetes Notizbrett: Protokoll mit Eingaben, Rechendauer, Hängern; OBS per WebSocket;
Panel Notiz bleibt angeheftet in jedem Modus sichtbar."""
import json
import os
import tempfile
import time

from PySide6.QtCore import QPoint, Qt
from PySide6.QtNetwork import QHostAddress
from PySide6.QtTest import QTest
from PySide6.QtWebSockets import QWebSocketServer
from PySide6.QtWidgets import QLineEdit

from tests.harness import H
from sketch_machine import recorder


def _rows(rec):
    with open(os.path.join(rec.folder, "protokoll.jsonl"), encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _start(h, with_obs=False):
    tmp = tempfile.mkdtemp(prefix="mule_aufnahme_")
    recorder.recordings_dir = lambda: tmp
    rec = h.w.recorder
    rec.start(with_obs=with_obs)
    h.pump(0.1)
    return rec


def test_eingaben_aktionen_und_modus_landen_im_protokoll(h: H):
    h.new_scene()
    rec = _start(h)
    assert h.w._rec_label.isVisible() and "REC" in h.w._rec_label.text()
    h.edit_mode()
    h.pump(0.05)
    h.draw_mode()
    h.pump(0.05)
    h.click(QPoint(300, 300))
    h.pump(0.1)
    h.w.toggle_recording()  # wie Menü: beendet
    rows = _rows(rec)
    kinds = [r["typ"] for r in rows]
    assert kinds[0] == "start" and kinds[-1] == "ende", kinds
    assert rows[0]["wann"] and "bildschirm" in rows[0]
    modes = [r["modus"] for r in rows if r["typ"] == "modus"]
    assert "edit" in modes and modes[-1] == "zeichnen", modes
    clicks = [r for r in rows if r["typ"] == "klick"]
    assert clicks and clicks[-1]["knopf"] == "links" and "dauer_ms" in clicks[-1] and clicks[-1]["modus"] == "zeichnen"
    assert any(r["typ"] == "loslassen" for r in rows)
    assert all(rows[i]["t"] >= 0 for i in range(len(rows)))
    assert not h.w._rec_label.isVisible() and h.w.rec_action.text() == "Aufnahme starten"


def test_haenger_mit_bild(h: H):
    rec = _start(h)
    h.pump(0.12)
    time.sleep(0.4)  # Mule beschäftigt
    h.pump(0.12)
    time.sleep(1.2)
    h.pump(0.2)
    rec.stop()
    hangs = [r for r in _rows(rec) if r["typ"] == "haenger"]
    assert len(hangs) >= 2, hangs
    assert any(300 <= r["ms"] < 1000 and "bild" not in r for r in hangs), hangs
    big = [r for r in hangs if r["ms"] >= 1000]
    assert big and big[0].get("bild") and os.path.isfile(os.path.join(rec.folder, big[0]["bild"]))


def test_text_in_eingabefeldern_wird_nicht_mitgeschrieben(h: H):
    edit = QLineEdit(h.w)
    edit.show()
    edit.setFocus()
    h.pump(0.05)
    rec = _start(h)
    QTest.keyClicks(edit, "geheim")
    h.pump(0.1)
    rec.stop()
    edit.deleteLater()
    text = open(os.path.join(rec.folder, "protokoll.jsonl"), encoding="utf-8").read()
    assert "geheim" not in text and '"g"' not in text
    assert sum(1 for r in _rows(rec) if r["typ"] == "tippen") == 6


def test_obs_wird_angemeldet_und_gestartet(h: H):
    server = QWebSocketServer("obs-attrappe", QWebSocketServer.NonSecureMode)
    assert server.listen(QHostAddress.LocalHost, 0)
    port = server.serverPort()
    seen = {"auth": None, "requests": []}
    clients = []

    def on_conn():
        sock = server.nextPendingConnection()
        clients.append(sock)

        def on_msg(text):
            msg = json.loads(text)
            if msg["op"] == 1:
                seen["auth"] = msg["d"].get("authentication")
                sock.sendTextMessage(json.dumps({"op": 2, "d": {"negotiatedRpcVersion": 1}}))
            elif msg["op"] == 6:
                kind = msg["d"]["requestType"]
                seen["requests"].append(kind)
                sock.sendTextMessage(json.dumps({"op": 7, "d": {"requestType": kind, "requestId": msg["d"]["requestId"],
                                                                "requestStatus": {"result": True, "code": 100}}}))
                state = "OBS_WEBSOCKET_OUTPUT_STARTED" if kind == "StartRecord" else "OBS_WEBSOCKET_OUTPUT_STOPPED"
                sock.sendTextMessage(json.dumps({"op": 5, "d": {"eventType": "RecordStateChanged", "eventData": {
                    "outputActive": kind == "StartRecord", "outputState": state, "outputPath": "C:/Videos/test.mkv"}}}))
        sock.textMessageReceived.connect(on_msg)
        sock.sendTextMessage(json.dumps({"op": 0, "d": {"rpcVersion": 1, "authentication": {
            "challenge": "abc", "salt": "xyz"}}}))
    server.newConnection.connect(on_conn)
    old = recorder.obs_config
    recorder.obs_config = lambda: (port, "geheim", True)
    try:
        rec = _start(h, with_obs=True)
        end = time.monotonic() + 3
        while time.monotonic() < end and not (rec.obs and rec.obs.recording):
            h.pump(0.02)
        assert seen["auth"] == recorder.obs_auth("geheim", "xyz", "abc")
        assert seen["requests"] == ["StartRecord"] and rec.obs.recording
        assert "OBS ●" in h.w._rec_label.text()
        rec.stop()
        end = time.monotonic() + 3
        while time.monotonic() < end and rec.obs is not None:
            h.pump(0.02)
        assert rec.obs is None and "StopRecord" in seen["requests"]
        obs_rows = [r for r in _rows(rec) if r["typ"] == "obs"]
        assert [r["zustand"] for r in obs_rows] == ["verbunden", "laeuft", "steht"], obs_rows
        assert obs_rows[1]["info"] == "C:/Videos/test.mkv" and rec.obs_file == "C:/Videos/test.mkv"
    finally:
        recorder.obs_config = old
        server.close()


def test_obs_ausgeschaltet_meldet_sich(h: H):
    old = recorder.obs_config
    recorder.obs_config = lambda: (4455, "", False)
    try:
        rec = _start(h, with_obs=True)
        h.pump(0.05)
        assert "WebSocket" in h.w.statusBar().currentMessage()
        rec.stop()
        h.pump(0.05)
        assert any(r["typ"] == "obs" and r["zustand"] == "fehler" for r in _rows(rec))
    finally:
        recorder.obs_config = old
        rec._close_obs()


def test_notizbrett_angeheftet_in_jedem_modus(h: H):
    h.new_scene()
    w = h.w
    h.draw_mode()
    h.pump(0.05)
    assert not w.note_dock.isVisible()
    w.set_note_pinned(True)
    h.pump(0.05)
    assert w.note_dock.isVisible() and w.pin_note_action.isChecked() and w.note_panel.pin_button.isChecked()
    h.edit_mode()
    h.pump(0.05)
    assert w.note_dock.isVisible(), "Edit: bleibt"
    w.viewport.set_paint_mode(True)
    h.pump(0.05)
    assert w.note_dock.isVisible(), "Malmodus: bleibt"
    w.viewport.set_paint_mode(False)
    h.draw_mode()
    w.note_panel.pin_button.click()  # Knopf im Panel löst wieder
    h.pump(0.05)
    assert not w._note_pinned and not w.pin_note_action.isChecked() and not w.note_dock.isVisible()
    w.notes_mode_action.trigger()
    h.pump(0.05)
    assert w.note_dock.isVisible(), "Modus Notizen zeigt das Panel wie bisher"
    w.draw_mode_action.trigger()
    h.pump(0.05)
    assert not w.note_dock.isVisible()


def test_angeheftet_zeigt_globale_notiz_beim_zeichnen(h: H):
    h.new_scene()
    w = h.w
    w.set_note_pinned(True)
    w._set_note_scope("global")
    h.draw_mode()
    h.pump(0.05)
    assert w.note_panel.note_id == w.viewport.scene.global_note.id
    w._set_note_scope("local")
    w.set_note_pinned(False)
    h.pump(0.05)

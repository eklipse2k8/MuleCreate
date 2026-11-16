"""Videos im Notizbrett: Bild mit Wiedergabe – Pfeile wie bei Bildern, Datei neben der Szene, im Brief nur auf Nachfrage.

tests/assets/clip.mp4: 3 s, 320 x 180, Farbe läuft von Blau nach Rot."""
import json
import os
import shutil
import tempfile
import time

import numpy as np
from PySide6.QtCore import QMimeData, QPointF, Qt, QUrl
from PySide6.QtTest import QTest

from tests.harness import H, ROOT
from sketch_machine import brief
from sketch_machine.note_board import ImageItem, StrokeItem, TextBlock, VideoItem, board_for
from sketch_machine.scene import Note, Scene

CLIP = os.path.join(ROOT, "tests", "assets", "clip.mp4")


def _board(h: H):
    h.new_scene()
    note = Note("Bewegung", np.array([0.0, 0.0, 0.0]))
    h.sc.notes.append(note)
    h.v.set_notes_mode(True)
    h.v.ws.active_note = note.id
    board = board_for(h.v)
    board.open(h.v, note.id)
    h.pump(0.05)
    return note, board


def _drop(h: H, board, path=CLIP, pos=QPointF(0, 0)):
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(path)])
    board.insert_mime(mime, pos)
    h.pump(0.02)
    items = [i for i in board.gscene.items() if isinstance(i, VideoItem)]
    return items[0] if items else None


def _wait(h: H, cond, seconds=4.0):
    end = time.monotonic() + seconds
    while not cond() and time.monotonic() < end:
        h.pump(0.02)
    return cond()


def _rgb(item):
    img = item.pixmap().toImage()
    c = img.pixelColor(img.width() // 2, img.height() // 4)
    return c.red(), c.green(), c.blue()


def _click(h: H, board, item, local):
    pos = board.view.mapFromScene(item.mapToScene(local))
    QTest.mouseClick(board.view.viewport(), Qt.LeftButton, Qt.NoModifier, pos)
    h.pump(0.02)


def test_video_hineinziehen_wird_bild_mit_vorschau(h: H):
    note, board = _board(h)
    item = _drop(h, board)
    assert isinstance(item, ImageItem) and 2500 < item.duration < 3500, item and item.duration
    assert item.pixmap().width() == 320, "Vorschau in Originalgröße (kleiner als FRAME_MAX)"
    entry = note.board["items"][0]
    assert entry["kind"] == "image" and entry["video"]["path"] == os.path.abspath(CLIP)
    assert h.sc.asset_bytes(entry["file"]), "Vorschau liegt in der Szene wie ein Bild"


def test_abspielen_anhalten_und_scrubben(h: H):
    """Knopf spielt, die Elementgröße bleibt; die Zeitleiste springt an die Stelle und hält dort an."""
    _, board = _board(h)
    item = _drop(h, board)
    size = item.pixmap().size()
    rect = item.sceneBoundingRect()
    center, _ = item._button()
    _click(h, board, item, center)
    assert item.playing and board.video_item is item
    assert _wait(h, lambda: item.position > 800), f"läuft nicht: {item.position}"
    assert item.pixmap().size() == size and item.sceneBoundingRect() == rect
    _click(h, board, item, center)
    assert not item.playing
    bar = item._bar()
    _click(h, board, item, QPointF(bar.left() + bar.width() * 0.95, bar.center().y()))
    assert not item.playing and _wait(h, lambda: _rgb(item)[0] > 180 and _rgb(item)[2] < 90), _rgb(item)
    _click(h, board, item, QPointF(bar.left() + 3, bar.center().y()))
    assert _wait(h, lambda: _rgb(item)[2] > 180 and _rgb(item)[0] < 90), f"zurück am Anfang blau: {_rgb(item)}"


def test_nur_ein_video_laeuft(h: H):
    _, board = _board(h)
    a = _drop(h, board)
    other = os.path.join(tempfile.mkdtemp(), "zweites.mp4")
    shutil.copy(CLIP, other)
    b = board.add_video(other, QPointF(500, 0))
    board.toggle_video(a)
    board.toggle_video(b)
    assert board.video_item is b and b.playing and not a.playing
    p = b.position
    assert _wait(h, lambda: b.position > p), "zweite Datei läuft im neuen Player"


def test_pfeil_und_unterschrift_wie_beim_bild(h: H):
    """Pfeil von einem Text aufs Video: Verbindung im Brief, auch nach dem Abspielen an derselben Stelle."""
    from sketch_machine import board_links
    note, board = _board(h)
    item = _drop(h, board)
    text = TextBlock("Das Scharnier")
    text.setPos(-420, 40)
    board.gscene.addItem(text)
    r = item.sceneBoundingRect()
    tip = QPointF(r.left() + r.width() * 0.25, r.top() + r.height() * 0.5)
    arrow = StrokeItem([QPointF(-80, 50), QPointF(-30, 60), tip], [2.0] * 3, "pen")
    board.gscene.addItem(arrow)
    link = board_links.stroke_link(board.gscene, arrow)
    assert link["kind"] == "link" and link["target"] is item and abs(link["uv"][0] - 0.25) < 0.01
    board.toggle_video(item)
    assert _wait(h, lambda: item.position > 300)
    board.toggle_video(item)
    assert abs(board_links.stroke_link(board.gscene, arrow)["uv"][0] - 0.25) < 0.01
    from sketch_machine.note_board import set_image_captions
    set_image_captions(h.v, {item.file: "nur wie die Klappe öffnet"})
    assert item.caption and brief.image_captions(h.sc)[item.file].startswith("nur wie")


def test_beim_speichern_neben_die_szene_kopiert_und_relativ(h: H):
    note, board = _board(h)
    item = _drop(h, board)
    folder = tempfile.mkdtemp()
    path = os.path.join(folder, "szene.sketch.json")
    board.commit()
    h.sc.save(path)
    copy = os.path.join(folder, "videos", "clip.mp4")
    assert os.path.getsize(copy) == os.path.getsize(CLIP)
    with open(path, encoding="utf-8") as f:
        saved = json.load(f)
    assert saved["notes"][0]["board"]["items"][0]["video"]["path"] == "videos/clip.mp4"
    assert note.board["items"][0]["video"]["path"] == copy, "im Speicher absolut"
    h.sc.dirty = False
    board.commit()
    assert item.path == copy, "offenes Brett übernimmt die Kopie"
    assert not h.sc.dirty, "kein Undo-Schritt durchs Speichern"
    h.sc.save(path)  # zweites Speichern: keine zweite Kopie
    assert os.listdir(os.path.join(folder, "videos")) == ["clip.mp4"]
    moved = tempfile.mkdtemp()  # Ordner samt Szene weitergegeben
    shutil.copytree(folder, os.path.join(moved, "x"))
    scene, _ = Scene.load(os.path.join(moved, "x", "szene.sketch.json"))
    assert os.path.isfile(scene.notes[0].board["items"][0]["video"]["path"])


def test_gleicher_name_andere_datei_ueberschreibt_nichts(h: H):
    from sketch_machine import video
    folder = tempfile.mkdtemp()
    other = os.path.join(tempfile.mkdtemp(), "clip.mp4")
    with open(other, "wb") as f:
        f.write(b"anders")
    first, second = video.adopt(CLIP, folder), video.adopt(other, folder)
    assert first != second and os.path.getsize(first) == os.path.getsize(CLIP) and second.endswith("clip_2.mp4")
    assert video.adopt(first, folder) == first and video.adopt(CLIP, folder) == first


def test_brief_kopiert_video_und_fragt_nach_statt_zu_zerlegen(h: H):
    note, board = _board(h)
    _drop(h, board)
    board.commit()
    target = os.path.join(tempfile.mkdtemp(), "brief")
    files = brief.export(h.sc, h.v, target, "video")
    assert "videos/clip.mp4" in files and "videos/clip_overview.jpg" in files
    frames = [f for f in os.listdir(os.path.join(target, "videos")) if f.endswith((".jpg", ".png"))]
    assert frames == ["clip_overview.jpg"], f"Video nicht zerlegt: {frames}"
    from PySide6.QtGui import QImage
    sheet = QImage(os.path.join(target, "videos", "clip_overview.jpg"))
    assert sheet.width() == 320 * 3 and sheet.height() == 180 * 2, "sechs Bilder im Raster"
    with open(os.path.join(target, "brief.md"), encoding="utf-8") as f:
        md = f.read()
    with open(os.path.join(target, "project.md"), encoding="utf-8") as f:
        project = f.read()   # Bau-Brief (Paket v4): erste Runde im Projekt-Dokument
    assert "**Videos** (1)" in project and "Do not cut a video into frames" in project
    assert "`videos/clip.mp4`" in md and "`videos/clip_overview.jpg`" in md
    with open(os.path.join(target, "brief.json"), encoding="utf-8") as f:
        entry = json.load(f)["notes"][0]["videos"][0]
    assert entry["file"] == "videos/clip.mp4" and entry["poster"].startswith("notes/") and entry["seconds"] > 2
    assert entry["poster"] in json.load(open(os.path.join(target, "brief.json"), encoding="utf-8"))["notes"][0]["uncaptioned"]


def test_ohne_video_kein_videoschritt_im_brief(h: H):
    _board(h)
    target = os.path.join(tempfile.mkdtemp(), "brief")
    brief.export(h.sc, h.v, target, "ohne")
    with open(os.path.join(target, "project.md"), encoding="utf-8") as f:
        assert "**Videos**" not in f.read()
    assert not os.path.exists(os.path.join(target, "videos"))


def test_fehlende_datei_bleibt_vorschau_und_steht_im_brief(h: H):
    gone = os.path.join(tempfile.mkdtemp(), "weg.mp4")
    shutil.copy(CLIP, gone)
    note, board = _board(h)
    item = _drop(h, board, gone)
    board.commit()
    os.remove(gone)
    assert item.absent and item.control_at(item._button()[0]) is None
    folder = tempfile.mkdtemp()
    h.sc.save(os.path.join(folder, "s.sketch.json"))  # Speichern scheitert nicht
    target = os.path.join(tempfile.mkdtemp(), "brief")
    brief.export(h.sc, h.v, target, "fehlt")
    with open(os.path.join(target, "brief.md"), encoding="utf-8") as f:
        md = f.read()
    assert "video file(s) not found" in md and "MISSING" in md
    assert not os.path.exists(os.path.join(target, "videos", "weg.mp4"))


def test_kaputte_datei_gibt_meldung_statt_text(h: H):
    bad = os.path.join(tempfile.mkdtemp(), "kaputt.mp4")
    with open(bad, "wb") as f:
        f.write(b"kein video" * 100)
    note, board = _board(h)
    assert _drop(h, board, bad) is None
    assert not note.board.get("items"), "kein Element und kein Text mit dem Pfad"


def test_standbild_und_loeschen_waehrend_es_laeuft(h: H):
    note, board = _board(h)
    item = _drop(h, board)
    board.seek_video(item, 0.9)
    assert _wait(h, lambda: _rgb(item)[0] > 180)
    still = board.video_still(item)
    assert still is not None and not isinstance(still, VideoItem) and "clip.mp4 @ 0:03" in still.caption
    assert abs(still.sceneBoundingRect().width() - item.sceneBoundingRect().width()) < 2
    board.toggle_video(item)
    board.gscene.removeItem(item)
    board.commit()
    assert _wait(h, lambda: board.video_item is None), "Wiedergabe endet mit dem Element"
    board.undo()
    h.pump(0.05)
    assert any(isinstance(i, VideoItem) for i in board.gscene.items()), "Undo holt das Video zurück"


def test_brett_wechseln_haelt_das_video_an(h: H):
    note, board = _board(h)
    item = _drop(h, board)
    board.toggle_video(item)
    board.commit()
    second = Note("Andere", np.array([1.0, 0.0, 0.0]))
    h.sc.notes.append(second)
    board.open(h.v, second.id)
    h.pump(0.1)
    assert board.video_item is None and board._player is None


def test_mcp_liest_nur_gewuenschte_bilder(h: H):
    from sketch_machine import mcp_server
    from tests.test_mcp_server import _call
    note, board = _board(h)
    _drop(h, board)
    board.commit()
    server = mcp_server.Server(h.w, port=0).start()
    try:
        out = _call(h, server, "video_frames", video="videos/clip.mp4", times=[0.2, 2.8])["content"]
        assert [c["type"] for c in out].count("image") == 2 and "at 2.80 s" in " ".join(c.get("text", "") for c in out)
        assert _call(h, server, "video_frames", video="fehlt.mp4")["isError"]
    finally:
        server.stop()

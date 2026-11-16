"""Review mode: the artist walks through the scene and speaks feedback as in a review session;
Mule records the voice and also where the artist looked and pointed. Afterwards Claude (MCP: review_read,
review_moment, review_note) turns it into draft notes that are looked through and adopted in Mule.

Per review a folder under <user folder>/Reviews/<scene>_<date_time>/:
- ton.wav: the voice (microphone, as the system delivers it, 16 bit).
- protokoll.jsonl: one line per event, t = seconds since start (same clock as ton.wav). Types:
  start (wann, szene), kamera (vp, target, dist, rot, ortho, w, h - only on change), maus (vp, x, y - fraction 0..1
  of the view, from top left), ziel (what lies under the resting cursor: curve, obj, point, x, y), auswahl (ids),
  notiz (open or active board), marke (n, bild, x, y, curve, obj, point - click with the "Mark" tool,
  which is on during the review; a preview ring shows beforehand what will be hit), brettmarke (n, bild, brett = note id, x, y - the same click on an open
  board; on an image additionally datei = image in scene.assets, uv = spot in the image 0..1 from top left, unterschrift),
  marke_weg (n - Ctrl+Z while marking took it back; read_log omits both), ende.
  What the artist changes during it (compared every CHANGE_TICKS ticks): notiz_neu (id,
  titel), brett (id, growth bilder/texte/striche, new titel), notiz_weg (ids), linien (anzahl, neu = line ids,
  objekte), linien_weg (anzahl).
- marke_<n>.jpg: the view at the press of "Here!" (without controls).
- review.json: header data (scene, start, duration, marks) - written only at the end.
- transkript.json: from review_transcribe.py (faster-whisper, local) - sections with word timestamps.

No video: Mule knows the camera at every point in time and re-renders each moment cleanly from it.
"""
import datetime
import json
import os
import re
import subprocess
import sys
import time
import wave

import numpy as np
from PySide6.QtCore import QEvent, QObject, QPointF, QProcess, QSettings, Qt, QTimer, Signal
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QApplication

from . import paths
from .i18n import tr

SAMPLE_MS = 100  # look at camera, mouse, selection this often
REST_MS = 350  # the cursor rests this long, then a check is made of what lies under it
MOVE_PX = 3
CHANGE_TICKS = 5  # compare own changes (notes, boards, lines) this rarely
CHANGES = ("notiz_neu", "brett", "notiz_weg", "linien", "linien_weg")
FLASH_S = 0.9  # a new mark flashes in the viewport this long
MARK_SNAP = 4.0  # a draft snaps to a "Here!" mark up to this many seconds away
REST_SNAP = (2.0, 3.0)  # ... otherwise to a cursor rest up to this far before/after
WORD_SNAP = 3.0  # ... or to a spoken "here" up to this far away (cursor still, camera still)
POINT_WORDS = {"hier", "hierhin", "hierher", "dort", "dorthin", "here", "there"}
AIM_MS = 50  # update the preview while marking (ring at the cursor) this often
TRANSCRIPT = "transkript.json"
AUDIO = "ton.wav"
LOG = "protokoll.jsonl"
META = "review.json"
MODEL = "large-v3-turbo"


def saved_microphone():
    """Selected microphone (device id) or "" = system default."""
    return str(QSettings("SketchMachine", "SketchMachine").value("review_mic", "") or "")


def save_microphone(device_id):
    QSettings("SketchMachine", "SketchMachine").setValue("review_mic", device_id or "")


def microphones():
    """[(device id, name)] of all microphones."""
    from PySide6.QtMultimedia import QMediaDevices
    return [(bytes(d.id()).decode("utf-8", "replace"), d.description()) for d in QMediaDevices.audioInputs()]


def reviews_dir():
    path = os.path.join(paths.user_dir(), "Reviews")
    os.makedirs(path, exist_ok=True)
    return path


def list_reviews():
    """[(name, folder)] - newest first."""
    base = reviews_dir()
    out = [(n, os.path.join(base, n)) for n in os.listdir(base)
           if os.path.isfile(os.path.join(base, n, LOG))]
    return sorted(out, key=lambda x: os.path.getmtime(os.path.join(x[1], LOG)), reverse=True)


def find_review(name=None):
    """Folder of a review (name, folder or start of the name; empty: the newest) or None."""
    items = list_reviews()
    if not name:
        return items[0][1] if items else None
    if os.path.isdir(name) and os.path.isfile(os.path.join(name, LOG)):
        return name
    key = os.path.basename(name.replace("\\", "/").rstrip("/")).lower()
    for n, folder in items:
        if n.lower() == key:
            return folder
    hits = [folder for n, folder in items if n.lower().startswith(key) or key in n.lower()]
    return hits[0] if len(hits) == 1 else None


# --- Recording ---------------------------------------------------------------------------------------------------
class AudioWriter(QObject):
    """Microphone -> WAV (16 bit), written continuously during recording. Without a microphone: ok False."""

    def __init__(self, path, parent=None):
        super().__init__(parent)
        from PySide6.QtMultimedia import QAudioFormat, QAudioSource, QMediaDevices
        self.ok, self.error, self.frames = False, "", 0
        device = QMediaDevices.defaultAudioInput()
        chosen = saved_microphone()
        for d in QMediaDevices.audioInputs():
            if chosen and bytes(d.id()).decode("utf-8", "replace") == chosen:
                device = d
        if device.isNull():
            self.error = tr("kein Mikrofon gefunden")
            return
        fmt = QAudioFormat()
        fmt.setSampleRate(16000)
        fmt.setChannelCount(1)
        fmt.setSampleFormat(QAudioFormat.Int16)
        if not device.isFormatSupported(fmt):
            fmt = device.preferredFormat()
        self.fmt = fmt
        self._float = fmt.sampleFormat() == QAudioFormat.Float
        self._int32 = fmt.sampleFormat() == QAudioFormat.Int32
        self._uint8 = fmt.sampleFormat() == QAudioFormat.UInt8
        self.rate, self.channels = fmt.sampleRate(), max(fmt.channelCount(), 1)
        self.wav = wave.open(path, "wb")
        self.wav.setnchannels(self.channels)
        self.wav.setsampwidth(2)
        self.wav.setframerate(self.rate)
        self.source = QAudioSource(device, fmt, self)
        self.io = self.source.start()
        if self.io is None:
            self.error = tr("Mikrofon lässt sich nicht öffnen")
            self.wav.close()
            return
        self.io.readyRead.connect(self._read)
        self.device_name = device.description()
        self.ok = True

    def _read(self):
        data = bytes(self.io.readAll())
        if not data:
            return
        if self._float:
            a = np.frombuffer(data[: len(data) // 4 * 4], np.float32)
            data = (np.clip(a, -1, 1) * 32767).astype("<i2").tobytes()
        elif self._int32:
            a = np.frombuffer(data[: len(data) // 4 * 4], np.int32)
            data = (a >> 16).astype("<i2").tobytes()
        elif self._uint8:
            a = np.frombuffer(data, np.uint8).astype(np.int16)
            data = ((a - 128) << 8).astype("<i2").tobytes()
        self.wav.writeframes(data)
        self.frames += len(data) // (2 * self.channels)

    def stop(self):
        if not self.ok:
            return
        self._read()
        self.source.stop()
        self.wav.close()
        self.ok = False


def pick_at(vp, pos):
    """What lies under a screen spot of the view: {"curve", "obj", "point"} (line before surface, like when attaching
    a note) or None."""
    try:
        curve, point, _ = vp._front_curve(pos, exact_over_surface=True)
        if curve is not None:
            owner = vp.scene.owner_of(curve)
            return {"curve": curve.id, "obj": getattr(owner, "id", None), "point": _r3(point)}
        obj, hit, _ = vp._mesh_under(pos)
        if obj is not None and hit is not None:
            return {"curve": None, "obj": obj.id, "point": _r3(hit)}
    except Exception:  # picking must never disturb the recording
        return None
    return None


def _r3(p):
    return [round(float(x), 5) for x in p]


def scene_state(scene):
    """State for the comparison: {note id: (title, images, texts, strokes)} including project note, {line id: object id}."""
    notes = {}
    for n in list(scene.notes) + [scene.global_note]:
        items = (n.board or {}).get("items", [])
        count = lambda kind: sum(1 for i in items if i.get("kind") == kind)
        notes[n.id] = (n.title or "", count("image"), count("text"), count("stroke"))
    curves = {c.id: st.id for st in scene.strokes for c in st.curves}
    return notes, curves


def camera_entry(vp):
    target, dist, rot = vp.cam.state()
    return {"target": _r3(target), "dist": round(float(dist), 5),
            "rot": [[round(float(x), 6) for x in row] for row in rot], "ortho": bool(vp.cam.ortho),
            "w": vp.width(), "h": vp.height()}


class ReviewSession(QObject):
    """A running review recording on the main window."""
    changed = Signal()
    transcribed = Signal(str, bool)  # folder, ok
    marked = Signal(int, bool, str)  # number, something hit, name of the part
    unmarked = Signal(int)  # mark taken back (0: none left)
    aiming = Signal(str)  # while aiming: what would be hit ("" = nothing; None replacement "-": aim missed)
    marking_changed = Signal(bool)  # "Mark" tool on/off

    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.active = False
        self.folder = None
        self.audio = None
        self._file = None
        self._t0 = 0.0
        self._timer = QTimer(self, interval=SAMPLE_MS)
        self._timer.timeout.connect(self._sample)
        self._last = {}
        self._marks = 0
        self._procs = {}
        self.cursor = QCursor.pos  # global cursor position (tests set their own)
        self.marking = False  # "Mark" tool (on at start): left click sets marks
        self._aim = None  # while marking: {"pos"} (last checked cursor position) - otherwise None
        self._swallow = False  # do not pass the release click after a mark click to the tool
        self._aim_timer = QTimer(self, interval=AIM_MS)
        self._aim_timer.timeout.connect(self._aim_tick)

    # --- Start/End ---
    def start(self):
        if self.active:
            return self.folder
        path = getattr(self.window, "path", None)
        stem = re.sub(r"[^\w\-]+", "_", os.path.basename(path).split(".")[0]) if path else "ohne_szene"
        stamp = datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S")
        self.folder = os.path.join(reviews_dir(), f"{stem}_{stamp}")
        os.makedirs(self.folder, exist_ok=True)
        self._file = open(os.path.join(self.folder, LOG), "w", encoding="utf-8", buffering=1)
        self._t0 = time.perf_counter()
        self.audio = AudioWriter(os.path.join(self.folder, AUDIO), self)
        self._t0 = time.perf_counter()  # the clock starts with the sound
        self._last, self._marks = {}, 0
        self._state, self._ticks = None, 0
        self.last_mark = None
        self.window.viewport.ws.review_pins = []
        self.active = True
        self.write("start", wann=datetime.datetime.now().isoformat(timespec="seconds"), szene=path,
                   mikrofon=getattr(self.audio, "device_name", None), ton=self.audio.ok,
                   fehler=self.audio.error or None)
        self._sample()
        self._timer.start()
        QApplication.instance().installEventFilter(self)
        self.changed.emit()
        self.set_marking(True)
        return self.folder

    def stop(self, transcribe=True):
        if not self.active:
            return None
        self._timer.stop()
        self.set_marking(False)
        QApplication.instance().removeEventFilter(self)
        self._changes()  # what was added since the last comparison
        dur = self.elapsed()
        self.write("ende")
        self.active = False
        self.window.viewport.ws.review_pins = []  # pins only during the review
        self._repaint()
        self.audio.stop()
        self._file.close()
        self._file = None
        meta = {"szene": getattr(self.window, "path", None), "dauer": round(dur, 2), "marken": self._marks,
                "ton": os.path.isfile(os.path.join(self.folder, AUDIO)) and self.audio.frames > 0,
                "beginn": os.path.basename(self.folder)}
        with open(os.path.join(self.folder, META), "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=1)
        self.changed.emit()
        if transcribe and meta["ton"]:
            self.transcribe(self.folder)
        return self.folder

    def elapsed(self):
        return time.perf_counter() - self._t0 if self.active else 0.0

    def write(self, typ, **data):
        if self._file is None:
            return
        self._file.write(json.dumps({"t": round(self.elapsed(), 3), "typ": typ, **data}, ensure_ascii=False) + "\n")

    # --- Recording the log ---
    def _viewport(self):
        """View under the cursor (several viewports possible), otherwise the main view -> (vp, number, cursor in vp)."""
        vps = list(getattr(self.window.viewport.ws, "viewports", None) or [self.window.viewport])
        glob = self.cursor()
        for k, vp in enumerate(vps):
            if vp.isVisible():
                local = vp.mapFromGlobal(glob)
                if vp.rect().contains(local):
                    return vp, k, local
        vp = self.window.viewport
        return vp, vps.index(vp) if vp in vps else 0, None

    def _changes(self):
        """Own changes since the last comparison into the log (new notes, boards, lines)."""
        scene = self.window.viewport.scene
        notes, curves = scene_state(scene)
        old, self._state = self._state, (id(scene), notes, curves)
        if old is None or old[0] != id(scene):  # start or other scene loaded: just remember
            return
        _, on, oc = old
        for nid, v in notes.items():
            if nid not in on:
                self.write("notiz_neu", id=nid, titel=v[0], bilder=v[1], texte=v[2])
            elif v != on[nid]:
                d = {key: v[i] - on[nid][i] for i, key in ((1, "bilder"), (2, "texte"), (3, "striche"))
                     if v[i] != on[nid][i]}
                if v[0] != on[nid][0]:
                    d["titel"] = v[0]
                self.write("brett", id=nid, **d)
        gone = [nid for nid in on if nid not in notes]
        if gone:
            self.write("notiz_weg", ids=gone)
        new = [c for c in curves if c not in oc]
        if new:
            self.write("linien", anzahl=len(new), neu=new[:40], objekte=sorted({curves[c] for c in new}))
        removed = sum(1 for c in oc if c not in curves)
        if removed:
            self.write("linien_weg", anzahl=removed)

    def _sample(self):
        self._ticks += 1
        if self._state is None or self._ticks % CHANGE_TICKS == 0:
            self._changes()
        vp, k, local = self._viewport()
        cam = {"vp": k, **camera_entry(vp)}
        if cam != self._last.get("kamera"):
            self._last["kamera"] = cam
            self.write("kamera", **cam)
            self._last.pop("ziel", None)  # new view: check again
        now = time.perf_counter()
        if local is not None:
            w, h = max(vp.width(), 1), max(vp.height(), 1)
            xy = (local.x(), local.y())
            prev = self._last.get("maus")
            if prev is None or abs(prev[0] - xy[0]) + abs(prev[1] - xy[1]) > MOVE_PX or prev[2] != k:
                self._last["maus"] = (xy[0], xy[1], k)
                self._last["ruhe"] = now
                self.write("maus", vp=k, x=round(xy[0] / w, 4), y=round(xy[1] / h, 4))
            elif now - self._last.get("ruhe", now) >= REST_MS / 1000 and self._last.get("ziel") != xy:
                self._last["ziel"] = xy
                hit = pick_at(vp, QPointF(*xy))
                if hit is not None:
                    self.write("ziel", vp=k, x=round(xy[0] / w, 4), y=round(xy[1] / h, 4), **hit)
        sel = sorted(getattr(o, "id", 0) for o in vp.selected_objects)
        if sel != self._last.get("auswahl"):
            self._last["auswahl"] = sel
            self.write("auswahl", ids=sel)
        from .note_board import open_note_id
        note = open_note_id(vp) or getattr(vp.ws, "active_note", None)
        if note != self._last.get("notiz", -1):
            self._last["notiz"] = note
            self.write("notiz", id=note)

    # --- Marking: own tool while the review runs ---
    def set_marking(self, on):
        """"Mark" tool on/off (on at start): every simple left click into a view or onto an open
        board sets a mark, a ring at the cursor shows beforehand what will be hit. Off: the tools keep working
        normally (the review still records)."""
        on = bool(on) and self.active
        if on == self.marking:
            return
        self.marking = on
        if on:
            self._aim = {"pos": None}
            self._aim_tick()
            self._aim_timer.start()
        else:
            self._aim_clear()
            self.aiming.emit("-")
        self.marking_changed.emit(on)

    def _target(self, obj):
        """Where a click on obj aims: ("brett", ...) / ("ansicht", vp, number, cursor) or None (controls,
        menus - they stay usable)."""
        from PySide6.QtWidgets import QWidget
        if not isinstance(obj, QWidget):
            return None
        on_board = self._board_under()
        if on_board is not None:
            port = on_board[0].view.viewport()
            if obj is port or port.isAncestorOf(obj):
                return ("brett",) + on_board
        vp, k, local = self._viewport()
        if local is not None and (obj is vp or vp.isAncestorOf(obj)):
            return ("ansicht", vp, k, local)
        return None

    def eventFilter(self, obj, e):
        """Marking on: a simple left click sets a mark and does not go to the tool; with Alt/Ctrl/Shift or
        held space bar (navigating) it passes through. Ctrl+Z takes back the last mark."""
        if not self.marking:
            return False
        t = e.type()
        if t in (QEvent.ShortcutOverride, QEvent.KeyPress) and e.key() == Qt.Key_Z                 and (e.modifiers() & ~Qt.KeypadModifier) == Qt.ControlModifier:
            e.accept()  # Ctrl+Z is otherwise the scene undo
            if t == QEvent.KeyPress and not e.isAutoRepeat():
                self.undo_mark()
            return True
        if self._swallow and t in (QEvent.MouseButtonRelease, QEvent.MouseButtonDblClick, QEvent.MouseMove):
            if t == QEvent.MouseButtonRelease:
                self._swallow = False
            return True
        if t == QEvent.MouseButtonPress and e.button() == Qt.LeftButton and e.modifiers() == Qt.NoModifier:
            where = self._target(obj)
            if where is None or (where[0] == "ansicht" and getattr(where[1], "_space", False)):
                return False
            self._swallow = True
            if where[0] == "brett":
                self.mark_board(*where[1:])
            else:
                self.mark(*where[1:])
            return True
        return False

    def _aim_clear(self):
        if self._aim is None:
            return
        self._aim = None
        self._aim_timer.stop()
        ws = self.window.viewport.ws
        if getattr(ws, "review_aim", None) is not None:
            ws.review_aim = None
            self._repaint()

    def _aim_tick(self):
        """Preview while aiming: ring at the cursor, magenta if something would be hit (only re-check when moved)."""
        if self._aim is None:
            return
        ws = self.window.viewport.ws
        on_board = self._board_under()
        if on_board is not None:
            key = ("brett", id(on_board[0]), id(on_board[3]))
            if key != self._aim["pos"]:
                self._aim["pos"] = key
                if getattr(ws, "review_aim", None) is not None:
                    ws.review_aim = None
                    self._repaint()
                self.aiming.emit(board_label(on_board[3]))
            return
        vp, k, local = self._viewport()
        if local is None:
            if getattr(ws, "review_aim", None) is not None:
                ws.review_aim = None
                self._repaint()
            return
        key = (id(vp), local.x(), local.y(), json.dumps(camera_entry(vp)))
        if key == self._aim["pos"]:
            return
        self._aim["pos"] = key
        hit = pick_at(vp, QPointF(local))
        obj = vp.scene.object_by_id(hit["obj"]) if hit and hit.get("obj") is not None else None
        name = (getattr(obj, "name", "") or "?") if hit else ""
        ws.review_aim = {"vp": vp, "screen": QPointF(local), "hit": hit is not None, "name": name}
        self.aiming.emit(name)
        self._repaint()

    def undo_mark(self):
        """Ctrl+Z while marking: take back the last still valid mark -> its number (0: none there)."""
        pins = getattr(self.window.viewport.ws, "review_pins", None) or []
        if not self.active or not pins:
            self.unmarked.emit(0)
            return 0
        pin = pins.pop()
        self.write("marke_weg", n=pin["n"])
        self._repaint()
        self.unmarked.emit(pin["n"])
        return pin["n"]

    def _board_under(self):
        """Open board under the cursor -> (board, cursor in its view, spot on the board, image beneath or
        None) or None."""
        from .note_board import ImageItem, _open_boards
        glob = self.cursor()
        for b in _open_boards(self.window.viewport):
            port = b.view.viewport()
            if not port.isVisible():
                continue
            local = port.mapFromGlobal(glob)
            if not port.rect().contains(local):
                continue
            img = next((i for i in b.view.items(local) if isinstance(i, ImageItem)), None)
            return b, local, b.view.mapToScene(local), img
        return None

    def mark_board(self, board, local, at, img):
        """"Here!" on a board: which board, which image and where in the image (for Claude: this image into the note on the
        part just shown, with an arrow to the spot) -> number of the mark."""
        if not self.active:
            return None
        self._marks += 1
        n = self._marks
        name = f"marke_{n}.jpg"
        port = board.view.viewport()
        try:
            if not port.grab().save(os.path.join(self.folder, name), "JPG", 85):
                name = None
        except Exception:
            name = None
        extra = {"x": round(local.x() / max(port.width(), 1), 4), "y": round(local.y() / max(port.height(), 1), 4)}
        if img is not None:
            r = img.image_rect()
            q = img.mapFromScene(at)
            u = (q.x() - r.left()) / max(r.width(), 1e-9)
            v = (q.y() - r.top()) / max(r.height(), 1e-9)
            extra.update(datei=img.file, uv=[round(min(max(u, 0.0), 1.0), 4), round(min(max(v, 0.0), 1.0), 4)])
            if img.caption:
                extra["unterschrift"] = img.caption
        self.write("brettmarke", n=n, bild=name, brett=board.note_id, **extra)
        ws = self.window.viewport.ws
        ws.review_pins.append({"n": n, "point": None, "at": time.monotonic(), "vp": None, "screen": None,
                               "board": True})
        self.last_mark = {"n": n, "hit": img is not None, "name": board_label(img)}
        self.marked.emit(n, img is not None, board_label(img))
        return n

    def mark(self, vp=None, k=None, local=None):
        """"Here!": view as an image and what lies at the spot (default: under the cursor) -> number of the mark."""
        if not self.active:
            return None
        from .note_board import snapshot
        if vp is None:
            vp, k, local = self._viewport()
        self._marks += 1
        n = self._marks
        name = f"marke_{n}.jpg"
        try:
            data, _ = snapshot(vp)
            with open(os.path.join(self.folder, name), "wb") as f:
                f.write(data)
        except Exception:
            name = None
        extra = {}
        if local is not None:
            w, h = max(vp.width(), 1), max(vp.height(), 1)
            extra = {"x": round(local.x() / w, 4), "y": round(local.y() / h, 4)}
            extra.update(pick_at(vp, QPointF(local)) or {})
        self.write("marke", n=n, vp=k, bild=name, **extra)
        # make visible: pin at the hit spot (stays), without a hit briefly a gray ring
        obj = vp.scene.object_by_id(extra["obj"]) if extra.get("obj") is not None else None
        self.last_mark = {"n": n, "hit": extra.get("point") is not None, "name": getattr(obj, "name", "") or ""}
        vp.ws.review_pins.append({"n": n, "point": extra.get("point"), "at": time.monotonic(), "vp": vp,
                                  "screen": QPointF(local) if local is not None else None})
        self._flash_until = time.monotonic() + FLASH_S
        if not hasattr(self, "_flash"):
            self._flash = QTimer(self, interval=40)
            self._flash.timeout.connect(self._flash_tick)
        self._flash.start()
        self.marked.emit(n, self.last_mark["hit"], self.last_mark["name"])
        return n

    def _flash_tick(self):
        self._repaint()
        if time.monotonic() > self._flash_until + 0.6:
            self._flash.stop()

    def _repaint(self):
        vp = self.window.viewport
        for v in list(getattr(vp.ws, "viewports", None) or [vp]):
            v.update_view()

    # --- Transcript ---
    def transcribe(self, folder):
        """faster-whisper in its own process (does not block Mule) -> signal transcribed."""
        cmd = transcribe_command(folder)
        if cmd is None:
            self.transcribed.emit(folder, False)
            return False
        proc = QProcess(self)
        proc.setProgram(cmd[0])
        proc.setArguments(cmd[1:])
        proc.finished.connect(lambda code, _status, f=folder: self._done(f, code))
        self._procs[folder] = proc
        proc.start()
        return True

    def transcribing(self):
        return bool(self._procs)

    def _done(self, folder, code):
        proc = self._procs.pop(folder, None)
        if proc is not None:
            proc.deleteLater()
        self.transcribed.emit(folder, code == 0 and os.path.isfile(os.path.join(folder, TRANSCRIPT)))


# --- Send review: get it ready for Claude in the chat -------------------------------------------------------------
# Mule only sees Claude's tool calls, not the end of its answer: "Claude is working" holds only as long as calls
# come in. The next call turns the display back on immediately.
IDLE_RESET_S = 120  # this long without a call: Claude is no longer on it (reading, asking in the chat ...)
RECHECK_S = 300  # this long after "finished", mere reading (review_read ...) does not turn the display back on
DRAFT_SETTLE_S = 45  # after individually created drafts this long without a call: finished (as after review_notes)
CHECK_MS = 2000
CHAT_PROMPT = "Review ist da: „{0}“ – mach bitte Entwürfe daraus."


class ReviewSender(QObject):
    """"Send Review": end the running recording, wait for the transcript, back up the scene - then the review is ready
    for Claude in the chat (a sentence is in the clipboard). The Mule tools report when Claude is working on it
    (working) and when the drafts are in (finished). States: idle, transcribing, ready, working."""
    state = Signal()
    done = Signal(str, int)  # review, number of drafts

    def __init__(self, window, session):
        super().__init__(window)
        self.window, self.session = window, session
        self.phase, self.folder, self._last_call = "idle", None, 0.0
        self._drafts = 0  # individually created drafts since "working"
        self._done_at, self._done_name = -1e9, None
        self._idle = QTimer(self, interval=CHECK_MS)
        self._idle.timeout.connect(self._check_idle)
        session.transcribed.connect(self._transcribed)

    @property
    def busy(self):
        return self.phase in ("transcribing", "working")

    def name(self):
        return os.path.basename(self.folder) if self.folder else ""

    def prompt(self, folder=None):
        return tr(CHAT_PROMPT).format(os.path.basename(folder or self.folder or ""))  # chat in Mule's language

    def _set(self, phase):
        self.phase = phase
        if phase == "working":
            self._idle.start()
        else:
            self._idle.stop()
        self.state.emit()

    def send(self):
        """-> ("none"|"transcribing"|"ready", review folder or None)."""
        s = self.session
        folder = s.stop() if s.active else find_review()
        if folder is None:
            return "none", None
        from .mcp_server import backup_before_review
        backup_before_review(self.window, os.path.basename(folder))  # state from before the review
        self.folder = folder
        if read_transcript(folder) is None and os.path.isfile(os.path.join(folder, AUDIO))                 and (folder in s._procs or s.transcribe(folder)):
            self._set("transcribing")
            return "transcribing", folder
        self._ready()
        return "ready", folder

    def _transcribed(self, folder, ok):
        if self.phase == "transcribing" and folder == self.folder:
            self._ready()

    def _ready(self):
        QApplication.clipboard().setText(self.prompt())
        self._set("ready")

    def working(self, name, drafting=False):
        """A Mule tool reads or edits a review (Claude is on it). Shortly after "finished" only a new
        draft counts (drafting), not reading."""
        if (not drafting and self.phase != "working" and name == self._done_name
                and time.monotonic() - self._done_at < RECHECK_S):
            return
        if self.folder is None or name != self.name():
            found = find_review(name)
            if found is None:
                return
            self.folder = found
        self._last_call = time.monotonic()
        if self.phase != "working":
            self._drafts = 0
            self._set("working")

    def activity(self):
        """Some Mule tool was called: Claude is still on it (keeps "working" alive, does not turn it on)."""
        if self.phase == "working":
            self._last_call = time.monotonic()

    def drafted(self, name):
        """A single draft (review_note without review_notes) is in the scene."""
        self.working(name, drafting=True)
        self._drafts += 1

    def finished(self, name, made):
        """review_notes is done: drafts are in the scene."""
        if name == self.name() or self.phase == "working":
            self._drafts = 0
            self._done_at, self._done_name = time.monotonic(), name
            self._set("idle")
            self.done.emit(name, int(made))

    def stop_waiting(self):
        """Button during "Claude is working": display off (Claude can continue, the next call shows it again)."""
        if self.phase == "working":
            self._drafts = 0
            self._set("idle")

    def _check_idle(self):
        if self.phase != "working":
            return
        quiet = time.monotonic() - self._last_call
        if self._drafts and quiet > DRAFT_SETTLE_S:
            self.finished(self.name(), self._drafts)
        elif quiet > IDLE_RESET_S:
            self._set("idle")


def whisper_python():
    """Python with faster-whisper: environment SM_WHISPER_PYTHON, setting whisper_python, the one created by "Set up
    transcription" (whisper_setup), ~/mcp/whisper_venv or Mule's own Python (if faster_whisper is
    installed there). None: none found."""
    from . import whisper_setup
    tries = [os.environ.get("SM_WHISPER_PYTHON"), QSettings("SketchMachine", "SketchMachine").value("whisper_python"),
             whisper_setup.venv_python()]
    venv = os.path.expanduser(os.path.join("~", "mcp", "whisper_venv"))
    tries.append(os.path.join(venv, "Scripts", "python.exe") if sys.platform == "win32"
                 else os.path.join(venv, "bin", "python"))
    for p in tries:
        if p and os.path.isfile(str(p)):
            return str(p)
    import importlib.util
    if not getattr(sys, "frozen", False) and importlib.util.find_spec("faster_whisper") is not None:
        return sys.executable
    return None


def transcribe_command(folder, model=MODEL):
    py = whisper_python()
    if py is None:
        return None
    script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "review_transcribe.py")
    return [py, "-I", script, folder, model]


def transcribe_now(folder, timeout=1800):
    """Create the transcript in the calling thread (for the MCP server, if it is still missing) -> (ok, message)."""
    cmd = transcribe_command(folder)
    if cmd is None:
        return False, ("no Python with faster-whisper found (setting whisper_python, SM_WHISPER_PYTHON or "
                       "~/mcp/whisper_venv)")
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except subprocess.TimeoutExpired:
        return False, "transcription took too long"
    if r.returncode != 0 or not os.path.isfile(os.path.join(folder, TRANSCRIPT)):
        return False, (r.stderr or r.stdout or "transcription failed").strip()[-800:]
    return True, ""


# --- Reading ------------------------------------------------------------------------------------------------------
def read_log(folder):
    out = []
    with open(os.path.join(folder, LOG), encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except ValueError:
                    pass  # aborted last line (crash during recording)
    gone = {e.get("n") for e in out if e["typ"] == "marke_weg"}  # Ctrl+Z: marks that were taken back do not exist
    return [e for e in out if e["typ"] != "marke_weg" and not (e["typ"] in ("marke", "brettmarke") and e.get("n") in gone)]


def word_pointings(events, transcript):
    """Spoken pointing words ("hier", "dort", "here" ...) as pointing spots: time of the word (Whisper
    word times), where the cursor was then - only if the camera was still (not while navigating) and the cursor was in
    the same view. -> [{"t", "typ": "wort", "wort", "vp", "x", "y"}]"""
    import bisect
    cams = [e["t"] for e in events if e["typ"] == "kamera"]
    out = []
    for s in (transcript or {}).get("segments") or []:
        for w in s.get("words") or ():
            word, a, b = w[0], float(w[1]), float(w[2])
            if re.sub(r"[^\w]", "", word.lower()) not in POINT_WORDS:
                continue
            t = (a + b) / 2
            i = bisect.bisect_left(cams, t - 0.3)
            if i < len(cams) and cams[i] <= t + 0.3:
                continue  # camera is moving right now: no pointing
            mouse, cam = at_time(events, "maus", t), at_time(events, "kamera", t)
            if mouse is None or cam is None or mouse["t"] > t or mouse.get("vp") != cam.get("vp"):
                continue
            out.append({"t": round(t, 2), "typ": "wort", "wort": re.sub(r"[^\w]", "", word), "vp": mouse["vp"],
                        "x": mouse["x"], "y": mouse["y"]})
    return out


def read_transcript(folder):
    path = os.path.join(folder, TRANSCRIPT)
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def at_time(events, typ, t):
    """Last event of this type up to time t (otherwise the first one after) or None."""
    best = None
    for e in events:
        if e["typ"] != typ:
            continue
        if e["t"] <= t + 1e-6:
            best = e
        else:
            return best or e
    return best


def cameras(events):
    """Camera events with a running number (#1 ...) - the same view does not keep its number (every
    change counts), so rest phases can be read off."""
    return [e for e in events if e["typ"] == "kamera"]


def moment(events, t):
    """What applied at time t: camera, mouse (x, y), target under the cursor (up to 1.5 s after, the nearest),
    selection, open note, mark nearby."""
    cam = at_time(events, "kamera", t)
    mouse = at_time(events, "maus", t)
    near = [e for e in events if e["typ"] in ("ziel", "marke") and e.get("obj") is not None
            and t - 1.0 <= e["t"] <= t + 1.5]
    target = min(near, key=lambda e: (abs(e["t"] - t), e["typ"] != "marke")) if near else None
    return {"kamera": cam, "maus": mouse, "ziel": target, "auswahl": at_time(events, "auswahl", t),
            "notiz": at_time(events, "notiz", t)}


def segments_with_context(events, transcript):
    """Per section of the transcript: time, text and what happened in that time (targets under the cursor in order,
    marks, camera changes, selection, open note). Without a transcript: empty list."""
    segs = (transcript or {}).get("segments") or []
    cams = cameras(events)
    out = []
    for s in segs:
        a, b = float(s["start"]), float(s["end"])
        inside = [e for e in events if a - 0.3 <= e["t"] <= b + 0.6]
        targets, seen = [], set()
        for e in inside:
            if e["typ"] in ("ziel", "marke") and e.get("obj") is not None:
                key = (e.get("curve"), e.get("obj"))
                if key not in seen:
                    seen.add(key)
                    targets.append(e)
        cam_ids = sorted({cams.index(c) + 1 for c in cams if a - 0.3 <= c["t"] <= b} |
                         ({cams.index(at_time(events, "kamera", a)) + 1} if cams else set()))
        out.append({"start": a, "end": b, "text": s["text"].strip(), "targets": targets,
                    "changes": [e for e in inside if e["typ"] in CHANGES],
                    "marks": [e for e in inside if e["typ"] == "marke"], "cams": cam_ids,
                    "board_marks": [e for e in inside if e["typ"] == "brettmarke"],
                    "moving": sum(1 for c in cams if a <= c["t"] <= b) > 3,
                    "selection": (at_time(events, "auswahl", b) or {}).get("ids") or [],
                    "note": (at_time(events, "notiz", b) or {}).get("id")})
    return out


def board_label(img):
    """Short name of an image on the board for the status line (None: spot on the board without an image)."""
    if img is None:
        return tr("Brett")
    return tr("Bild „{0}“").format(img.caption[:30]) if img.caption else tr("Bild auf dem Brett")


def pointing_near(events, t, words=()):
    """Where pointing really happened around t: a "Here!" mark up to MARK_SNAP seconds away, otherwise a spoken
    pointing word up to WORD_SNAP (word_pointings; if a cursor rest is right next to it, that one - it knows the part), otherwise a
    cursor rest (target) up to REST_SNAP before/after - in each case the nearest. None: nothing was pointed at nearby."""
    marks = [e for e in events if e["typ"] == "marke" and abs(e["t"] - t) <= MARK_SNAP]
    if marks:
        return min(marks, key=lambda e: abs(e["t"] - t))
    said = [w for w in words if abs(w["t"] - t) <= WORD_SNAP]
    if said:
        w = min(said, key=lambda e: abs(e["t"] - t))
        close = [e for e in events if e["typ"] == "ziel" and abs(e["t"] - w["t"]) <= 0.6]
        return min(close, key=lambda e: abs(e["t"] - w["t"])) if close else w
    rests = [e for e in events if e["typ"] == "ziel" and t - REST_SNAP[0] <= e["t"] <= t + REST_SNAP[1]]
    return min(rests, key=lambda e: abs(e["t"] - t)) if rests else None


def clock(t):
    t = max(float(t), 0.0)
    return f"{int(t // 60)}:{t % 60:04.1f}"

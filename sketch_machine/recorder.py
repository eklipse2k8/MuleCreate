"""Recording for evaluating your own work (View menu → Recording): every input with a timestamp into a file.

One folder per recording under <user folder>/Aufnahmen/<date_time>/:
- protokoll.jsonl: one line per event. Fields: t (seconds since start), typ, plus per type:
  start (when, version, szene, obs), taste (taste, mods, ziel, modus, dauer_ms), klick (knopf, x/y in the target, gx/gy
  global, ziel, modus, dauer_ms), loslassen (knopf, ziel, gezogen_px, dauer_ms), doppelklick, rad, aktion (menu,
  bar or shortcut: text, dauer_ms), modus (base state/tool has changed), haenger (ms, last input,
  image), obs (recording runs/stopped, file), ende.
- haenger_<n>.png: small image of the window when Mule did not respond for longer than HANG_SHOT_MS.

Computing time: dauer_ms per input = time until the event loop is free again (processing including immediate
redraw). Plus a tick every TICK_MS: if it comes clearly too late, Mule was busy → entry "haenger".
Text in input fields is not recorded (only that typing happened).

OBS (optional): Mule starts and stops the recording via OBS's WebSocket server (built in since OBS 28).
Mule reads address and password from the OBS settings file; the server must be switched on in OBS
(Tools → WebSocket Server Settings). The moment OBS reports "recording runs" is in the log as t –
so video and log can be laid on top of each other frame-accurately.
"""
import base64
import datetime
import hashlib
import json
import os
import sys
import threading
import time
import uuid

from PySide6.QtCore import QEvent, QObject, QSettings, Qt, QTimer, QUrl, Signal
from PySide6.QtWidgets import QAbstractSpinBox, QApplication, QLineEdit, QPlainTextEdit, QTextEdit

from . import paths
from .i18n import tr

TICK_MS = 50
HANG_MS = 150  # from here a delay counts as a hang
HANG_SHOT_MS = 1000  # from here with image
SHOT_WIDTH = 640
DRAG_PX = 4

_KEYS = {QEvent.KeyPress}
_MOUSE = {QEvent.MouseButtonPress: "klick", QEvent.MouseButtonRelease: "loslassen",
          QEvent.MouseButtonDblClick: "doppelklick"}
_TEXT_WIDGETS = (QLineEdit, QTextEdit, QPlainTextEdit, QAbstractSpinBox)


def recordings_dir():
    path = os.path.join(paths.user_dir(), "Aufnahmen")
    os.makedirs(path, exist_ok=True)
    return path


def obs_config():
    """(port, password or "", enabled) from the OBS settings file, None without OBS WebSocket."""
    if sys.platform == "win32":
        base = os.environ.get("APPDATA", "")
    elif sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    path = os.path.join(base, "obs-studio", "plugin_config", "obs-websocket", "config.json")
    try:
        with open(path, encoding="utf-8") as f:
            c = json.load(f)
    except (OSError, ValueError):
        return None
    password = c.get("server_password", "") if c.get("auth_required", True) else ""
    return int(c.get("server_port", 4455)), password, bool(c.get("server_enabled", False))


def obs_auth(password, salt, challenge):
    """Login according to obs-websocket 5: base64(sha256(base64(sha256(password + salt)) + challenge))."""
    secret = base64.b64encode(hashlib.sha256((password + salt).encode()).digest()).decode()
    return base64.b64encode(hashlib.sha256((secret + challenge).encode()).digest()).decode()


def _widget_path(w):
    """Short name of the target: class or objectName, from inside to outside (at most three levels)."""
    parts = []
    while w is not None and len(parts) < 3:
        name = w.objectName()
        parts.append(name if name and not name.startswith("qt_") else type(w).__name__)
        w = w.parentWidget()
    return "/".join(parts)


class ObsLink(QObject):
    """Connection to OBS's WebSocket server: start/stop recording, report state."""
    state = Signal(str, str)  # ("verbunden" | "laeuft" | "steht" | "fehler", text/file)

    def __init__(self, parent=None):
        super().__init__(parent)
        from PySide6.QtWebSockets import QWebSocket
        self.ws = QWebSocket()
        self.ws.textMessageReceived.connect(self._message)
        self.ws.errorOccurred.connect(lambda _e: self.state.emit("fehler", self.ws.errorString()))
        self.ready = False
        self.recording = False
        self._password = ""
        self._pending = []

    def connect_obs(self):
        conf = obs_config()
        if conf is None:
            self.state.emit("fehler", tr("OBS-WebSocket nicht gefunden (OBS ab Version 28 nötig)"))
            return False
        port, self._password, enabled = conf
        if not enabled:
            self.state.emit("fehler", tr("In OBS den WebSocket-Server einschalten: Werkzeuge → WebSocket-Servereinstellungen"))
            return False
        self.ws.open(QUrl(f"ws://127.0.0.1:{port}"))
        return True

    def request(self, kind):
        if not self.ready:
            self._pending.append(kind)
            return
        self.ws.sendTextMessage(json.dumps({"op": 6, "d": {"requestType": kind, "requestId": uuid.uuid4().hex}}))

    def close(self):
        self.ws.close()

    def _message(self, text):
        try:
            msg = json.loads(text)
        except ValueError:
            return
        op, d = msg.get("op"), msg.get("d", {})
        if op == 0:  # Hello: log in, subscribe to the outputs' events (recording)
            ident = {"rpcVersion": 1, "eventSubscriptions": 1 << 6}
            auth = d.get("authentication")
            if auth:
                ident["authentication"] = obs_auth(self._password, auth["salt"], auth["challenge"])
            self.ws.sendTextMessage(json.dumps({"op": 1, "d": ident}))
        elif op == 2:  # Identified
            self.ready = True
            self.state.emit("verbunden", "")
            for kind in self._pending:
                self.request(kind)
            self._pending = []
        elif op == 5 and d.get("eventType") == "RecordStateChanged":
            data = d.get("eventData", {})
            out = data.get("outputState", "")
            if out == "OBS_WEBSOCKET_OUTPUT_STARTED":
                self.recording = True
                self.state.emit("laeuft", data.get("outputPath") or "")
            elif out == "OBS_WEBSOCKET_OUTPUT_STOPPED":
                self.recording = False
                self.state.emit("steht", data.get("outputPath") or "")
        elif op == 7:
            status = d.get("requestStatus", {})
            if not status.get("result", True) and status.get("code") not in (500,):  # 500 = already running / already stopped
                self.state.emit("fehler", f"OBS {d.get('requestType')}: {status.get('comment') or status.get('code')}")


class Recorder(QObject):
    """Records inputs, actions, mode changes and hangs of the main window."""
    changed = Signal()

    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.active = False
        self.folder = None
        self._file = None
        self._t0 = 0.0
        self._tick = QTimer(self)
        self._tick.setInterval(TICK_MS)
        self._tick.timeout.connect(self._on_tick)
        self._last_tick = 0.0
        self._last_input = None
        self._press = {}
        self._mode = None
        self._shots = 0
        self._busy = False
        self.obs = None
        self.obs_file = ""
        self._hooked = set()
        self._last_event = None

    # --- Start/end ---
    def start(self, with_obs=False):
        if self.active:
            return self.folder
        stamp = datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S")
        self.folder = os.path.join(recordings_dir(), stamp)
        os.makedirs(self.folder, exist_ok=True)
        self._file = open(os.path.join(self.folder, "protokoll.jsonl"), "w", encoding="utf-8", buffering=1)
        self._t0 = time.perf_counter()
        self._last_tick = self._t0
        self._shots = 0
        self.obs_file = ""
        self.active = True
        scene = getattr(self.window, "path", None)
        self.write("start", wann=datetime.datetime.now().isoformat(timespec="milliseconds"),
                   version=_version(), szene=scene, obs=bool(with_obs),
                   bildschirm=_screen_info(self.window))
        self._hook_actions()
        QApplication.instance().installEventFilter(self)
        self._tick.start()
        self._watch_start()
        self._mode = None
        self._note_mode()
        if with_obs:
            self._start_obs()
        self.changed.emit()
        return self.folder

    def stop(self):
        if not self.active:
            return
        if self.obs is not None:
            self.obs.request("StopRecord")
            QTimer.singleShot(3000, self._close_obs)  # time for the "stopped" message including the file name
        QApplication.instance().removeEventFilter(self)
        self._tick.stop()
        self.write("ende")
        self.active = False
        if self.obs is None:
            self._close_file()
        self.changed.emit()

    def _close_file(self):
        if self._file is not None:
            self._file.close()
            self._file = None

    def _close_obs(self):
        if self.obs is not None:
            self.obs.close()
            self.obs.deleteLater()
            self.obs = None
        self._close_file()

    def elapsed(self):
        return time.perf_counter() - self._t0 if self.active else 0.0

    def write(self, typ, **data):
        if self._file is None:
            return
        row = {"t": round(time.perf_counter() - self._t0, 4), "typ": typ}
        row.update(data)
        try:
            self._file.write(json.dumps(row, ensure_ascii=False) + "\n")
        except (OSError, ValueError):
            pass

    # --- OBS ---
    def _start_obs(self):
        self.obs = ObsLink(self)
        self.obs.state.connect(self._obs_state)
        if self.obs.connect_obs():
            self.obs.request("StartRecord")

    def _obs_state(self, kind, text):
        if kind == "laeuft":
            self.obs_file = text
        self.write("obs", zustand=kind, info=text)
        if kind == "fehler":
            self.window.statusBar().showMessage(tr("OBS: {0}").format(text), 8000)
        elif kind == "steht" and not self.active:
            self._close_obs()
        self.changed.emit()

    # --- Recording ---
    def _hook_actions(self):
        from PySide6.QtGui import QAction
        for action in self.window.findChildren(QAction):
            if id(action) in self._hooked:
                continue
            self._hooked.add(id(action))
            action.triggered.connect(lambda _=False, a=action: self._on_action(a))

    def _on_action(self, action):
        if not self.active:
            return
        text = action.text().split("\t")[0].replace("&", "") or action.toolTip().split(":")[0]
        self._timed("aktion", text=text[:80], kuerzel=action.shortcut().toString())

    def _timed(self, typ, **data):
        """Event with computing time: written as soon as the event loop is free again."""
        t = time.perf_counter()
        self._last_input = typ + ":" + str(data.get("taste") or data.get("text") or data.get("knopf") or "")

        def done():
            data["dauer_ms"] = round((time.perf_counter() - t) * 1000, 1)
            if self.active:
                self._write_at(t, typ, data)
            self._note_mode()
        QTimer.singleShot(0, done)

    def _write_at(self, t, typ, data):
        if self._file is None:
            return
        row = {"t": round(t - self._t0, 4), "typ": typ}
        row.update(data)
        try:
            self._file.write(json.dumps(row, ensure_ascii=False) + "\n")
        except (OSError, ValueError):
            pass

    def _note_mode(self):
        """Base state and tool: one "modus" entry when something changed."""
        try:
            vp = self.window.viewport
            ws = vp.ws
            mode = {"modus": "notizen" if vp.notes_mode else "edit" if vp.select_mode else "zeichnen",
                    "werkzeug": ws.draw_tool, "malen": bool(ws.paint_mode), "komponente": ws.component,
                    "gizmo": vp.gizmo.tool, "board_angeheftet": bool(getattr(self.window, "_note_pinned", False))}
        except Exception:  # noqa: BLE001 – recording must never disturb the work
            return
        if mode != self._mode:
            self._mode = mode
            self.write("modus", **mode)

    def _mode_name(self):
        return self._mode["modus"] if self._mode else ""

    def eventFilter(self, obj, e):
        if not self.active:
            return False
        try:
            t = e.type()
            if t in _KEYS and obj.isWidgetType() and obj is QApplication.focusWidget() and not e.isAutoRepeat():
                self._on_key(obj, e)
            elif t in _MOUSE and obj.isWidgetType() and self._first(e):
                self._on_mouse(obj, e, _MOUSE[t])
            elif t == QEvent.Wheel and obj.isWidgetType() and self._first(e):
                self.write("rad", ziel=_widget_path(obj), schritte=e.angleDelta().y() / 120)
        except Exception:  # noqa: BLE001
            pass
        return False

    def _first(self, e):
        """An unaccepted event travels on to the parent: count only at the first (innermost) receiver."""
        key = (int(e.type().value), e.timestamp(), e.globalPosition().x(), e.globalPosition().y())
        if key == self._last_event:
            return False
        self._last_event = key
        return True

    def _on_key(self, obj, e):
        from PySide6.QtGui import QKeySequence
        if isinstance(obj, _TEXT_WIDGETS) and (e.modifiers() & ~Qt.ShiftModifier) == Qt.NoModifier:
            if e.text() and e.text().isprintable():
                self.write("tippen", ziel=_widget_path(obj))
                return
        name = QKeySequence(e.keyCombination()).toString() or e.text()
        self._timed("taste", taste=name, ziel=_widget_path(obj), modus=self._mode_name())

    def _on_mouse(self, obj, e, typ):
        p, g = e.position(), e.globalPosition()
        button = {Qt.LeftButton: "links", Qt.RightButton: "rechts", Qt.MiddleButton: "mitte"}.get(e.button(), "andere")
        data = {"knopf": button, "ziel": _widget_path(obj), "x": round(p.x()), "y": round(p.y()),
                "gx": round(g.x()), "gy": round(g.y()), "modus": self._mode_name()}
        if typ == "klick":
            self._press[button] = (g.x(), g.y(), time.perf_counter())
        elif typ == "loslassen" and button in self._press:
            x0, y0, t0 = self._press.pop(button)
            data["gezogen_px"] = round(((g.x() - x0) ** 2 + (g.y() - y0) ** 2) ** 0.5)
            data["gehalten_s"] = round(time.perf_counter() - t0, 3)
            if data["gezogen_px"] < DRAG_PX:
                data.pop("gezogen_px")
        self._timed(typ, **data)

    def _on_tick(self):
        now = time.perf_counter()
        late = (now - self._last_tick) * 1000 - TICK_MS
        self._last_tick = now
        if late < HANG_MS or self._busy:
            self._hang_where = None
            return
        row = {"ms": round(late), "letzte_eingabe": self._last_input, "modus": self._mode_name()}
        where, self._hang_where = self._hang_where, None
        if where:
            row["wo"] = where  # program location in the middle of the hang (_watch)
        if late >= HANG_SHOT_MS:
            row["bild"] = self._shot()
        self._write_at(now - late / 1000, "haenger", row)

    # --- Where is Mule stuck when it hangs? ---
    # The tick notices a hang only when it is over. A second thread therefore watches the clock on the side: if
    # the tick stays away longer than HANG_MS, it reads once in which functions the main thread is currently
    # stuck. That then appears as "wo" in the hang entry (innermost first) – so a recording shows the cause, not just the duration.
    def _watch_start(self):
        self._hang_where = None
        self._main_thread = threading.main_thread().ident
        t = threading.Thread(target=self._watch, name="mule-aufnahme-uhr", daemon=True)
        t.start()

    def _watch(self):
        seen = None
        while self.active:
            time.sleep(0.04)
            last = self._last_tick
            if last == seen or self._busy:
                continue
            if (time.perf_counter() - last) * 1000 < TICK_MS + HANG_MS:
                continue
            seen = last  # once per missed tick
            frame = sys._current_frames().get(self._main_thread)
            parts = []
            while frame is not None and len(parts) < 9:
                name = frame.f_code.co_filename.replace("\\", "/")
                if "/sketch_machine/" in name and not name.endswith("recorder.py"):
                    parts.append(f"{name.rsplit('/', 1)[-1][:-3]}.{frame.f_code.co_name}:{frame.f_lineno}")
                frame = frame.f_back
            self._hang_where = " < ".join(parts) or "außerhalb von Mule (Qt, Grafiktreiber)"

    def _shot(self):
        self._busy = True
        try:
            self._shots += 1
            name = f"haenger_{self._shots:03d}.png"
            pix = self.window.grab()
            if pix.width() > SHOT_WIDTH:
                pix = pix.scaledToWidth(SHOT_WIDTH)
            pix.save(os.path.join(self.folder, name))
            return name
        except Exception:  # noqa: BLE001
            return None
        finally:
            self._last_tick = time.perf_counter()  # the image itself does not count as a hang
            self._busy = False


def _version():
    try:
        import subprocess
        if not paths.FROZEN:
            out = subprocess.run(["git", "describe", "--tags", "--always"], cwd=paths.ROOT, capture_output=True,
                                 text=True, timeout=3)
            return out.stdout.strip() or None
    except Exception:  # noqa: BLE001
        pass
    path = os.path.join(paths.ROOT, "VERSION")
    try:
        with open(path, encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return None


def _screen_info(window):
    s = window.screen()
    if s is None:
        return None
    g = s.geometry()
    return {"breite": g.width(), "hoehe": g.height(), "skalierung": s.devicePixelRatio()}


def saved_obs_choice():
    return QSettings("SketchMachine", "SketchMachine").value("recorder_obs", True, type=bool)


def save_obs_choice(on):
    QSettings("SketchMachine", "SketchMachine").setValue("recorder_obs", bool(on))

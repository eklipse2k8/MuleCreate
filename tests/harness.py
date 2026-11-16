"""Test-Harness: startet Sketch Machine wie ein Nutzer (echtes Fenster, echte Maus- und Tastenereignisse).

Einstellungen: QSettings wird VOR dem Import der App auf eine Wegwerf-Datei umgelenkt – Tests schreiben nie in die
echten Einstellungen (Fensterlayout, Farben, Druck …), auch nicht beim Schließen des Fensters.

Gebrauch in einer Testdatei:

    from tests.harness import H, expected_failure

    def test_etwas(h: H):
        h.new_scene()
        ...
        assert bedingung, "Meldung"

    @expected_failure("Loft hält Geister-Querschnitte (F5)")
    def test_bekanntes_problem(h: H):
        ...
"""
import math
import os
import tempfile
import time

import numpy as np
from PySide6 import QtCore

# --- Einstellungen umlenken (vor jedem Import der App) ---
_SETTINGS_DIR = tempfile.mkdtemp(prefix="sketch_tests_")
_SETTINGS_FILE = os.path.join(_SETTINGS_DIR, "settings.ini")
_OrigSettings = QtCore.QSettings


class _TestSettings(_OrigSettings):
    def __init__(self, *args, **kwargs):
        super().__init__(_SETTINGS_FILE, _OrigSettings.IniFormat)


QtCore.QSettings = _TestSettings

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt  # noqa: E402

from sketch_machine import renderer as _renderer  # noqa: E402

# Teil-Upload der Striche in jedem Test gegen die volle Aufbereitung prüfen (Messskripte: SM_FAST=1 schaltet es ab)
_renderer.Renderer.VERIFY_STROKES = not os.environ.get("SM_FAST")
from sketch_machine.vp import display_lists as _display_lists  # noqa: E402

# … und die je Linienobjekt gemerkten Strich-Einträge gegen frisch zusammengestellte
_display_lists.DisplayListMixin.VERIFY_LISTS = not os.environ.get("SM_FAST")
from sketch_machine import scene_surfaces as _scene_surfaces  # noqa: E402

# … und jede beim Abgleich übersprungene Fläche: trotzdem abgleichen, es darf sich nichts ändern
_scene_surfaces.SurfaceSyncMixin.VERIFY_SYNC = not os.environ.get("SM_FAST")
# Undo-Kopie teilt Unverändertes mit dem vorigen Schritt: jede Kopie zusätzlich voll anlegen und vergleichen
from sketch_machine import scene as _scene_mod  # noqa: E402

_scene_mod.Scene.VERIFY_UNDO = not os.environ.get("SM_FAST")
# Verzeichnisse (Objekt/Linie zu einer id) in jedem Test gegen die Suche über alle Listen prüfen
_scene_mod.Scene.VERIFY_INDEX = not os.environ.get("SM_FAST")
_scene_mod.SurfaceObject.VERIFY_KEY = not os.environ.get("SM_FAST")  # gemerkte Flächen-Schlüssel nachrechnen
from PySide6.QtGui import QColor, QMouseEvent, QWheelEvent  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

# Fehler in Qt-Rückrufen (paintGL, Ereignisse) landen sonst nur auf der Konsole – im Viewport sieht man dann bunte
# Kästchen. Sie werden hier gesammelt, und der Test, in dem sie auftreten, gilt als FEHLER (run.py).
QT_ERRORS = []


def _qt_hook(kind, value, tb):
    import traceback
    QT_ERRORS.append("".join(traceback.format_exception(kind, value, tb)).strip())


import sys  # noqa: E402
sys.excepthook = _qt_hook

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCENES = os.path.join(ROOT, "tests", "scenes")
OUT = os.path.join(ROOT, "tests", "_out")  # Bilder und Zwischenstände der Läufe (nicht im Repo)


def expected_failure(reason):
    """Bekanntes Problem: der Test beschreibt das gewünschte Verhalten und darf (noch) scheitern."""
    def mark(fn):
        fn.expected_failure = reason
        return fn
    return mark


class H:
    """Ein App-Fenster für alle Tests einer Datei, mit Helfern für echte Eingaben."""

    def __init__(self, size=(1200, 800)):
        from sketch_machine.app import MainWindow
        QApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
        self.app = QApplication.instance() or QApplication([])
        self.w = MainWindow()
        self.w.viewport.set_display_resolution(1.0)  # Viewport-Qualität aus der App-Einstellung: in Tests immer 1
        from sketch_machine.workspace import CLEANUP_DIST_DEFAULT
        self.w.ws.cleanup_dist = CLEANUP_DIST_DEFAULT  # Cleanup-Fangweite aus der App-Einstellung: in Tests der Standard
        self.w.resize(*size)
        self.w.move(-4000, 40)
        self.w.show()
        self.pump(0.2)
        self.w._set_dark(False, persist=False)
        os.makedirs(OUT, exist_ok=True)

    # --- Grundlagen ---
    @property
    def v(self):
        return self.w.viewport

    @property
    def sc(self):
        return self.v.scene

    def pump(self, seconds=0.0):
        end = time.monotonic() + seconds
        while True:
            self.app.processEvents()
            if time.monotonic() >= end:
                break
            time.sleep(0.01)

    def new_scene(self):
        from sketch_machine.scene import Scene
        self.v.set_scene(Scene())
        if self.v.select_mode:
            self.v.set_select_mode(False)
        self.v.ws.paint_mode = False
        self.v.set_draw_tool("pen")
        self.pump(0.02)
        return self.sc

    def load(self, path):
        """Szene laden (Pfad relativ zum Repo); liefert die gespeicherten Daten (z. B. Kamera)."""
        from sketch_machine.scene import Scene
        scene, data = Scene.load(os.path.join(ROOT, path) if not os.path.isabs(path) else path)
        self.v.set_scene(scene)
        views = (data.get("views") or {}).get("children") or []
        if views and views[0].get("camera"):
            cam = views[0]["camera"]
            self.v.cam.set_state(np.array(cam["target"]), cam["dist"], np.array(cam["rot"]))
        self.v._changed()
        self.pump(0.02)
        return data

    def camera(self, target, dist, back):
        from sketch_machine.camera import view_for_back
        self.v.cam.set_state(np.asarray(target, float), float(dist), view_for_back(np.asarray(back, float)))
        self.v._changed()
        self.grab()

    def frame(self, points, back=(0.4, 0.6, 0.7), margin=1.6):
        """Kamera so, dass die Punkte im Bild sind."""
        pts = np.asarray(points, float).reshape(-1, 3)
        size = float(np.linalg.norm(np.ptp(pts, axis=0))) or 1.0
        self.camera(pts.mean(axis=0), size * margin, back)

    def grab(self):
        return self.v.grabFramebuffer()

    def stroke_frames(self, screen_points, step_px=4):
        """Wie stroke, aber mit einem gezeichneten Bild nach jeder Mausbewegung (Fehler beim Zeichnen des laufenden
        Strichs zeigen sich nur so)."""
        pts = [np.array([p.x(), p.y()], float) for p in screen_points]
        dense = [pts[0]]
        for a, b in zip(pts[:-1], pts[1:]):
            n = max(1, int(np.linalg.norm(b - a) / step_px))
            dense += [a + (b - a) * (k / n) for k in range(1, n + 1)]
        self.move(QPointF(*dense[0]))
        QTest.mousePress(self.v, Qt.LeftButton, Qt.NoModifier, QPoint(*dense[0].astype(int)))
        for p in dense[1:]:
            self.move(QPointF(*p), Qt.LeftButton)
            self.grab()
        QTest.mouseRelease(self.v, Qt.LeftButton, Qt.NoModifier, QPoint(*dense[-1].astype(int)))
        self.pump(0.02)
        self.grab()

    def save_image(self, name):
        img = self.grab()
        img.save(os.path.join(OUT, name))
        return img

    def edit_mode(self, component="edge"):
        if not self.v.select_mode:
            self.key(Qt.Key_Tab)
        self.v.ws.component = component
        self.v._changed()
        self.grab()

    def draw_mode(self):
        if self.v.select_mode:
            self.key(Qt.Key_Tab)

    # --- Bildschirm ---
    def scr(self, point):
        """Weltpunkt -> QPoint auf dem Bildschirm."""
        q = self.v.project(np.asarray(point, float).reshape(1, 3))[0][0]
        return QPoint(int(round(q[0])), int(round(q[1])))

    def scrf(self, point):
        q = self.v.project(np.asarray(point, float).reshape(1, 3))[0][0]
        return QPointF(float(q[0]), float(q[1]))

    # --- Eingaben ---
    def move(self, pos, buttons=Qt.NoButton, mods=Qt.NoModifier):
        pos = QPointF(pos)
        self.app.sendEvent(self.v, QMouseEvent(QEvent.MouseMove, pos, self.v.mapToGlobal(pos), Qt.NoButton, buttons, mods))
        self.app.processEvents()

    def click(self, pos, mods=Qt.NoModifier):
        self.move(pos, mods=mods)
        QTest.mouseClick(self.v, Qt.LeftButton, mods, QPoint(pos.x(), pos.y()) if isinstance(pos, QPoint) else pos.toPoint())
        self.pump(0.02)

    def dclick(self, pos, mods=Qt.NoModifier):
        pos = pos if isinstance(pos, QPoint) else pos.toPoint()
        self.click(pos, mods)
        QTest.mouseDClick(self.v, Qt.LeftButton, mods, pos)
        QTest.mouseRelease(self.v, Qt.LeftButton, mods, pos)  # wie eine echte Maus: nach dem Doppelklick loslassen
        self.pump(0.02)

    def key(self, k, mods=Qt.NoModifier):
        QTest.keyClick(self.v, k, mods)
        self.pump(0.02)

    def wheel(self, steps, mods=Qt.NoModifier, pos=None):
        pos = QPointF(self.v.width() / 2, self.v.height() / 2) if pos is None else QPointF(pos)
        ev = QWheelEvent(pos, self.v.mapToGlobal(pos), QPoint(0, 0), QPoint(0, int(120 * steps)), Qt.NoButton, mods,
                         Qt.NoScrollPhase, False)
        QApplication.sendEvent(self.v, ev)
        self.pump(0.02)

    def stroke(self, screen_points, hold=False, mods=Qt.NoModifier, step_px=4):
        """Strich entlang von Bildschirmpunkten (QPoint/QPointF); hold = am Ende stillhalten (Gerade/Form)."""
        pts = [np.array([p.x(), p.y()], float) for p in screen_points]
        dense = [pts[0]]
        for a, b in zip(pts[:-1], pts[1:]):
            n = max(1, int(np.linalg.norm(b - a) / step_px))
            dense += [a + (b - a) * (k / n) for k in range(1, n + 1)]
        self.move(QPointF(*dense[0]), mods=mods)
        QTest.mousePress(self.v, Qt.LeftButton, mods, QPoint(*dense[0].astype(int)))
        self.app.processEvents()
        for p in dense[1:]:
            self.move(QPointF(*p), Qt.LeftButton, mods)
        if hold:
            self.pump(0.7)
            self.move(QPointF(*(dense[-1] + 0.3)), Qt.LeftButton, mods)
        QTest.mouseRelease(self.v, Qt.LeftButton, mods, QPoint(*dense[-1].astype(int)))
        self.pump(0.02)

    def stroke_world(self, points, hold=False, mods=Qt.NoModifier):
        """Strich durch Weltpunkte (auf die aktive Zeichenfläche projiziert, wie ein Nutzer zeichnen würde)."""
        self.stroke([self.scrf(p) for p in points], hold=hold, mods=mods)

    # --- Abfragen ---
    def curves(self):
        return [c for st in self.sc.strokes for c in st.curves]

    # --- Zugang zur Szene für Tests (Umbau-Plan, Etappe 2) ---
    # Tests sollen die Szene über diese Fragen lesen statt über ihre inneren Felder: Mit den Objekt-Inseln und der Lage
    # je Objekt ändert sich, wo Punkte stehen (lokal statt Welt) und wie Verbindungen gespeichert sind. Dann wird hier
    # EINE Stelle angepasst statt hunderter Tests. Neue Tests benutzen sie; alte werden umgestellt, wenn sie brechen.
    def welt(self, curve):
        """Punkte einer Linie in Weltkoordinaten, (N, 3)."""
        return np.asarray(curve.points, float)

    def objekt_von(self, curve):
        """Linienobjekt, zu dem die Linie gehört (None: zu keinem)."""
        return self.sc.owner_of(curve)

    def verbunden(self, a, ka, b, kb):
        """Hängen Knoten ka der Linie a und Knoten kb der Linie b am selben Punkt?"""
        from sketch_machine import network
        network.sync(self.sc)
        pa, pb = network.pid_of(a, ka), network.pid_of(b, kb)
        return pa is not None and pa == pb

    def flaechen_von(self, stroke):
        """Flächen, die dem Linienobjekt gehören."""
        return [f for f in self.sc.surfaces if f.owner == stroke.id]

    def form(self, surface):
        """Angezeigtes Netz einer Fläche in Weltkoordinaten: (Punkte (N, 3), Dreiecke (M, 3))."""
        mesh = surface.fill_mesh()
        return np.asarray(mesh[0], float), np.asarray(mesh[1])

    def pixel(self, img, pos):
        return QColor(img.pixel(pos.x(), pos.y())).getRgb()[:3]

    @staticmethod
    def diff(a, b, step=2, threshold=2):
        """Anzahl abweichender Pixel (Stichprobe, Toleranz in Farbstufen) zwischen zwei Bildern."""
        if a.size() != b.size():
            return -1
        n = 0
        for y in range(0, a.height(), step):
            for x in range(0, a.width(), step):
                pa, pb = a.pixel(x, y), b.pixel(x, y)
                if pa != pb:
                    ca, cb = QColor(pa).getRgb(), QColor(pb).getRgb()
                    if max(abs(i - j) for i, j in zip(ca[:3], cb[:3])) > threshold:
                        n += 1
        return n

    def close(self):
        """Fenster schließen – schreibt nur in die Wegwerf-Einstellungen."""
        self.sc.dirty = False
        self.w.close()


def line(a, b, n=12):
    return np.linspace(np.asarray(a, float), np.asarray(b, float), n)


def arc(center, radius, a0, a1, n=24, axis="y"):
    """Kreisbogen um center in der Ebene senkrecht zu axis (Winkel in Grad)."""
    t = np.radians(np.linspace(a0, a1, n))
    c = np.asarray(center, float)
    if axis == "y":
        return np.stack([c[0] + radius * np.cos(t), np.full_like(t, c[1]), c[2] + radius * np.sin(t)], axis=1)
    if axis == "z":
        return np.stack([c[0] + radius * np.cos(t), c[1] + radius * np.sin(t), np.full_like(t, c[2])], axis=1)
    return np.stack([np.full_like(t, c[0]), c[1] + radius * np.cos(t), c[2] + radius * np.sin(t)], axis=1)


def circle(center, radius, n=33, axis="y"):
    return arc(center, radius, 0.0, 360.0, n, axis)


__all__ = ["H", "expected_failure", "line", "arc", "circle", "ROOT", "SCENES", "OUT", "Qt", "QPoint", "QPointF", "math"]

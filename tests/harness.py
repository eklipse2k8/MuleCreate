"""Test harness: starts Sketch Machine like a user (real window, real mouse and key events).

Settings: QSettings is redirected to a throwaway file BEFORE the app is imported – tests never write to the real
settings (window layout, colors, pressure …), not even when the window is closed.

Usage in a test file:

    from tests.harness import H, expected_failure

    def test_something(h: H):
        h.new_scene()
        ...
        assert condition, "message"

    @expected_failure("Loft keeps ghost cross-sections (F5)")
    def test_known_problem(h: H):
        ...
"""
import math
import os
import tempfile
import time

import numpy as np
from PySide6 import QtCore

# --- Redirect settings (before any import of the app) ---
_SETTINGS_DIR = tempfile.mkdtemp(prefix="sketch_tests_")
_SETTINGS_FILE = os.path.join(_SETTINGS_DIR, "settings.ini")
_OrigSettings = QtCore.QSettings


class _TestSettings(_OrigSettings):
    def __init__(self, *args, **kwargs):
        super().__init__(_SETTINGS_FILE, _OrigSettings.IniFormat)


QtCore.QSettings = _TestSettings
# brief recipes of the user (recipes.py): tests see an empty recipe folder of their own, never the real one
os.environ["MULE_RECIPES"] = os.path.join(_SETTINGS_DIR, "recipes")

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt  # noqa: E402

from sketch_machine import renderer as _renderer  # noqa: E402

# Check the partial stroke upload in every test against the full preparation (measuring scripts: SM_FAST=1 turns it off)
_renderer.Renderer.VERIFY_STROKES = not os.environ.get("SM_FAST")
from sketch_machine.vp import display_lists as _display_lists  # noqa: E402

# ... and the stroke entries remembered per line object against freshly assembled ones
_display_lists.DisplayListMixin.VERIFY_LISTS = not os.environ.get("SM_FAST")
from sketch_machine import scene_surfaces as _scene_surfaces  # noqa: E402

# ... and every surface skipped during the sync: sync it anyway, nothing may change
_scene_surfaces.SurfaceSyncMixin.VERIFY_SYNC = not os.environ.get("SM_FAST")
# An undo copy shares unchanged data with the previous step: also build every copy in full and compare
from sketch_machine import scene as _scene_mod  # noqa: E402

_scene_mod.Scene.VERIFY_UNDO = not os.environ.get("SM_FAST")
# Check the directories (object/line for an id) in every test against a search over all lists
_scene_mod.Scene.VERIFY_INDEX = not os.environ.get("SM_FAST")
_scene_mod.SurfaceObject.VERIFY_KEY = not os.environ.get("SM_FAST")  # recompute remembered surface keys
from PySide6.QtGui import QColor, QMouseEvent, QWheelEvent  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

# Errors in Qt callbacks (paintGL, events) otherwise only end up on the console – the viewport then shows colored
# boxes. They are collected here, and the test in which they occur counts as an ERROR (run.py).
QT_ERRORS = []


def _qt_hook(kind, value, tb):
    import traceback
    QT_ERRORS.append("".join(traceback.format_exception(kind, value, tb)).strip())


import sys  # noqa: E402
sys.excepthook = _qt_hook

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCENES = os.path.join(ROOT, "tests", "scenes")
OUT = os.path.join(ROOT, "tests", "_out")  # images and intermediate results of the runs (not in the repo)


def expected_failure(reason):
    """Known problem: the test describes the desired behavior and may (still) fail."""
    def mark(fn):
        fn.expected_failure = reason
        return fn
    return mark


class H:
    """One app window for all tests of a file, with helpers for real input."""

    def __init__(self, size=(1200, 800)):
        from sketch_machine.app import MainWindow
        QApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
        self.app = QApplication.instance() or QApplication([])
        self.w = MainWindow()
        self.w.viewport.set_display_resolution(1.0)  # viewport quality from the app setting: always 1 in tests
        from sketch_machine.workspace import CLEANUP_DIST_DEFAULT
        self.w.ws.cleanup_dist = CLEANUP_DIST_DEFAULT  # cleanup snap distance from the app setting: the default in tests
        self.w.resize(*size)
        self.w.move(-4000, 40)
        self.w.show()
        self.pump(0.2)
        self.w._set_dark(False, persist=False)
        os.makedirs(OUT, exist_ok=True)

    # --- Basics ---
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
        """Load a scene (path relative to the repo); returns the saved data (e.g. camera)."""
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
        """Camera such that the points are in the picture."""
        pts = np.asarray(points, float).reshape(-1, 3)
        size = float(np.linalg.norm(np.ptp(pts, axis=0))) or 1.0
        self.camera(pts.mean(axis=0), size * margin, back)

    def grab(self):
        return self.v.grabFramebuffer()

    def stroke_frames(self, screen_points, step_px=4):
        """Like stroke, but with a drawn frame after every mouse move (errors while drawing the running
        stroke only show up this way)."""
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

    # --- Screen ---
    def scr(self, point):
        """World point -> QPoint on the screen."""
        q = self.v.project(np.asarray(point, float).reshape(1, 3))[0][0]
        return QPoint(int(round(q[0])), int(round(q[1])))

    def scrf(self, point):
        q = self.v.project(np.asarray(point, float).reshape(1, 3))[0][0]
        return QPointF(float(q[0]), float(q[1]))

    # --- Input ---
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
        QTest.mouseRelease(self.v, Qt.LeftButton, mods, pos)  # like a real mouse: release after the double click
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
        """Stroke along screen points (QPoint/QPointF); hold = keep still at the end (line/shape)."""
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
        """Stroke through world points (projected onto the active drawing plane, as a user would draw)."""
        self.stroke([self.scrf(p) for p in points], hold=hold, mods=mods)

    # --- Queries ---
    def curves(self):
        return [c for st in self.sc.strokes for c in st.curves]

    # --- Access to the scene for tests (rebuild plan, stage 2) ---
    # Tests should read the scene through these queries instead of its inner fields: with object islands and a pose
    # per object, where points live (local instead of world) and how connections are stored changes. Then ONE place
    # is adjusted here instead of hundreds of tests. New tests use them; old ones are converted when they break.
    def world(self, curve):
        """Points of a line in world coordinates, (N, 3)."""
        return np.asarray(curve.points, float)

    def object_of(self, curve):
        """Line object the line belongs to (None: none)."""
        return self.sc.owner_of(curve)

    def connected(self, a, ka, b, kb):
        """Are node ka of line a and node kb of line b attached to the same point?"""
        from sketch_machine import network
        network.sync(self.sc)
        pa, pb = network.pid_of(a, ka), network.pid_of(b, kb)
        return pa is not None and pa == pb

    def surfaces_of(self, stroke):
        """Surfaces owned by the line object."""
        return [f for f in self.sc.surfaces if f.owner == stroke.id]

    def shape(self, surface):
        """Displayed mesh of a surface in world coordinates: (points (N, 3), triangles (M, 3))."""
        mesh = surface.fill_mesh()
        return np.asarray(mesh[0], float), np.asarray(mesh[1])

    def pixel(self, img, pos):
        return QColor(img.pixel(pos.x(), pos.y())).getRgb()[:3]

    @staticmethod
    def diff(a, b, step=2, threshold=2):
        """Number of differing pixels (sampled, tolerance in color steps) between two images."""
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
        """Close the window – only writes to the throwaway settings."""
        self.sc.dirty = False
        self.w.close()


def line(a, b, n=12):
    return np.linspace(np.asarray(a, float), np.asarray(b, float), n)


def arc(center, radius, a0, a1, n=24, axis="y"):
    """Circular arc around center in the plane perpendicular to axis (angles in degrees)."""
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

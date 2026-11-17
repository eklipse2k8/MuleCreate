"""Startup animation: the logo draws itself in a circle at program start, transparent outside, in front of the desktop.

It starts before the rest of Mule is loaded (see launch.py): the head draws itself, then the animation holds and
"Loading …" stands below the circle until Mule is ready; then the head shakes, "Mule" is written, the tongue licks,
and the main window appears. A click or key skips the rest (once Mule is ready); the animation can be switched off in
the View menu. If the file is missing or unreadable, Mule starts without it.

Only light imports here: this module runs while the big modules are still loading."""
import os
import sys

from PySide6.QtCore import QRect, QSettings, Qt, QTimer, QVariantAnimation
from PySide6.QtGui import QColor, QFont, QGuiApplication, QIcon, QMovie, QPainter
from PySide6.QtWidgets import QApplication, QWidget

from . import paths

ANIMATION = os.path.join(paths.ROOT, "sketch_machine", "assets", "mule_start.webp")
ICON = os.path.join(paths.ROOT, "sketch_machine", "assets", "mule_icon.png")
SETTING = "startup_animation"
SIDE = 460  # edge length on screen, at most 60 % of the shorter screen side
HOLD_FRAME = 60  # head drawn and settled, just before it shakes: here the animation waits while Mule loads
LABEL_H = 44  # room below the circle for "Loading …"
FADE_MS = 250
LONGEST_MS = 8000  # safeguard after loading: if playback hangs, Mule starts anyway


def enabled():
    return QSettings("SketchMachine", "SketchMachine").value(SETTING, True, type=bool)


def set_enabled(on):
    QSettings("SketchMachine", "SketchMachine").setValue(SETTING, bool(on))


def make_application():
    """QApplication with Mule's settings, app id and icon (before any big module is loaded)."""
    QApplication.setAttribute(Qt.AA_ShareOpenGLContexts)  # all viewports share their GPU buffers
    # graphics tablet: ~200 positions/s; unbundled, the queue backs up when one event takes longer
    # (feels like freezing) - Qt merges waiting tablet moves like with the mouse
    QApplication.setAttribute(Qt.AA_CompressTabletEvents)
    if sys.platform == "win32":  # own app ID - otherwise the taskbar groups Mule under python.exe with its icon
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("felixbfx.Mule")
        except Exception:
            pass
    app = QApplication(sys.argv)
    if os.path.isfile(ICON):
        app.setWindowIcon(QIcon(ICON))
    app.setDesktopFileName("mule")
    return app


class StartAnimation(QWidget):
    def __init__(self, done=None, path=ANIMATION):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.SplashScreen)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self._done, self._finished, self._skip = done, False, False
        self._waiting, self._dots = False, 0
        self.movie = QMovie(path, parent=self)
        self.movie.setCacheMode(QMovie.CacheNone)
        self.movie.frameChanged.connect(self._frame)
        self.movie.finished.connect(self.finish)
        self.dots = QTimer(self, interval=400)
        self.dots.timeout.connect(self._tick)
        area = QGuiApplication.primaryScreen().availableGeometry()
        self.side = min(SIDE, int(min(area.width(), area.height()) * 0.6))
        self.setFixedSize(self.side, self.side + LABEL_H)
        self.move(area.center().x() - self.side // 2, area.center().y() - self.side // 2)

    def play(self):
        """Starts playback. False: file not readable, nothing to show."""
        if not self.movie.isValid():
            return False
        self.show()
        self.movie.start()
        if self._done is not None:
            QTimer.singleShot(LONGEST_MS, self, self.finish)
        return True

    def loaded(self, done):
        """Mule is ready: go on from the held frame (head shake, lettering, tongue), then done() shows the window."""
        self._done = done
        self.dots.stop()
        if self._skip:
            self.finish()
            return
        if self._waiting:
            self._waiting = False
            self.movie.setPaused(False)
        self.update()
        QTimer.singleShot(LONGEST_MS, self, self.finish)

    def _frame(self, number):
        if number == HOLD_FRAME and self._done is None:  # still loading: hold the drawn head
            self._waiting = True
            self.movie.setPaused(True)
            self.dots.start()
        self.update()
        count = self.movie.frameCount()
        if count > 0 and number >= count - 1:  # the last frame carries the still image at the end: wait for its duration first
            QTimer.singleShot(max(self.movie.nextFrameDelay(), 0), self, self.finish)

    def _tick(self):
        self._dots = (self._dots + 1) % 4
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.setRenderHint(QPainter.Antialiasing)
        p.drawImage(QRect(0, 0, self.side, self.side), self.movie.currentImage())
        if self._waiting:
            text = "Loading" + " ." * self._dots
            font = QFont("Segoe UI")
            font.setPixelSize(15)
            p.setFont(font)
            w = 128
            box = QRect((self.side - w) // 2, self.side + 8, w, 28)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(34, 38, 37, 235))  # the dark of the circle, readable on any desktop
            p.drawRoundedRect(box, 14, 14)
            p.setPen(QColor(226, 223, 218))
            p.drawText(box.adjusted(22, 0, 0, 0), Qt.AlignVCenter | Qt.AlignLeft, text)
        p.end()

    def mousePressEvent(self, _):
        self._skip_or_finish()

    def keyPressEvent(self, _):
        self._skip_or_finish()

    def _skip_or_finish(self):
        if self._done is None:
            self._skip = True  # still loading: skip the rest as soon as Mule is ready
        else:
            self.finish()

    def finish(self):
        """Once (and only when Mule is ready): show the main window, then fade out; the animation is still on top
        meanwhile."""
        if self._finished or self._done is None:
            return
        self._finished = True
        self.movie.setPaused(True)
        self.dots.stop()
        self._waiting = False
        self._done()
        fade = QVariantAnimation(self, startValue=1.0, endValue=0.0, duration=FADE_MS)
        fade.valueChanged.connect(self.setWindowOpacity)
        fade.finished.connect(self.close)
        fade.start()


def start(owner, begin):
    """Shows the animation and then calls begin(); immediately if there is no animation. owner keeps the window alive.
    (Path without early start: Mule is already loaded here.)"""
    if enabled():
        owner.start_animation = StartAnimation(begin)
        if owner.start_animation.play():
            return
        owner.start_animation = None
    begin()

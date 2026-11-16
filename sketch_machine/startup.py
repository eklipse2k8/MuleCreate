"""Startup animation: the logo draws itself in a circle at program start, transparent outside, in front of the desktop.

The main window only appears afterwards; until then the UI stays free and the animation runs smoothly. A click
or key skips it, it can be switched off in the View menu. If the file is missing or unreadable, Mule starts
without it."""
import os

from PySide6.QtCore import QSettings, Qt, QTimer, QVariantAnimation
from PySide6.QtGui import QGuiApplication, QMovie, QPainter
from PySide6.QtWidgets import QWidget

from . import paths

ANIMATION = os.path.join(paths.ROOT, "sketch_machine", "assets", "mule_start.webp")
SETTING = "startup_animation"
SIDE = 460  # edge length on screen, at most 60 % of the shorter screen side
FADE_MS = 250
LONGEST_MS = 8000  # safeguard: if playback hangs, Mule starts anyway


def enabled():
    return QSettings("SketchMachine", "SketchMachine").value(SETTING, True, type=bool)


def set_enabled(on):
    QSettings("SketchMachine", "SketchMachine").setValue(SETTING, bool(on))


class StartAnimation(QWidget):
    def __init__(self, done, path=ANIMATION):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.SplashScreen)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self._done, self._finished = done, False
        self.movie = QMovie(path, parent=self)
        self.movie.setCacheMode(QMovie.CacheNone)
        self.movie.frameChanged.connect(self._frame)
        self.movie.finished.connect(self.finish)
        area = QGuiApplication.primaryScreen().availableGeometry()
        side = min(SIDE, int(min(area.width(), area.height()) * 0.6))
        self.setFixedSize(side, side)
        self.move(area.center() - self.rect().center())

    def play(self):
        """Starts playback. False: file not readable, nothing to show."""
        if not self.movie.isValid():
            return False
        self.show()
        self.movie.start()
        QTimer.singleShot(LONGEST_MS, self, self.finish)
        return True

    def _frame(self, number):
        self.update()
        count = self.movie.frameCount()
        if count > 0 and number >= count - 1:  # the last frame carries the still image at the end: wait for its duration first
            QTimer.singleShot(max(self.movie.nextFrameDelay(), 0), self, self.finish)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.drawImage(self.rect(), self.movie.currentImage())
        p.end()

    def mousePressEvent(self, _):
        self.finish()

    def keyPressEvent(self, _):
        self.finish()

    def finish(self):
        """Once: show the main window, then fade out; the animation is still on top meanwhile."""
        if self._finished:
            return
        self._finished = True
        self.movie.setPaused(True)
        self._done()
        fade = QVariantAnimation(self, startValue=1.0, endValue=0.0, duration=FADE_MS)
        fade.valueChanged.connect(self.setWindowOpacity)
        fade.finished.connect(self.close)
        fade.start()


def start(owner, begin):
    """Shows the animation and then calls begin(); immediately if there is no animation. owner keeps the window alive."""
    if enabled():
        owner.start_animation = StartAnimation(begin)
        if owner.start_animation.play():
            return
        owner.start_animation = None
    begin()

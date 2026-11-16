"""Startanimation (startup): spielt einmal durch, ruft genau einmal das Hauptfenster auf, Klick überspringt, ohne Datei geht es trotzdem."""
import os
import tempfile
import time

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

from tests.harness import H
from sketch_machine import startup


def _wait(until, seconds):
    end = time.monotonic() + seconds
    while time.monotonic() < end and not until():
        QApplication.processEvents()
        time.sleep(0.002)


def test_datei_ist_lesbar_mit_durchsichtigem_rand(h: H):
    anim = startup.StartAnimation(lambda: None)
    assert anim.movie.isValid() and anim.movie.frameCount() > 200
    assert anim.movie.jumpToNextFrame()
    image = anim.movie.currentImage()
    assert image.hasAlphaChannel() and image.pixelColor(3, 3).alpha() == 0
    assert image.pixelColor(image.width() // 2, image.height() // 2).alpha() == 255


def test_spielt_durch_und_ruft_einmal_auf(h: H):
    calls = []
    anim = startup.StartAnimation(lambda: calls.append(1))
    anim.movie.setSpeed(1000)  # zehnfach: der Test soll nicht fünf Sekunden warten
    assert anim.play()
    _wait(lambda: calls, 3)
    assert calls == [1]
    _wait(lambda: not anim.isVisible(), 1)
    assert not anim.isVisible(), "nach dem Ausblenden geschlossen"
    anim.finish()
    assert calls == [1]


def test_standbild_am_schluss_wird_abgewartet(h: H):
    """Gleiche Bilder fasst die Datei zusammen: das letzte Bild steht rund eine Sekunde."""
    calls = []
    anim = startup.StartAnimation(lambda: calls.append(time.monotonic()))
    anim.movie.setSpeed(400)
    t0 = time.monotonic()
    assert anim.play()
    _wait(lambda: calls, 3)
    assert calls and calls[0] - t0 > 1.0, "viermal so schnell: 4,6 s werden gut 1,1 s"
    _wait(lambda: not anim.isVisible(), 1)


def test_klick_ueberspringt(h: H):
    calls = []
    anim = startup.StartAnimation(lambda: calls.append(1))
    assert anim.play()
    QApplication.processEvents()
    assert not calls
    pos = QPointF(10, 10)
    anim.mousePressEvent(QMouseEvent(QEvent.MouseButtonPress, pos, anim.mapToGlobal(pos), Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))
    assert calls == [1]
    _wait(lambda: not anim.isVisible(), 1)


def test_ohne_datei_oder_abgeschaltet_startet_mule_trotzdem(h: H):
    calls = []
    missing = startup.StartAnimation(lambda: calls.append(1), os.path.join(tempfile.mkdtemp(), "fehlt.webp"))
    assert not missing.play() and not missing.isVisible()
    original = startup.ANIMATION, startup.enabled

    class Owner:
        pass
    try:
        startup.enabled = lambda: False
        startup.start(Owner(), lambda: calls.append(2))
        assert calls == [2]
        startup.enabled = lambda: True
        startup.StartAnimation.__init__.__defaults__ = (os.path.join(tempfile.mkdtemp(), "fehlt.webp"),)
        owner = Owner()
        startup.start(owner, lambda: calls.append(3))
        assert calls == [2, 3] and owner.start_animation is None
    finally:
        startup.StartAnimation.__init__.__defaults__ = (original[0],)
        startup.enabled = original[1]

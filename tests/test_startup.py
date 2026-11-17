"""Start animation (startup): plays through once, calls the main window exactly once, a click skips it, without a file it still works."""
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


def test_file_is_readable_with_transparent_border(h: H):
    anim = startup.StartAnimation(lambda: None)
    assert anim.movie.isValid() and anim.movie.frameCount() > 200
    assert anim.movie.jumpToNextFrame()
    image = anim.movie.currentImage()
    assert image.hasAlphaChannel() and image.pixelColor(3, 3).alpha() == 0
    assert image.pixelColor(image.width() // 2, image.height() // 2).alpha() == 255


def test_plays_through_and_calls_once(h: H):
    calls = []
    anim = startup.StartAnimation(lambda: calls.append(1))
    anim.movie.setSpeed(1000)  # ten times: the test should not wait five seconds
    assert anim.play()
    _wait(lambda: calls, 3)
    assert calls == [1]
    _wait(lambda: not anim.isVisible(), 1)
    assert not anim.isVisible(), "closed after fading out"
    anim.finish()
    assert calls == [1]


def test_final_still_frame_is_waited_for(h: H):
    """The file merges identical frames: the last frame stays about one second."""
    calls = []
    anim = startup.StartAnimation(lambda: calls.append(time.monotonic()))
    anim.movie.setSpeed(400)
    t0 = time.monotonic()
    assert anim.play()
    _wait(lambda: calls, 3)
    assert calls and calls[0] - t0 > 1.0, "four times as fast: 4.6 s become a good 1.1 s"
    _wait(lambda: not anim.isVisible(), 1)


def test_click_skips(h: H):
    calls = []
    anim = startup.StartAnimation(lambda: calls.append(1))
    assert anim.play()
    QApplication.processEvents()
    assert not calls
    pos = QPointF(10, 10)
    anim.mousePressEvent(QMouseEvent(QEvent.MouseButtonPress, pos, anim.mapToGlobal(pos), Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))
    assert calls == [1]
    _wait(lambda: not anim.isVisible(), 1)


def test_without_file_or_disabled_mule_starts_anyway(h: H):
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


def test_holds_with_loading_until_mule_is_ready(h: H):
    """Early start (launch.py): the head draws itself and waits at HOLD_FRAME with "Loading"; only after loaded() the
    animation plays on and the window comes – exactly once."""
    calls = []
    anim = startup.StartAnimation()
    anim.movie.setSpeed(1000)
    assert anim.play()
    _wait(lambda: anim._waiting, 3)
    assert anim._waiting and anim.movie.currentFrameNumber() == startup.HOLD_FRAME
    _wait(lambda: False, 0.3)
    assert anim.movie.currentFrameNumber() == startup.HOLD_FRAME and not calls, "holds while loading"
    anim.finish()
    assert not calls, "finish before loading does nothing"
    anim.loaded(lambda: calls.append(1))
    assert not anim._waiting
    _wait(lambda: calls, 3)
    assert calls == [1]
    _wait(lambda: not anim.isVisible(), 1)


def test_click_while_loading_skips_once_ready(h: H):
    calls = []
    anim = startup.StartAnimation()
    assert anim.play()
    QApplication.processEvents()
    anim._skip_or_finish()
    assert not calls
    anim.loaded(lambda: calls.append(1))
    assert calls == [1], "skipped right when Mule was ready"
    _wait(lambda: not anim.isVisible(), 1)

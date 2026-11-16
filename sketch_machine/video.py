"""Reference videos on the note board: read frames from a video file, overview image for the brief, storage next to the scene.

On the board a video is an image with a preview (note_board.VideoItem), the file itself is never in the scene file:
When dragged in, the item points to the original file, on saving a copy moves into the folder videos/ next to the
scene (Scene.adopt_videos), the scene remembers the relative path. QtMultimedia is only loaded at the first video.
"""
import os
import shutil
import time

from PySide6.QtCore import QEventLoop, QPointF, QRectF, Qt, QUrl
from PySide6.QtGui import QColor, QFont, QImage, QPainter
from PySide6.QtWidgets import QApplication

VIDEO_EXT = (".mp4", ".mov", ".m4v", ".webm", ".mkv", ".avi")
FOLDER = "videos"  # next to the scene and in the brief folder
FRAME_MAX = 960  # preview and playback on the board at most this large (longest side, pixels)
STILL_MAX = 1600  # stills and images for the AI
LOAD_MS, SEEK_MS = 8000, 2500  # wait at most this long: opening the file, seeking to a position
SEEK_NEAR_US = 1500000  # a frame this close to the requested position counts as a hit
OVERVIEW_FRAMES, OVERVIEW_COLS, OVERVIEW_W = 6, 3, 480


def available():
    """Can this installation read videos? (QtMultimedia belongs to PySide6-Addons)"""
    try:
        from PySide6 import QtMultimedia  # noqa: F401
    except ImportError:
        return False
    return True


def is_video(path):
    return os.path.splitext(path)[1].lower() in VIDEO_EXT


def time_label(ms):
    s = int(round(ms / 1000))
    return f"{s // 60}:{s % 60:02d}"


def fit(image, longest):
    """Image to at most longest pixels (longest side), without transparency."""
    if max(image.width(), image.height()) > longest:
        image = image.scaled(longest, longest, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    return image.convertToFormat(QImage.Format_RGB32)


def wait(done, ms):
    """Wait without the user's input falling into the middle of a running action."""
    app, end = QApplication.instance(), time.monotonic() + ms / 1000
    while not done() and time.monotonic() < end:
        app.processEvents(QEventLoop.ExcludeUserInputEvents, 20)
    return done()


def read_frames(path, at, longest=FRAME_MAX):
    """([(time in ms, QImage)], duration in ms) of the positions named by at(duration). Empty: file not readable. Waits (without
    input), a separate player per call – playback on the board continues unaffected."""
    from PySide6.QtMultimedia import QMediaPlayer, QVideoSink
    player, sink = QMediaPlayer(), QVideoSink()
    player.setVideoSink(sink)
    latest, failed = [None], []
    sink.videoFrameChanged.connect(lambda frame: latest.__setitem__(0, frame))
    player.errorOccurred.connect(lambda *_: failed.append(True))
    player.setSource(QUrl.fromLocalFile(os.path.abspath(path)))
    try:
        if not wait(lambda: player.duration() > 0 or failed, LOAD_MS) or failed:
            return [], 0
        duration = player.duration()
        player.pause()
        out = []
        for ms in at(duration):
            ms = max(0, min(int(ms), duration))
            latest[0] = None
            player.setPosition(ms)
            near = lambda: latest[0] is not None and abs(latest[0].startTime() - ms * 1000) <= SEEK_NEAR_US
            wait(near, SEEK_MS)
            image = latest[0].toImage() if latest[0] is not None else QImage()
            if not image.isNull():
                out.append((ms, fit(image, longest)))
        return out, duration
    finally:
        player.stop()
        player.setVideoSink(None)


def overview_times(duration, n=OVERVIEW_FRAMES):
    """Evenly distributed over the video, each from the middle of an equally long piece."""
    return [duration * (k + 0.5) / n for k in range(n)]


def overview(path):
    """Overview image for the brief: a few frames with timestamps in a grid. None: not readable."""
    frames, _ = read_frames(path, overview_times, OVERVIEW_W)
    if not frames:
        return None
    w, h = frames[0][1].width(), frames[0][1].height()
    rows = (len(frames) + OVERVIEW_COLS - 1) // OVERVIEW_COLS
    sheet = QImage(w * OVERVIEW_COLS, h * rows, QImage.Format_RGB32)
    sheet.fill(QColor(20, 20, 20))
    p = QPainter(sheet)
    font = QFont()
    font.setPixelSize(max(h // 10, 12))
    p.setFont(font)
    for k, (ms, image) in enumerate(frames):
        x, y = (k % OVERVIEW_COLS) * w, (k // OVERVIEW_COLS) * h
        p.drawImage(QPointF(x, y), image)
        label = QRectF(x, y + h - font.pixelSize() * 1.5, font.pixelSize() * 3.2, font.pixelSize() * 1.5)
        p.fillRect(label, QColor(0, 0, 0, 170))
        p.setPen(QColor(255, 255, 255))
        p.drawText(label, Qt.AlignCenter, time_label(ms))
    p.end()
    return sheet


def adopt(path, folder):
    """Copy of the video file into folder/videos (if it is already there: stays); returns the new path. Same name and
    same size counts as the same file, otherwise the copy gets a free name."""
    path = os.path.abspath(path)
    target = os.path.join(os.path.abspath(folder), FOLDER)
    if os.path.normcase(os.path.dirname(path)) == os.path.normcase(target):
        return path
    os.makedirs(target, exist_ok=True)
    stem, ext = os.path.splitext(os.path.basename(path))
    k = 1
    while True:
        dest = os.path.join(target, f"{stem}{ext}" if k == 1 else f"{stem}_{k}{ext}")
        if not os.path.exists(dest):
            shutil.copy2(path, dest)
            return dest
        if os.path.getsize(dest) == os.path.getsize(path):
            return dest
        k += 1

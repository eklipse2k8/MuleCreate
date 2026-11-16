"""Introduction in pictures inside the program: the pictures of docs/handbook (made by packaging/handbook_images.py)
as a slide show in its own window – arrows or buttons, Esc closes. Plus the way to the AI handbook: AI_HANDBOOK.md
is the full reference for the user's own AI.

The texts of the pictures come from docs/handbook/pictures.json (English, like the pictures)."""
import json
import os
import subprocess
import sys

from PySide6.QtCore import QSettings, Qt, QUrl
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtWidgets import (QApplication, QHBoxLayout, QLabel, QMessageBox, QPushButton, QSizePolicy, QVBoxLayout,
                               QWidget)

from . import paths, ui
from .i18n import tr

GITHUB = "https://github.com/felixbfx/MuleCreate"
ASKED_KEY = "intro_asked"  # the question at the first start has been answered (yes or "don't ask again")


def pictures():
    """[(path, title, summary)] of the introduction, in order; [] if the pictures are not there."""
    folder = paths.doc_path("docs", "handbook")
    try:
        with open(os.path.join(folder, "pictures.json"), encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return []
    out = []
    for p in data.values():
        path = os.path.join(folder, p["file"])
        if os.path.isfile(path):
            out.append((path, p["title"], p["summary"]))
    return out


class IntroWindow(QWidget):
    """Slide show of the introduction pictures: ← → (or the buttons), Esc closes."""

    def __init__(self, parent=None):
        super().__init__(parent, Qt.Window)
        self.setWindowTitle(tr("Mule Create – Einführung in Bildern"))
        self.setStyleSheet(f"""
            QWidget {{ background: {ui.BG}; color: {ui.TEXT}; }}
            QLabel#title {{ color: {ui.ACCENT}; font-size: 18px; font-weight: 600; }}
            QLabel#count {{ color: {ui.TEXT_DIM}; }}
            QPushButton {{ background: {ui.RAISED}; border: 1px solid {ui.LINE}; border-radius: 5px; padding: 6px 14px; }}
            QPushButton:hover {{ border-color: {ui.ACCENT}; }}""")
        self.resize(1280, 860)
        self.items = pictures()
        self.k = 0
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 12)
        bar = QHBoxLayout()
        self.title = QLabel()
        self.title.setObjectName("title")
        self.count = QLabel()
        self.count.setObjectName("count")
        self.prev = QPushButton("←")
        self.next = QPushButton("→")
        self.prev.clicked.connect(self.previous_picture)  # bound methods, no lambda holding self: no cycle
        self.next.clicked.connect(self.next_picture)
        ask = QPushButton(tr("Mit der eigenen KI fragen (AI_HANDBOOK.md)"))
        ask.clicked.connect(self._ask_ai)
        bar.addWidget(self.title, 1)
        bar.addWidget(ask)
        bar.addSpacing(12)
        bar.addWidget(self.prev)
        bar.addWidget(self.count)
        bar.addWidget(self.next)
        lay.addLayout(bar)
        self.image = QLabel(alignment=Qt.AlignCenter)
        self.image.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        self.image.setMinimumSize(400, 300)
        lay.addWidget(self.image, 1)
        if not self.items:
            self.image.setText(tr("Die Bilder der Einführung fehlen in diesem Ordner – online: {0}").format(
                GITHUB + "/blob/main/docs/INTRODUCTION.md"))
            self.image.setWordWrap(True)
            self.image.setTextInteractionFlags(Qt.TextBrowserInteraction)
            self.image.setOpenExternalLinks(True)
            self.prev.setEnabled(False)
            self.next.setEnabled(False)
        else:
            self.show_picture(0)

    def next_picture(self):
        self.show_picture(self.k + 1)

    def previous_picture(self):
        self.show_picture(self.k - 1)

    def _ask_ai(self):
        show_ai_handbook(self)

    def show_picture(self, k):
        if not self.items:
            return
        self.k = k % len(self.items)
        path, title, _summary = self.items[self.k]
        self._pixmap = QPixmap(path)
        self.title.setText(title)
        self.count.setText(f"{self.k + 1} / {len(self.items)}")
        self._fit()

    def _fit(self):
        pm = getattr(self, "_pixmap", None)
        if pm is not None and not pm.isNull():
            self.image.setPixmap(pm.scaled(self.image.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._fit()

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key_Right, Qt.Key_Space, Qt.Key_PageDown):
            self.show_picture(self.k + 1)
        elif e.key() in (Qt.Key_Left, Qt.Key_PageUp):
            self.show_picture(self.k - 1)
        elif e.key() == Qt.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(e)


def show_intro(parent):
    """Open (or bring to the front) the slide show; one window per main window."""
    win = getattr(parent, "_intro", None)
    if win is None:
        win = parent._intro = IntroWindow(parent)
    win.show()
    win.raise_()
    win.activateWindow()
    return win


def show_ai_handbook(parent):
    """Explain the AI handbook and show the file (Explorer with the file selected); its path goes to the clipboard."""
    path = paths.doc_path("AI_HANDBOOK.md")
    exists = os.path.isfile(path)
    box = QMessageBox(parent)
    box.setWindowTitle(tr("Mit der eigenen KI fragen"))
    box.setText(tr("AI_HANDBOOK.md beschreibt alle Funktionen, Kürzel und Abläufe von Mule – geschrieben für KIs.\n\n"
                   "Gib die Datei deiner KI (Claude, ChatGPT, Codex …): in den Chat ziehen oder anhängen, dann "
                   "einfach fragen, z. B. „Wie mache ich in Mule eine Röhre?“"))
    show = box.addButton(tr("Datei zeigen") if exists else tr("Online öffnen"), QMessageBox.AcceptRole)
    box.addButton(tr("Schließen"), QMessageBox.RejectRole)
    box.exec()
    if box.clickedButton() is not show:
        return
    if not exists:
        QDesktopServices.openUrl(QUrl(GITHUB + "/blob/main/AI_HANDBOOK.md"))
        return
    QApplication.clipboard().setText(path)
    if sys.platform == "win32":
        subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
    else:
        QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(path)))


def ask_at_first_start(parent):
    """Once: offer the introduction (Yes / Later / Don't ask again). Later asks again at the next start."""
    settings = QSettings("SketchMachine", "SketchMachine")
    if settings.value(ASKED_KEY, False, type=bool) or not pictures():
        return
    box = QMessageBox(parent)
    box.setWindowTitle(tr("Willkommen bei Mule Create"))
    box.setText(tr("Möchtest du die Einführung in Bildern ansehen? 18 Bilder zu den wichtigsten Funktionen, "
                   "etwa zwei Minuten.\n\nSpäter jederzeit: Hilfe → Einführung in Bildern."))
    yes = box.addButton(tr("Ansehen"), QMessageBox.AcceptRole)
    later = box.addButton(tr("Später"), QMessageBox.RejectRole)
    box.addButton(tr("Nicht mehr fragen"), QMessageBox.DestructiveRole)
    box.setDefaultButton(yes)
    box.exec()
    if box.clickedButton() is later:
        return
    settings.setValue(ASKED_KEY, True)
    if box.clickedButton() is yes:
        show_intro(parent)

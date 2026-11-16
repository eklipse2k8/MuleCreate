"""Set up transcription (review mode): Whisper (faster-whisper) in its own Python next to Mule - once, without a
command line. Mule looks for an installed Python 3.10-3.13, creates <user folder>/whisper_venv, installs
faster-whisper (with an NVIDIA graphics card also the CUDA libraries) and downloads the model (large-v3-turbo, ~1.6 GB).
After that review.whisper_python() finds this Python by itself.

Without Python: the dialog explains where to get it (python.org, checkbox "Add python.exe to PATH")."""
import os
import shutil
import subprocess
import sys

from PySide6.QtCore import QObject, QProcess, QSettings, Qt, Signal
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QPlainTextEdit, QProgressBar,
                               QPushButton, QVBoxLayout)

from . import paths
from .i18n import tr

VERSIONS = ((3, 10), (3, 13))  # faster-whisper/ctranslate2 come prebuilt for these Python versions
MODEL = "large-v3-turbo"
PY_URL = "https://www.python.org/downloads/"


def venv_dir():
    return os.path.join(paths.user_dir(), "whisper_venv")


def venv_python():
    d = venv_dir()
    return os.path.join(d, "Scripts", "python.exe") if sys.platform == "win32" else os.path.join(d, "bin", "python")


def find_python():
    """Installed Python for the setup (py launcher preferred, Store placeholder excluded) -> path or None."""
    tries = []
    if sys.platform == "win32" and shutil.which("py"):
        tries += [["py", f"-{a}.{b}"] for a, b in ((3, 12), (3, 13), (3, 11), (3, 10))]
    tries += [["python3"], ["python"]]
    for cmd in tries:
        exe = shutil.which(cmd[0])
        if not exe or (cmd[0] != "py" and "WindowsApps" in exe):  # python(3).exe there = Store placeholder
            continue  # (the py.exe launcher also sits there for Store installs and is real)
        try:
            r = subprocess.run(cmd + ["-c", "import sys; print(sys.executable); print(*sys.version_info[:2])"],
                               capture_output=True, text=True, timeout=15,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except (OSError, subprocess.TimeoutExpired):
            continue
        lines = r.stdout.strip().splitlines()
        if r.returncode != 0 or len(lines) < 2:
            continue
        try:
            version = tuple(int(x) for x in lines[1].split())
        except ValueError:
            continue
        if VERSIONS[0] <= version <= VERSIONS[1] and os.path.isfile(lines[0]):
            return lines[0]
    return None


def has_nvidia():
    return shutil.which("nvidia-smi") is not None


def steps(python, gpu=None):
    """[(label, [program, arguments ...])] of the setup."""
    gpu = has_nvidia() if gpu is None else gpu
    vpy = venv_python()
    pkgs = ["faster-whisper"] + (["nvidia-cublas-cu12", "nvidia-cudnn-cu12==9.*"] if gpu else [])
    return [
        (tr("Eigenes Python für Whisper anlegen …"), [python, "-m", "venv", venv_dir()]),
        (tr("Whisper installieren (einige Minuten) …"),
         [vpy, "-m", "pip", "install", "--disable-pip-version-check", "--no-input", *pkgs]),
        (tr("Sprachmodell laden (~1,6 GB, einmalig) …"),
         [vpy, "-c", f"from faster_whisper import WhisperModel; WhisperModel('{MODEL}', device='cpu', "
                     "compute_type='int8'); print('Modell bereit')"]),
    ]


class Setup(QObject):
    """Runs the steps one after another as separate processes (Mule stays usable)."""
    progress = Signal(int, str)  # step number (0 ...), label
    output = Signal(str)
    finished = Signal(bool, str)  # ok, message

    def __init__(self, plan, parent=None):
        super().__init__(parent)
        self.plan, self.k, self.proc, self.cancelled = list(plan), -1, None, False

    def start(self):
        self._next()

    def cancel(self):
        self.cancelled = True
        if self.proc is not None:
            self.proc.kill()

    def _next(self):
        self.k += 1
        if self.k >= len(self.plan):
            QSettings("SketchMachine", "SketchMachine").setValue("whisper_python", venv_python())
            return self.finished.emit(True, tr("Transkription eingerichtet – ab jetzt bekommt jedes Review sein Transkript."))
        label, cmd = self.plan[self.k]
        self.progress.emit(self.k, label)
        proc = QProcess(self)
        proc.setProcessChannelMode(QProcess.MergedChannels)
        proc.readyReadStandardOutput.connect(
            lambda: self.output.emit(bytes(proc.readAllStandardOutput()).decode("utf-8", "replace")))
        proc.finished.connect(lambda code, _s: self._done(code))
        proc.errorOccurred.connect(lambda err: err == QProcess.FailedToStart and self._done(-1))
        self.proc = proc
        proc.start(cmd[0], cmd[1:])

    def _done(self, code):
        proc, self.proc = self.proc, None
        if proc is None:
            return
        proc.deleteLater()
        if self.cancelled:
            return self.finished.emit(False, tr("Abgebrochen – „Transkription einrichten“ macht später weiter."))
        if code != 0:
            return self.finished.emit(False, tr("Schritt fehlgeschlagen: {0}").format(self.plan[self.k][0].rstrip(" …")))
        self._next()


class SetupDialog(QDialog):
    """Setup window: what happens, progress, output; without Python the pointer to python.org."""

    def __init__(self, parent=None, python=None, plan=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Transkription einrichten"))
        self.setMinimumWidth(560)
        self.python = python if python is not None else find_python()
        lay = QVBoxLayout(self)
        self.info = QLabel()
        self.info.setWordWrap(True)
        self.info.setTextFormat(Qt.RichText)
        self.info.setOpenExternalLinks(True)
        lay.addWidget(self.info)
        self.step = QLabel()
        lay.addWidget(self.step)
        self.bar = QProgressBar()
        self.bar.setRange(0, 0)
        self.bar.hide()
        lay.addWidget(self.bar)
        self.log = QPlainTextEdit(readOnly=True)
        self.log.setMaximumBlockCount(400)
        self.log.setMinimumHeight(140)
        self.log.hide()
        lay.addWidget(self.log)
        row = QHBoxLayout()
        self.go = QPushButton(tr("Einrichten"))
        self.go.clicked.connect(self._start)
        self.again = QPushButton(tr("Nochmal nach Python suchen"))
        self.again.clicked.connect(self._search)
        self.close_btn = QPushButton(tr("Schließen"))
        self.close_btn.clicked.connect(self._close)
        row.addStretch(1)
        for b in (self.again, self.go, self.close_btn):
            row.addWidget(b)
        lay.addLayout(row)
        self.setup, self.ok = None, False
        self._plan = plan
        self._show_state()

    def _show_state(self):
        if self.python:
            gpu = has_nvidia()
            self.info.setText(tr(
                "Für das Transkript eines Reviews nutzt Mule <b>Whisper</b> – es läuft nur auf diesem Rechner, nichts "
                "wird hochgeladen. Einmalig richtet Mule dafür ein eigenes Python ein, installiert Whisper{0} und lädt "
                "das Sprachmodell (zusammen etwa 2–4 GB). Das dauert je nach Internet einige Minuten; du kannst "
                "währenddessen weiterarbeiten.<br><br>Gefundenes Python: <code>{1}</code>").format(
                tr(" samt Grafikkarten-Bibliotheken (NVIDIA)") if gpu else "", self.python))
            self.go.setEnabled(True)
            self.again.hide()
        else:
            self.info.setText(tr(
                "Für das Transkript eines Reviews nutzt Mule <b>Whisper</b> (läuft nur auf diesem Rechner). Dafür "
                "braucht es einmalig ein installiertes <b>Python 3.10 bis 3.13</b>, das Mule nicht gefunden hat.<br><br>"
                "1. Python von <a href='{0}'>python.org</a> laden und installieren – im Installer unten den Haken "
                "<b>„Add python.exe to PATH“</b> setzen.<br>2. Dann hier „Nochmal nach Python suchen“.<br><br>"
                "Reviews kannst du trotzdem aufnehmen – das Transkript kommt nach, sobald Whisper eingerichtet ist.")
                .format(PY_URL))
            self.go.setEnabled(False)
            self.again.show()

    def _search(self):
        self.python = find_python()
        self._show_state()

    def _start(self):
        self.go.setEnabled(False)
        self.bar.show()
        self.log.show()
        self.setup = Setup(self._plan or steps(self.python), self)
        self.setup.progress.connect(lambda k, label: self.step.setText(f"{k + 1}/{len(self.setup.plan)}  {label}"))
        self.setup.output.connect(lambda text: self.log.appendPlainText(text.rstrip()))
        self.setup.finished.connect(self._finished)
        self.close_btn.setText(tr("Abbrechen"))
        self.setup.start()

    def _finished(self, ok, message):
        self.ok = ok
        self.bar.hide()
        self.step.setText(message)
        self.close_btn.setText(tr("Schließen"))
        if not ok:
            self.go.setText(tr("Nochmal versuchen"))
            self.go.setEnabled(True)
        self.setup = None

    def _close(self):
        if self.setup is not None:
            self.setup.cancel()
            return
        self.accept() if self.ok else self.reject()

    def closeEvent(self, e):
        if self.setup is not None:
            self.setup.cancel()
        super().closeEvent(e)

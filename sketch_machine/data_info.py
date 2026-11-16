"""Help → "Where Mule keeps its files" (2026-11-16): one overview of everything Mule writes outside the user's own
scenes – program folder, user data folder (recipes, reviews, recordings, speech recognition …), settings, backups –
with sizes, and how to remove all of it. Mule has no installer: removing Mule means deleting these places."""
import os
import sys

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QMessageBox

from . import paths
from .i18n import tr

# what the user data folder holds: name → what it is (unknown entries are listed by name)
PARTS = (("recipes", "Brief-Recipes – deine eigenen und importierten"),
         ("Reviews", "eingesprochenes Feedback (Ansicht → Review)"),
         ("Aufnahmen", "Klick-Protokolle des Recorders (nur wenn eingeschaltet)"),
         ("whisper_venv", "Spracherkennung für Reviews (nur wenn eingerichtet)"),
         ("bible", "deine Kopie der Workflow-Bible"),
         ("mule.log", "Protokoll des letzten Starts"),
         (".mcp.json", "eigene MCP-Einträge für Brief-Ordner"),
         (".codex", "eigene MCP-Einträge für Codex"))


def size(path):
    """Bytes of a file or folder (0 if missing)."""
    if os.path.isfile(path):
        return os.path.getsize(path)
    total = 0
    for base, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(base, f))
            except OSError:
                pass
    return total


def human(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024


def program_dir():
    return os.path.dirname(sys.executable) if paths.FROZEN else paths.ROOT


def text():
    """The overview as plain text (also for tests)."""
    from . import backup
    data = paths.user_dir(create=False)
    lines = [tr("Programm: {0}").format(os.path.normpath(program_dir())),
             tr("   Mule schreibt hier nichts hinein. Diesen Ordner löschen = Mule entfernen.") if paths.FROZEN else
             tr("   Quellcode-Fassung: Bible, Protokoll und MCP-Einträge liegen hier im Repo."), ""]
    if os.path.isdir(data):
        lines.append(tr("Deine Daten: {0} ({1})").format(os.path.normpath(data), human(size(data))))
        known = dict(PARTS)
        names = sorted(os.listdir(data), key=lambda n: ([p for p, _ in PARTS] + [n]).index(n))
        for n in names:
            lines.append(f"   • {n} – {tr(known[n]) if n in known else tr('(von Mule oder dir angelegt)')} "
                         f"({human(size(os.path.join(data, n)))})")
        if not names:
            lines.append(tr("   (leer)"))
    else:
        lines.append(tr("Deine Daten: {0} – noch nicht angelegt").format(os.path.normpath(data)))
    lines.append(tr("   Bleibt bei einem Update erhalten; löschen, wenn du Mule ganz entfernst."))
    settings = QSettings("SketchMachine", "SketchMachine").fileName()
    lines += ["", tr("Einstellungen: {0}").format(settings),
              tr("   Fenster, Farben, Sprache, Stiftdruck … ({0})").format(
                  tr("Windows-Registry") if sys.platform == "win32" else tr("eine Datei"))]
    unsaved = backup.folder_for(None)
    lines += ["", tr("Sicherungen ungespeicherter Szenen: {0}").format(os.path.normpath(unsaved))
              + ("" if os.path.isdir(unsaved) else tr(" – noch keine")),
              "", tr("Neben deinen eigenen Dateien: „backups“ neben jeder gespeicherten Szene, Brief-Ordner und "
                     "„work_<Name>“ dort, wo du exportierst."),
              "", tr("Mule ganz entfernen: Programmordner und Datenordner löschen, die Einstellungen mit "
                     "„Einstellungen löschen …“ hier unten.")]
    return "\n".join(lines)


def show(parent):
    """The overview with "Open data folder" and "Delete settings …"."""
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QDesktopServices
    box = QMessageBox(parent)
    box.setWindowTitle(tr("Wo Mule Dateien ablegt"))
    box.setText(text())
    box.setTextInteractionFlags(Qt.TextSelectableByMouse)  # paths can be copied
    open_btn = box.addButton(tr("Datenordner öffnen"), QMessageBox.ActionRole)
    clear_btn = box.addButton(tr("Einstellungen löschen …"), QMessageBox.DestructiveRole)
    box.addButton(tr("Schließen"), QMessageBox.RejectRole)
    box.exec()
    if box.clickedButton() is open_btn:
        QDesktopServices.openUrl(QUrl.fromLocalFile(paths.user_dir()))
    elif box.clickedButton() is clear_btn:
        if QMessageBox.question(parent, tr("Einstellungen löschen"), tr(
                "Alle Einstellungen von Mule löschen (Fenster, Farben, Sprache, Stiftdruck …)? Szenen, Recipes und "
                "Reviews bleiben. Das lässt sich nicht rückgängig machen; Mule nutzt beim nächsten Start die "
                "Vorgaben.")) == QMessageBox.Yes:
            QSettings("SketchMachine", "SketchMachine").clear()

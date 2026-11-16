"""Automatic backups and recently opened scenes.

Backup: every N minutes (settings, default 10, can be turned off) a copy of the scene goes into the "backups" folder next to the
scene file (working folder) – only if something changed since the last backup. Unsaved scenes end up in
Documents/Mule/backups. The scene itself stays untouched: no save, no "saved" state, no videos
copied. The newest KEEP backups remain per scene.

Recently opened: list of recently opened or saved scenes (File menu).
"""
import glob
import hashlib
import json
import os
import time

from PySide6.QtCore import QSettings, QStandardPaths

from . import assoc

DEFAULT_MINUTES = 10
MINUTES_RANGE = (1, 240)
KEEP = 50  # this many backups remain per scene (older ones are deleted)
FOLDER = "backups"
REVIEW_FOLDER = "review_backups"  # state before every submitted review (review.py)
REVIEW_KEEP = 20  # this many review backups per scene (setting review_backup_keep)
REVIEW_KEEP_RANGE = (1, 500)
RECENT_MAX = 10


def _settings():
    return QSettings("SketchMachine", "SketchMachine")


# --- Settings ------------------------------------------------------------------
def enabled():
    return _settings().value("backup_on", True, type=bool)


def minutes():
    m = _settings().value("backup_minutes", DEFAULT_MINUTES, type=int)
    return int(min(max(m, MINUTES_RANGE[0]), MINUTES_RANGE[1]))


def set_options(on, mins):
    s = _settings()
    s.setValue("backup_on", bool(on))
    s.setValue("backup_minutes", int(min(max(int(mins), MINUTES_RANGE[0]), MINUTES_RANGE[1])))


def review_keep():
    k = _settings().value("review_backup_keep", REVIEW_KEEP, type=int)
    return int(min(max(k, REVIEW_KEEP_RANGE[0]), REVIEW_KEEP_RANGE[1]))


def set_review_keep(k):
    _settings().setValue("review_backup_keep", int(min(max(int(k), REVIEW_KEEP_RANGE[0]), REVIEW_KEEP_RANGE[1])))


# --- Backups -------------------------------------------------------------------
def folder_for(path, folder=FOLDER):
    """Backup folder: "backups" (or folder) next to the scene file; unsaved: Documents/Mule/backups."""
    if path:
        return os.path.join(os.path.dirname(os.path.abspath(path)), folder)
    docs = QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation) or os.path.expanduser("~")
    return os.path.join(docs, "Mule", folder)


def _base(path):
    return assoc.strip_ext(os.path.basename(path) if path else "unbenannt")


def write(scene, path, extra=None, last_hash=None, now=None, folder=FOLDER, keep=KEEP):
    """Write a backup of the scene if it changed since last_hash -> (file or None, hash).
    The scene is not modified in the process (to_dict instead of save: no dirty=False, no video copies). folder/keep:
    another folder next to the scene and how many stay there (review backups)."""
    out = folder_for(path, folder)
    data = scene.to_dict(out)  # paths (videos, meshes) relative to the backup folder – the copy opens directly
    if extra:
        data.update(extra)
    text = json.dumps(data, separators=(",", ":"))  # without indentation: half the size (harbor: 54 instead of 98 MB per backup)
    digest = hashlib.sha1(text.encode("utf-8")).hexdigest()
    if digest == last_hash:
        return None, digest
    os.makedirs(out, exist_ok=True)
    stamp = time.strftime("%Y-%m-%d_%H-%M-%S", time.localtime(now))
    target = os.path.join(out, f"{_base(path)}_{stamp}{assoc.EXT}")  # to open by double click
    tmp = target + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, target)  # never a half-written file
    prune(path, keep, folder)
    return target, digest


def backups(path, folder=FOLDER):
    """Backups of a scene, newest first."""
    stem = os.path.join(glob.escape(folder_for(path, folder)), glob.escape(_base(path)) + "_????-??-??_??-??-??")
    found = [f for ext in (assoc.EXT, assoc.OLD_EXT) for f in glob.glob(stem + ext)]  # (older backups: .sketch.json)
    return sorted(found, key=lambda f: assoc.strip_ext(os.path.basename(f)), reverse=True)


def prune(path, keep=KEEP, folder=FOLDER):
    for old in backups(path, folder)[keep:]:
        try:
            os.remove(old)
        except OSError:
            pass


# --- Recently opened ------------------------------------------------------------
def recent():
    """Recently opened scenes (newest first), only those still existing."""
    items = _settings().value("recent_files", [], type=list) or []
    return [p for p in items if isinstance(p, str) and os.path.isfile(p)]


def add_recent(path):
    path = os.path.abspath(path)
    norm = os.path.normcase(path)
    items = [p for p in (_settings().value("recent_files", [], type=list) or []) if os.path.normcase(p) != norm]
    _settings().setValue("recent_files", [path] + items[:RECENT_MAX - 1])


def clear_recent():
    _settings().setValue("recent_files", [])

"""Automatic backup (folder "backups" next to the scene, only on changes, settings) and "Recently opened"."""
import os
import tempfile

import numpy as np

from tests.harness import H
from sketch_machine import backup
from sketch_machine.scene import Scene


def _scene_file(h: H):
    """Saved scene with one stroke in a fresh folder -> path."""
    h.new_scene()
    h.stroke_world(np.array([[-1.0, 0, 0], [1.0, 0.5, 0]]))
    path = os.path.join(tempfile.mkdtemp(), "probe.sketch.json")
    h.w.path = path
    assert h.w.save_scene()
    return path


def test_backup_only_on_change_in_the_folder_next_to_the_scene(h: H):
    path = _scene_file(h)
    assert h.w.auto_backup() is None, "saved and unchanged: no backup"
    h.stroke_world(np.array([[-1.0, 1, 0], [1.0, 1.5, 0]]))
    target = h.w.auto_backup()
    assert target and os.path.dirname(target) == os.path.join(os.path.dirname(path), "backups")
    assert os.path.basename(target).startswith("probe_") and target.endswith(".mule")
    assert h.sc.dirty, "the backup does not save the scene (it stays unsaved)"
    assert h.w.auto_backup() is None, "nothing changed since the last backup: no second one"
    sc, _ = Scene.load(target)
    assert len(sc.curves) == 2, "the backup can be opened and has the new stroke"
    assert backup.backups(path) == [target]


def test_old_backups_are_thinned_out(h: H):
    path = _scene_file(h)
    for k in range(5):
        h.stroke_world(np.array([[-1.0, k, 0], [1.0, k + 0.5, 0]]))
        backup.write(h.sc, path, now=1_700_000_000 + 60 * k)
    backup.prune(path, keep=3)
    left = backup.backups(path)
    assert len(left) == 3 and left == sorted(left, reverse=True)


def test_settings_and_timer(h: H):
    assert backup.enabled() and backup.minutes() == 10, "default: on, every 10 minutes"
    backup.set_options(True, 3)
    h.w._restart_backup_timer()
    assert h.w._backup_timer.isActive() and h.w._backup_timer.interval() == 3 * 60 * 1000
    backup.set_options(False, 3)
    h.w._restart_backup_timer()
    assert not h.w._backup_timer.isActive()
    backup.set_options(True, 10)
    h.w._restart_backup_timer()


def test_recently_opened(h: H):
    backup.clear_recent()
    a = _scene_file(h)
    b = _scene_file(h)
    assert backup.recent()[:2] == [b, a], "most recently saved first"
    h.w.load_path(a)
    assert backup.recent()[0] == a, "opening moves it to the front, without duplicates"
    assert len(backup.recent()) == 2
    os.remove(b)
    assert backup.recent() == [a], "files that no longer exist drop out"
    h.w._fill_recent_menu()
    texts = [act.text() for act in h.w.recent_menu.actions()]
    assert any(os.path.basename(a) in t for t in texts)
    h.sc.dirty = False
    h.w.open_recent(a)
    assert h.w.path == a

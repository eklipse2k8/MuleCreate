"""Doppelklick auf eine Szene: eigene Endung .mule, Mule bekommt die Datei als Argument (app.main). Die Zuordnung selbst
(Registrierung des Benutzers) wird hier nicht geschrieben – nur, was eingetragen würde."""
import os
import sys
import tempfile

from sketch_machine import assoc, backup
from sketch_machine.scene import Scene
from tests.harness import H, line


def test_eintraege_zeigen_auf_dieses_mule(h: H):
    e = assoc.entries()
    assert e[".mule"] == assoc.PROGID
    cmd = e[assoc.PROGID + r"\shell\open\command"]
    assert cmd.endswith('"%1"') and os.path.dirname(sys.executable) in cmd
    assert "sketch_machine.app" in cmd and os.path.dirname(os.path.dirname(assoc.__file__)) in cmd


def test_endung_beim_speichern_und_alte_dateien(h: H):
    assert assoc.with_ext("C:/x/szene") == "C:/x/szene.mule" and assoc.with_ext("C:/x/a.sketch.json") == "C:/x/a.sketch.json"
    assert assoc.strip_ext("a.mule") == assoc.strip_ext("a.sketch.json") == assoc.strip_ext("a.json") == "a"
    h.new_scene()
    h.sc.new_stroke()
    h.sc.add_curve(line([0, 0, 0], [1, 0, 0], 5), None)
    folder = tempfile.mkdtemp()
    for name in ("neu.mule", "alt.sketch.json"):  # derselbe Inhalt, beide Endungen öffnen sich
        path = os.path.join(folder, name)
        h.sc.save(path)
        assert len(Scene.load(path)[0].curves) == 1
    h.sc.dirty = True
    target, _ = backup.write(h.sc, os.path.join(folder, "neu.mule"))
    assert os.path.basename(target).startswith("neu_") and target.endswith(".mule")
    old = os.path.join(folder, "backups", "neu_2020-01-01_00-00-00.sketch.json")  # Backup einer älteren Version
    h.sc.save(old)
    assert backup.backups(os.path.join(folder, "neu.mule")) == [target, old], "neueste zuerst, alte Endung zählt mit"

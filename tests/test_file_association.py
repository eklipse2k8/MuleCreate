"""Double-click on a scene: its own extension .mule, Mule gets the file as an argument (launch.main). The association itself
(the user's registration) is not written here - only what would be entered."""
import os
import sys
import tempfile

from sketch_machine import assoc, backup
from sketch_machine.scene import Scene
from tests.harness import H, line


def test_entries_point_to_this_mule(h: H):
    e = assoc.entries()
    assert e[".mule"] == assoc.PROGID
    cmd = e[assoc.PROGID + r"\shell\open\command"]
    assert cmd.endswith('"%1"') and os.path.dirname(sys.executable) in cmd
    assert "sketch_machine.launch" in cmd and os.path.dirname(os.path.dirname(assoc.__file__)) in cmd


def test_extension_on_save_and_old_files(h: H):
    assert assoc.with_ext("C:/x/szene") == "C:/x/szene.mule" and assoc.with_ext("C:/x/a.sketch.json") == "C:/x/a.sketch.json"
    assert assoc.strip_ext("a.mule") == assoc.strip_ext("a.sketch.json") == assoc.strip_ext("a.json") == "a"
    h.new_scene()
    h.sc.new_stroke()
    h.sc.add_curve(line([0, 0, 0], [1, 0, 0], 5), None)
    folder = tempfile.mkdtemp()
    for name in ("neu.mule", "alt.sketch.json"):  # same content, both extensions open
        path = os.path.join(folder, name)
        h.sc.save(path)
        assert len(Scene.load(path)[0].curves) == 1
    h.sc.dirty = True
    target, _ = backup.write(h.sc, os.path.join(folder, "neu.mule"))
    assert os.path.basename(target).startswith("neu_") and target.endswith(".mule")
    old = os.path.join(folder, "backups", "neu_2020-01-01_00-00-00.sketch.json")  # backup of an older version
    h.sc.save(old)
    assert backup.backups(os.path.join(folder, "neu.mule")) == [target, old], "newest first, old extension counts too"

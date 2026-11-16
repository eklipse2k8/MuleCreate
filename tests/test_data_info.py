"""Help → "Where Mule keeps its files": program folder, user data folder with every entry and its size, settings,
backups, and how to remove Mule completely (there is no installer)."""
import os
import sys
import tempfile

from tests.harness import H
from sketch_machine import data_info, paths


def test_overview_names_every_place(h: H):
    old = {k: os.environ.get(k) for k in ("APPDATA", "XDG_DATA_HOME")}
    base = tempfile.mkdtemp()
    os.environ["APPDATA"] = os.environ["XDG_DATA_HOME"] = base
    try:
        assert "noch nicht angelegt" in data_info.text() and not os.path.exists(os.path.join(base, "Mule")), \
            "looking does not create the folder"
        data = paths.user_dir()
        os.makedirs(os.path.join(data, "recipes", "lean"))
        with open(os.path.join(data, "recipes", "lean", "recipe.toml"), "w") as fh:
            fh.write("x" * 2048)
        os.makedirs(os.path.join(data, "Reviews"))
        open(os.path.join(data, "something_else.txt"), "w").close()
        text = data_info.text()
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    if sys.platform in ("win32", "linux"):
        assert os.path.normpath(data) in text
    lines = text.splitlines()
    assert lines[0].startswith("Programm: ") and os.path.normpath(data_info.program_dir()) in lines[0]
    recipes_line = next(l for l in lines if "• recipes" in l)
    assert "Brief-Recipes" in recipes_line and "2.0 KB" in recipes_line
    assert lines.index(recipes_line) < lines.index(next(l for l in lines if "• Reviews" in l)), "known parts first"
    assert any("something_else.txt" in l and "von Mule oder dir angelegt" in l for l in lines)
    assert "Einstellungen: " in text and "Sicherungen ungespeicherter Szenen" in text
    assert "Mule ganz entfernen" in text
    assert data_info.human(0) == "0 B" and data_info.human(3 * 1024 ** 3) == "3.0 GB"
    help_menu = next(a.menu() for a in h.w.menuBar().actions() if a.menu() and "Hilfe" in a.text())
    assert any("Dateien ablegt" in a.text() for a in help_menu.actions()), "in the Help menu"

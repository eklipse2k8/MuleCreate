"""Programme der Brief-Hooks: settings.json im Paket nennt die Windows-Standardpfade, der Export setzt die Programme
dieses Rechners ein (Git woanders installiert, Linux mit bash und pwsh). Fehlt eins, sagt es der Brief-Dialog."""
import json
import os

from sketch_machine import brief_v4

STUFE = "kern"

SETTINGS = os.path.join(brief_v4.PACKAGE_DIR, "_claude", "settings.json")


def test_paket_nennt_genau_die_ersetzten_pfade(h=None):
    text = open(SETTINGS, encoding="utf-8").read()
    assert brief_v4.WIN_BASH in text and brief_v4.WIN_PS in text, "settings.json und brief_v4 nennen dieselben Pfade"
    rest = text.replace(brief_v4.WIN_BASH, "").replace(brief_v4.WIN_PS, "")
    assert ".exe" not in rest, "kein weiteres fest eingetragenes Programm, das der Export nicht ersetzt"


def test_programme_dieses_rechners(h=None):
    bash, ps, missing = brief_v4.hook_programs()
    for prog, name in ((bash, "bash"), (ps, "PowerShell")):
        assert "\\" not in prog, f"{name}: Schrägstriche, sonst bricht der Pfad das JSON"
        assert os.path.isfile(prog) or missing, f"{name} gibt es nicht, und missing sagt es nicht: {prog}"


def test_ersetzt_ergibt_gueltiges_json(h=None):
    bash, ps, _ = brief_v4.hook_programs()
    for b, p in ((bash, ps), ("/usr/bin/bash", "/usr/bin/pwsh"), ("D:/Tools/Git/bin/bash.exe", "pwsh")):
        text = open(SETTINGS, encoding="utf-8").read().replace("__BRIEF__", "D:/x/y_brief")
        settings = json.loads(text.replace(brief_v4.WIN_BASH, b).replace(brief_v4.WIN_PS, p))
        cmds = json.dumps(settings)
        assert b in cmds and p in cmds and brief_v4.WIN_BASH not in cmds.replace(b, "")

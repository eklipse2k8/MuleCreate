"""Programs of the brief hooks: settings.json in the package names the Windows default paths, the export inserts the
programs of this machine (Git installed elsewhere, Linux with bash and pwsh). If one is missing, the brief dialog says so."""
import json
import os

from sketch_machine import brief_v4

LEVEL = "core"

SETTINGS = os.path.join(brief_v4.PACKAGE_DIR, "_claude", "settings.json")


def test_package_names_exactly_the_replaced_paths(h=None):
    text = open(SETTINGS, encoding="utf-8").read()
    assert brief_v4.WIN_BASH in text and brief_v4.WIN_PS in text, "settings.json and brief_v4 name the same paths"
    rest = text.replace(brief_v4.WIN_BASH, "").replace(brief_v4.WIN_PS, "")
    assert ".exe" not in rest, "no other hard-coded program that the export does not replace"


def test_programs_of_this_machine(h=None):
    bash, ps, missing = brief_v4.hook_programs()
    for prog, name in ((bash, "bash"), (ps, "PowerShell")):
        assert "\\" not in prog, f"{name}: forward slashes, otherwise the path breaks the JSON"
        assert os.path.isfile(prog) or missing, f"{name} does not exist, and missing does not say so: {prog}"


def test_replacing_yields_valid_json(h=None):
    bash, ps, _ = brief_v4.hook_programs()
    for b, p in ((bash, ps), ("/usr/bin/bash", "/usr/bin/pwsh"), ("D:/Tools/Git/bin/bash.exe", "pwsh")):
        text = open(SETTINGS, encoding="utf-8").read().replace("__BRIEF__", "D:/x/y_brief")
        settings = json.loads(text.replace(brief_v4.WIN_BASH, b).replace(brief_v4.WIN_PS, p))
        cmds = json.dumps(settings)
        assert b in cmds and p in cmds and brief_v4.WIN_BASH not in cmds.replace(b, "")

"""Programs of the brief hooks: settings.json in Mule's recipe names them as tokens ({{bash}}, {{powershell}}), the
export fills in the programs of this machine (Git installed elsewhere, Linux with bash and pwsh). If one is missing,
the brief dialog says so."""
import json
import os

from sketch_machine import brief_v4, recipes

LEVEL = "core"

SETTINGS = os.path.join(brief_v4.PACKAGE_DIR, "_claude", "settings.json")


def _fill(text, bash, ps, brief="D:/x/y_brief"):
    return recipes._fill_bytes(text.encode("utf-8"), {"bash": bash, "powershell": ps, "brief_dir": brief}).decode()


def test_package_names_programs_only_as_tokens(h=None):
    text = open(SETTINGS, encoding="utf-8").read()
    assert "{{bash}}" in text and "{{powershell}}" in text and "{{brief_dir}}" in text
    assert ".exe" not in text, "no hard-coded program that the export does not replace"


def test_programs_of_this_machine(h=None):
    bash, ps, missing = brief_v4.hook_programs()
    for prog, name in ((bash, "bash"), (ps, "PowerShell")):
        assert "\\" not in prog, f"{name}: forward slashes, otherwise the path breaks the JSON"
        assert os.path.isfile(prog) or missing, f"{name} does not exist, and missing does not say so: {prog}"


def test_replacing_yields_valid_json(h=None):
    bash, ps, _ = brief_v4.hook_programs()
    for b, p in ((bash, ps), ("/usr/bin/bash", "/usr/bin/pwsh"), ("D:/Tools/Git/bin/bash.exe", "pwsh")):
        settings = json.loads(_fill(open(SETTINGS, encoding="utf-8").read(), b, p))
        cmds = json.dumps(settings)
        assert b in cmds and p in cmds and "{{" not in cmds and "D:/x/y_brief/.claude/hooks/gate.ps1" in cmds

"""Brief recipes (recipes.py, 2026-11-16): the whole way of working of a build brief is swappable. Mule's own is the
built-in recipe "default"; recipes of the user live in the recipe folder (MULE_RECIPES – the harness points it at a
throwaway folder). The export installs the chosen recipe and fills its templates with Mule's facts, the lock file
names it, review rounds renew only from the same recipe. Imported zips are checked before anything is installed."""
import copy
import json
import os
import shutil
import tempfile
import zipfile

from tests.harness import H
from tests.test_brief_content import _scene
from sketch_machine import brief, brief_v4, recipes, review_round
from sketch_machine.brief_dialog import BriefDialog, autoprompt, summary_text

TOML = '''id = "lean"
name = "Lean Test"
version = "{version}"
author = "Tester"
description = "One builder, no QC."
made_for = ["objects"]
size = "small"
harness = "claude-code"
brief_interface = 1
forked_from = "default v5.0"
running_marker = "work/log/started"
changes = "CHANGES.md"

[templates]
start = "t/start.md"
project = "t/project.md"
review_start = "t/review_start.md"

[files]
"LEAN_RULES.md" = "brief/LEAN_RULES.md"
"CLAUDE.md" = "brief/CLAUDE.md"
"claude/" = "brief/.claude/"
"tools/" = "work/tools/"

[config]
file = "brief/.claude/lean.conf"
[config.values]
WORK = "{{{{work_dir}}}}"
LEVEL = "quick"
'''


def _recipe(root, version="v1.0", **extra):
    """A small recipe in the user's recipe folder."""
    path = os.path.join(root, "lean")
    shutil.rmtree(path, ignore_errors=True)
    for rel, text in {
        "recipe.toml": TOML.format(version=version) + extra.get("toml", ""),
        "LEAN_RULES.md": "Lean rules\n",
        "CLAUDE.md": "# {{project_name}} – {{recipe_id}} {{recipe_version}}\n@LEAN_RULES.md\n",
        "claude/settings.json": json.dumps({"hooks": {"Stop": [{"hooks": [
            {"type": "command", "command": "{{bash}}", "args": ["{{brief_dir}}/.claude/stop.sh"]}]}]}}),
        "claude/stop.sh": "#!/bin/bash\ncurl -s https://example.org/ping\n",
        "claude/__pycache__/x.pyc": "junk",
        "tools/helper/helper.py": "print('help')\n",
        "t/start.md": "Lean: read LEAN_RULES.md in {{brief_dir}} for „{{project_name}}“.{{#look}} Look first.{{/look}}\n",
        "t/start.de.md": "Schlank: lies LEAN_RULES.md in {{brief_dir}} („{{project_name}}“).\n",
        "t/project.md": "# {{project_name}} ({{recipe.name}} {{recipe.version}})\n{{#task_sentence}}Task: {{task_sentence}}\n"
                        "{{/task_sentence}}Cameras: {{#cameras}}{{name}}{{^_last}}, {{/_last}}{{/cameras}}\n"
                        "Work: {{work_dir}}\n",
        "t/review_start.md": "Round {{round}} of {{project_name}}: {{round_dir}}\n",
        "CHANGES.md": "# Changes\n## v1.1\n- shorter rules\n## v1.0\n- first\n",
    }.items():
        full = os.path.join(path, *rel.split("/"))
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
    return path


def _user():
    root = recipes.user_dir()
    for n in os.listdir(root):
        shutil.rmtree(os.path.join(root, n))
    return root


def test_templates_are_a_mustache_subset(h=None):
    r = recipes.render
    assert r("a {{x}} b {{y.z}} {{missing}}!", {"x": 1, "y": {"z": "Z"}}) == "a 1 b Z !"
    assert r("{{#on}}yes{{/on}}{{^on}}no{{/on}}", {"on": False}) == "no"
    assert r("{{#n}}({{n}}){{/n}}", {"n": 0}) + r("{{#n}}({{n}}){{/n}}", {"n": 3}) == "(3)", "0 counts as empty"
    assert r("{{#l}}{{name}}{{^_last}}, {{/_last}}{{/l}}", {"l": [{"name": "a"}, {"name": "b"}]}) == "a, b"
    assert r("{{#l}}[{{.}}]{{/l}}", {"l": ["x", "y"]}) == "[x][y]"
    assert r("{{#s}}<{{s}}>{{/s}}", {"s": "text"}) == "<text>", "inside a section the outer names stay visible"
    assert r("a\n{{#on}}\nline\n{{/on}}\nb\n", {"on": True}) == "a\nline\nb\n", "tag lines vanish with their break"
    assert r("a\n  {{^on}}  \nline\n{{/on}}\nb", {"on": True}) == "a\nb"
    for bad in ("{{#a}}x", "x{{/a}}", "{{#a}}{{/b}}"):
        try:
            r(bad, {})
            raise AssertionError(f"accepted: {bad}")
        except recipes.RecipeError:
            pass


def test_default_recipe_is_complete(h=None):
    d = recipes.default()
    assert d.ok, d.problems
    assert d.id == "default" and d.builtin and d.version == brief_v4.VERSION
    assert set(recipes.TEMPLATES) <= set(d.templates), "Mule's own recipe brings every template"
    assert d.template("start", "de") != d.template("start", "en"), "German and English start sentence"
    targets = [t for _s, t in recipes.plan(d)]
    assert "brief/.claude/hooks/gate.ps1" in targets and "work/tools/vis_map/vis_map.py" in targets
    assert not any("__pycache__" in t or t.endswith(".pyc") for t in targets)
    assert "brief/.claude/hooks/gate.conf" in targets, "the template file is in the plan, install skips it"


def test_bad_recipes_are_shown_but_not_usable(h=None):
    root = _user()
    cases = {
        "escape": 'id="escape"\n[templates]\nstart="s.md"\n[files]\n"s.md" = "brief/../../evil.md"\n',
        "absolute": 'id="absolute"\n[templates]\nstart="s.md"\n[files]\n"s.md" = "C:/evil.md"\n',
        "source_out": 'id="source_out"\n[templates]\nstart="../s.md"\n',
        "nostart": 'id="nostart"\n',
        "future": 'id="future"\nbrief_interface=99\n[templates]\nstart="s.md"\n',
        "broken": 'id="broken"\n[templates]\nstart="b.md"\n',
        "toml": 'id = "toml\n',
        "Upper": 'id="Upper Case"\n[templates]\nstart="s.md"\n',
        "dup": 'id="default"\n[templates]\nstart="s.md"\n',
        "clash": 'id="clash"\n[templates]\nstart="s.md"\n[files]\n"s.md" = "brief/Brief.md"\n',
    }
    for name, toml in cases.items():
        os.makedirs(os.path.join(root, name))
        open(os.path.join(root, name, "recipe.toml"), "w", encoding="utf-8").write(toml)
        open(os.path.join(root, name, "s.md"), "w", encoding="utf-8").write("ok\n")
        open(os.path.join(root, name, "b.md"), "w", encoding="utf-8").write("{{#a}}open\n")
    got = {r.path.split(os.sep)[-1]: r for r in recipes.available()[1:]}
    assert set(got) == set(cases)
    for name, r in got.items():
        assert not r.ok, f"{name} should not be usable"
    assert "leaves its folder" in " ".join(got["escape"].problems + got["absolute"].problems)
    assert "already taken" in " ".join(got["dup"].problems)
    assert "belong to Mule's content" in " ".join(got["clash"].problems), "brief.md is Mule's, in any case"
    assert "update Mule" in " ".join(got["future"].problems)
    assert recipes.find("broken") is None and recipes.get("broken").id == "default"
    _user()


def test_export_with_an_own_recipe(h: H):
    """The chosen recipe replaces Mule's way of working completely: its files, its config, its project.md and its
    sentence for the chat; brief.md keeps the content."""
    root = _user()
    _recipe(root)
    lean = recipes.find("lean")
    assert lean is not None and lean.ok, lean and lean.problems
    sc = _scene(h)
    sc.brief_task = {"task": "Build the wing", "recipe": "lean"}
    assert brief.task_clean(sc.brief_task)["recipe"] == "lean"
    assert "recipe" not in brief.task_clean({"task": "x", "recipe": "default"}), "Mule's own is not stored"
    parent = tempfile.mkdtemp()
    folder = os.path.join(parent, "wing_brief")
    files = brief.export(sc, h.v, folder, "wing")
    work = brief_v4.work_dir(folder)
    for f in ("LEAN_RULES.md", "CLAUDE.md", ".claude/settings.json", ".claude/stop.sh", ".claude/lean.conf", "project.md",
              recipes.LOCK_FILE, "brief.md"):
        assert f in files and os.path.isfile(os.path.join(folder, f)), f
    for f in ("rules.md", "conductor.md", "roles", ".claude/hooks"):
        assert not os.path.exists(os.path.join(folder, f)), f"nothing of Mule's own way of working: {f}"
    assert not os.path.exists(os.path.join(folder, ".claude", "__pycache__"))
    assert os.path.isfile(os.path.join(work, "tools", "helper", "helper.py"))
    slash = lambda p: os.path.abspath(p).replace(os.sep, "/")  # noqa: E731
    assert open(os.path.join(folder, "CLAUDE.md"), encoding="utf-8").read().startswith("# wing – lean v1.0")
    settings = json.load(open(os.path.join(folder, ".claude", "settings.json"), encoding="utf-8"))
    cmd = settings["hooks"]["Stop"][0]["hooks"][0]
    assert cmd["command"] == brief_v4.hook_programs()[0] and cmd["args"] == [slash(folder) + "/.claude/stop.sh"]
    assert settings["permissions"]["additionalDirectories"] == [slash(work)], "Mule adds the work folder"
    conf = open(os.path.join(folder, ".claude", "lean.conf"), encoding="utf-8").read()
    assert conf == f"WORK={slash(work)}\nLEVEL=quick\n"
    project = open(os.path.join(folder, "project.md"), encoding="utf-8").read()
    assert project.startswith("# wing (Lean Test v1.0)\nTask: Build the wing\nCameras: ") and slash(work) in project
    md = open(os.path.join(folder, "brief.md"), encoding="utf-8").read()
    assert "conductor.md" not in md and "the way of working comes with the recipe" in md, "neutral head"
    lock = json.load(open(os.path.join(folder, recipes.LOCK_FILE), encoding="utf-8"))
    assert lock["id"] == "lean" and lock["version"] == "v1.0" and lock["digest"] == recipes.digest(lean)
    assert brief_v4.recipe_of(folder).id == "lean"
    from sketch_machine import i18n
    lang = i18n.LANG
    try:
        i18n.LANG = "en"
        assert autoprompt("wing", folder, sc.brief_task) == f"Lean: read LEAN_RULES.md in {os.path.normpath(folder)} for „wing“."
        assert autoprompt("wing", folder, dict(sc.brief_task, parts=["look"])).endswith(" Look first.")
        i18n.LANG = "de"
        assert autoprompt("wing", folder, sc.brief_task).startswith("Schlank:"), "language variant"
    finally:
        i18n.LANG = lang
    # running run (the recipe's marker): nothing of the recipe is touched, content is renewed
    os.makedirs(os.path.join(work, "log"))
    open(os.path.join(work, "log", "started"), "w").close()
    open(os.path.join(folder, "LEAN_RULES.md"), "w", encoding="utf-8").write("rules of the run\n")
    assert brief_v4.running(folder)
    files = brief.export(sc, h.v, folder, "wing")
    assert open(os.path.join(folder, "LEAN_RULES.md"), encoding="utf-8").read() == "rules of the run\n"
    assert "LEAN_RULES.md" not in files and "project.md" in files

    # review round: the brief's recipe stays; a newer version of it comes along, its changes are quoted
    target = review_round.next_folder(folder)
    task = {"based_on": folder}
    try:
        i18n.LANG = "en"
        assert autoprompt("wing", target, task) == f"Round 1 of wing: {os.path.normpath(target)}"
    finally:
        i18n.LANG = lang
    _recipe(root, version="v1.1")
    open(os.path.join(folder, ".claude", "lean.conf"), "w", encoding="utf-8").write("WORK=x\nLEVEL=deep\n")
    brief.export(sc, h.v, target, "wing", review_round=True)
    review = open(os.path.join(target, "review.md"), encoding="utf-8").read()
    assert "Lean Test v1.0 → v1.1" in review and "shorter rules" in review
    assert "- first" not in review, "only what is newer than the brief's version"
    assert "not a new brief" in review, "neutral intro without the recipe's template"
    assert open(os.path.join(folder, "LEAN_RULES.md"), encoding="utf-8").read() == "Lean rules\n", "new version in"
    assert open(os.path.join(folder, ".claude", "lean.conf"), encoding="utf-8").read() == "WORK=x\nLEVEL=deep\n", \
        "the run's settings stay"
    assert json.load(open(os.path.join(folder, recipes.LOCK_FILE), encoding="utf-8"))["version"] == "v1.1"
    # the recipe is gone on this machine: the round brings nothing, the brief keeps what it has
    shutil.rmtree(os.path.join(root, "lean"))
    assert brief_v4.update_package(folder, "wing") is None and brief_v4.recipe_of(folder) is None
    _user()


def _zip(src, dst, prefix="", extra=None):
    with zipfile.ZipFile(dst, "w") as z:
        for base, _d, files in os.walk(src):
            for f in files:
                full = os.path.join(base, f)
                z.write(full, prefix + os.path.relpath(full, src).replace(os.sep, "/"))
        for name, data in (extra or {}).items():
            z.writestr(name, data)
    return dst


def test_import_checks_before_it_installs(h=None):
    root = _user()
    src = _recipe(tempfile.mkdtemp())
    tmp = tempfile.mkdtemp()
    for bad, extra in (("slip", {"../evil.txt": "x"}), ("abs", {"/etc/evil": "x"})):
        try:
            recipes.unpack(_zip(src, os.path.join(tmp, f"{bad}.zip"), extra=extra))
            raise AssertionError(f"{bad} accepted")
        except recipes.RecipeError as exc:
            assert "outside" in str(exc)
    assert os.listdir(root) == [], "nothing installed"
    open(os.path.join(tmp, "nozip.zip"), "w").write("plain text")
    try:
        recipes.unpack(os.path.join(tmp, "nozip.zip"))
        raise AssertionError("text accepted as zip")
    except recipes.RecipeError:
        pass
    r = recipes.unpack(_zip(src, os.path.join(tmp, "lean.zip"), prefix="lean-main/"))  # zip of the folder
    assert r.ok and r.id == "lean"
    sm = recipes.summary(r)
    assert sm["hooks"] == [("Stop", "{{bash}} {{brief_dir}}/.claude/stop.sh")]
    assert [n[0] for n in sm["network"]] == [".claude/stop.sh"], "curl in the hook script is named"
    text = summary_text(r)
    assert "Lean Test v1.0 – Tester" in text and "stop.sh" in text and "<Brief>" in text and "curl" in text
    installed = recipes.install_unpacked(r)
    recipes.discard(r)
    assert installed.ok and os.path.isdir(os.path.join(root, "lean")) and recipes.find("lean") is not None
    r2 = recipes.unpack(_zip(src, os.path.join(tmp, "lean2.zip")))
    try:
        recipes.install_unpacked(r2)
        raise AssertionError("installed over an existing recipe without asking")
    except recipes.RecipeError:
        assert recipes.install_unpacked(r2, replace=True).ok
    finally:
        recipes.discard(r2)
    own = tempfile.mkdtemp()
    shutil.copytree(src, os.path.join(own, "x"))
    p = os.path.join(own, "x", "recipe.toml")
    text = open(p, encoding="utf-8").read().replace('id = "lean"', 'id = "default"')
    open(p, "w", encoding="utf-8").write(text)
    r3 = recipes.unpack(_zip(os.path.join(own, "x"), os.path.join(tmp, "d.zip")))
    try:
        recipes.install_unpacked(r3)
        raise AssertionError("a recipe took Mule's own id")
    except recipes.RecipeError as exc:
        assert "default" in str(exc)
    finally:
        recipes.discard(r3)
    _user()


def test_new_and_copied_recipes(h: H):
    """„New recipe“ gives a nearly empty recipe that works at once (with the format and a start guide for the AI that
    writes it); „Copy as my own“ gives Mule Default under its own id, without Mule's development files and with a
    fresh history – both chosen in the dialog, the sentence for a Claude session in the clipboard."""
    from PySide6.QtWidgets import QApplication
    root = _user()
    assert recipes.slug("Kleine Requisite!") == "kleine_requisite" and recipes.slug("Default") == "my_default"
    empty = recipes.create_empty("Kreatur Größe")
    assert empty.ok, empty.problems
    assert empty.id == "kreatur_groesse" and empty.name == "Kreatur Größe" and empty.version == "v0.1"
    for f in ("FORMAT.md", "START_HERE.md", "CHANGES.md", "CLAUDE.md", "templates/start.de.md"):
        assert os.path.isfile(os.path.join(empty.path, *f.split("/"))), f
    assert "brief_interface" in open(os.path.join(empty.path, "FORMAT.md"), encoding="utf-8").read()
    assert recipes.slug("Kreatur Größe") == "kreatur_groesse_2", "taken ids get a number"
    sc = _scene(h)
    sc.brief_task = {"task": "Monster", "recipe": empty.id}
    folder = os.path.join(tempfile.mkdtemp(), "m_brief")
    files = brief.export(sc, h.v, folder, "monster")
    assert "CLAUDE.md" in files and "project.md" in files and recipes.LOCK_FILE in files
    assert "START_HERE.md" not in files and "FORMAT.md" not in files and "recipe.toml" not in files
    assert not os.path.exists(os.path.join(folder, "START_HERE.md")) and not os.path.exists(
        os.path.join(folder, "FORMAT.md")), "guides stay in the recipe"
    project = open(os.path.join(folder, "project.md"), encoding="utf-8").read()
    assert "**In one sentence:** Monster" in project and "{{" not in project
    assert open(os.path.join(folder, "CLAUDE.md"), encoding="utf-8").read().startswith("# Sketch Brief – monster")

    copy = recipes.copy_recipe(recipes.default(), "Mein Default")
    assert copy.ok, copy.problems
    assert copy.id == "mein_default" and copy.version == "v1.0" and copy.forked_from == f"default {brief_v4.VERSION}"
    assert copy.author == "" and not copy.builtin and copy.description == recipes.default().description
    for gone in ("_claude/tests", "LIESMICH.md", "_claude/AENDERUNGEN_HOOKS.md", "tools/vis_map/PILOT_README_de.md"):
        assert not os.path.exists(os.path.join(copy.path, *gone.split("/"))), gone
    assert os.path.isfile(os.path.join(copy.path, "_claude", "hooks", "gate.ps1"))
    changes = open(os.path.join(copy.path, "PACKAGE_CHANGES.md"), encoding="utf-8").read()
    assert "## v1.0" in changes and "## v5" not in changes, "fresh history: review rounds quote nothing old"
    assert [t for _s, t in recipes.plan(copy)] == [t for _s, t in recipes.plan(recipes.default())
                                                   if not t.endswith("PILOT_README_de.md")]

    dlg = BriefDialog(None, {"task": "x"}, 0, None, "a", "C:/x/a_brief")
    dlg.quiet = True
    made = dlg._new_recipe("Landschaft")
    assert made.id == "landschaft" and dlg.recipe().id == "landschaft" and dlg.values()["recipe"] == "landschaft"
    assert "START_HERE.md" in QApplication.clipboard().text() and os.path.normpath(made.path) in QApplication.clipboard().text()
    made = dlg._copy_recipe("Landschaft groß")
    assert made.forked_from.startswith("landschaft v0.1") and dlg.recipe().id == "landschaft_gross"
    # a recipe folder from elsewhere: checked and copied, the original stays
    src = _recipe(tempfile.mkdtemp())
    got = dlg._import_recipe_folder(src, ask=False)
    assert got.id == "lean" and os.path.isdir(src) and os.path.isdir(os.path.join(root, "lean"))
    try:
        recipes.unpack_folder(tempfile.mkdtemp())
        raise AssertionError("a folder without recipe.toml was accepted")
    except recipes.RecipeError:
        pass
    _user()


def test_brief_md_holds_only_content_with_an_own_recipe(h: H):
    """brief.md: Mule's reading aid, the look procedure, „raise with the artist“ and the context head are the recipe's
    templates. Without them an own recipe gets content only (neutral look and context lines); with them, its own
    texts. Every build brief says that its way of working wins over reading aids – not over the artist's words."""
    root = _user()
    _recipe(root)
    from tests.test_brief_task import _text_note
    sc = _scene(h)
    sc.notes += [_text_note("Later", "Saddle in a later round")]
    sc.brief_task = {"task": "x", "recipe": "lean", "parts": ["look"]}
    data = brief.analyse(sc)
    data["cameras"] = [{"id": "hero_1", "name": "Hero 1", "image": "views/hero_1.png", "default": False,
                        "prompt": "chrome bike, studio light"}]
    real_points, real_later = brief._open_points, brief._later_notes
    brief._open_points = lambda d, lang="en": ["Two lines cross without a joint"]
    brief._later_notes = lambda d: {d["notes"][-1]["id"]}
    try:
        def md_of(d):
            folder = tempfile.mkdtemp()
            brief.write_markdown(d, [], os.path.join(folder, "brief.md"), "bike")
            ctx = os.path.join(folder, "context.md")
            return (open(os.path.join(folder, "brief.md"), encoding="utf-8").read(),
                    open(ctx, encoding="utf-8").read() if os.path.isfile(ctx) else "")
        md, ctx = md_of(copy.deepcopy(data))
        assert brief.PRECEDENCE in md and md.index(brief.PRECEDENCE) < md.index(brief.READ_SECTION)
        assert "**Reading notes:**" not in md and "How to read the sketch" not in md, "no reading aid of Mule's"
        assert "The scene contains:" in md and "Units: 1 unit = 1 m" in md, "the content stays"
        assert "## Open points the tool noticed\n- Two lines cross without a joint" in md, "no „raise with the artist“"
        assert "## Look images (before building)\nThe artist asked for look images" in md
        assert "`hero_1` – prompt approved by the artist: chrome bike, studio light" in md
        assert "Generate 2–3 variants" not in md, "no look procedure of Mule's"
        assert "no work lines" not in ctx and "not built in this round" in ctx
        # the same with Mule Default: its texts
        d2 = copy.deepcopy(data)
        d2["task"] = {"task": "x", "parts": ["look"]}
        md, ctx = md_of(d2)
        assert "**Reading notes:**" in md and "Raise these with the artist:" in md and "Generate 2–3 variants" in md
        assert "- `hero_1` – prompt approved by the artist (use it, no need to ask again): chrome bike" in md
        assert "They give no work lines in this round." in ctx
        # an own recipe with its own texts
        tpl = os.path.join(root, "lean", "t")
        for name, text in (("reading", "**Read strictly:** every line binds within 1 %.\n"),
                           ("look", "## Look\n{{#cameras}}- {{name}}{{#prompt}}: {{prompt}}{{/prompt}}\n{{/cameras}}"),
                           ("open_points", "Decide these yourself and log them.\n"),
                           ("context_head", "Ignore for now.\n")):
            open(os.path.join(tpl, name + ".md"), "w", encoding="utf-8").write(text)
        toml = os.path.join(root, "lean", "recipe.toml")
        t = open(toml, encoding="utf-8").read().replace('review_start = "t/review_start.md"\n',
                                                         'review_start = "t/review_start.md"\nreading = "t/reading.md"\n'
                                                         'look = "t/look.md"\nopen_points = "t/open_points.md"\n'
                                                         'context_head = "t/context_head.md"\n')
        open(toml, "w", encoding="utf-8").write(t)
        assert recipes.find("lean").ok, recipes.Recipe(os.path.join(root, "lean")).problems
        md, ctx = md_of(copy.deepcopy(data))
        assert "**Read strictly:** every line binds within 1 %.\n\nUnits:" in md
        assert "## Look\n- Hero 1: chrome bike, studio light" in md
        assert "## Open points the tool noticed\nDecide these yourself and log them.\n- Two lines" in md
        assert "Ignore for now." in ctx
    finally:
        brief._open_points, brief._later_notes = real_points, real_later
    _user()


def test_dialog_chooses_the_recipe(h: H):
    root = _user()
    dlg = BriefDialog(None, {"task": "x"}, 0, None, "a", "C:/x/a_brief")
    assert dlg.recipe_combo.count() == 1 and dlg.recipe().id == "default" and "recipe" not in dlg.values()
    assert "Hook" in dlg.recipe_info.text() and "nicht von Mule geprüft" not in dlg.recipe_info.text()
    _recipe(root)
    os.makedirs(os.path.join(root, "zz_broken"))
    open(os.path.join(root, "zz_broken", "recipe.toml"), "w").write('id="zz"\n')
    dlg = BriefDialog(None, {"task": "x", "recipe": "lean"}, 0, None, "a", "C:/x/a_brief")
    assert dlg.recipe_combo.count() == 3 and dlg.recipe().id == "lean" and dlg.values()["recipe"] == "lean"
    assert not dlg.recipe_combo.model().item(2).isEnabled(), "broken recipe cannot be chosen"
    info = dlg.recipe_info.text()
    assert "One builder, no QC." in info and "Tester" in info and "1 Hook" in info and "Netz" in info
    assert dlg.prompt.toPlainText().startswith("Schlank:"), "the sentence follows the recipe"
    dlg.recipe_combo.setCurrentIndex(0)
    assert "recipe" not in dlg.values() and "GATE STATUS" in dlg.prompt.toPlainText()
    dlg.discuss.setChecked(True)
    assert not dlg.recipe_row.isEnabled() and "Nur besprechen" in dlg.recipe_info.text()
    missing = BriefDialog(None, {"recipe": "gone"}, 0, None, "a", "C:/x/a_brief")
    assert missing.recipe().id == "default" and "„gone“" in missing.recipe_info.text()
    assert missing.values().get("recipe") is None
    # import from the dialog (without the question)
    shutil.rmtree(os.path.join(root, "lean"))
    src = _recipe(tempfile.mkdtemp())
    z = _zip(src, os.path.join(tempfile.mkdtemp(), "lean.zip"))
    got = missing._import_recipe(z, ask=False)
    assert got is not None and got.id == "lean" and missing.recipe().id == "lean", "imported recipe is chosen"
    _user()

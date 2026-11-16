"""Assignment on brief export: the dialog only sets the task sentence, notes, "discuss only", look pre-stage and
focus. Build brief = working-method package v4 (rules, levels, conductor, roles, hooks) + project.md (goal, round card,
task) + brief.md (content); "discuss only" keeps the short core (core.md with the clarification list)."""
import os
import tempfile

from PySide6.QtCore import Qt

from sketch_machine.i18n import tr
from tests.harness import H
from tests.test_brief_content import _scene
from sketch_machine import brief
from sketch_machine.brief_dialog import BriefDialog
from sketch_machine.scene import Scene

# old settings (v0.99.68–91): fields the clarification list now asks for are dropped when read
OLD_TASK = {"task": "Build the glider as a model", "notes": "Leave out the landing gear this time", "kind": "new",
            "parts": ["materials", "geometry", "rig", "look", "nonsense"], "stage": "complete",
            "target": "Houdini (prozedural)", "workflow": "build", "fidelity": {"meshes": "exact"}}


def _md(sc, folder=None):
    folder = folder or tempfile.mkdtemp()
    path = os.path.join(folder, "brief.md")
    brief.write_markdown(brief.analyse(sc), [], path, "t")
    return open(path, encoding="utf-8").read()


def _core(md):
    return md[md.index("## Core"):md.index(brief.READ_SECTION)]


def test_old_tasks_keep_only_what_the_dialog_still_sets(h: H):
    assert brief.task_clean(OLD_TASK) == {"task": OLD_TASK["task"], "notes": OLD_TASK["notes"], "parts": ["look"]}
    assert brief.task_clean({"kind": "discuss", "parts": ["look"]}) == {"kind": "discuss"}, "discuss without look"
    assert brief.task_clean({"task": "  ", "kind": "revise"}) == {}
    sc = _scene(h)
    sc.brief_task = brief.task_clean(OLD_TASK)
    base = tempfile.mkdtemp()
    assert Scene.from_dict(sc.to_dict(base), base).brief_task == sc.brief_task


def _project(sc, folder=None):
    """brief.md and project.md as in the build export (without images): returns (brief.md, project.md)."""
    from sketch_machine import brief_v4
    folder = folder or tempfile.mkdtemp()
    data = brief.analyse(sc)
    ctx = brief.write_markdown(data, [], os.path.join(folder, "brief.md"), "t")
    brief_v4.write_project(data, "t", folder, ctx)
    return (open(os.path.join(folder, "brief.md"), encoding="utf-8").read(),
            open(os.path.join(folder, brief_v4.PROJECT_FILE), encoding="utf-8").read())


def test_build_brief_head_and_project_document(h: H):
    """Package v4: brief.md is content (notes, scene); goal, round card and task are in project.md; the old
    core (core.md) is omitted in the build brief."""
    sc = _scene(h)
    sc.brief_task = {"task": "Build wing", "notes": "  Ignore the landing gear this time\n\nPriority: joints  "}
    folder = tempfile.mkdtemp()
    md, project = _project(sc, folder)
    assert "## Core" not in md and md.index("`project.md`") < md.index(brief.READ_SECTION) < md.index("## Overview")
    assert not os.path.isfile(os.path.join(folder, brief.CORE_FILE))
    assert "**In one sentence:** Build wing" in project and "proposed from the task: Build wing" in project
    assert "> Ignore the landing gear this time\n>\n> Priority: joints\n" in project
    assert "a creature, a place or a whole scene" in project and "**It is a prompt, not a finished spec.**" in project
    assert "`SET: level=scout|study|final`" in project and "key `level`" in project
    assert "`review/round_report.md`" in project, "done criteria of the goal"
    for old in ("Stage:", "Parts of this task", "Software / environment", "### First round", "Goals and checks",
                "## How to work with the artist"):
        assert old not in md, f"old core or rules text: {old}"


def test_first_round_in_the_project_document(h: H):
    sc = _scene(h)
    md, project = _project(sc)
    assert "set no task sentence on export – the first round works out the goal" in project
    first = project[project.index("## First round"):]
    assert "`views/hero_*.png`" in first and "`notes/board_N#.png`" in first and "how many you opened" in first
    assert "it does not replace opening the picture" in first, "a caption does not replace looking"
    assert "write_clarified" in first
    assert "No focus and no binding set in Mule: the first round fills this map" in project
    assert "ask in the first round which software is at hand" in project, "tools: global note or question"
    path = brief.BIBLE.replace(os.sep, "/")
    assert f"`{path}`" in project and os.path.isfile(brief.BIBLE)


def test_package_in_brief_folder_and_work_folder(h: H):
    """Export copies the package (rules, levels, conductor, roles, hooks, agent types) into the brief folder and creates
    the work folder next to it (vis map as a tool); gate.conf and settings.json with real paths. If a run is already
    going there, rules and hooks stay untouched."""
    import json
    from sketch_machine import brief_v4
    root = tempfile.mkdtemp()
    folder = os.path.join(root, "hafen_brief")
    os.makedirs(folder)
    with open(os.path.join(folder, brief.CORE_FILE), "w", encoding="utf-8") as fh:
        fh.write("old core")
    sc = _scene(h)
    files = brief.export(sc, h.v, folder, "hafen")
    work = os.path.join(root, "work_hafen")
    assert brief_v4.work_dir(folder) == work and os.path.isdir(os.path.join(work, "review"))
    for f in ("rules.md", "levels.md", "conductor.md", "project.md", "CLAUDE.md", "roles/builder.md",
              "roles/viewer.md", ".claude/hooks/gate.ps1", ".claude/hooks/pretool_build.sh", ".claude/hooks/gate.conf",
              ".claude/agents/qc.md", ".claude/settings.json"):
        assert f in files and os.path.isfile(os.path.join(folder, f)), f
    assert not os.path.exists(os.path.join(folder, ".claude", "tests")), "hook tests stay in the repo"
    assert not os.path.isfile(os.path.join(folder, brief.CORE_FILE)), "old core removed"
    for f in ("vis_map/vis_export.py", "vis_map/vis_map.py", "vis_map/README.md", "sketch_overlay/sketch_overlay.py",
              "sketch_overlay/README.md"):
        assert os.path.isfile(os.path.join(work, "tools", *f.split("/"))), f
    assert not os.path.exists(os.path.join(work, "tools", "vis_map", "__pycache__"))
    claude = open(os.path.join(folder, "CLAUDE.md"), encoding="utf-8").read()
    assert "# Mule Sketch Brief – hafen" in claude and "@rules.md" in claude
    conf = dict(l.split("=", 1) for l in open(os.path.join(folder, ".claude", "hooks", "gate.conf"),
                                                encoding="utf-8").read().splitlines())
    assert conf["WORK"] == work.replace(os.sep, "/") and conf["LEVEL"] == "study" and conf["MAX_WEEKLY"] == "90"
    raw = open(os.path.join(folder, ".claude", "settings.json"), encoding="utf-8").read()
    settings = json.loads(raw)
    assert "__BRIEF__" not in raw and folder.replace(os.sep, "/") + "/.claude/hooks/gate.ps1" in raw
    assert settings["permissions"]["additionalDirectories"] == [work.replace(os.sep, "/")]
    with open(os.path.join(folder, ".claude", "hooks", "pretool_build.sh"), "rb") as fh:
        assert b"\r\n" not in fh.read(), "shell hooks with LF"
    # running run: rules stay, content is renewed
    os.makedirs(os.path.join(work, "review", "gate"))
    open(os.path.join(work, "review", "gate", "agents.log"), "w").close()
    with open(os.path.join(folder, "rules.md"), "w", encoding="utf-8") as fh:
        fh.write("Rules of the running run")
    assert brief_v4.running(folder)
    files = brief.export(sc, h.v, folder, "hafen")
    assert open(os.path.join(folder, "rules.md"), encoding="utf-8").read() == "Rules of the running run"
    assert "rules.md" not in files and "project.md" in files and "brief.md" in files


def _text_note(title, *texts):
    import numpy as np
    from sketch_machine.scene import Note
    return Note(title, np.array([1.0, 2.0, 0.0]),
                board={"items": [{"kind": "text", "x": 0, "y": 80 * k, "text": t} for k, t in enumerate(texts)]})


def test_review_round_only_what_is_new(h: H):
    """Review round (artist 2026-11-15): "Builds on <brief folder>" exports without a folder choice to
    <brief>/review_rounds/review_NN_<date>/ – no brief.md, an older package is renewed; review.md names only what changed
    in the notes since the last export (notes via uid, older exports via the title), plus the
    current state. The running run stays untouched; the next round compares with the previous one."""
    import json
    from sketch_machine import brief_v4, recipes, review_round
    root = tempfile.mkdtemp()
    base = os.path.join(root, "alpaka_brief")
    sc = _scene(h)
    sc.notes += [_text_note("Wheel", "Wheel bigger"), _text_note("Saddle", "Saddle made of leather"),
                 _text_note("Handlebar", "Handlebar straight")]
    brief.export(sc, h.v, base, "alpaka")
    gate = os.path.join(base, ".claude", "hooks", "gate.conf")
    stamp = os.path.getmtime(gate), open(os.path.join(base, "brief.md"), encoding="utf-8").read()
    # older export without uid: notes are found again via the title
    data = json.load(open(os.path.join(base, "brief.json"), encoding="utf-8"))
    for n in data["notes"]:
        n.pop("uid", None)
    json.dump(data, open(os.path.join(base, "brief.json"), "w", encoding="utf-8"))
    # review: wheel changed, saddle deleted, pedal new, handlebar the same
    wheel = next(n for n in sc.notes if n.title == "Wheel")
    wheel.board = {"items": [{"kind": "text", "x": 0, "y": 0, "text": "Wheel much bigger, 26 inch"}]}
    sc.notes = [n for n in sc.notes if n.title != "Saddle"] + [_text_note("Pedal", "Pedals made of aluminum")]
    target = review_round.next_folder(base)
    assert os.path.dirname(target) == os.path.join(base, review_round.ROUNDS_DIR)
    assert os.path.basename(target).startswith("review_01_") and review_round.round_number(target) == 1
    assert review_round.base_of(target) == os.path.abspath(base) and review_round.is_brief(target)
    files = brief.export(sc, h.v, target, "alpaka", review_round=True)
    assert "review.md" in files and os.path.isfile(os.path.join(target, "scene.usd"))
    for f in ("brief.md", "rules.md", "CLAUDE.md", "project.md", ".claude", ".mcp.json"):
        assert not os.path.exists(os.path.join(target, f)), f"no rules, no new brief: {f}"
    assert not os.path.exists(brief_v4.work_dir(target)), "no work folder"
    md = open(os.path.join(target, "review.md"), encoding="utf-8").read()
    assert "not a new brief and not a new run" in md
    new, changed = md[md.index("## New notes"):md.index("## Changed notes")], md[md.index("## Changed notes"):]
    assert "„Pedal“" in new and "Pedals made of aluminum" in new and "„Wheel“" not in new
    assert "„Wheel“" in changed and "Wheel much bigger, 26 inch" in changed and "> Wheel bigger" in changed
    assert "## Notes no longer in the scene (1)" in md and "„Saddle“" in md and "revokes nothing" in md
    assert "Unchanged since the last export:" in md and "„Handlebar“" in md.split("Unchanged since")[1]
    assert (os.path.getmtime(gate), open(os.path.join(base, "brief.md"), encoding="utf-8").read()) == stamp,         "running run untouched"
    # second round without changes: compares with round 1
    target2 = review_round.next_folder(base)
    assert review_round.round_number(target2) == 2
    brief.export(sc, h.v, target2, "alpaka", review_round=True)
    md2 = open(os.path.join(target2, "review.md"), encoding="utf-8").read()
    assert "## No changed notes" in md2 and "review_01_" in md2
    assert "rules were updated" not in md and "rules were updated" not in md2, "same package: nothing renewed"
    # older package in the running brief (artist 2026-11-16): the review round brings the new one, settings stay
    lock_path = os.path.join(base, recipes.LOCK_FILE)
    lock = json.load(open(lock_path, encoding="utf-8"))
    assert lock["id"] == "default" and lock["version"] == brief_v4.VERSION and len(lock["digest"]) == 64
    json.dump(dict(lock, version="v4.8"), open(lock_path, "w", encoding="utf-8"))
    open(os.path.join(base, "rules.md"), "w", encoding="utf-8").write("OLD RULES\n")
    conf = open(gate, encoding="utf-8").read().replace("LEVEL=study", "LEVEL=final").replace("STOP_AT=\n", "")
    open(gate, "w", encoding="utf-8").write(conf)
    local = os.path.join(base, ".claude", "hooks", "gate.local.conf")
    open(local, "w", encoding="utf-8").write("LEVEL=final\n")
    work_tool = os.path.join(brief_v4.work_dir(base), "tools", "sketch_overlay", "sketch_overlay.py")
    os.remove(work_tool)
    target3 = review_round.next_folder(base)
    brief.export(sc, h.v, target3, "alpaka", review_round=True)
    md3 = open(os.path.join(target3, "review.md"), encoding="utf-8").read()
    assert f"package v4.8 → {brief_v4.VERSION}" in md3 and "## v4.11" in md3 and "## v4.8" not in md3
    assert "only the rules were updated" in md3 and "apply the changes below backwards".lower() in md3.lower()
    assert open(os.path.join(base, "rules.md"), encoding="utf-8").read() == \
        open(os.path.join(brief_v4.PACKAGE_DIR, "rules.md"), encoding="utf-8").read(), "new rules in the brief"
    assert json.load(open(lock_path, encoding="utf-8"))["version"] == brief_v4.VERSION
    conf3 = open(gate, encoding="utf-8").read()
    assert "LEVEL=final" in conf3 and "WORK=" in conf3 and "STOP_AT=" in conf3, "settings stay, new keys"
    assert open(local, encoding="utf-8").read() == "LEVEL=final\n" and os.path.isfile(work_tool)
    assert open(os.path.join(base, "brief.md"), encoding="utf-8").read() == stamp[1], "content stays"
    # the note's id stays across saving and loading
    path = os.path.join(root, "s.sketch.json")
    sc.save(path)
    loaded, _ = Scene.load(path)
    assert [n.uid for n in loaded.notes] == [n.uid for n in sc.notes]


def test_review_round_from_the_app(h: H):
    """Saved task with "Builds on": export without a dialog (MCP export_brief) becomes a review round, clarified items
    then belong in the brief of the running run; without a brief there, an error message instead of a folder."""
    from sketch_machine import review_round
    root = tempfile.mkdtemp()
    base = os.path.join(root, "x_brief")
    sc = h.v.scene
    keep = sc.brief_task
    try:
        sc.brief_task = {}
        h.w.export_brief_to(base)
        sc.brief_task = {"based_on": base}
        target = h.w.export_brief_to()
        assert review_round.round_number(target) == 1 and os.path.isfile(os.path.join(target, "review.md"))
        assert h.w.last_brief == os.path.abspath(base)
        sc.brief_task = {"based_on": os.path.join(root, "doesnotexist")}
        try:
            h.w.export_brief_to()
            assert False, "no round without a brief"
        except ValueError as exc:
            assert "brief.json" in str(exc)
    finally:
        sc.brief_task = keep


def test_review_round_in_the_dialog(h: H):
    """Dialog: "Builds on" shows where the round goes (without a folder choice); the sentence for the chat is a
    continuation sentence without hook check. No brief there, "Discuss only" or empty: normal export."""
    from sketch_machine import review_round
    root = tempfile.mkdtemp()
    base = os.path.join(root, "a_brief")
    os.makedirs(base)
    with open(os.path.join(base, "brief.json"), "w", encoding="utf-8") as fh:
        fh.write("{}")
    dlg = BriefDialog(None, {"based_on": base}, 0, None, "a", os.path.join(root, "new_brief"))
    assert dlg.values()["based_on"] == base
    target = review_round.next_folder(base)
    assert dlg.round_folder() == target and os.path.normpath(target) in dlg.based_on_info.text()
    prompt = dlg.prompt.toPlainText()
    assert os.path.normpath(target) in prompt and "review.md" in prompt and "GATE STATUS" not in prompt
    os.makedirs(target)  # a round already exists: the next one is 02
    dlg.based_on.setText(base)
    dlg._sync()
    assert "review_02_" in dlg.based_on_info.text()
    dlg.discuss.setChecked(True)
    assert dlg.round_folder() is None and "review.md" not in dlg.prompt.toPlainText()
    dlg.discuss.setChecked(False)
    dlg.based_on.setText(os.path.join(root, "empty"))
    assert dlg.round_folder() is None and "brief.json" in dlg.based_on_info.text()
    assert "GATE STATUS" in dlg.prompt.toPlainText(), "normal build brief"
    dlg.based_on.setText("")
    assert "based_on" not in dlg.values() and not dlg.based_on_info.text()


def test_notes_of_later_rounds_in_context(h: H):
    """With focus: notes that point only to parts outside the focus are in context.md; without focus everything is in the
    brief."""
    sc = _scene(h)
    data = brief.analyse(sc)
    targets = [(n["id"], (n["anchors"][0].get("target") or {}).get("id")) for n in data["notes"] if n["anchors"]]
    assert targets, "test scene needs a note with a target"
    assert brief._later_notes(data) == set(), "without focus everything in the brief"
    data["focus"] = {"ids": ["X99"], "selected": [], "bounds": data["bounds"]}
    later = brief._later_notes(data)
    assert {n for n, t in targets if t} <= later
    folder = tempfile.mkdtemp()
    assert brief.write_markdown(data, [], os.path.join(folder, "brief.md"), "t")
    ctx = open(os.path.join(folder, "context.md"), encoding="utf-8").read()
    md = open(os.path.join(folder, "brief.md"), encoding="utf-8").read()
    nid = targets[0][0]
    assert f"### {nid} –" in ctx and f"### {nid} –" not in md and "`context.md`" in md
    data["focus"] = {"ids": [targets[0][1]], "selected": [], "bounds": data["bounds"]}
    assert nid not in brief._later_notes(data), "note on a focus part stays in the brief"
    brief.write_markdown(dict(data, focus=None), [], os.path.join(folder, "brief.md"), "t")
    assert not os.path.isfile(os.path.join(folder, "context.md")), "stale context.md removed"


def test_general_for_every_object(h: H):
    md = _md(_scene(h))
    assert "where its character is irregular (bark, rock, skin" in md and "is not intent – smooth it" not in md
    assert "where it may be a one-off (damage, a scar" in md and "wing joints" not in md
    assert "develop the rest – main bodies, cross-sections, transitions, connections" in md


def test_discuss_only(h: H):
    sc = _scene(h)
    sc.brief_task = {"kind": "discuss"}
    md = _md(sc)
    core = _core(md)
    assert "**Do not build anything.**" in core and "### First round" not in core and "Work list" not in core
    assert f"    1. {brief.CLARIFY[0]}" in core, "clarification questions as a guide"
    how = md[md.index("## How to work with the artist"):]
    assert "Review sheets" not in how and "bible" not in how and "**Feedback**" in how


def test_binding_per_object_in_the_outliner(h: H):
    """Outliner column "Brief": binding on a null (inherited) or an object, in the core under the task;
    saved, one undo step."""
    from sketch_machine.outliner import BRIEF, BRIEF_ROLE
    sc = _scene(h)
    group = next(n for n in sc.nulls if n.name == "Wing")
    wing = next(m for m in sc.meshes if m.name == "Wing_L")
    h.v.set_binding([group.id], "fixed")
    assert sc.binding_of(wing) == ("fixed", group), "mesh inherits from the null"
    data = brief.analyse(sc)
    assert data["meshes"][0]["binding"] == "fixed"
    assert data["bindings"] == [{"id": "H1", "name": "Wing", "level": "fixed", "group": True}]
    project = _project(sc)[1]
    assert "| Wing | H1 and everything in it | – (first round) | fixed |" in project, "round card"
    h.v.set_binding([wing.id], "guide")
    assert sc.binding_of(wing) == ("guide", wing), "own level beats that of the null"
    base = tempfile.mkdtemp()
    again = Scene.from_dict(sc.to_dict(base), base)
    assert [n.binding for n in again.nulls] == ["fixed"] and again.meshes[0].binding == "guide"
    sc.undo()  # undo restores copies: fetch the objects again
    wing = next(m for m in sc.meshes if m.name == "Wing_L")
    assert wing.binding is None and sc.binding_of(wing)[0] == "fixed"
    h.app.processEvents()
    out = h.w.outliner
    out.rebuild()
    cells = {it.text(0): it.data(BRIEF, BRIEF_ROLE) for it in out.findItems("*", Qt.MatchWildcard | Qt.MatchRecursive)}
    fixed = tr(brief.TASK_LEVELS["fixed"][0]).split(" – ")[0]
    assert cells["Wing"] == (fixed, True) and cells["Wing_L"] == ("↳ " + fixed, False), cells
    assert cells["Stroke 1"] is None, "stroke objects have no brief field"


def test_dialog_values(h: H):
    task = brief.task_clean(OLD_TASK)
    dlg = BriefDialog(None, task, selected=0)
    assert dlg.values() == task, "dialog shows the saved task"
    assert dlg.look.isChecked() and dlg.look.isEnabled()
    dlg.discuss.setChecked(True)
    assert not dlg.look.isEnabled() and dlg.values() == {"task": task["task"], "notes": task["notes"],
                                                         "kind": "discuss"}
    dlg._clear()
    assert dlg.values() == {}
    picked = BriefDialog(None, {}, selected=3)
    assert picked.layout().isRowVisible(picked.focus) and not picked.focus.isChecked()
    assert not dlg.layout().isRowVisible(dlg.focus), "without a selection no scope"


def test_dialog_closes(h: H):
    """v0.99.68 had a field self.done – it shadowed QDialog.done(), Cancel/X/Esc no longer closed."""
    from PySide6.QtCore import QObject
    from PySide6.QtWidgets import QDialog
    dlg = BriefDialog(None, brief.task_clean(OLD_TASK), selected=2)
    shadowed = [name for name, v in vars(dlg).items() if isinstance(v, QObject) and hasattr(QDialog, name)]
    assert not shadowed, f"fields shadow Qt methods: {shadowed}"
    dlg.show()
    dlg.reject()
    assert not dlg.isVisible() and dlg.result() == QDialog.Rejected


def test_dialog_shows_open_points_before_the_export(h: H):
    """Open points from the scene are in the dialog, not in the brief; a hint if there is no goal and no notes."""
    from sketch_machine.scene import NoteAnchor
    import numpy as np
    sc = _scene(h)
    sc.notes[0].anchors.append(NoteAnchor(np.array([0.0, 30.0, 0.0])))
    checks = brief.precheck(sc, brief.analyse(sc))
    assert any(p.startswith("N1 Wing: ") and " 2 " in p for p in checks["points"]), checks["points"]
    assert "wing" in checks["text"] and "wing_l" in checks["text"], "note titles and names count"
    assert brief.part_hints({}, "") == [tr("Kein Auftragssatz und keine Notizen – die KI kennt das Ziel nicht")]
    assert not brief._mentions("original", ["rig"]) and brief._mentions("rigging, wingjoint", ["rig", "joint"])
    dlg = BriefDialog(None, {"parts": ["look"]}, 0, checks)
    assert tr("<b>Vor dem Export prüfen ({0}):</b><br>").format(2) in dlg.hints.text() and not dlg.hints_box.isHidden()
    dlg.notes.setPlainText("Stimmung: staubig, warmes Licht")
    assert tr("<b>Vor dem Export prüfen ({0}):</b><br>").format(1) in dlg.hints.text(), "hints follow the text live"


def test_autoprompt_in_the_dialog(h: H):
    """Autoprompt: is in the field, follows the settings (look pre-stage), own changes stay; on export the
    actual folder instead of the proposed one."""
    dlg = BriefDialog(None, {}, 0, None, "glider", r"C:\scenes\glider_brief")
    text = dlg.prompt.toPlainText()
    assert "glider" in text and r"(C:\scenes\glider_brief)" in text and "write_clarified" in text and "set_hero_prompt" not in text
    assert "conductor.md" in text and "project.md" in text and "GATE STATUS" in text and "Core" not in text
    assert "Stufe" in text, "level at the very bottom of the first message"
    other = BriefDialog(None, {"kind": "discuss"}, 0, None, "glider", r"C:\scenes\glider_brief")
    talk = other.prompt.toPlainText()
    assert "Core" in talk and "GATE STATUS" not in talk, "discuss only: old short core"
    dlg.look.setChecked(True)
    assert "set_hero_prompt" in dlg.prompt.toPlainText(), "follows the look pre-stage"
    # Harbor test 2026-11-12: the session ran in the project folder instead of the brief folder, the hooks were missing. The sentence asks
    # for the brief folder first and names it twice (location of the session, brief).
    assert dlg.prompt_text(r"D:\neu\glider_brief").count(r"D:\neu\glider_brief") == 2
    assert text.index("Brief-Ordner") < text.index("GATE STATUS"), "folder check before the gate"
    if os.sep == "\\":
        assert r"C:\x\05_built\b_brief" in dlg.prompt_text("C:/x/05_built\\b_brief"), "path without mixed slashes"
    dlg.prompt.setPlainText(r"Own text for C:\scenes\glider_brief")
    dlg.look.setChecked(False)
    assert dlg.prompt.toPlainText().startswith("Own text"), "own change stays"


def test_clarified_in_the_dialog(h: H):
    """Row "Clarified with the AI": only with content, viewable as text, deletion only on export (toggleable)."""
    plain = BriefDialog(None, {})
    assert not plain.layout().isRowVisible(plain.clarified_label.parentWidget())
    c = {"summary": "A glider.", "answers": [{"question": "Foldable?", "answer": "Yes"},
                                               {"question": "Color?", "answer": "decide"}]}
    dlg = BriefDialog(None, {}, clarified=c)
    assert dlg.layout().isRowVisible(dlg.clarified_label.parentWidget())
    assert dlg.clarified_label.text().startswith(tr("{0} Punkt{1}").format(2, "e") + tr(" und eine Zusammenfassung"))
    assert dlg.clarified_text() == "A glider.\n\n• Foldable? → Yes\n• Color? → " + tr("entscheidet die KI")
    dlg.clarified_drop.setChecked(True)
    assert dlg.clear_clarified and dlg.clarified_drop.text() == tr("Behalten")
    dlg.clarified_drop.setChecked(False)
    assert not dlg.clear_clarified

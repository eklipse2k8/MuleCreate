"""Auftrag beim Brief-Export: der Dialog setzt nur Auftragssatz, Hinweise, „nur besprechen“, Look-Vorstufe und
Fokus. Bau-Brief = Arbeitsweise-Paket v4 (Regeln, Stufen, Dirigent, Rollen, Hooks) + project.md (Ziel, Rundenkarte,
Auftrag) + brief.md (Inhalt); „nur besprechen“ behält den kurzen Kern (core.md mit Klärungsliste)."""
import os
import tempfile

from PySide6.QtCore import Qt

from sketch_machine.i18n import tr
from tests.harness import H
from tests.test_brief_inhalt import _scene
from sketch_machine import brief
from sketch_machine.brief_dialog import BriefDialog
from sketch_machine.scene import Scene

# alte Einstellungen (v0.99.68–91): Felder, die jetzt die Klärungsliste fragt, fallen beim Lesen weg
OLD_TASK = {"task": "Den Glider als Modell aufbauen", "notes": "Fahrwerk diesmal weglassen", "kind": "new",
            "parts": ["materials", "geometry", "rig", "look", "quatsch"], "stage": "complete",
            "target": "Houdini (prozedural)", "workflow": "build", "fidelity": {"meshes": "exact"}}


def _md(sc, folder=None):
    folder = folder or tempfile.mkdtemp()
    path = os.path.join(folder, "brief.md")
    brief.write_markdown(brief.analyse(sc), [], path, "t")
    return open(path, encoding="utf-8").read()


def _core(md):
    return md[md.index("## Core"):md.index(brief.READ_SECTION)]


def test_alte_auftraege_behalten_nur_was_der_dialog_noch_setzt(h: H):
    assert brief.task_clean(OLD_TASK) == {"task": OLD_TASK["task"], "notes": OLD_TASK["notes"], "parts": ["look"]}
    assert brief.task_clean({"kind": "discuss", "parts": ["look"]}) == {"kind": "discuss"}, "Besprechen ohne Look"
    assert brief.task_clean({"task": "  ", "kind": "revise"}) == {}
    sc = _scene(h)
    sc.brief_task = brief.task_clean(OLD_TASK)
    base = tempfile.mkdtemp()
    assert Scene.from_dict(sc.to_dict(base), base).brief_task == sc.brief_task


def _project(sc, folder=None):
    """brief.md und project.md wie beim Bau-Export (ohne Bilder): liefert (brief.md, project.md)."""
    from sketch_machine import brief_v4
    folder = folder or tempfile.mkdtemp()
    data = brief.analyse(sc)
    ctx = brief.write_markdown(data, [], os.path.join(folder, "brief.md"), "t")
    brief_v4.write_project(data, "t", folder, ctx)
    return (open(os.path.join(folder, "brief.md"), encoding="utf-8").read(),
            open(os.path.join(folder, brief_v4.PROJECT_FILE), encoding="utf-8").read())


def test_bau_brief_kopf_und_projekt_dokument(h: H):
    """Paket v4: brief.md ist Inhalt (Notizen, Szene), Ziel, Rundenkarte und Auftrag stehen in project.md; der alte
    Kern (core.md) entfällt beim Bau-Brief."""
    sc = _scene(h)
    sc.brief_task = {"task": "Flügel bauen", "notes": "  Fahrwerk diesmal ignorieren\n\nPriorität: Gelenke  "}
    folder = tempfile.mkdtemp()
    md, project = _project(sc, folder)
    assert "## Core" not in md and md.index("`project.md`") < md.index(brief.READ_SECTION) < md.index("## Overview")
    assert not os.path.isfile(os.path.join(folder, brief.CORE_FILE))
    assert "**In one sentence:** Flügel bauen" in project and "proposed from the task: Flügel bauen" in project
    assert "> Fahrwerk diesmal ignorieren\n>\n> Priorität: Gelenke\n" in project
    assert "a creature, a place or a whole scene" in project and "**It is a prompt, not a finished spec.**" in project
    assert "`SET: level=scout|study|final`" in project and "key `level`" in project
    assert "`review/round_report.md`" in project, "Fertig-Kriterien des Ziels"
    for old in ("Stage:", "Parts of this task", "Software / environment", "### First round", "Goals and checks",
                "## How to work with the artist"):
        assert old not in md, f"alter Kern- bzw. Regeltext: {old}"


def test_erste_runde_im_projekt_dokument(h: H):
    sc = _scene(h)
    md, project = _project(sc)
    assert "set no task sentence on export – the first round works out the goal" in project
    first = project[project.index("## First round"):]
    assert "`views/hero_*.png`" in first and "`notes/board_N#.png`" in first and "how many you opened" in first
    assert "it does not replace opening the picture" in first, "Unterschrift ersetzt das Hinschauen nicht"
    assert "write_clarified" in first
    assert "No focus and no binding set in Mule: the first round fills this map" in project
    assert "ask in the first round which software is at hand" in project, "Werkzeuge: Global-Notiz oder Frage"
    path = brief.BIBLE.replace(os.sep, "/")
    assert f"`{path}`" in project and os.path.isfile(brief.BIBLE)


def test_paket_im_brief_ordner_und_arbeitsordner(h: H):
    """Export kopiert das Paket (Regeln, Stufen, Dirigent, Rollen, Hooks, Agent-Typen) in den Brief-Ordner und legt
    den Arbeitsordner daneben an (Sichtkarte als Werkzeug); gate.conf und settings.json mit echten Pfaden. Läuft dort
    schon ein Lauf, bleiben Regeln und Hooks unangetastet."""
    import json
    from sketch_machine import brief_v4
    root = tempfile.mkdtemp()
    folder = os.path.join(root, "hafen_brief")
    os.makedirs(folder)
    with open(os.path.join(folder, brief.CORE_FILE), "w", encoding="utf-8") as fh:
        fh.write("alter Kern")
    sc = _scene(h)
    files = brief.export(sc, h.v, folder, "hafen")
    work = os.path.join(root, "work_hafen")
    assert brief_v4.work_dir(folder) == work and os.path.isdir(os.path.join(work, "review"))
    for f in ("rules.md", "levels.md", "conductor.md", "project.md", "CLAUDE.md", "roles/builder.md",
              "roles/viewer.md", ".claude/hooks/gate.ps1", ".claude/hooks/pretool_build.sh", ".claude/hooks/gate.conf",
              ".claude/agents/qc.md", ".claude/settings.json"):
        assert f in files and os.path.isfile(os.path.join(folder, f)), f
    assert not os.path.exists(os.path.join(folder, ".claude", "tests")), "Hook-Tests bleiben im Repo"
    assert not os.path.isfile(os.path.join(folder, brief.CORE_FILE)), "alter Kern entfernt"
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
        assert b"\r\n" not in fh.read(), "Shell-Hooks mit LF"
    # laufender Lauf: Regeln bleiben, Inhalt wird neu
    os.makedirs(os.path.join(work, "review", "gate"))
    open(os.path.join(work, "review", "gate", "agents.log"), "w").close()
    with open(os.path.join(folder, "rules.md"), "w", encoding="utf-8") as fh:
        fh.write("Regeln des laufenden Laufs")
    assert brief_v4.running(folder)
    files = brief.export(sc, h.v, folder, "hafen")
    assert open(os.path.join(folder, "rules.md"), encoding="utf-8").read() == "Regeln des laufenden Laufs"
    assert "rules.md" not in files and "project.md" in files and "brief.md" in files


def _text_note(title, *texts):
    import numpy as np
    from sketch_machine.scene import Note
    return Note(title, np.array([1.0, 2.0, 0.0]),
                board={"items": [{"kind": "text", "x": 0, "y": 80 * k, "text": t} for k, t in enumerate(texts)]})


def test_review_runde_nur_neues(h: H):
    """Review-Runde (Künstler 2026-11-15): „Baut auf <Brief-Ordner>“ exportiert ohne Ordnerwahl nach
    <Brief>/review_rounds/review_NN_<Datum>/ – kein brief.md, ein älteres Paket wird erneuert; review.md nennt nur, was sich an
    den Notizen seit dem letzten Export geändert hat (Notizen über uid, ältere Exporte über die Überschrift), dazu der
    aktuelle Stand. Der laufende Lauf bleibt unberührt; die nächste Runde vergleicht mit der vorigen."""
    import json
    from sketch_machine import brief_v4, review_round
    root = tempfile.mkdtemp()
    base = os.path.join(root, "alpaka_brief")
    sc = _scene(h)
    sc.notes += [_text_note("Rad", "Rad größer"), _text_note("Sattel", "Sattel aus Leder"),
                 _text_note("Lenker", "Lenker gerade")]
    brief.export(sc, h.v, base, "alpaka")
    gate = os.path.join(base, ".claude", "hooks", "gate.conf")
    stamp = os.path.getmtime(gate), open(os.path.join(base, "brief.md"), encoding="utf-8").read()
    # älterer Export ohne uid: Notizen werden über die Überschrift wiedergefunden
    data = json.load(open(os.path.join(base, "brief.json"), encoding="utf-8"))
    for n in data["notes"]:
        n.pop("uid", None)
    json.dump(data, open(os.path.join(base, "brief.json"), "w", encoding="utf-8"))
    # Review: Rad geändert, Sattel gelöscht, Pedal neu, Lenker gleich
    rad = next(n for n in sc.notes if n.title == "Rad")
    rad.board = {"items": [{"kind": "text", "x": 0, "y": 0, "text": "Rad deutlich größer, 26 Zoll"}]}
    sc.notes = [n for n in sc.notes if n.title != "Sattel"] + [_text_note("Pedal", "Pedale aus Alu")]
    target = review_round.next_folder(base)
    assert os.path.dirname(target) == os.path.join(base, review_round.ROUNDS_DIR)
    assert os.path.basename(target).startswith("review_01_") and review_round.round_number(target) == 1
    assert review_round.base_of(target) == os.path.abspath(base) and review_round.is_brief(target)
    files = brief.export(sc, h.v, target, "alpaka", review_round=True)
    assert "review.md" in files and os.path.isfile(os.path.join(target, "scene.usd"))
    for f in ("brief.md", "rules.md", "CLAUDE.md", "project.md", ".claude", ".mcp.json"):
        assert not os.path.exists(os.path.join(target, f)), f"keine Regeln, kein neuer Brief: {f}"
    assert not os.path.exists(brief_v4.work_dir(target)), "kein Arbeitsordner"
    md = open(os.path.join(target, "review.md"), encoding="utf-8").read()
    assert "not a new brief and not a new run" in md
    new, changed = md[md.index("## New notes"):md.index("## Changed notes")], md[md.index("## Changed notes"):]
    assert "„Pedal“" in new and "Pedale aus Alu" in new and "„Rad“" not in new
    assert "„Rad“" in changed and "Rad deutlich größer, 26 Zoll" in changed and "> Rad größer" in changed
    assert "## Notes no longer in the scene (1)" in md and "„Sattel“" in md and "revokes nothing" in md
    assert "Unchanged since the last export:" in md and "„Lenker“" in md.split("Unchanged since")[1]
    assert (os.path.getmtime(gate), open(os.path.join(base, "brief.md"), encoding="utf-8").read()) == stamp,         "laufender Lauf unberührt"
    # zweite Runde ohne Änderung: vergleicht mit Runde 1
    target2 = review_round.next_folder(base)
    assert review_round.round_number(target2) == 2
    brief.export(sc, h.v, target2, "alpaka", review_round=True)
    md2 = open(os.path.join(target2, "review.md"), encoding="utf-8").read()
    assert "## No changed notes" in md2 and "review_01_" in md2
    assert "rules were updated" not in md and "rules were updated" not in md2, "gleiches Paket: nichts erneuert"
    # älteres Paket im laufenden Brief (Künstler 2026-11-16): die Review-Runde bringt das neue mit, Einstellungen bleiben
    pv = os.path.join(base, ".claude", "package_version")
    open(pv, "w", encoding="utf-8").write("v4.8\n")
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
        open(os.path.join(brief_v4.PACKAGE_DIR, "rules.md"), encoding="utf-8").read(), "neue Regeln im Brief"
    assert open(pv, encoding="utf-8").read().strip() == brief_v4.VERSION
    conf3 = open(gate, encoding="utf-8").read()
    assert "LEVEL=final" in conf3 and "WORK=" in conf3 and "STOP_AT=" in conf3, "Einstellungen bleiben, neue Schlüssel"
    assert open(local, encoding="utf-8").read() == "LEVEL=final\n" and os.path.isfile(work_tool)
    assert open(os.path.join(base, "brief.md"), encoding="utf-8").read() == stamp[1], "Inhalt bleibt"
    # Kennung der Notiz bleibt über Speichern und Laden
    path = os.path.join(root, "s.sketch.json")
    sc.save(path)
    loaded, _ = Scene.load(path)
    assert [n.uid for n in loaded.notes] == [n.uid for n in sc.notes]


def test_review_runde_aus_der_app(h: H):
    """Gespeicherter Auftrag mit „Baut auf“: Export ohne Dialog (MCP export_brief) wird eine Review-Runde, Geklärtes
    gehört danach in den Brief des laufenden Laufs; ohne Brief dort eine Fehlermeldung statt eines Ordners."""
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
        sc.brief_task = {"based_on": os.path.join(root, "gibtsnicht")}
        try:
            h.w.export_brief_to()
            assert False, "ohne Brief keine Runde"
        except ValueError as exc:
            assert "brief.json" in str(exc)
    finally:
        sc.brief_task = keep


def test_review_runde_im_dialog(h: H):
    """Dialog: „Baut auf“ zeigt, wohin die Runde geht (ohne Ordnerwahl); der Satz für den Chat ist ein
    Fortsetzungs-Satz ohne Hook-Prüfung. Kein Brief dort, „Nur besprechen“ oder leer: normaler Export."""
    from sketch_machine import review_round
    root = tempfile.mkdtemp()
    base = os.path.join(root, "a_brief")
    os.makedirs(base)
    with open(os.path.join(base, "brief.json"), "w", encoding="utf-8") as fh:
        fh.write("{}")
    dlg = BriefDialog(None, {"based_on": base}, 0, None, "a", os.path.join(root, "neu_brief"))
    assert dlg.values()["based_on"] == base
    target = review_round.next_folder(base)
    assert dlg.round_folder() == target and os.path.normpath(target) in dlg.based_on_info.text()
    prompt = dlg.prompt.toPlainText()
    assert os.path.normpath(target) in prompt and "review.md" in prompt and "GATE STATUS" not in prompt
    os.makedirs(target)  # eine Runde gibt es schon: die nächste ist 02
    dlg.based_on.setText(base)
    dlg._sync()
    assert "review_02_" in dlg.based_on_info.text()
    dlg.discuss.setChecked(True)
    assert dlg.round_folder() is None and "review.md" not in dlg.prompt.toPlainText()
    dlg.discuss.setChecked(False)
    dlg.based_on.setText(os.path.join(root, "leer"))
    assert dlg.round_folder() is None and "brief.json" in dlg.based_on_info.text()
    assert "GATE STATUS" in dlg.prompt.toPlainText(), "normaler Bau-Brief"
    dlg.based_on.setText("")
    assert "based_on" not in dlg.values() and not dlg.based_on_info.text()


def test_notizen_spaeterer_runden_in_context(h: H):
    """Mit Fokus: Notizen, die nur auf Teile außerhalb des Fokus zeigen, stehen in context.md; ohne Fokus alles im
    Brief."""
    sc = _scene(h)
    data = brief.analyse(sc)
    targets = [(n["id"], (n["anchors"][0].get("target") or {}).get("id")) for n in data["notes"] if n["anchors"]]
    assert targets, "Testszene braucht eine Notiz mit Ziel"
    assert brief._later_notes(data) == set(), "ohne Fokus alles im Brief"
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
    assert nid not in brief._later_notes(data), "Notiz auf ein Fokus-Teil bleibt im Brief"
    brief.write_markdown(dict(data, focus=None), [], os.path.join(folder, "brief.md"), "t")
    assert not os.path.isfile(os.path.join(folder, "context.md")), "veraltete context.md entfernt"


def test_allgemein_fuer_jedes_objekt(h: H):
    md = _md(_scene(h))
    assert "where its character is irregular (bark, rock, skin" in md and "is not intent – smooth it" not in md
    assert "where it may be a one-off (damage, a scar" in md and "wing joints" not in md
    assert "develop the rest – main bodies, cross-sections, transitions, connections" in md


def test_nur_besprechen(h: H):
    sc = _scene(h)
    sc.brief_task = {"kind": "discuss"}
    md = _md(sc)
    core = _core(md)
    assert "**Do not build anything.**" in core and "### First round" not in core and "Work list" not in core
    assert f"    1. {brief.CLARIFY[0]}" in core, "Klärungsfragen als Leitfaden"
    how = md[md.index("## How to work with the artist"):]
    assert "Review sheets" not in how and "bible" not in how and "**Feedback**" in how


def test_verbindlichkeit_je_objekt_im_outliner(h: H):
    """Outliner-Spalte „Brief“: Verbindlichkeit an Null (vererbt) oder Objekt, im Kern unter dem Auftrag;
    gespeichert, ein Undo-Schritt."""
    from sketch_machine.outliner import BRIEF, BRIEF_ROLE
    sc = _scene(h)
    group = next(n for n in sc.nulls if n.name == "Flügel")
    wing = next(m for m in sc.meshes if m.name == "Wing_L")
    h.v.set_binding([group.id], "fixed")
    assert sc.binding_of(wing) == ("fixed", group), "Mesh erbt vom Null"
    data = brief.analyse(sc)
    assert data["meshes"][0]["binding"] == "fixed"
    assert data["bindings"] == [{"id": "H1", "name": "Flügel", "level": "fixed", "group": True}]
    project = _project(sc)[1]
    assert "| Flügel | H1 and everything in it | – (first round) | fixed |" in project, "Rundenkarte"
    h.v.set_binding([wing.id], "guide")
    assert sc.binding_of(wing) == ("guide", wing), "eigene Stufe schlägt die des Nulls"
    base = tempfile.mkdtemp()
    again = Scene.from_dict(sc.to_dict(base), base)
    assert [n.binding for n in again.nulls] == ["fixed"] and again.meshes[0].binding == "guide"
    sc.undo()  # Undo stellt Kopien her: Objekte neu holen
    wing = next(m for m in sc.meshes if m.name == "Wing_L")
    assert wing.binding is None and sc.binding_of(wing)[0] == "fixed"
    h.app.processEvents()
    out = h.w.outliner
    out.rebuild()
    cells = {it.text(0): it.data(BRIEF, BRIEF_ROLE) for it in out.findItems("*", Qt.MatchWildcard | Qt.MatchRecursive)}
    fixed = tr(brief.TASK_LEVELS["fixed"][0]).split(" – ")[0]
    assert cells["Flügel"] == (fixed, True) and cells["Wing_L"] == ("↳ " + fixed, False), cells
    assert cells["Stroke 1"] is None, "Stroke-Objekte haben kein Brief-Feld"


def test_dialog_werte(h: H):
    task = brief.task_clean(OLD_TASK)
    dlg = BriefDialog(None, task, selected=0)
    assert dlg.values() == task, "Dialog zeigt den gespeicherten Auftrag"
    assert dlg.look.isChecked() and dlg.look.isEnabled()
    dlg.discuss.setChecked(True)
    assert not dlg.look.isEnabled() and dlg.values() == {"task": task["task"], "notes": task["notes"],
                                                         "kind": "discuss"}
    dlg._clear()
    assert dlg.values() == {}
    picked = BriefDialog(None, {}, selected=3)
    assert picked.layout().isRowVisible(picked.focus) and not picked.focus.isChecked()
    assert not dlg.layout().isRowVisible(dlg.focus), "ohne Auswahl kein Umfang"


def test_dialog_schliesst(h: H):
    """v0.99.68 hatte ein Feld self.done – das überdeckte QDialog.done(), Cancel/X/Esc schlossen nicht mehr."""
    from PySide6.QtCore import QObject
    from PySide6.QtWidgets import QDialog
    dlg = BriefDialog(None, brief.task_clean(OLD_TASK), selected=2)
    shadowed = [name for name, v in vars(dlg).items() if isinstance(v, QObject) and hasattr(QDialog, name)]
    assert not shadowed, f"Felder überdecken Qt-Methoden: {shadowed}"
    dlg.show()
    dlg.reject()
    assert not dlg.isVisible() and dlg.result() == QDialog.Rejected


def test_dialog_zeigt_offenes_vor_dem_export(h: H):
    """Offenes aus der Szene steht im Dialog, nicht im Brief; ohne Ziel und Notizen ein Hinweis."""
    from sketch_machine.scene import NoteAnchor
    import numpy as np
    sc = _scene(h)
    sc.notes[0].anchors.append(NoteAnchor(np.array([0.0, 30.0, 0.0])))
    checks = brief.precheck(sc, brief.analyse(sc))
    assert any(p.startswith("N1 Flügel: ") and " 2 " in p for p in checks["points"]), checks["points"]
    assert "flügel" in checks["text"] and "wing_l" in checks["text"], "Notiztitel und Namen zählen"
    assert brief.part_hints({}, "") == [tr("Kein Auftragssatz und keine Notizen – die KI kennt das Ziel nicht")]
    assert not brief._mentions("original", ["rig"]) and brief._mentions("rigging, flügelgelenk", ["rig", "gelenk"])
    dlg = BriefDialog(None, {"parts": ["look"]}, 0, checks)
    assert tr("<b>Vor dem Export prüfen ({0}):</b><br>").format(2) in dlg.hints.text() and not dlg.hints_box.isHidden()
    dlg.notes.setPlainText("Stimmung: staubig, warmes Licht")
    assert tr("<b>Vor dem Export prüfen ({0}):</b><br>").format(1) in dlg.hints.text(), "Hinweise folgen dem Text live"


def test_autoprompt_im_dialog(h: H):
    """Autoprompt: steht im Feld, folgt den Einstellungen (Look-Vorstufe), eigene Änderungen bleiben; beim Export der
    tatsächliche Ordner statt des vorgeschlagenen."""
    dlg = BriefDialog(None, {}, 0, None, "glider", r"C:\szenen\glider_brief")
    text = dlg.prompt.toPlainText()
    assert "glider" in text and r"(C:\szenen\glider_brief)" in text and "write_clarified" in text and "set_hero_prompt" not in text
    assert "conductor.md" in text and "project.md" in text and "GATE STATUS" in text and "Core" not in text
    assert "Stufe" in text, "Stufe ganz unten in der ersten Nachricht"
    other = BriefDialog(None, {"kind": "discuss"}, 0, None, "glider", r"C:\szenen\glider_brief")
    talk = other.prompt.toPlainText()
    assert "Core" in talk and "GATE STATUS" not in talk, "Nur besprechen: alter kurzer Kern"
    dlg.look.setChecked(True)
    assert "set_hero_prompt" in dlg.prompt.toPlainText(), "folgt der Look-Vorstufe"
    # Hafen-Test 2026-11-12: Sitzung lief im Projektordner statt im Brief-Ordner, die Hooks fehlten. Der Satz verlangt
    # den Brief-Ordner zuerst und nennt ihn zweimal (Ort der Sitzung, Brief).
    assert dlg.prompt_text(r"D:\neu\glider_brief").count(r"D:\neu\glider_brief") == 2
    assert text.index("Brief-Ordner") < text.index("GATE STATUS"), "Ordnerprüfung vor dem Gate"
    if os.sep == "\\":
        assert r"C:\x\05_built\b_brief" in dlg.prompt_text("C:/x/05_built\\b_brief"), "Pfad ohne gemischte Schrägstriche"
    dlg.prompt.setPlainText(r"Eigener Text für C:\szenen\glider_brief")
    dlg.look.setChecked(False)
    assert dlg.prompt.toPlainText().startswith("Eigener Text"), "eigene Änderung bleibt"


def test_geklaertes_im_dialog(h: H):
    """Zeile „Geklärt mit der KI“: nur mit Inhalt, Ansehen als Text, Löschen erst beim Export (umschaltbar)."""
    plain = BriefDialog(None, {})
    assert not plain.layout().isRowVisible(plain.clarified_label.parentWidget())
    c = {"summary": "Ein Glider.", "answers": [{"question": "Klappbar?", "answer": "Ja"},
                                               {"question": "Farbe?", "answer": "decide"}]}
    dlg = BriefDialog(None, {}, clarified=c)
    assert dlg.layout().isRowVisible(dlg.clarified_label.parentWidget())
    assert dlg.clarified_label.text().startswith(tr("{0} Punkt{1}").format(2, "e") + tr(" und eine Zusammenfassung"))
    assert dlg.clarified_text() == "Ein Glider.\n\n• Klappbar? → Ja\n• Farbe? → " + tr("entscheidet die KI")
    dlg.clarified_drop.setChecked(True)
    assert dlg.clear_clarified and dlg.clarified_drop.text() == tr("Behalten")
    dlg.clarified_drop.setChecked(False)
    assert not dlg.clear_clarified

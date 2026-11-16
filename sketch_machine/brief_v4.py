"""Working-method package v4 in the brief export (glider runs 004-006, handover 2026-11-09): per export Mule writes
the project document project.md (content: goal, round map, assignment, hero cameras) and copies the fixed, versioned
package alongside (rules.md, levels.md, conductor.md, roles/, .claude/ with hooks and agent types, tools/vis_map, tools/sketch_overlay).
Work folder next to the brief (work_<name>): the run works there (review/, tools/, export/ ...), the hooks find
it via gate.conf (WORK) and settings.json (additionalDirectories).

If a run is already going there (review/gate/agents.log in the work folder), package, hooks and gate.conf
stay untouched - otherwise rules would change mid-run; only content (brief.md, project.md, images) is renewed."""
import json
import os
import shutil

from . import paths

PACKAGE_DIR = os.path.join(paths.ROOT, "sketch_machine", "brief_package")
VERSION = "v5.0"  # increment on every change to the package - appears in project.md and .claude/package_version
PROJECT_FILE = "project.md"
PACKAGE_FILES = ("rules.md", "levels.md", "conductor.md")
BRIEF_NAME = "<project name>"
# gate.conf defaults for Mule exports; changeable live via the artist line "SET: <key>=<value>" (level, max_builders,
# pause, max_weekly). 67 % in the template applied only to test 006.
GATE_DEFAULTS = {"REMIND_EVERY": "30", "MAX_BUILDERS": "1", "SHARED_FILES": "", "LEVEL": "study", "MAX_WEEKLY": "90",
                 "MAX_5H": "90", "HANDOVER_AT": "500000", "STOP_AT": "", "PAUSE": ""}
BINDING_WORDS = {"fixed": "fixed", "exact": "authoritative", "basis": "basis", "guide": "guide"}


def _slash(p):
    return os.path.abspath(p).replace("\\", "/")


# Programs the hooks run with, as written in the package's settings.json (Windows standard paths)
WIN_BASH = "C:/Program Files/Git/bin/bash.exe"
WIN_PS = "C:/WINDOWS/System32/WindowsPowerShell/v1.0/powershell.exe"


def hook_programs():
    """(bash, powershell, missing) for this machine: Git Bash and Windows PowerShell on Windows (also when Git is
    not in the standard folder), bash and PowerShell 7 (pwsh) elsewhere. missing names what is not installed –
    without it the gate hooks fail and the build brief only runs by the rules in the chat."""
    missing = []
    if os.name == "nt":
        roots = [os.environ.get(k) for k in ("ProgramW6432", "ProgramFiles", "ProgramFiles(x86)")]
        cands = [os.path.join(r, "Git", "bin", "bash.exe") for r in roots if r]
        if os.environ.get("LOCALAPPDATA"):
            cands.append(os.path.join(os.environ["LOCALAPPDATA"], "Programs", "Git", "bin", "bash.exe"))
        git = shutil.which("git")  # …/Git/cmd/git.exe → …/Git/bin/bash.exe (not System32\bash.exe = WSL)
        if git:
            cands.append(os.path.join(os.path.dirname(os.path.dirname(git)), "bin", "bash.exe"))
        bash = next((c for c in cands if os.path.isfile(c)), None)
        if bash is None:
            bash = WIN_BASH
            missing.append("Git for Windows (bash)")
        ps = os.path.join(os.environ.get("SystemRoot", "C:/WINDOWS"), "System32", "WindowsPowerShell", "v1.0",
                          "powershell.exe")
        if not os.path.isfile(ps):
            ps = shutil.which("pwsh") or WIN_PS
            if not os.path.isfile(ps):
                missing.append("PowerShell")
        return bash.replace("\\", "/"), ps.replace("\\", "/"), missing
    bash = shutil.which("bash") or "/bin/bash"
    ps = shutil.which("pwsh")
    if ps is None:
        ps = "pwsh"
        missing.append("PowerShell 7 (pwsh)")
    return bash, ps, missing


def work_dir(folder):
    """Work folder next to the brief: .../hafen_brief -> .../work_hafen, .../hafen -> .../work_hafen."""
    folder = os.path.abspath(folder)
    name = os.path.basename(folder.rstrip("\\/"))
    if name.lower().endswith("_brief") and len(name) > 6:
        name = name[:-6]
    return os.path.join(os.path.dirname(folder), f"work_{name}")


def running(folder):
    """Has a run with agents already begun in the work folder?"""
    return os.path.isfile(os.path.join(work_dir(folder), "review", "gate", "agents.log"))


def _copy(src, dst):
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copyfile(src, dst)


def _same(a, b):
    return os.path.normcase(os.path.abspath(a)).rstrip("\\/") == os.path.normcase(os.path.abspath(b)).rstrip("\\/")


def _write_package(folder, scene_name, work, fresh_conf):
    """Rules, roles, CLAUDE.md, .claude (agent types, hooks, settings), tools into the work folder.
    fresh_conf: write gate.conf anew (new brief) - otherwise the run's settings stay."""
    written = []
    for f in PACKAGE_FILES:
        _copy(os.path.join(PACKAGE_DIR, f), os.path.join(folder, f))
        written.append(f)
    for f in sorted(os.listdir(os.path.join(PACKAGE_DIR, "roles"))):
        _copy(os.path.join(PACKAGE_DIR, "roles", f), os.path.join(folder, "roles", f))
        written.append(f"roles/{f}")
    with open(os.path.join(PACKAGE_DIR, "CLAUDE.md"), encoding="utf-8") as fh:
        text = fh.read().replace(BRIEF_NAME, scene_name)
    with open(os.path.join(folder, "CLAUDE.md"), "w", encoding="utf-8") as fh:
        fh.write(text)
    written.append("CLAUDE.md")
    src = os.path.join(PACKAGE_DIR, "_claude")
    for sub in ("agents", "hooks"):
        for f in sorted(os.listdir(os.path.join(src, sub))):
            if f in ("gate.conf", "gate.local.conf"):
                continue
            _copy(os.path.join(src, sub, f), os.path.join(folder, ".claude", sub, f))
            written.append(f".claude/{sub}/{f}")
    conf_path = os.path.join(folder, ".claude", "hooks", "gate.conf")
    if fresh_conf or not os.path.isfile(conf_path):
        conf = dict(GATE_DEFAULTS, WORK=_slash(work))
        keys = ["WORK", *GATE_DEFAULTS]
        with open(conf_path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write("".join(f"{k}={conf[k]}\n" for k in keys))
        written.append(".claude/hooks/gate.conf")
    else:  # running run: settings stay, only new keys are added with their defaults
        with open(conf_path, encoding="utf-8") as fh:
            have = {line.split("=", 1)[0] for line in fh.read().splitlines() if "=" in line}
        missing = [k for k in GATE_DEFAULTS if k not in have]
        if missing:
            with open(conf_path, "a", encoding="utf-8", newline="\n") as fh:
                fh.write("".join(f"{k}={GATE_DEFAULTS[k]}\n" for k in missing))
            written.append(".claude/hooks/gate.conf")
    with open(os.path.join(src, "settings.json"), encoding="utf-8") as fh:
        bash, ps, _missing = hook_programs()
        settings = json.loads(fh.read().replace("__BRIEF__", _slash(folder)).replace(WIN_BASH, bash)
                              .replace(WIN_PS, ps))
    settings.setdefault("permissions", {})["additionalDirectories"] = [_slash(work)]
    with open(os.path.join(folder, ".claude", "settings.json"), "w", encoding="utf-8") as fh:
        json.dump(settings, fh, indent=2, ensure_ascii=False)
    written.append(".claude/settings.json")
    with open(os.path.join(folder, ".claude", "package_version"), "w", encoding="utf-8") as fh:
        fh.write(VERSION + "\n")
    # work folder: tools (visibility map, sketch overlay; Mule files, may be renewed; cache/ stays)
    for sub in ("review", "export", "tools"):
        os.makedirs(os.path.join(work, sub), exist_ok=True)
    tools = os.path.join(PACKAGE_DIR, "tools")
    for name in sorted(os.listdir(tools)):
        tool = os.path.join(tools, name)
        if not os.path.isdir(tool) or name.startswith(("_", ".")):
            continue
        for f in sorted(os.listdir(tool)):
            if os.path.isfile(os.path.join(tool, f)):
                _copy(os.path.join(tool, f), os.path.join(work, "tools", name, f))
    return written


def install(folder, scene_name):
    """Package into the brief folder, create the work folder. Returns (written files relative to the brief, notice
    or None). With a running run: change nothing in the package (notice). Review rounds ("builds on") do not go
    through here, but as feedback into the running run (review_round.py)."""
    work = work_dir(folder)
    if running(folder):
        return [], (f"Im Arbeitsordner {work} läuft schon ein Lauf – Regeln, Rollen und Hooks wurden nicht "
                    "überschrieben, nur Inhalt (brief.md, project.md, Bilder) ist neu.")
    return _write_package(folder, scene_name, work, fresh_conf=True), None


def _version_key(v):
    try:
        return tuple(int(x) for x in v.strip().lstrip("v").split("."))
    except ValueError:
        return (0,)


def changes_since(old):
    """Sections from PACKAGE_CHANGES.md that are newer than old (Markdown, without the file's header lines)."""
    try:
        with open(os.path.join(PACKAGE_DIR, "PACKAGE_CHANGES.md"), encoding="utf-8") as fh:
            text = fh.read()
    except OSError:
        return ""
    out, keep = [], False
    for line in text.splitlines():
        if line.startswith("## v"):
            keep = _version_key(line[3:]) > _version_key(old or "v0")
        if keep:
            out.append(line)
    return "\n".join(out).strip()


def update_package(folder, scene_name):
    """Review round into a running brief (user, 2026-11-16): if the package in the brief folder is older than the one
    from Mule, the new package goes in - rules, roles, agent types, hooks, tools. The run's settings
    (gate.conf, gate.local.conf), work folder and content stay. -> {"old", "new", "files"} or None."""
    if not os.path.isdir(os.path.join(folder, ".claude", "hooks")):
        return None  # no v4 brief (e.g. discussion): no package
    vf = os.path.join(folder, ".claude", "package_version")
    old = open(vf, encoding="utf-8").read().strip() if os.path.isfile(vf) else ""
    if old and _version_key(old) >= _version_key(VERSION):
        return None
    files = _write_package(folder, scene_name, work_dir(folder), fresh_conf=False)
    return {"old": old or "unknown", "new": VERSION, "files": files}


def remove_old_core(folder):
    """Remove the core.md of an older export (old core) - it would contradict the package."""
    from .brief import CORE_FILE
    p = os.path.join(folder, CORE_FILE)
    if os.path.isfile(p):
        os.remove(p)


def project_md(data, scene_name, folder, has_context=False):
    """Project document (template project_template.md), filled from assignment, focus, bindingness, hero cameras and
    note boards. What Mule does not know it names as a matter for the first round - nothing is claimed."""
    task = data.get("task") or {}
    focus = data.get("focus") or {}
    bindings = {b["id"]: b for b in data.get("bindings") or ()}
    md = [f"# Project document – {scene_name}  (written by Mule on every export; everything here is content, the "
          f"process is in the package {VERSION})",
          "This is a Sketch Brief from Mule, a 3D sketching tool. What is sketched may be a thing, a creature, a place "
          "or a whole scene; „the object“ means any of them. **It is a prompt, not a finished spec.** The process is "
          "in `rules.md`, `levels.md`, `conductor.md` and `roles/`; `brief.md` holds the notes of this round and the "
          "scene" + ("; `context.md` the notes of later rounds (intent only, no work lines)." if has_context else "."),
          (f"Work folder: `{_slash(work_dir(folder))}` (review/, tools/, export/ – everything the run writes goes there)."
           if folder else "Live from Mule (no export folder): the package files and the work folder come with an "
           "export."),
          "", "## Goal of this round – what „done“ means",
          "- **Goal:** " + (f"proposed from the task: {task['task']} – " if task.get("task") else "")
          + "the artist confirms it as key `goal`.",
          "- **Level:** the level in gate.conf (Mule's default `study`), confirmed as key `level`; the artist changes it "
          "any time with a line `SET: level=scout|study|final`.",
          "- **Done only when all hold, each shown with a picture:**",
          "  1. every work line of the goal passes its „fails if …“ criterion in its camera and state;",
          "  2. every unit's picture targets are reached, or its two QC rounds are used up and the open targets are "
          "listed;",
          "  3. no veto is open, and the last QC of every unit says `VERDICT: PASS` – or, after its rounds are used up "
          "(rule 15), its open points are listed – a failure against the artist's words or drawing is never closed: "
          "it heads the artist's list;",
          "  4. every `DEPART:`, `BREAK:`, open QC point, stand-in decision, open `ASSUMED` entry and open question is listed for "
          "the artist with a picture;",
          "  5. the four-group report is written, and a fresh QC (`UNIT: ROUND`) passed the whole goal in "
          "`review/round_report.md`.",
          "- **When done:** stop and report. Start nothing outside the goal; propose the next step. If the goal cannot "
          "be reached, say which criterion fails, with a picture.",
          "", "## Round map – what this round touches"]
    rows = []
    for s in focus.get("selected") or ():
        b = bindings.get(s["id"])
        rows.append((s["name"], s["id"], BINDING_WORDS[b["level"]] if b else "by kind of mark (rule 10) – confirm"))
    for i, b in bindings.items():
        if not any(r[1] == i for r in rows):
            rows.append((b["name"], i + (" and everything in it" if b["group"] else ""), BINDING_WORDS[b["level"]]))
    if rows:
        md += ["| Artist's word | Ids | Rig joint / control (range) | How binding |", "|---|---|---|---|",
               *[f"| {w} | {i} | – (first round) | {b} |" for w, i, b in rows]]
        if focus:
            md.append(f"- **Focus:** the artist selected these parts for this round "
                      f"({len(focus.get('ids') or ())} ids in all, see „Focus – what to build“ in `brief.md`); build "
                      "only these, the rest is context.")
    else:
        md.append("No focus and no binding set in Mule: the first round fills this map (keys `goal`, `units`, "
                  "`blockout`) with the artist's words, the ids and the rig joints.")
    md += ["- **Binding levels:** fixed = keep exactly · authoritative = form follows within the tolerance of rule 10 "
           "(lines, directions, curves, proportions), construction is free, refining welcome · basis = only for what the "
           "artist calls a placeholder or blockout: silhouette, covered area and placement hold (tolerance from key "
           "`blockout`), construction is free · guide = character only. **Without a binding, the kind of mark decides "
           "(rule 10):** precise lines and modelled surfaces bind their form like `authoritative`, gestures their "
           "character, route lines their ends and order.",
           "- **Main states of motion:** from the rig or the notes, settled in the first round; the level decides "
           "which are checked."]
    cams = data.get("cameras") or []
    if cams and not cams[0].get("default"):
        md.append("- **Hero cameras:** " + ", ".join(f"{c['name']} `{c['image']}`" for c in cams)
                  + " – cameras in `scene.usd` under `/sketch/cameras` and in `brief.json` (`tools/vis_map` reads them "
                  "from there). **Control cameras:** per unit, in its state note.")
    elif cams:
        md.append("- **Hero cameras:** the artist set none – the brief has standard angles (" + ", ".join(
            f"`{c['image']}`" for c in cams) + "). Propose hero cameras in the first round; the visibility map needs "
            "them. **Control cameras:** per unit, in its state note.")
    pn = data.get("project_note") or {}
    md += ["- **Tools and methods of the artist:** " + ("as the project note in `brief.md` or the task notes say; " if pn.get("text") or task.get("notes")
                                                         else "")
           + "if it names none, ask in the first round which software is at hand and what it is used for (rule 12).",
           "- **Delivered:** formats, where, which files are never overwritten – settled in the first round.",
           "- **Precedence:** sketch and notes > photos in the notes > generated images.",
           f"- **Workflow bible** of earlier Mule projects: `{_bible()}` – suggestions, never rules; builders may look "
           "up their topic there (rule 12 first).",
           "", "## Task (set by the artist on export)",
           f"**In one sentence:** {task['task']}" if task.get("task") else
           "The artist set no task sentence on export – the first round works out the goal from the notes."]
    if task.get("notes"):
        md += ["", "**Artist's notes for this task** (they win over a note in the scene; point out the conflict):",
               *[f"> {l}" if l.strip() else ">" for l in task["notes"].splitlines()]]
    from .brief import TASK_LOOK
    if TASK_LOOK in (task.get("parts") or []):
        md += ["", "**Look images first:** before anything is built, a helper generates images from the hero cameras "
               "and the artist picks (see „Look images“ in `brief.md`)."]
    boards = [n for n in data.get("notes", []) + [pn] if n.get("board") and not n.get("later")]
    secs = sum(len(n.get("sections") or []) for n in boards)
    uncaptioned = sum(len(n.get("uncaptioned") or ()) for n in data.get("notes", []) + [pn])
    videos = sum(len(n.get("videos") or ()) for n in data.get("notes", []) + [pn])
    md += ["", "## First round – pictures to open",
           "- the hero pictures `views/hero_*.png`" + (f" ({len(cams)})" if cams else ""),
           f"- the whole-board pictures `notes/board_N#.png` ({len(boards)}) and the section pictures "
           f"`notes/board_N#_k.png` ({secs}) of the notes in `brief.md`"
           + ("; the boards of `context.md` when their unit starts" if has_context else ""),
           "- one line per section: what you understand there; say in the first message how many you opened.",
           "- **Captions:** a caption („…“) is the artist's word on what a picture stands for, not a full description "
           "– it does not replace opening the picture."
           + (f" {uncaptioned} reference picture(s) have none: propose one each in the first message (what it stands "
              "for, what matters in it, the part ids); with the Mule tools store the confirmed ones with "
              "set_image_captions." if uncaptioned else ""),
           "- **Picture list** (`review/pictures.md`, kept by the main chat): one line per reference picture once you "
           "opened it in full: the part ids it is about, what it shows that its caption does not say, what follows for "
           "the model. Single pictures are opened in full when their unit starts.",
           *(["- **Videos** (" + str(videos) + "): look at the overview sheets `videos/*_overview.jpg` and say in one "
              "line per video what it shows. Do not cut a video into frames on your own: ask in the first message which "
              "videos need a closer look and what to look for; then read only the frames that answer it (Mule tool "
              "video_frames, otherwise ffmpeg) and name the timestamps."] if videos else []),
           "- With the Mule tools (MCP server `sketch_machine`): store the confirmed first-round answers with "
           "write_clarified – they appear in `brief.md` from then on."]
    return md


def _bible():
    from .brief import BIBLE
    return BIBLE.replace(os.sep, "/")


def write_project(data, scene_name, folder, has_context=False):
    with open(os.path.join(folder, PROJECT_FILE), "w", encoding="utf-8") as fh:
        fh.write("\n".join(project_md(data, scene_name, folder, has_context)) + "\n")
    return PROJECT_FILE

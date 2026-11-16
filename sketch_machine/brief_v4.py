"""Working method of a build brief (glider runs 004-006, handover 2026-11-09; swappable as a recipe since
2026-11-16, recipes.py): per export Mule writes the content and the project document project.md, filled from the
recipe's template, and installs the chosen recipe alongside (Mule's own: rules.md, levels.md, conductor.md, roles/,
.claude/ with hooks and agent types, tools/vis_map, tools/sketch_overlay).
Work folder next to the brief (work_<name>): the run works there (review/, tools/, export/ ...); Mule adds it to
permissions.additionalDirectories of the recipe's .claude/settings.json and offers it to the recipe as {{work_dir}}.

If a run is already going there (the recipe's running_marker, for Mule's own review/gate/agents.log in the work
folder), the recipe stays untouched - otherwise rules would change mid-run; only content (brief.md, project.md,
images) is renewed."""
import json
import os
import re
import shutil

from . import paths, recipes

PACKAGE_DIR = recipes.BUILTIN_DIR
VERSION = recipes.default().version  # Mule's own recipe – raise it in brief_package/recipe.toml
PROJECT_FILE = "project.md"
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


def recipe_of(folder):
    """Recipe a brief folder was made with (lock file; briefs from before recipes: Mule's own). None if the brief
    names none (a discussion brief) or that recipe is no longer installed – never silently another one."""
    lock = recipes.read_lock(folder)
    return recipes.find(lock["id"]) if lock else None


def running(folder, recipe=None):
    """Has a run already begun in the work folder? (marker of the recipe that is in the folder, else of recipe)"""
    r = recipe_of(folder) or recipe or recipes.default()
    try:
        return recipes.is_running(r, folder, work_dir(folder))
    except recipes.RecipeError:
        return False


def _tokens(folder, scene_name, work, recipe):
    bash, ps, _missing = hook_programs()
    return {"project_name": scene_name, "brief_dir": _slash(folder), "work_dir": _slash(work), "bash": bash,
            "powershell": ps, "recipe_id": recipe.id, "recipe_version": recipe.version}


def _write_package(folder, scene_name, work, fresh_conf, recipe):
    """The recipe into brief and work folder (fresh_conf: write its config anew - new brief - otherwise the run's
    settings stay). The work folder always gets review/, export/, tools/."""
    for sub in ("review", "export", "tools"):
        os.makedirs(os.path.join(work, sub), exist_ok=True)
    written = recipes.install(recipe, folder, work, _tokens(folder, scene_name, work, recipe), fresh_conf)
    sp = os.path.join(folder, ".claude", "settings.json")
    if ".claude/settings.json" in written:  # Claude Code: the run may write in the work folder
        with open(sp, encoding="utf-8") as fh:
            settings = json.load(fh)
        settings.setdefault("permissions", {})["additionalDirectories"] = [_slash(work)]
        with open(sp, "w", encoding="utf-8") as fh:
            json.dump(settings, fh, indent=2, ensure_ascii=False)
    old = os.path.join(folder, ".claude", "package_version")  # before recipes; the lock file replaces it
    if os.path.isfile(old):
        os.remove(old)
    return written


def install(folder, scene_name, recipe=None):
    """Recipe into the brief folder, create the work folder. Returns (written files relative to the brief, notice
    or None). With a running run: change nothing (notice). Review rounds ("builds on") do not go through here, but
    as feedback into the running run (review_round.py)."""
    recipe = recipe or recipes.default()
    work = work_dir(folder)
    if running(folder, recipe):
        return [], (f"A run is already active in the work folder {work} - rules, roles and hooks were not "
                    "overwritten, only content (brief.md, project.md, images) is new.")
    return _write_package(folder, scene_name, work, True, recipe), None


def _version_key(v):
    """recipes.version_key, with no number counting as the oldest."""
    return recipes.version_key(v) or (0,)


def changes_since(old, recipe=None):
    """Sections of the recipe's changes file that are newer than old (Markdown, without the file's header)."""
    text = (recipe or recipes.default()).changes_text()
    out, keep = [], False
    for line in text.splitlines():
        if re.match(r"## (v\d|\d+\.\d)", line):  # "## v1.1", "## v1.1 (2026-11-16)", "## 1.1" – not "## 3 things"
            keep = _version_key(line[3:]) > _version_key(old or "v0")
        if keep:
            out.append(line)
    return "\n".join(out).strip()


def update_package(folder, scene_name):
    """Review round into a running brief (user, 2026-11-16): if the recipe in the brief folder is older than the
    installed recipe of the same id, the newer one goes in - never another recipe. The run's settings (config,
    keep files), work folder and content stay. -> {"old", "new", "files", "recipe"} or None."""
    lock = recipes.read_lock(folder)
    if not lock:
        return None  # no build brief (e.g. discussion): nothing to renew
    recipe = recipes.find(lock["id"])
    if recipe is None:
        return None
    old = lock.get("version") or "unknown"
    if old != "unknown" and _version_key(old) >= _version_key(recipe.version):
        return None
    files = _write_package(folder, scene_name, work_dir(folder), False, recipe)
    return {"old": old, "new": recipe.version, "files": files, "recipe": recipe}


def remove_old_core(folder):
    """Remove the core.md of an older export (old core) - it would contradict the package."""
    from .brief import CORE_FILE
    p = os.path.join(folder, CORE_FILE)
    if os.path.isfile(p):
        os.remove(p)


def project_context(data, scene_name, folder, has_context=False, recipe=None):
    """Mule's facts for the recipe's templates (docs/recipes.md) - content only, no process."""
    recipe = recipe or recipes.default()
    task = data.get("task") or {}
    focus = data.get("focus") or {}
    bindings = {b["id"]: b for b in data.get("bindings") or ()}
    rows = []
    for s in focus.get("selected") or ():
        b = bindings.get(s["id"])
        rows.append({"word": s["name"], "ids": s["id"], "group": False,
                     "binding": BINDING_WORDS[b["level"]] if b else ""})
    for i, b in bindings.items():
        if not any(r["ids"] == i for r in rows):
            rows.append({"word": b["name"], "ids": i, "group": bool(b["group"]), "binding": BINDING_WORDS[b["level"]]})
    cams = data.get("cameras") or []
    pn = data.get("project_note") or {}
    boards = [n for n in data.get("notes", []) + [pn] if n.get("board") and not n.get("later")]
    notes = [*(task.get("notes") or "").splitlines()] if task.get("notes") else []
    return {
        "project_name": scene_name, "has_context": bool(has_context), "live": not folder,
        "work_dir": _slash(work_dir(folder)) if folder else "",
        "brief_dir": _slash(folder) if folder else "",
        "recipe": {"id": recipe.id, "name": recipe.name, "version": recipe.version},
        "task_sentence": task.get("task") or "", "task_notes": task.get("notes") or "",
        "task_notes_quoted": "\n".join(f"> {l}" if l.strip() else ">" for l in notes),
        "look": _look(task), "round_map": rows,
        "focus": {"count": len(focus.get("ids") or ()), "parts": [{"id": s["id"], "name": s["name"]}
                                                                   for s in focus.get("selected") or ()]}
        if focus else None,
        "cameras": [{"name": c["name"], "image": c["image"]} for c in cams],
        "cameras_set": bool(cams) and not cams[0].get("default"),
        "cameras_default": bool(cams) and bool(cams[0].get("default")),
        "hero_count": len(cams),
        "artist_tools_noted": bool(pn.get("text") or task.get("notes")),
        "bible": _bible(),
        "boards": len(boards), "board_sections": sum(len(n.get("sections") or []) for n in boards),
        "uncaptioned": sum(len(n.get("uncaptioned") or ()) for n in data.get("notes", []) + [pn]),
        "videos": sum(len(n.get("videos") or ()) for n in data.get("notes", []) + [pn]),
    }


def _look(task):
    from .brief import TASK_LOOK
    return TASK_LOOK in (task.get("parts") or [])


def project_md(data, scene_name, folder, has_context=False, recipe=None):
    """Project document from the recipe's template (lines; empty if the recipe has none)."""
    recipe = recipe or recipes.default()
    text = recipe.render("project", project_context(data, scene_name, folder, has_context, recipe))
    return text.rstrip("\n").split("\n") if text else []


def _bible():
    from .brief import BIBLE
    return BIBLE.replace(os.sep, "/")


def write_project(data, scene_name, folder, has_context=False, recipe=None):
    """project.md, if the recipe has a template for it. -> file name or None."""
    md = project_md(data, scene_name, folder, has_context, recipe)
    if not md:
        return None
    with open(os.path.join(folder, PROJECT_FILE), "w", encoding="utf-8") as fh:
        fh.write("\n".join(md) + "\n")
    return PROJECT_FILE

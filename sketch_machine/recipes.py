"""Brief recipes (2026-11-16): the whole working method of a build brief – rules, roles, hooks, agent types, tools, the
process part of project.md and the sentence for the chat – is a recipe that can be swapped. Mule's own method is the
built-in recipe "default" (sketch_machine/brief_package/); recipes of the user or the community live in the recipe
folder (paths.user_dir()/recipes, or MULE_RECIPES) and are chosen per export in the brief dialog.

The seam: Mule writes the content (brief.md, brief.json, scene.usd, views/, notes/) and offers its facts to the
recipe's templates; everything about how the AI works comes from the recipe. Format: docs/recipes.md.

A recipe is a folder with recipe.toml:
- [files]: recipe path → "brief/…" (brief folder) or "work/…" (work folder next to it); a trailing "/" copies a folder.
  In copied text files the tokens {{project_name}}, {{brief_dir}}, {{work_dir}}, {{bash}}, {{powershell}},
  {{recipe_id}}, {{recipe_version}} are filled in; nothing else is touched.
- [templates]: Mustache templates Mule fills with its facts (project, brief_head, start, review_start, review_intro,
  package_update); "start.md" may have language variants "start.de.md".
- [config]: a key=value file written fresh for a new brief and only extended in a running run (keys of the artist stay).
The brief folder gets a lock file (LOCK_FILE) naming recipe, version and digest; review rounds renew from the same
recipe, never from another one."""
import hashlib
import json
import os
import re
import shutil
import tempfile
import tomllib
import zipfile

from . import paths

BRIEF_INTERFACE = 1  # version of what Mule offers recipes (facts, tokens, folders) – docs/recipes.md
DEFAULT_ID = "default"
BUILTIN_DIR = os.path.join(paths.ROOT, "sketch_machine", "brief_package")
RECIPE_FILE = "recipe.toml"
LOCK_FILE = ".mule_recipe.json"
TEMPLATES = ("project", "brief_head", "start", "review_start", "review_intro", "package_update")
TOKENS = ("project_name", "brief_dir", "work_dir", "bash", "powershell", "recipe_id", "recipe_version")
HARNESSES = ("claude-code", "any")
# what Mule writes into the brief folder itself – a recipe may not put files there (compared without case: Windows)
MULE_FILES = {"brief.md", "brief.json", "project.md", "context.md", "core.md", "scene.usd", "review.md",
              "clarified_history.md", ".mcp.json", ".codex", "views", "notes", "shots", "videos", "gen",
              "review_rounds", ".mule_recipe.json"}
_SKIP = {"__pycache__", ".git", ".DS_Store", "Thumbs.db"}
_TEXT = (".md", ".json", ".sh", ".ps1", ".psm1", ".conf", ".txt", ".toml", ".py", ".yml", ".yaml", ".cmd", ".bat",
         ".js", ".ts", ".ini", ".cfg")
_ID = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,63}$")
MAX_ZIP = 50 * 1024 * 1024  # unpacked size of an imported recipe


class RecipeError(Exception):
    pass


class Recipe:
    """A loaded recipe; problems lists what makes it unusable (then it is shown, but cannot be chosen)."""

    def __init__(self, path, builtin=False):
        self.path = os.path.abspath(path)
        self.builtin = builtin
        self.problems = []
        self.meta = {}
        self.files = {}
        self.templates = {}
        self.config_file = None
        self.config_values = {}
        self.keep = []
        try:
            with open(os.path.join(self.path, RECIPE_FILE), "rb") as fh:
                self.meta = tomllib.load(fh)
        except FileNotFoundError:
            self.problems.append(f"no {RECIPE_FILE}")
        except (tomllib.TOMLDecodeError, OSError) as exc:
            self.problems.append(f"{RECIPE_FILE} cannot be read: {exc}")
        m = self.meta
        self.id = str(m.get("id") or os.path.basename(self.path))
        self.name = str(m.get("name") or self.id)
        self.version = str(m.get("version") or "v0")
        self.author = str(m.get("author") or "")
        self.description = str(m.get("description") or "")
        self.made_for = [str(x) for x in m.get("made_for") or ()]
        self.size = str(m.get("size") or "")
        self.harness = str(m.get("harness") or "claude-code")
        self.interface = m.get("brief_interface", BRIEF_INTERFACE)
        self.forked_from = str(m.get("forked_from") or "")
        self.running_marker = m.get("running_marker") or ""
        self.changes = m.get("changes") or ""
        if not self.meta:
            return
        if not _ID.match(self.id):
            self.problems.append(f"id „{self.id}“: only lower-case letters, digits, '-', '_' and '.'")
        if not isinstance(self.interface, int) or self.interface > BRIEF_INTERFACE:
            self.problems.append(f"needs brief interface {self.interface}, this Mule offers {BRIEF_INTERFACE} – "
                                 "update Mule")
        if self.harness not in HARNESSES:
            self.problems.append(f"harness „{self.harness}“ unknown (known: {', '.join(HARNESSES)})")
        for src, dst in (m.get("files") or {}).items():
            if not (self._inside(src) and _target_ok(dst)):
                self.problems.append(f"files: „{src}“ → „{dst}“ leaves its folder (targets start with brief/ or work/)")
                continue
            full = os.path.join(self.path, src)
            if src.endswith("/") != dst.endswith("/"):
                self.problems.append(f"files: „{src}“ → „{dst}“: folder to folder, file to file")
            elif not (os.path.isdir(full) if src.endswith("/") else os.path.isfile(full)):
                self.problems.append(f"files: „{src}“ is missing")
            else:
                self.files[src] = dst
        for key, rel in (m.get("templates") or {}).items():
            if key not in TEMPLATES:
                self.problems.append(f"templates: „{key}“ unknown (known: {', '.join(TEMPLATES)})")
            elif not (self._inside(rel) and os.path.isfile(os.path.join(self.path, rel))):
                self.problems.append(f"templates: „{rel}“ is missing")
            else:
                self.templates[key] = rel
        taken = sorted({t.split("/")[1] for _s, t in plan(self) if t.startswith("brief/")
                        and t.split("/")[1].lower() in MULE_FILES})
        if taken:
            self.problems.append("files: " + ", ".join(taken) + " in the brief folder belong to Mule's content")
        if "start" not in self.templates:
            self.problems.append("templates: „start“ (the sentence for the chat) is required")
        conf = m.get("config") or {}
        if conf:
            if not _target_ok(conf.get("file", "")) or conf["file"].endswith("/"):
                self.problems.append("config: „file“ must be a file under brief/ or work/")
            else:
                self.config_file = conf["file"]
                self.config_values = {str(k): str(v) for k, v in (conf.get("values") or {}).items()}
        for k in [*(conf.get("keep") or ()), *(m.get("keep") or ())]:
            if _target_ok(k):
                self.keep.append(k)
            else:
                self.problems.append(f"keep: „{k}“ must be under brief/ or work/")
        if self.running_marker and not _target_ok(self.running_marker):
            self.problems.append("running_marker must be under brief/ or work/")
        if self.changes and not (self._inside(self.changes) and os.path.isfile(os.path.join(self.path, self.changes))):
            self.problems.append(f"changes: „{self.changes}“ is missing")
        check_templates(self)

    def _inside(self, rel):
        if not isinstance(rel, str) or not rel or os.path.isabs(rel) or rel.startswith(("/", "\\")):
            return False
        full = os.path.normpath(os.path.join(self.path, rel))
        return full == self.path or full.startswith(self.path + os.sep)

    @property
    def ok(self):
        return not self.problems

    def label(self):
        return f"{self.name} ({self.version})"

    def template(self, key, lang=None):
        """Text of a template (language variant name.<lang>.ext first) or None."""
        rel = self.templates.get(key)
        if not rel:
            return None
        cands = []
        if lang:
            stem, ext = os.path.splitext(rel)
            cands.append(f"{stem}.{lang}{ext}")
        cands.append(rel)
        for c in cands:
            p = os.path.join(self.path, c)
            if os.path.isfile(p):
                with open(p, encoding="utf-8") as fh:
                    return fh.read()
        return None

    def render(self, key, ctx, lang=None):
        """Filled template (None if the recipe has none)."""
        t = self.template(key, lang)
        return None if t is None else render(t, ctx)

    def changes_text(self):
        if not self.changes:
            return ""
        try:
            with open(os.path.join(self.path, self.changes), encoding="utf-8") as fh:
                return fh.read()
        except OSError:
            return ""


def _target_ok(t):
    if not isinstance(t, str) or not t.startswith(("brief/", "work/")):
        return False
    rest = t.split("/", 1)[1]
    return bool(rest) and ".." not in rest.replace("\\", "/").split("/") and not os.path.isabs(rest) \
        and ":" not in rest


# ---- folders and lookup

def user_dir(create=True):
    """Recipe folder of the user (MULE_RECIPES overrides – tests); created on demand, not by just listing."""
    path = os.environ.get("MULE_RECIPES") or os.path.join(paths.user_dir(create), "recipes")
    if create:
        os.makedirs(path, exist_ok=True)
    return path


def default():
    return Recipe(BUILTIN_DIR, builtin=True)


def available():
    """Built-in recipe first, then the user's (by name); recipes whose id is taken by an earlier one are marked."""
    out = [default()]
    try:
        root = user_dir(create=False)
        names = sorted(os.listdir(root))
    except OSError:
        names = []
    for n in names:
        p = os.path.join(root, n)
        if os.path.isdir(p) and n not in _SKIP and not n.startswith("."):
            r = Recipe(p)
            if any(o.id == r.id for o in out):
                r.problems.append(f"id „{r.id}“ is already taken by another recipe")
            out.append(r)
    return [out[0]] + sorted(out[1:], key=lambda r: r.name.lower())


def find(rid):
    """Usable recipe with this id or None."""
    rid = rid or DEFAULT_ID
    if rid == DEFAULT_ID:
        return default()
    return next((r for r in available() if r.id == rid and r.ok), None)


def get(rid):
    """Recipe with this id, the default if it is missing or broken."""
    return find(rid) or default()


# ---- templates (Mustache subset)

_TAG = re.compile(r"\{\{\s*([#^/]?)\s*([\w.]+)\s*\}\}")
_STANDALONE = re.compile(r"(?m)^[ \t]*(\{\{\s*[#^/]\s*[\w.]+\s*\}\})[ \t]*\r?\n")


def render(template, ctx):
    """Mustache subset: {{name}}, {{a.b}}, {{.}}, sections {{#x}}…{{/x}} (list: once per item, item fields visible,
    plus _first/_last; other truthy value: once) and inverted sections {{^x}}…{{/x}}. No HTML escaping (Markdown).
    A line holding only a section tag disappears with its line break. Unknown names give an empty text."""
    tree, rest = _parse(_STANDALONE.sub(r"\1", template), 0, None)
    return _emit(tree, [ctx])


def _parse(text, pos, closing):
    out = []
    while True:
        m = _TAG.search(text, pos)
        if not m:
            if closing:
                raise RecipeError(f"template: {{{{/{closing}}}}} is missing")
            out.append(text[pos:])
            return out, len(text)
        out.append(text[pos:m.start()])
        kind, name = m.group(1), m.group(2)
        if kind in ("#", "^"):
            body, pos = _parse(text, m.end(), name)
            out.append((kind, name, body))
        elif kind == "/":
            if name != closing:
                raise RecipeError(f"template: {{{{/{name}}}}} without its opening tag")
            return out, m.end()
        else:
            out.append(("", name, None))
            pos = m.end()


def _lookup(stack, name):
    if name == ".":
        return stack[-1]
    first, *more = name.split(".")
    for frame in reversed(stack):
        if isinstance(frame, dict) and first in frame:
            v = frame[first]
            break
    else:
        return None
    for part in more:
        v = v.get(part) if isinstance(v, dict) else None
    return v


def _falsy(v):
    return v is None or v is False or v == "" or v == [] or v == {} or (type(v) is int and v == 0)


def _emit(tree, stack):
    out = []
    for node in tree:
        if isinstance(node, str):
            out.append(node)
            continue
        kind, name, body = node
        v = _lookup(stack, name)
        if kind == "":
            out.append("" if v is None or v is False else str(v))
        elif kind == "^":
            if _falsy(v):
                out.append(_emit(body, stack))
        elif not _falsy(v):
            if isinstance(v, list):
                for i, item in enumerate(v):
                    out.append(_emit(body, stack + [{"_first": i == 0, "_last": i == len(v) - 1}, item]))
            else:
                out.append(_emit(body, stack + [v]))
    return "".join(out)


def check_templates(recipe):
    """Template syntax errors as problems (so a broken recipe cannot be chosen)."""
    for key in recipe.templates:
        for lang in (None, "de", "en"):
            t = recipe.template(key, lang)
            if t is None:
                continue
            try:
                _parse(_STANDALONE.sub(r"\1", t), 0, None)
            except RecipeError as exc:
                recipe.problems.append(f"{recipe.templates[key]}: {exc}")
                break
    return recipe


# ---- installing into a brief

def _resolve(target, brief, work):
    root, rest = target.split("/", 1)
    return os.path.join(brief if root == "brief" else work, *rest.split("/"))


def _fill_bytes(raw, tokens):
    if b"{{" not in raw:
        return raw
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw
    for k, v in tokens.items():
        text = text.replace("{{" + k + "}}", v)
    return text.encode("utf-8")


def _walk(src):
    """Files of a folder, relative, without caches and version-control folders."""
    for base, dirs, files in os.walk(src):
        dirs[:] = sorted(d for d in dirs if d not in _SKIP)
        for f in sorted(files):
            if f in _SKIP or f.endswith(".pyc"):
                continue
            yield os.path.relpath(os.path.join(base, f), src)


def plan(recipe):
    """[(source file, target)] the recipe installs – folders expanded."""
    out = []
    for src, dst in recipe.files.items():
        if src.endswith("/"):
            for rel in _walk(os.path.join(recipe.path, src)):
                out.append((os.path.join(recipe.path, src, rel), dst + rel.replace(os.sep, "/")))
        else:
            out.append((os.path.join(recipe.path, src), dst))
    return out


def install(recipe, brief, work, tokens, fresh_conf=True):
    """Copy the recipe into brief folder and work folder, write the config file and the lock file. In a running run
    (fresh_conf False) the config keeps its values and only gets new keys; files under keep are never overwritten.
    Returns the written files relative to the brief folder (work-folder files are not listed)."""
    written = []
    skip = {recipe.config_file} if recipe.config_file else set()
    for src, target in plan(recipe):
        if target in skip:
            continue
        dst = _resolve(target, brief, work)
        if target in recipe.keep and os.path.exists(dst):
            continue
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with open(src, "rb") as fh:
            raw = fh.read()
        if os.path.splitext(src)[1].lower() in _TEXT:
            raw = _fill_bytes(raw, tokens)
        with open(dst, "wb") as fh:
            fh.write(raw)
        if target.startswith("brief/"):
            written.append(target[6:])
    if recipe.config_file:
        conf_path = _resolve(recipe.config_file, brief, work)
        values = {k: _fill_bytes(v.encode("utf-8"), tokens).decode("utf-8") for k, v in recipe.config_values.items()}
        if fresh_conf or not os.path.isfile(conf_path):
            os.makedirs(os.path.dirname(conf_path), exist_ok=True)
            with open(conf_path, "w", encoding="utf-8", newline="\n") as fh:
                fh.write("".join(f"{k}={v}\n" for k, v in values.items()))
            if recipe.config_file.startswith("brief/"):
                written.append(recipe.config_file[6:])
        else:
            with open(conf_path, encoding="utf-8") as fh:
                have = {line.split("=", 1)[0] for line in fh.read().splitlines() if "=" in line}
            missing = [k for k in values if k not in have]
            if missing:
                with open(conf_path, "a", encoding="utf-8", newline="\n") as fh:
                    fh.write("".join(f"{k}={values[k]}\n" for k in missing))
                if recipe.config_file.startswith("brief/"):
                    written.append(recipe.config_file[6:])
    write_lock(brief, recipe)
    written.append(LOCK_FILE)
    return written


def is_running(recipe, brief, work):
    return bool(recipe.running_marker) and os.path.exists(_resolve(recipe.running_marker, brief, work))


def digest(recipe):
    """sha256 over what makes the recipe (recipe.toml, the files it installs, its templates in every language, its
    changes file; path and content) – names exactly which recipe a result came from. Other files in its folder
    (tests, their runs, notes) do not count, so the same recipe has the same digest on every machine."""
    rels = {RECIPE_FILE, *(os.path.relpath(src, recipe.path) for src, _t in plan(recipe))}
    if recipe.changes:
        rels.add(recipe.changes)
    for rel in recipe.templates.values():
        stem, ext = os.path.splitext(rel)
        folder = os.path.dirname(os.path.join(recipe.path, rel))
        rels.add(rel)
        if os.path.isdir(folder):
            base = os.path.basename(stem)
            rels.update(os.path.relpath(os.path.join(folder, f), recipe.path) for f in os.listdir(folder)
                        if f.startswith(base + ".") and f.endswith(ext))
    h = hashlib.sha256()
    for rel in sorted(r.replace(os.sep, "/") for r in rels):
        p = os.path.join(recipe.path, *rel.split("/"))
        if not os.path.isfile(p):
            continue
        h.update(rel.encode("utf-8") + b"\0")
        with open(p, "rb") as fh:
            h.update(fh.read())
        h.update(b"\0")
    return h.hexdigest()


def write_lock(brief, recipe):
    with open(os.path.join(brief, LOCK_FILE), "w", encoding="utf-8") as fh:
        json.dump({"id": recipe.id, "name": recipe.name, "version": recipe.version, "author": recipe.author,
                   "builtin": recipe.builtin, "digest": digest(recipe)}, fh, indent=1, ensure_ascii=False)
        fh.write("\n")


def read_lock(brief):
    """Lock of a brief folder; briefs from before recipes (only .claude/package_version) count as the default."""
    try:
        with open(os.path.join(brief, LOCK_FILE), encoding="utf-8") as fh:
            lock = json.load(fh)
        return lock if isinstance(lock, dict) and lock.get("id") else None
    except (OSError, ValueError):
        pass
    pv = os.path.join(brief, ".claude", "package_version")
    if os.path.isfile(pv):
        with open(pv, encoding="utf-8") as fh:
            return {"id": DEFAULT_ID, "version": fh.read().strip() or "unknown", "builtin": True}
    return None


# ---- what a recipe does on the machine (shown before import and in the dialog)

_NET = re.compile(r"\b(curl|wget|Invoke-WebRequest|Invoke-RestMethod|iwr|irm|Start-BitsTransfer|scp|ssh|nc|ncat|"
                  r"FromBase64String|base64\s+-d|DownloadString|DownloadFile)\b|https?://", re.I)


def summary(recipe):
    """{"files", "hooks": [(event, command)], "allow": [...], "mode", "network": [(file, line, text)], "mcp": [...]}
    – read from the recipe's Claude settings and scripts. A help for looking, not a guarantee."""
    out = {"files": 0, "hooks": [], "allow": [], "mode": "", "network": [], "mcp": [], "brief": [], "work": []}
    for src, target in plan(recipe):
        out["files"] += 1
        out["brief" if target.startswith("brief/") else "work"].append(target.split("/", 1)[1])
        name = os.path.basename(target)
        if name in ("settings.json", "settings.local.json", ".mcp.json"):
            try:
                with open(src, encoding="utf-8") as fh:
                    data = json.load(fh)
            except (OSError, ValueError):
                continue
            for event, groups in (data.get("hooks") or {}).items():
                for g in groups or ():
                    for hk in (g or {}).get("hooks") or ():
                        cmd = " ".join([str(hk.get("command", "")), *map(str, hk.get("args") or ())]).strip()
                        out["hooks"].append((event, cmd))
            if data.get("statusLine"):
                out["hooks"].append(("statusLine", str(data["statusLine"].get("command", ""))))
            perm = data.get("permissions") or {}
            out["allow"] += [str(a) for a in perm.get("allow") or ()]
            out["mode"] = out["mode"] or str(perm.get("defaultMode") or "")
            out["mcp"] += list((data.get("mcpServers") or {}).keys())
        if os.path.splitext(src)[1].lower() in _TEXT and not src.endswith(".md"):
            try:
                with open(src, encoding="utf-8", errors="replace") as fh:
                    for k, line in enumerate(fh, 1):
                        if _NET.search(line):
                            out["network"].append((target.split("/", 1)[1], k, line.strip()[:120]))
            except OSError:
                pass
    return out


# ---- import

def unpack(zip_path):
    """Unpack a recipe zip into a fresh temporary folder (checked: no paths out of it, size limit) and load it.
    -> Recipe (its folder is temporary; install_unpacked moves it into the recipe folder)."""
    tmp = tempfile.mkdtemp(prefix="mule_recipe_")
    try:
        with zipfile.ZipFile(zip_path) as z:
            total = 0
            for info in z.infolist():
                name = info.filename.replace("\\", "/")
                if name.startswith("/") or ".." in name.split("/") or ":" in name:
                    raise RecipeError(f"„{info.filename}“ points outside the recipe")
                total += info.file_size
                if total > MAX_ZIP:
                    raise RecipeError("the recipe is larger than 50 MB unpacked")
                if (info.external_attr >> 16) & 0o170000 == 0o120000:
                    raise RecipeError(f"„{info.filename}“ is a link – not allowed in a recipe")
            z.extractall(tmp)
    except zipfile.BadZipFile as exc:
        shutil.rmtree(tmp, ignore_errors=True)
        raise RecipeError(f"not a zip file: {exc}") from exc
    except RecipeError:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    root = tmp
    if not os.path.isfile(os.path.join(root, RECIPE_FILE)):  # zip of the folder: one level down
        subs = [d for d in os.listdir(root) if os.path.isdir(os.path.join(root, d)) and d not in _SKIP
                and d != "__MACOSX"]
        if len(subs) == 1 and os.path.isfile(os.path.join(root, subs[0], RECIPE_FILE)):
            root = os.path.join(root, subs[0])
        else:
            shutil.rmtree(tmp, ignore_errors=True)
            raise RecipeError(f"no {RECIPE_FILE} in the zip")
    r = Recipe(root)
    r._tmp = tmp
    return r


def target_of(recipe):
    """Folder the recipe goes to in the recipe folder."""
    return os.path.join(user_dir(), recipe.id)


def install_unpacked(recipe, replace=False):
    """Move an unpacked recipe into the recipe folder. -> the installed Recipe."""
    if recipe.id == DEFAULT_ID:
        raise RecipeError("the id „default“ belongs to Mule's own recipe – give the recipe its own id")
    if not _ID.match(recipe.id):
        raise RecipeError(f"id „{recipe.id}“ is not usable as a folder name")
    dst = target_of(recipe)
    if os.path.exists(dst):
        if not replace:
            raise RecipeError(f"a recipe „{recipe.id}“ is already installed")
        shutil.rmtree(dst)
    shutil.copytree(recipe.path, dst, ignore=shutil.ignore_patterns(*_SKIP, "*.pyc"))
    shutil.rmtree(getattr(recipe, "_tmp", ""), ignore_errors=True)
    return Recipe(dst)


def discard(recipe):
    shutil.rmtree(getattr(recipe, "_tmp", "") or "", ignore_errors=True)

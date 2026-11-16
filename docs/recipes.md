# Brief recipes

A **brief recipe** is a complete way of working for a build brief: the rules the AI follows, the roles and agent
types, the hooks that guard the run, the tools it gets, the process part of `project.md` and the sentence you paste
into the chat. Mule writes the *content* of a brief (the scene, the notes, the pictures, the cameras); the recipe
decides *how the AI works with it*.

Mule ships one recipe, **Mule Default** (`sketch_machine/brief_package/`). You can write your own, or load one
somebody else made, and choose it per export in the brief dialog under **Brief recipe**. One recipe might suit a
small prop, another a creature, another a whole landscape; comparing them on the same sketches is how we find out
what works.

> **A recipe is instructions and program at once.** Its rules steer an AI that can write files on your machine, and
> its hooks are scripts that Claude Code runs on your machine. Only use recipes whose source you trust, and read
> them before the first run. Mule shows what a recipe runs before you import it (see [Importing](#importing)), but
> that overview is a help for looking, not a guarantee.

## Where recipes live

- Mule's own: `sketch_machine/brief_package/` in the program (read-only for you).
- Yours: the recipe folder – `%APPDATA%\Mule\recipes\` on Windows, `~/Library/Application Support/Mule/recipes/` on
  macOS, `~/.local/share/Mule/recipes/` on Linux. One sub-folder per recipe. The brief dialog opens it for you
  (**…** → **Open recipe folder**). The environment variable `MULE_RECIPES` points Mule at another folder.

A recipe that has a problem (a missing file, a path that leaves its folder, a template with an open section …) is
still listed, greyed out, with the problem as its tooltip.

## Folder layout

Any layout you like – `recipe.toml` says where every file goes. A small example:

```
lean_prop/
  recipe.toml
  RULES.md
  CLAUDE.md
  claude/
    settings.json
    hooks/stop.sh
  tools/
    turntable/render.py
  templates/
    start.md
    start.de.md
    project.md
  CHANGES.md
```

## recipe.toml

```toml
id = "lean_prop"                 # lower-case letters, digits, - _ . ; unique; "default" is Mule's
name = "Lean Prop"
version = "v1.0"                 # v<major>.<minor>[.<patch>] – review rounds compare it
author = "Your name"
description = "One builder, one QC pass, no levels – for small props."
made_for = ["objects"]           # free words: objects, creatures, vehicles, buildings, environments …
size = "small"                   # free word: small, medium, large, any
harness = "claude-code"          # the AI tool it is written for ("claude-code" or "any")
brief_interface = 1              # the version of what Mule offers (this page); Mule refuses newer ones
forked_from = "default v5.0"     # optional: what it started from
running_marker = "work/review/started"   # optional: this file exists = a run has begun (see below)
changes = "CHANGES.md"           # optional: quoted into review rounds when the version goes up

[templates]                      # Mustache templates Mule fills with its facts (below); only "start" is required
start = "templates/start.md"
project = "templates/project.md"
brief_head = "templates/brief_head.md"
review_start = "templates/review_start.md"
review_intro = "templates/review_intro.md"
package_update = "templates/package_update.md"

[files]                          # recipe path = target; targets start with brief/ or work/; "x/" copies a folder
"RULES.md" = "brief/RULES.md"
"CLAUDE.md" = "brief/CLAUDE.md"
"claude/" = "brief/.claude/"
"tools/" = "work/tools/"

[config]                         # optional: a key=value file, e.g. for your hooks
file = "brief/.claude/hooks/run.conf"
keep = ["brief/.claude/hooks/run.local.conf"]   # never overwritten once it exists

[config.values]
WORK = "{{work_dir}}"
LEVEL = "study"
```

### Targets

- `brief/…` is the brief folder (`<scene>_brief/`), `work/…` the work folder next to it (`work_<scene>/`). Mule
  always creates `work/review/`, `work/export/` and `work/tools/`.
- Targets may not leave these folders and may not use the names Mule writes itself in the brief folder: `brief.md`,
  `brief.json`, `project.md`, `context.md`, `core.md`, `scene.usd`, `review.md`, `clarified_history.md`, `.mcp.json`,
  `.codex/`, `views/`, `notes/`, `shots/`, `videos/`, `gen/`, `review_rounds/`, `.mule_recipe.json` (case does not
  matter – Windows).
- Folders are copied with everything inside except `__pycache__`, `.git`, `*.pyc`, `.DS_Store`, `Thumbs.db`.
- If the recipe installs `brief/.claude/settings.json`, Mule adds the work folder to
  `permissions.additionalDirectories`, so Claude Code may write there.

### Tokens in copied files

In copied text files (`.md .json .sh .ps1 .conf .txt .toml .py .yml .yaml .cmd .bat .js .ts .ini .cfg …`) Mule
replaces exactly these tokens and touches nothing else:

| Token | Becomes |
|---|---|
| `{{project_name}}` | the scene name |
| `{{brief_dir}}` | the brief folder, forward slashes |
| `{{work_dir}}` | the work folder, forward slashes |
| `{{bash}}` | bash on this machine (Git Bash on Windows) |
| `{{powershell}}` | Windows PowerShell, or `pwsh` elsewhere |
| `{{recipe_id}}`, `{{recipe_version}}` | from `recipe.toml` |

The same tokens work in `[config.values]`.

### A run in progress

If `running_marker` exists, a new export into the same brief folder leaves the recipe's files alone and only renews
the content (brief.md, project.md, pictures) – rules must not change in the middle of a run. Without a marker the
recipe is installed on every export.

## Templates

Templates are [Mustache](https://mustache.github.io/mustache.5.html), a small subset of it:

- `{{name}}`, `{{a.b}}`, `{{.}}` (the current item); unknown names give an empty text; nothing is escaped
  (Markdown, not HTML).
- `{{#name}}…{{/name}}` – a list: once per item, the item's fields visible, plus `_first` and `_last`; any other
  non-empty value (true, a text, a number other than 0): once.
- `{{^name}}…{{/name}}` – only when the value is empty, false, 0 or missing.
- A line that holds nothing but a section tag disappears with its line break, so templates stay readable.

Language variants: `start.de.md` next to `start.md` is used when Mule runs in German. The other templates are
English (the AI reads them; it talks to the artist in the artist's language anyway).

### `start` – the sentence for the chat (required)

Mule puts it into the clipboard after the export (the artist can still change it in the dialog).
Facts: `project_name`, `brief_dir`, `look` (the look pre-stage is ticked), `recipe.id`, `recipe.name`,
`recipe.version`.

### `project` – project.md

Written on every export; without the template there is no `project.md`. Facts:

| Fact | Meaning |
|---|---|
| `project_name` | scene name |
| `brief_dir`, `work_dir` | folders (forward slashes); empty when `live` |
| `live` | true when the MCP tool `scene_brief` shows the brief live (no export folder yet) |
| `has_context` | there is a `context.md` (notes outside the focus) |
| `recipe.id`, `recipe.name`, `recipe.version` | this recipe |
| `task_sentence` | the task in one sentence from the dialog, or empty |
| `task_notes` | the export notes, as written |
| `task_notes_quoted` | the same as a Markdown quote (`> …`) |
| `look` | the look pre-stage is ticked |
| `round_map` | list: `word` (the artist's name for a part), `ids`, `group` (a group and everything in it), `binding` (`fixed`, `authoritative`, `basis`, `guide`, or empty) – from the focus and the Outliner "Brief" column |
| `focus` | when only the selection is built: `count` (ids in all), `parts` (list of `id`, `name`); else empty |
| `cameras` | list of `name`, `image` (hero cameras) |
| `cameras_set` / `cameras_default` | the artist set hero cameras / the brief has standard angles |
| `hero_count` | number of hero pictures |
| `artist_tools_noted` | the project note or the task notes have text (where the artist may name tools) |
| `bible` | path of the workflow bible of earlier Mule projects |
| `boards`, `board_sections` | whole-board pictures and their section pictures |
| `uncaptioned` | reference pictures without a caption |
| `videos` | reference videos |

Everything else about the scene – notes, parts, sizes, pictures – is in `brief.md` and `brief.json`, the same for
every recipe.

### `brief_head` – the first lines of brief.md

Where the AI finds the way of working. Fact: `has_context`. Without it Mule writes one neutral sentence.

### Review rounds: `review_start`, `review_intro`, `package_update`

A review round ("Builds on" in the dialog) is feedback for a running chat. It always uses **the recipe the brief was
made with** – the dialog's choice does not apply.

- `review_start` – the sentence for the chat. Facts: `round` (number), `project_name`, `round_dir`.
- `review_intro` – the top of `review.md`, before Mule lists what changed in the notes. Facts: `date`, `base` (the
  brief folder), `updated` (this round brings a newer version of the recipe).
- `package_update` – the section when a newer version came along. Facts: `old`, `new`, `changes` (the sections of
  your `changes` file newer than `old`), `recipe.id`, `recipe.name`.

Without these templates Mule writes short neutral texts.

## The lock file

Every build brief gets `.mule_recipe.json`: id, name, version, author and a **digest** (sha256 over all files of the
recipe). It tells review rounds which recipe to renew from, and it names exactly which recipe a result came from –
quote it when you share results.

## Versions and review rounds

Raise `version` whenever you change the recipe, and add a section to your `changes` file:

```markdown
# Changes
## v1.1
- QC now also checks the silhouette from above.
## v1.0
- First version.
```

A review round into a brief made with v1.0 then copies v1.1 into the brief folder (the config file keeps the run's
values and only gets new keys; `keep` files stay) and quotes the v1.1 section in `review.md`. If the recipe is no
longer installed, the round brings nothing new and the brief keeps what it has.

## Importing

**…** → **Import recipe (.zip)** in the brief dialog. The zip may hold the recipe folder itself or the files of it.
Before anything is installed Mule checks the zip (no paths out of it, no links, at most 50 MB) and shows:

- name, author, version, what it is made for, the digest;
- every hook command Claude Code would run, the permissions it grants without asking, its own MCP servers;
- every line in its scripts that downloads or talks to the network (`curl`, `Invoke-WebRequest`, URLs …).

An imported recipe that is not Mule's own says so in the dialog every time it is chosen.

## Sharing

Zip the recipe folder and share it, for example in the GitHub Discussions of Mule Create. Say what it is for, which
model you ran it with, and what the lock file says.

## Writing a recipe: tips

- Start from a copy of Mule Default (`sketch_machine/brief_package/` in the source) and change one thing at a time,
  so a comparison tells you what that one thing did. Set `forked_from`.
- Rules that hold for every project beat rules that fix one project's problem.
- Everything Mule knows about the scene is in `brief.md` and `brief.json`; the MCP server `sketch_machine` (see the
  AI handbook) lets the AI look at the live scene and write back what was clarified.

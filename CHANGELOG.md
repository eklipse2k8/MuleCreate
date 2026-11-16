# Changelog

## Unreleased

- **Leaner build runs (Mule Default v5.1):** measured on a full run, no check removed. The main chat hands over and
  compacts at about 250 k tokens and goes on in the same chat; hook texts stay short enough to arrive whole (the full
  rules load through `CLAUDE.md`); each role names a *strong* or *light* model, harness-neutral; the detail stage
  starts only after the form was held against the sketch; `tools/quiet.sh` keeps long logs out of the agents' context,
  and builders get a hint to hand over when their context grows large.
- **Brief recipes:** the whole way of working of a build brief – rules, roles, agents, hooks, tools, the process
  part of `project.md` and the sentences for the chat – is now a swappable recipe. Choose it under **Brief recipe**
  in the brief dialog; **…** imports a recipe as .zip (Mule shows its hook commands, permissions and network calls
  first), shows its contents and opens the recipe folder. Mule's own method is the recipe **Mule Default**, unchanged.
  Every build brief names its recipe in `.mule_recipe.json`; review rounds keep the brief's recipe. Format:
  `docs/recipes.md`.
- README: picture at the top, direct links to the download, the introduction and the AI handbook.
- Known limits now say that the local MCP server has no password (it only listens on this computer).
- Contributing: questions and ideas welcome in GitHub Discussions.
- This changelog is now in English.
- The public repository is English only: German guides stay private, tests, developer tools, the brief package and
  remaining program texts outside the German UI are English (the German UI itself stays as a language option).
- Test scenes and their parts have English names (teacup, watering_can, horse_head …); the pictures are renewed.
- Tests: English file names, `LEVEL = "core"` and `tests/run.py --core`, results `FAIL` / `EXPECTED` / `FIXED`.

## Mule Create Alpha 1.2 – v0.99.255 (2026-11-16)

- **Introduction inside the program:** a slide show with the 18 pictures (Help → Introduction in Pictures); at the
  top of the manual (F1) as the first button, next to the way to the AI handbook; on the first start Mule asks once.
- Fixed: closing Mule could end with an error code (the new manual buttons held the window in a reference cycle).
- Developer tools: the public update stops before changing anything if Mule is running from the public folder.

## Mule Create Alpha 1.1 – v0.99.252 (2026-11-16)

- **`start.bat`** sets up its own Python environment on the first start under Windows (before: "pythonw.exe not
  found" in a fresh copy) and installs missing packages later.
- **Introduction in pictures:** `docs/INTRODUCTION.md` (click through on GitHub) and `docs/introduction.html` (slide
  show) – 18 pictures from the real program, linked at the very top of the AI handbook. New section "Start here":
  pen and brush, Draw and Paint mode, Free mode.

## Mule Create Alpha 1 – v0.99.249 (2026-11-16) – first public version

Open source under GPL-3.0. New since the internal test version v0.99.229:

- **`AI_HANDBOOK.md`:** the complete reference for AI assistants – every function, shortcut and workflow, the brief
  and all MCP tools, with a German → English UI glossary. Give it to your own AI and ask. A test keeps it in step with
  the program.
- **English README** and English code comments.
- **Review:** the **Mark** tool next to the Review button replaces F8/F9; a click on a picture on a board remembers
  that reference picture for the part's note; **Send Review** puts a sentence for the chat on the clipboard (in
  English when Mule runs in English); "Claude is working …" ends when Claude is done; Claude's arrows on the board
  follow text and picture.
- **Builds on** in the brief dialog is now a review round in the running chat.
- **Way-of-working package v5.0** in the build brief: sketch first (the drawn shape binds, tolerance per line), sketch
  overlay, the artist's words as a list, design left to the artist where not handed over.
- Fixed: **Ctrl+L** (loop along the net) did nothing from the keyboard; the **eraser** pressure slider had no effect
  (pressure now scales the eraser circle); the right-click menu showed Space+B for Maximize instead of Space+F; the
  outliner Info column is translated ("missing", "tris"); curve surfaces lost their border line on saving; a mixed
  edge selection was not fully highlighted.
- If port 8770 is taken (a second Mule), the status line says that the AI connection is off.
- Build brief hooks use the programs found on this computer (Git Bash outside its default folder; bash and
  PowerShell 7 `pwsh` on Linux/macOS, untested there); the brief dialog names what is missing.
- Removed: the old AI brief check through the Anthropic API (switched off since v0.99.78) and the `anthropic` package;
  clarifying happens in the chat and over MCP.
- The workflow bible in the public repository holds technique and tool entries; each user's AI extends its own copy.
- Guides: report problems as GitHub issues; scenes are `.mule` files.

## v0.99.229 (2026-11-14) – internal test version

- **Set up transcription:** Mule sets up Whisper for review transcripts itself (Review menu, or the question at the
  first review); needs a Python 3.10–3.13 from python.org once, about 2–4 GB of downloads.
- Official name **Mule Create** in the window title, manual, guides and release.
- Guides in German (`ANLEITUNG.md`) and English (`GUIDE.md`), this changelog, source package.
- Third-party licenses complete, including Mesa/LLVM (`opengl32sw.dll`).

**What Mule Create can do in this version**

- **Sketching in space:** lines on planes, drawing surfaces and imported meshes (OBJ, USD), Free mode without a plane,
  straight lines and shapes by holding still, smooth drawing, painting.
- **Surfaces from lines:** curve nets with shared points, loft, extrude, fill surfaces, symmetry and array.
- **Edit mode:** move, rotate, scale with the gizmo, snapping, point onto point, world / local / camera space.
- **Notes and note boards:** notes on parts of the drawing; boards with pictures, videos, handwriting, arrows and
  captions; screenshots as hero cameras.
- **Sketch Brief:** export as a folder with pictures, notes, a clarification list and working rules for the AI.
- **AI connection over MCP** (local, port 8770) for Claude Code, Codex and other MCP clients: read the scene, render
  views, dictate notes, insert pictures, export the brief.
- **Review mode:** talk your feedback while walking through the scene, mark places, local transcript with Whisper;
  the AI turns it into draft notes you listen to and accept.
- **Export:** the scene as USD for Houdini, Blender and Maya; curves as USD or JSON.
- **Shots and timing** (prototype): cameras, timeline, flipbook layers.
- Interface and manual (F1) in German and English.

**Known open points**

- No built-in "Report a problem" yet; Python for Whisper has to be installed by the user.
- Linux from source only and hardly tested; macOS untested; the program is not signed.
- The scene format can still change until the beta.

# Conductor – how the main chat runs a round
Read `rules.md`, `levels.md`, this file and the project document (`project.md`: goal, round map, task, binding levels, states, tools). `brief.md` holds the notes and the scene; `context.md` holds notes of later rounds (intent only, no work lines).

## Roles
Every agent is fresh. Start it with its agent type (`.claude/agents/<role>.md`) or with a first line `ROLE: <role>`, plus `UNIT: <unit>` and, for builders, `STAGE: <stage>`. The gate adds the rules, the level row, the role contract, the report path, the artist's recent words, `decisions.md` and the matching sections of `bauwissen.md`. So your task stays short: goal, work lines, picture targets, open veto, adopted proposal.

| Role | When | Gives |
|---|---|---|
| builder | every build step: one goal, usually one stage of one unit, or a fix (rule 17) | files, sheet, state note, `bauwissen.md` lines, report |
| referee | after every builder run (level decides) | rule check in minutes, `VERDICT` |
| qc | `STAGE: targets` at unit start (study, final); check at unit end and before every showing | targets, or a check on pictures with at most 3 work lines, `VERDICT` |
| engineer | after a finished unit (level decides) | judges adopted proposals (keep/drop/wait), at most 3 new ones; tidies `bauwissen.md` |
| helper | bounded side tasks: rig or scene analysis, first-round pictures, reference search, visibility map runs | short report |
| stand-in | questions of taste during the run (rule 6) | answer in `review/standin_answers.md` |
| viewer | show something to the artist in a live session: open a scene, set a camera or state; never saves | one line; no referee needed |

**Targets and judging are split:** one fresh QC writes the picture targets of a unit (from notes, readings, references and current pictures; for taste it asks the stand-in), another fresh QC judges against them. You only copy the targets into tasks and the work list. A target names an area of tier A, a camera and what must read there by function, never „like the generated image“.

## The loop for one unit
1. **Plan:** units and lanes are in `review/units.md` with dependencies and interfaces. Before the first detail stage: components, runs and areas of the unit in `review/components.md` with one picture per proposed view, confirmed by the artist by exception; the visibility map with the component views (rule 7, one config per component, `component` key) comes from the builder run that changed the geometry, at its end – only when none is due, a helper runs it (a map run gets no referee and no QC); at study and final, a QC writes the picture targets, also per component view.
2. **Task:** work lines, targets, tiers of the parts touched, open veto.
3. **Build → referee → (QC when due) → decide** by rule 4. Then the next run, or a showing.
4. **Unit end:** you write `review/units/<unit>_report.md` in four groups; QC judges the targets; the engineer runs if the level asks; apply its KEEP/DROP lines (WAIT: the proposal stays active and holds its slot) and adopt proposals (at most one per area) in `review/adopted.md` – a dropped one returns this round only with the artist's word.

Keep up to `MAX_BUILDERS` builders busy from the start: plan lanes and packages in the first round, write contracts first.

**Components, runs and areas (rule 7).** What can be judged standing alone is a *component* (crane, tree, creature's head, kit); what is too long for that is a *run* (quay wall, track, fence: judged on a typical section and its ends); what lives by distribution is an *area* (forest, terrain, crowd: hero views plus at most one view into it). In doubt, the smaller one. At each round start, before the first detail stage and on whatever geometry stands, list them in `review/components.md` with rank, views and readable size; the artist confirms by exception. Rank 1 (named in the notes, or it moves or works): 2–3 views; rank 2 (recurs often): 1 view; rank 3: none, also when the hero views already read it. Views are chosen by function – the view that identifies it, the one where it works, the one a viewer really gets – each with one line why; `tools/vis_map` places them at the rank's distance, which fixes the readable size. Assets with many instances are judged once, on a sample. Thresholds, states and cloud come from key `visibility`; a separate map run is a helper task without referee or QC; the map ages only when the unit's exports change. The artist may mark areas as tier A.

**Lanes, packages, interfaces (rule 14).** Lanes run in parallel only when they share no files and their interface is written in `units.md`. A live session belongs to one agent at a time (the hook holds it for the first agent that uses it); other lanes, QC and the map work headless. *Packages* (`<unit>-<package>`): parts whose form needs only an interface (procedural assets, kits, material ids) are built in parallel with the unit's main strand – contract first, own versioned files, brought in by a `STAGE: integrate` run. Whoever moves an interface port publishes the interface as a new version and names every dependent package; add a work line for each. Shared files (`SHARED_FILES`) are read-only unless held with `SHARED:`; review scene and rig load only published files.

## Files in `review/`
| File | Contents | Written by |
|---|---|---|
| `worklist.md` | one line per task: `id · unit · parts · artist's words (verbatim, with picture or mark) · main chat's reading (marked as such) · method · tier · what one must see · camera and state · fails if … · status` – no option or condition beyond the artist's words (rule 5) | main chat |
| `readings.md` | one line per mark or key, with its backing | main chat |
| `decisions.md` | decisions during the run and the artist's process words, dated, with source | main chat |
| `assumed.md` | readings builders took to go on – never a departure from what is drawn (rule 4) | builders (add only) |
| `overlay/` | sketch overlay per unit and run: `<name>_overlay.md`, `ov_<name>_<view>.png` (`tools/sketch_overlay`) | builders, QC |
| `units.md` | units, dependencies, interfaces with version, lanes, packages | main chat |
| `components.md` | table, one line per component, run or area, columns: name, unit, kind (component/run/area), rank, views (name: why), readable size | main chat |
| `units/<unit>_state.md` | files, cameras, what stands, dropped and why, next step | builders |
| `units/<unit>_targets.md` | picture targets per hero view | QC (`STAGE: targets`) |
| `vis/<unit>_vis.md` | tier per part from the visibility map, date, state of the geometry | helper or builder via `tools/vis_map` |
| `bauwissen.md` | tools, proven ways, pitfalls, dropped ways, scene map – sections by keyword, at most about two pages | builders add, engineer tidies |
| `adopted.md` | one line per adopted proposal: `proposal · area · number per run · value before · value after · quality guard · status (active/kept/dropped) · source` | main chat |
| `standin_answers.md` | the stand-in's answers to questions of taste | stand-in |
| review scene (path in `bauwissen.md`) | all units on the rig, for the artist to turn and fold | builders keep it current |

## What the hooks enforce (when one refuses, do what it says; never work around it)
If a refusal is wrong or asks for something it then refuses itself, do not work around it: send the exact text to the artist, or to the hook session the artist named. Go on with the other units.
- Rules in context at start, after compaction, with every artist message and every `REMIND_EVERY` tool calls.
- Agents only with a role; no forks; `SendMessage` only to resume an agent whose report is `ABORTED:` (once), or to another app session (`local_…`).
- The main chat does not build: no build tools, no scripts, no scene files. Read-only live tools (`inspect`, `geo`, `problems`, `screenshot`) are allowed.
- Builders: up to `MAX_BUILDERS`, one per unit or package; no new builder of a unit while its referee, QC or engineer is due; `STAGE: details` only with a current visibility map, the unit's lines in `components.md` with views made for every rank the level asks, and `tier` on every new part line; `STAGE: integrate` only when all packages are finished and refereed.
- Shared files read-only unless held with `SHARED:`; shared text files only added to with Edit, never rewritten, never by shell redirection.
- Checking roles and the viewer get no build tools; the viewer may not change any project file.
- Locked during a run: hooks, settings, rules, roles, brief files, gate logs. Settings change only by an artist message line `SET: <key>=<value>` (level, lanes, pause).
- Budget: no new agent when `review/gate/usage.txt` shows the weekly or 5-hour use at or above `MAX_WEEKLY` / `MAX_5H`, or after `STOP_AT`. `PAUSE=` stops new builder starts.
- Every run gets its number from the gate (GATE line of its prompt); never plan numbers. Its reports are written once, by its own agent, and no other agent overwrites them. At most two QC reports per gate.
- A turn cannot end while a required check is due.
- Logs: `review/gate/agents.log`, `tools.log`, `artist.log`.

**Your duties, not enforced:** QC before every showing; `usage.txt` is written by the status line (no recurring job: a job in this chat costs your whole context every time); only when the gate says it is missing or old, write it once by hand (usage tool, Write tool). When the budget or `STOP_AT` stops new agents: let running agents finish, write `ABORTED: <why>` as the report of any agent that was cut off, tell the artist where things stand, and go on only when the artist says so or the window has reset; every hand-over and round end names the changes agents made to `tools/`, so they can flow back into Mule; when your context passes about 500 k tokens, the gate starts no new agent until you have written a hand-over into `review/conductor_handover.md` (again every 100 k); then ask the artist for a fresh chat, or continue from it after a compaction.

**Fallback:** every start, compaction and artist message puts a `GATE STATUS` block into your context. If it is missing, the hooks are not running: tell the artist, paste rules, level row, role and report path into every agent prompt yourself, and keep the loop by hand.

**After a compaction or a long gap:** read `worklist.md`, `units.md` and the unit's state note before deciding.

## First round – before building
Open the hero pictures and the whole-board pictures, and the section pictures of the notes of the first units. Say in one line how many you opened. A helper does rig or scene analysis and the first-round pictures (the main chat does not render).

**Review rounds.** The artist's review of a running run comes as a folder `review_rounds/review_NN_<date>/` inside this brief folder, written by Mule. It is not a new brief and not a new run: it holds `review.md` (only what changed in the notes since the last export – new, changed, removed notes with their pictures) and the current state for looking things up (`scene.usd`, `views/`, `notes/`, `brief.json`). Take it in as `review.md` says: read it completely and open every picture, fit it into decisions, readings, units and the work list (where a note contradicts something established, the note wins – list each case), ask only what it leaves open, then go on as before. Rules, level, hooks and the work folder stay.

**Exceptions first.** One message, in this order:
1. The real questions, each with a picture where the part is marked and named.
2. One table of everything beyond doubt: point · reading · source.
3. The units with dependencies and lanes, on one colour-coded overview picture.

End this message with one line in the artist's language, e.g. „Current level: study – change it any time with a line `SET: level=scout|study|final`“, giving the level from gate.conf (the GATE STATUS shows it).

The artist may answer by exception („all fine except 3 and 7“); that confirms the rest. Marks of later units are clarified when their unit starts, as short questions with pictures, while other work goes on.

**Mandatory keys** – asked unless the brief settles them beyond doubt; each answer is one line in `readings.md`: `<key>: <answer> — backing: artist „<words>“ | brief <section, quoted>`. The hooks refuse the first builder until the keys of the level exist (`levels.md`).

| Key | Question |
|---|---|
| `goal` | the goal of this round in one sentence, what belongs to it and what not; contradictions between notes, task and answers |
| `level` | scout, study or final |
| `units` | the cut into units, with reasons and dependencies |
| `approach` | blockout and part-spec pass over everything first (unit `U0`), or straight into the first unit? A general „go“ does not answer this. If the project document names no tools of the artist, also ask which software is at hand and what it is used for (rule 12). |
| `blockout` | how existing geometry may be used (template, start geometry, partly final), and which parts are only placeholders (`basis`) |
| `tolerance` | how closely the build follows the drawing (rule 10) – propose the defaults and ask only for changes: precise lines and modelled surfaces within 3 % of each line's own length, direction 10°, curves stay curves; gestures 10 %; route lines by their ends and order. Ask what may move („up to 3 % of the line“) and what may never change (directions, curves, proportions), never as a share of area. Also: whether outlines like a footprint or a silhouette are hard limits or a starting area, and **where the artist hands design over** (the task or a note asks for design – free and bold there, within what is drawn) and where design that is not drawn stays quiet and comes to the artist as variants. The kind of every mark is part of its reading (`readings.md`). |
| `collision` | what counts as a collision: size, which cameras, which states |
| `visibility` | settings of the visibility map – propose the defaults and ask only for changes: 960 px picture width; threshold 20 px per piece; cloud of 16 cameras per hero camera, ±15° and ±20 % distance, fixed seed; states rest, middle, end and one extreme. Also: areas the artist wants as tier A; whether see-through surfaces (membranes, glass) hide what is behind them. The map runs where the review scene lives: a `.blend` with `tools/vis_map/vis_blender.py` alone, a Houdini scene with `vis_export.py` + `vis_map.py` (`tools/vis_map/README.md`) |
| `sheet` | what each sheet shows and when the artist wants to see it |
| `away` | what to do when a decision is needed and the artist is away |
| `marks` | the readings of the first units' marks are confirmed |

**Goal proposal:** right after the artist's answers, send one short message – no agents, no new pictures: the goal in one sentence, what belongs to it and what not, the done criteria as picture checks, the units with dependencies, the lane plan, a rough number of builder runs and the expected share of the weekly budget. Only after the artist confirms does `goal` go into `readings.md`.

## Reporting to the artist
- Present what QC passed, with the review scene (viewer) and a few sheet pictures.
- Before every sheet or showing, check the work list against `review/gate/artist.log`: every instruction and approval of the artist has its line, verbatim, with a status (rule 5). Visible faults put off under rule 15 go to the top of the artist list.
- In four groups (rule 16). List every `DEPART:` first, with its overlay picture – only the artist approves a departure (rule 4). Then every `BREAK:`, open QC point, stand-in decision, open `ASSUMED` entry, adopted or dropped proposal (`adopted.md`) and open question, each with a picture where the part is marked and named, so the artist can overrule in one go.
- Feedback with several points goes into the work list first, one line each (rule 5): part · view · kind (design or fault) · the artist's words · goal · what stays fixed – by default the form of the sketch within key `tolerance`. Words like „tighter“, „closer“, „sits together“ ask for fit within that tolerance, never for a changed form (rule 4).

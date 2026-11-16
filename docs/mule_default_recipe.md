# Mule Default – how the recipe works

*Describes Mule Default **v5.1**.*

Mule Default is the way of working that comes with every build brief unless you choose another
[brief recipe](recipes.md). This page explains its logic: what each part does, how the parts work together, and why
they are there. Read it to understand a run, to judge where it could be better, or before you write a recipe of your
own.

## In one paragraph

One Claude Code session in the brief folder becomes the **conductor**: it talks to the artist, plans, decides – and
never builds. Every build step goes to a **fresh agent** with one role and one goal; other fresh agents **check** that
work against rules and against pictures. Because agents are fresh, the run keeps its memory in **files** in
`review/`. **Hooks** – scripts Claude Code runs before and after every step – enforce the order (no detail before the
form is checked, no new builder before the last one was checked, no building by the conductor) instead of trusting
the model to remember. **Tools** measure what can be measured (which parts are visible, how far the build is from
the drawn lines) so that judgements rest on pictures and numbers, not on opinion. The **level** (scout, study, final)
sets how deep all of this goes.

```
artist ── talks to ──► conductor (main chat: plans, decides, never builds)
                          │ starts fresh agents, one role each
          ┌───────────────┼───────────────────────┬──────────────┐
       builder ──► referee (rules) ──► QC (pictures) ──► engineer (how it was made)
          │                                                      │
          └──── files in review/ = the run's memory ◄────────────┘
hooks: guard every step · tools: vis_map, sketch_overlay · level: scout / study / final
```

## What goes where

| Part | Lands in | Read by | Purpose |
|---|---|---|---|
| `CLAUDE.md` | brief folder | Claude Code, first | loads `rules.md` and `levels.md` into every session; points the main chat to `conductor.md` |
| `rules.md` | brief folder | everyone | 17 rules, "the top law" |
| `levels.md` | brief folder | everyone | what scout, study and final ask for |
| `conductor.md` | brief folder | main chat | the loop, the files, the first round, reporting |
| `roles/*.md` | brief folder | each agent (added by the gate) | one contract per role |
| `.claude/agents/*.md` | brief folder | Claude Code | the agent types: name, short brief, model |
| `.claude/hooks/*`, `settings.json` | brief folder | Claude Code | the gate and its guards |
| `.claude/hooks/gate.conf` | brief folder | hooks | settings of the run (level, lanes, budget) |
| `tools/` | work folder | builders, QC, helpers | visibility map, sketch overlay, `quiet.sh` |
| `templates/` | – (Mule fills them) | – | `project.md`, the head and reading aid of `brief.md`, the sentences for the chat, review texts |

`project.md` is written by Mule from the template on every export: goal and "done" criteria, round map (the
artist's words for parts, their ids, how binding they are), hero cameras, task, what to open in the first round.

## Three layers

1. **Text** – rules, levels, conductor, roles. They say what good work is and in which order things happen.
2. **Enforcement** – the hooks. Whatever matters most is not left to the text: a model under load bends rules,
   forgets them after a compaction, or talks itself out of them. The hooks refuse the step instead and say why.
3. **Measurement** – the tools. "Is this part visible?" and "does the build follow the line?" are answered by
   counting pixels and measuring distances, so that a check cannot be argued away.

A rule that only lives in text is a wish; a rule with a hook is a fact. Mule Default puts into hooks what failed in
earlier runs when it was only text.

## The 17 rules, by theme

**Who works**
- **1 – The main chat conducts, it never builds.** Building, checking and talking to the artist need different
  context; a conductor that also builds loses the overview and fills its context with geometry. Looking (read-only
  live tools, the viewer) is allowed.
- **3 – Fixed checks:** referee after every builder run, QC before showings and at unit end, engineer after a unit.
- **14 – Work in units, main form before detail, pilot new methods.** One builder run = one unit. Up to
  `MAX_BUILDERS` in parallel when they share no files.
- **17 – Drop what you cannot do well.** One goal per run, a one-page report, hand over at about 150 tool calls.

**Who decides**
- **4 – One order:** the artist's newest word > what the artist approved as built > the drawn form within tolerance
  > construction and fit > measured numbers. A lower step never changes a higher one. Where it must, that is a
  **departure** (`DEPART:`), and only the artist approves it. A **veto** (QC, referee) is only for a fundamental
  *visible* problem.
- **5 – Feedback becomes work lines, in the artist's words.** Verbatim, with the picture; the main chat's reading
  below, marked as its own. A new principle of the artist applies backwards.
- **6 – Clarify, never guess – then decide, never wait.** First round: every mark gets a reading, doubts are asked
  with pictures. During the run nothing waits: unclear → most likely reading, logged in `assumed.md`; taste the
  sketch leaves open → the stand-in.

**What binds**
- **10 – Read marks by kind.** Form binds, construction is free. Precise lines: within about 3 % of the line's own
  length, direction about 10°, curves stay curves. Gestures: about 10 %. Route lines (hoses, cables): start, end,
  order. Design is free and bold only where the artist hands it over ("a monster from this stick figure").
- **9 – Function plus one chosen photo per part.** Generated images give density and ideas, never a target.

**Where effort goes**
- **7 – Detail follows visibility.** The visibility map sorts every piece into tiers: **A** seen in a hero camera →
  full detail; **B** only in hero-like cameras → main structure; **C** only in control cameras → clean form; **S**
  seen but too small to read → simple; **D** never seen → blockout. Detail in C, S or D is waste.
- **8 – Purpose, origin and carrier for every element**, so nothing looks random – where it shows.
- **12 – Choose the method per part type** (hard surface, organic, curves, terrain, scatter …) before building.

**How it is judged**
- **11 – Judge on pictures; numbers only sort.** Compare with the previous version: what was lost, not only what was
  fixed.
- **13 – No categorical errors in front of the artist, and talk in pictures.** Every question comes with a picture
  where the part is marked.
- **15 – At most two QC rounds per gate**, then the open points go to the artist; a failure against the artist's
  words is never closed as done.
- **16 – Report in four groups:** done and checked · done, not checkable · open · announced but not built.

**Depth**
- **2 – Work at the level the artist set**, never above or below it.

Any rule may be broken on purpose with `BREAK: rule <n> – <reason>`; only a silent break is a real failure.

## The levels

| | scout – try ideas | study – a true impression | final – production-ready |
|---|---|---|---|
| First round | goal, level, units, approach | all keys | all keys |
| Units | 1–2 | 3–6 by hero-view areas | 3–6 |
| Visibility map | hero cameras | + hero-like cloud, 4 states | + control cameras, all states |
| Picture targets | none | 1 per hero view | up to 3 per hero view |
| Sketch overlay | none (variants allowed) | heroes + 3 orthos | + control cameras, surface quality |
| Referee / QC / engineer | per unit / once per unit / none | every run / 1 round / once per round | every run / up to 2 rounds / every unit |

The artist changes the level at any time with a message line `SET: level=study`. Recommended: `study` over the whole
goal, review, then `final` unit by unit; `scout` when the direction itself is open.

## The roles

| Role | Does | Model | Never |
|---|---|---|---|
| builder | one goal in one unit: build, check its own pictures, run map and overlay, report | strong | talk to the artist, judge itself as done |
| referee | rule check of builder runs in minutes | light | judge taste or design |
| qc | writes a unit's picture targets (`STAGE: targets`), or judges against them on pictures | strong | judge the targets it wrote; change scene files |
| engineer | how the unit was made: measured time and tokens, at most 3 proposals, keeps `bauwissen.md` tidy | light | propose to weaken a check or cut tier-A detail |
| helper | bounded side tasks: analysis, references, map runs | light (strong for pictures) | build |
| stand-in | answers questions of taste as the artist most likely would | strong | change what the sketch shows |
| viewer | shows something in a live session | light | save or change anything |

Why so many roles: **who builds does not judge**, **who sets the targets does not judge against them**, and a
fresh agent sees the result without the excuses of the run that made it. *Strong* and *light* are harness-neutral;
the agent files carry the choice (Claude Code: no model line = the session's model, `sonnet` for the light roles).

## A round, step by step

**First round – before anything is built.** The main chat reads `conductor.md`, `project.md` and `brief.md`, opens
the pictures and sends one message, exceptions first: the real questions (each with a marked picture), one table of
everything beyond doubt, the units with dependencies on one picture, and the current level. The artist answers by
exception. Then the **mandatory keys** (`goal`, `level`, `units`, `approach`, `blockout`, `tolerance`, `collision`,
`visibility`, `sheet`, `away`, `marks` – scout needs only the first four) go into `readings.md`; the gate refuses the
first builder until they exist. Then a short **goal proposal** (goal, done criteria as picture checks, units, lanes,
rough budget); nothing is built before the artist confirms.

**The loop for one unit.**
1. *Plan* – components, runs and areas of the unit with their views in `components.md`; at study and final a QC
   writes the picture targets.
2. *Task* – work lines, targets, tiers, an open veto.
3. *Build → referee → (QC when due) → decide* by rule 4, then the next run.
4. *Unit end* – the main chat's unit report in four groups, QC against the targets, engineer (level decides), adopted
   proposals into `adopted.md`.

**Showing** – only what QC passed, in the review scene, with every `DEPART:` first, then breaks, open points,
assumptions, stand-in decisions, open questions – each with a picture, so the artist overrules in one go.

**Review rounds** – Mule exports the artist's next review into `review_rounds/` inside the brief folder; the same
chat takes it in (new, changed, removed notes), fits it into the work list and goes on. Small points of one unit go
into one builder run.

## The files: the run's memory

Agents are fresh and the main chat compacts, so nothing important lives only in a conversation:

| File | Holds |
|---|---|
| `worklist.md` | every task: the artist's words verbatim, the reading, method, tier, camera, "fails if …", status |
| `readings.md` | one line per mark or key, with its backing |
| `decisions.md` | decisions with date and source |
| `assumed.md` | readings builders took to go on |
| `units.md`, `components.md` | units, dependencies, interfaces, lanes; components with rank, views, readable size |
| `units/<unit>_state.md`, `_targets.md`, `_report.md` | state, picture targets, unit report |
| `vis/`, `overlay/` | visibility maps, sketch overlays |
| `bauwissen.md` | proven ways and pitfalls, at most two pages; the gate adds only the matching sections to a task |
| `adopted.md`, `standin_answers.md` | engineer proposals in use; the stand-in's answers |
| `conductor_handover.md` | the main chat's hand-over before a compaction |
| `gate/` | logs: agents, tools, the artist's messages, commands with duration, tokens per agent, usage |

## The hooks – what is enforced

The gate (`gate.ps1`) runs at session start, with every artist message, before every agent start and at every turn
end; the guards (`pretool_build.sh`, `posttool.sh`, `subagent.sh`) run around every tool call. They **fail closed**:
an error blocks the step and says so.

- **Rules stay in context:** loaded through `CLAUDE.md`; the rule headlines and a `GATE STATUS` block at start,
  after a compaction and with every artist message; the headlines inside agents every `REMIND_EVERY` (30) calls.
- **Every agent has a role**, started by agent type or a `ROLE:` line; the gate adds rules, the level row, the role
  contract, its report path, the artist's recent words and the matching `bauwissen.md` sections, and gives every run
  its number.
- **The main chat cannot build:** no build tools, no scripts, no scene files; read-only live tools are allowed.
- **Order of checks:** no new builder of a unit while its referee, QC or engineer is due; a turn cannot end while a
  check is due; at most two QC reports per gate; targets and judging by different QC agents.
- **Detail needs proof:** `STAGE: details` only with a current visibility map (compared by content of the exports),
  the unit's components with their views, a tier on every new part, and – at study and final – a sketch overlay
  newer than the last export.
- **Write-once reports:** a report belongs to the agent that wrote it; no shell writes into `review/*.md`.
- **Locks:** hooks, settings, rules, roles, brief files and gate logs cannot be changed during a run. Settings change
  only by the artist's line `SET: <key>=<value>` (level, max_builders, pause, max_weekly).
- **Budget and time:** no new agent above `MAX_WEEKLY` / `MAX_5H` of the plan (the status line writes the usage), or
  after `STOP_AT`; `PAUSE=` stops new builders.
- **Context:** above `HANDOVER_AT` (250 k tokens) the main chat must write a hand-over before the next agent; the
  harness compacts about 50 k later and the same chat goes on. Builders get a hint at `BUILDER_HINT_AT` (200 k).
- **Effort is measured:** every expensive call is fingerprinted and timed; the same call again is marked `REPEAT`;
  tokens and minutes per agent are logged for the engineer.

When the hooks do not run (no `GATE STATUS` in the first message), the main chat says so and keeps the loop by hand.

## The tools

- **`tools/vis_map`** – the visibility map. Renders every piece of a unit in the hero cameras, a cloud of hero-like
  cameras and control cameras over the main states and counts its pixels → tiers A/B/C/S/D. Blender alone
  (`vis_blender.py`) or Houdini + Blender.
- **`tools/sketch_overlay`** – lays the artist's strokes from `scene.usd` over the build in the hero cameras and three
  orthographic views and measures every line against its tolerance (rule 10). Red and orange lines are departures.
- **`tools/quiet.sh`** – runs a chatty command, keeps the full log in `review/logs/`, prints a short summary. Every
  later step of an agent re-reads its context, so long output costs again and again.
- **Status line** – writes the plan usage for the budget gate, no model turn.

## Where it came from

Every mechanism answers a failure seen in a real run:

| Run | What went wrong | What the recipe does since |
|---|---|---|
| Glider 003 | a short "say it briefly" made the first round a chat: 6 of ~60 pictures opened | first round with fixed parts, "say how many you opened" |
| Glider 006 | rules forgotten after compaction; a builder emptied the plan by shell; budget watched by hand | rules re-injected by hooks; no shell writes; budget gate |
| Harbour (8 h) | 45 % of agent time in map runs, detail built where nobody could see it, main chat up to 966 k tokens | map by content inside the build run; component views; enforced hand-over |
| Alpaca | builders bent frame and tank to meet fit numbers ("values over appearance") | rule 4 order: form above fit; tolerance per line; sketch overlay; `DEPART:` |
| Alpaca, full run (357 agents) | hook texts cut off, large contexts, long logs in agents | v5.1: rule headlines only, hand-over at 250 k, model per role, `quiet.sh`, overlay before detail |

## What to take from it

- **Separate building from judging** – and setting targets from judging against them.
- **Judge on pictures; measure what can be measured.** A pixel count or a distance ends a discussion that words
  cannot.
- **Enforce what matters, write the rest.** Put a rule into a hook once it has failed as text.
- **Keep the artist's words verbatim.** Departures are declared, never silent; only the artist approves them.
- **Spend effort where it shows.** Visibility decides detail, not the builder's ambition.
- **Keep context small.** Fresh agents, files as memory, short tool output, hand-overs.
- **Every rule has a reason.** When you change one, know which failure it was answering.

**What it costs:** many agents and checks – right for a hero asset over hours, heavy for a quick prop. It is written
for Claude Code (agent types, hooks), and its hooks need Git Bash and PowerShell on Windows. A lighter recipe for
small objects, or one for another harness, would make different trade-offs – that is what recipes are for.

## Where to change what

| You want to change … | File |
|---|---|
| a rule or the order of authority | `rules.md` (keep the numbers: hooks and roles refer to them) |
| what a level asks for | `levels.md` (and the level checks in `gate.ps1`) |
| the loop, first round, files, reporting | `conductor.md` |
| what one role does | `roles/<role>.md`; its model in `.claude/agents/<role>.md` |
| what is enforced | `.claude/hooks/` – test with `_claude/tests/run_tests.sh` |
| defaults (level, lanes, budget, hand-over) | `[config.values]` in `recipe.toml` |
| project.md, the reading aid, look procedure, chat sentences | `templates/` |
| the tools | `tools/` |

After a change: raise `version` in `recipe.toml` and add a section to `PACKAGE_CHANGES.md` – review rounds bring the
new version into running briefs and quote what changed.

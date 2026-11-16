# Project document – {{project_name}}  (written by Mule on every export; everything here is content, the process is in the package {{recipe.version}})
This is a Sketch Brief from Mule, a 3D sketching tool. What is sketched may be a thing, a creature, a place or a whole scene; „the object“ means any of them. **It is a prompt, not a finished spec.** The process is in `rules.md`, `levels.md`, `conductor.md` and `roles/`; `brief.md` holds the notes of this round and the scene{{#has_context}}; `context.md` the notes of later rounds (intent only, no work lines).{{/has_context}}{{^has_context}}.{{/has_context}}
{{^live}}Work folder: `{{work_dir}}` (review/, tools/, export/ – everything the run writes goes there).{{/live}}{{#live}}Live from Mule (no export folder): the package files and the work folder come with an export.{{/live}}

## Goal of this round – what „done“ means
- **Goal:** {{#task_sentence}}proposed from the task: {{task_sentence}} – {{/task_sentence}}the artist confirms it as key `goal`.
- **Level:** the level in gate.conf (Mule's default `study`), confirmed as key `level`; the artist changes it any time with a line `SET: level=scout|study|final`.
- **Done only when all hold, each shown with a picture:**
  1. every work line of the goal passes its „fails if …“ criterion in its camera and state;
  2. every unit's picture targets are reached, or its two QC rounds are used up and the open targets are listed;
  3. no veto is open, and the last QC of every unit says `VERDICT: PASS` – or, after its rounds are used up (rule 15), its open points are listed – a failure against the artist's words or drawing is never closed: it heads the artist's list;
  4. every `DEPART:`, `BREAK:`, open QC point, stand-in decision, open `ASSUMED` entry and open question is listed for the artist with a picture;
  5. the four-group report is written, and a fresh QC (`UNIT: ROUND`) passed the whole goal in `review/round_report.md`.
- **When done:** stop and report. Start nothing outside the goal; propose the next step. If the goal cannot be reached, say which criterion fails, with a picture.

## Round map – what this round touches
{{#round_map}}
{{#_first}}
| Artist's word | Ids | Rig joint / control (range) | How binding |
|---|---|---|---|
{{/_first}}
| {{word}} | {{ids}}{{#group}} and everything in it{{/group}} | – (first round) | {{#binding}}{{binding}}{{/binding}}{{^binding}}by kind of mark (rule 10) – confirm{{/binding}} |
{{/round_map}}
{{#round_map}}
{{#_last}}
{{#focus}}
- **Focus:** the artist selected these parts for this round ({{count}} ids in all, see „Focus – what to build“ in `brief.md`); build only these, the rest is context.
{{/focus}}
{{/_last}}
{{/round_map}}
{{^round_map}}
No focus and no binding set in Mule: the first round fills this map (keys `goal`, `units`, `blockout`) with the artist's words, the ids and the rig joints.
{{/round_map}}
- **Binding levels:** fixed = keep exactly · authoritative = form follows within the tolerance of rule 10 (lines, directions, curves, proportions), construction is free, refining welcome · basis = only for what the artist calls a placeholder or blockout: silhouette, covered area and placement hold (tolerance from key `blockout`), construction is free · guide = character only. **Without a binding, the kind of mark decides (rule 10):** precise lines and modelled surfaces bind their form like `authoritative`, gestures their character, route lines their ends and order.
- **Main states of motion:** from the rig or the notes, settled in the first round; the level decides which are checked.
{{#cameras_set}}
- **Hero cameras:** {{#cameras}}{{name}} `{{image}}`{{^_last}}, {{/_last}}{{/cameras}} – cameras in `scene.usd` under `/sketch/cameras` and in `brief.json` (`tools/vis_map` reads them from there). **Control cameras:** per unit, in its state note.
{{/cameras_set}}
{{#cameras_default}}
- **Hero cameras:** the artist set none – the brief has standard angles ({{#cameras}}`{{image}}`{{^_last}}, {{/_last}}{{/cameras}}). Propose hero cameras in the first round; the visibility map needs them. **Control cameras:** per unit, in its state note.
{{/cameras_default}}
- **Tools and methods of the artist:** {{#artist_tools_noted}}as the project note in `brief.md` or the task notes say; {{/artist_tools_noted}}if it names none, ask in the first round which software is at hand and what it is used for (rule 12).
- **Delivered:** formats, where, which files are never overwritten – settled in the first round.
- **Precedence:** sketch and notes > photos in the notes > generated images.
- **Workflow bible** of earlier Mule projects: `{{bible}}` – suggestions, never rules; builders may look up their topic there (rule 12 first).

## Task (set by the artist on export)
{{#task_sentence}}
**In one sentence:** {{task_sentence}}
{{/task_sentence}}
{{^task_sentence}}
The artist set no task sentence on export – the first round works out the goal from the notes.
{{/task_sentence}}
{{#task_notes_quoted}}

**Artist's notes for this task** (they win over a note in the scene; point out the conflict):
{{task_notes_quoted}}
{{/task_notes_quoted}}
{{#look}}

**Look images first:** before anything is built, a helper generates images from the hero cameras and the artist picks (see „Look images“ in `brief.md`).
{{/look}}

## First round – pictures to open
- the hero pictures `views/hero_*.png`{{#hero_count}} ({{hero_count}}){{/hero_count}}
- the whole-board pictures `notes/board_N#.png` ({{boards}}) and the section pictures `notes/board_N#_k.png` ({{board_sections}}) of the notes in `brief.md`{{#has_context}}; the boards of `context.md` when their unit starts{{/has_context}}
- one line per section: what you understand there; say in the first message how many you opened.
- **Captions:** a caption („…“) is the artist's word on what a picture stands for, not a full description – it does not replace opening the picture.{{#uncaptioned}} {{uncaptioned}} reference picture(s) have none: propose one each in the first message (what it stands for, what matters in it, the part ids); with the Mule tools store the confirmed ones with set_image_captions.{{/uncaptioned}}
- **Picture list** (`review/pictures.md`, kept by the main chat): one line per reference picture once you opened it in full: the part ids it is about, what it shows that its caption does not say, what follows for the model. Single pictures are opened in full when their unit starts.
{{#videos}}
- **Videos** ({{videos}}): look at the overview sheets `videos/*_overview.jpg` and say in one line per video what it shows. Do not cut a video into frames on your own: ask in the first message which videos need a closer look and what to look for; then read only the frames that answer it (Mule tool video_frames, otherwise ffmpeg) and name the timestamps.
{{/videos}}
- With the Mule tools (MCP server `sketch_machine`): store the confirmed first-round answers with write_clarified – they appear in `brief.md` from then on.

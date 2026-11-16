# tools/vis_map – the visibility map (rule 7)
A measurement, not a judgement: how many pixels every **piece** (connected part of a mesh) of a unit gets in the hero cameras, a cloud of hero-like cameras and the control cameras, over the main states, with the whole object as occluder. Run by a helper (or a builder) headless; never in a live session, never saving a scene.

## Run – Blender (free; one command)
```
blender -b --factory-startup -P tools/vis_map/vis_blender.py -- review/vis/<unit>_config.json [--skip_render] [--only_states rest] [--max_cams N] [--no_pics]
blender -b --factory-startup -P tools/vis_map/vis_blender.py -- --selftest
```
Reads the `.blend` of the config read-only (never saves), evaluates modifiers, geometry nodes and instances per state, then counts in the same process. `--selftest` checks the tool itself on a synthetic scene (a seen box must be A, a box sealed in a shell D, a speck of a few pixels S, one object with two islands two pieces) – run it once on a new machine; it prints `SELFTEST PASS`. Tested with Blender 5.0 and 5.2.

## Run – Houdini (hython for the geometry, Blender for counting)
```
hython  tools/vis_map/vis_export.py -- review/vis/<unit>_config.json      # scene read-only -> geometry per state + cameras (~15 s)
blender -b --factory-startup -P tools/vis_map/vis_map.py -- review/vis/<unit>_config.json [--skip_render] [--only_states rest] [--max_cams N]
```
Both ways write the same cache (Y up, metres, like the brief), so tiers are comparable. `--skip_render` reuses the stored pixel counts and only recomputes tiers, report and pictures. Typical run: well under a minute for a small unit, 2–6 min for a big one with many states and cameras (glider test: 3 million triangles, 2 states, 18 cameras, 17 s).

## Output (in `out_dir`, normally `review/vis/`)
- `<unit>_vis.md` – the report the gate hook checks: tier per part and per piece, totals, stability of variants.
- `vis_<unit>.json` – everything as data; `vis_<unit>_tier_attr.json` – tier per piece, to write back as prim attribute `vis_tier` at the end of the run.
- `pic_<unit>_*.png` – judging pictures: whole object grey, the unit coloured A green, B yellow, C orange, S violet, D red.

## Tiers
A above the threshold in a hero camera or a component view · B only in the cloud or a random component view · C only in control cameras · S seen somewhere but below the threshold everywhere (too small to read) · D not one pixel anywhere (hidden).

## Config (JSON, one per unit)
| Key | Meaning |
|---|---|
| `unit` | unit id, names the output files |
| `hip` | Houdini scene, loaded read-only, never saved – or `geo_files: [paths]` (any geometry, no states) |
| `blend` | (Blender) the `.blend`, opened read-only |
| `target` | (Blender) the unit: `{"collection": name}`, `{"objects": [names]}` or `{"regex": "..."}` on object names; instances count for the object that instances them |
| `states` (Blender) | `{name: {"frame": 12, "props": {"objects[\"Rig\"][\"Fold_In\"]": 0.5}}}` – a frame and/or properties as Python paths relative to `bpy.data` |
| `hero_cams` (Blender) | camera object names in the `.blend`, in addition or instead of `brief_json` |
| `objects` | Houdini: `"displayed"` or a list of /obj paths; Blender: `"visible"` or a list of object names (the occluders) |
| `target_object` | /obj path of the unit to classify |
| `part_attrib` | prim (Houdini) or face (Blender) string attribute naming the parts (fallback: object name) |
| `occluder_attrib` | optional prim attribute to split occluders |
| `states` | `{name: {"/obj/node/parm": value}}` – rest, middle, end, one extreme at least (key `visibility`) |
| `brief_json` | path of the brief's `brief.json` – its hero cameras (the views of `views/hero_*.png`) are used directly; `hero_names: [ids]` picks some. Normal case. |
| `hero_cams` | camera node paths in the scene, in addition or instead (e.g. a hero camera that rides on the rig) |
| `control_cams` | `"NAME:ex,ey,ez:tx,ty,tz:hfov"` in world coordinates, Y up |
| `cloud` | `{n: 16, ang_deg: 15, dist_frac: 0.2, seed: <fixed>, pivot: "median_hit"}` |
| `brief_scale` | the scene is the brief scene scaled by this factor about the origin; the brief's hero cameras follow (default 1) |
| `component` | component views (rule 7), one config per component: `{name, rank: 1\|2, parts: "<regex on part names>", views: [{name, az, el, why}], front: [x,0,z], fill, hfov: 40, carrier: "<regex on occluder names>", random: {n: 2, el: [0, 35], seed}}`. The cameras come from the bounding box of `parts`: az in degrees around +Y from `front` (default +X), counter-clockwise from above, el above the horizon; the component fills `fill` of the picture width (rank 1: 0.6, rank 2: 0.3). In these views the component stands alone: occluders are hidden except `carrier`, other parts of the unit too. Views count like hero cameras (A), random views like the cloud (B); random views are never pictured. Writes `<unit>_views.json` (eye, target, fov per view, for builders, QC and viewer) and a report section with the **readable size** in metres and the blind spots (read only in a random view – a view may be missing). Pictures: one `pic_<unit>_view_<view>_<state>.png` per view. For an asset with many instances, point `parts` at one sample instance. |
| `clip_near_frac`, `clip` | camera clip range: far from the scene extent per camera, near = frac × far (default 5e-5, ≥ 0.05 m; 1e-3 for km-scale terrain against z-fighting); `clip: [near, far]` fixes both |
| `res_x` | picture width, default 960 |
| `thresholds`, `threshold_main` | e.g. `[20, 100]`, `20` (pixels per piece) |
| `cloud_sizes` | e.g. `[16, 32]` – the smaller cloud is the first n of the larger |
| `part_alias` | `{regex: part}` when a state swaps geometry under other names |
| `pictures` | `{heroes: 3, overview: [control cam names], overview_hide_occluders: true, overview_hide_parts: [regex]}` |
| `cache_dir` | big temporary files, e.g. `tools/vis_map/cache/<unit>` |
| `out_dir` | `review/vis` |

Defaults come from the first round (key `visibility`, see `conductor.md`).

## Check before trusting a new setup
- Tool: `vis_blender.py -- --selftest` must print `SELFTEST PASS` (includes a component view: a speck that is S in the hero camera must be A in its own view).
- Project: the hero pictures `pic_<unit>_<camera>_<state>.png` must frame the object like `views/<camera>.png` of the brief (same camera); a part clearly seen there must be A. If not, fix cameras, axes or objects before using the map.

## Known limits – say them in the report when they matter
- Everything counts as opaque. See-through surfaces (membranes, glass, nets): if the first round says they do not hide what is behind, run a second pass with them left out of `objects` and take the higher tier.
- All cameras use the aspect of the first hero camera (horizontal angle kept); a hero picture of another aspect shows a little more above and below.
- At most 65,535 pieces per run (the ID colour holds r + 256 g). Huge scatters (forests): realize them into clusters with a face or prim string, set `islands: false`.
- Control cameras are fixed in the world; cameras that ride on a joint are not covered – add states instead.
- Piece names follow primitive connectivity; they stay stable only while the topology stays the same (checked; otherwise part level).
- Thin parts near the threshold react to the resolution; the variants table shows how stable the tiers are.


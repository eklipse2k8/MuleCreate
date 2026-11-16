# tools/sketch_overlay – the artist's strokes over the build (rules 10 and 11)
A measurement on pictures, not a judgement: the Mule strokes of `scene.usd` are laid over the built geometry in the hero cameras of the brief and three orthographic views, and every line is measured against what the build shows there. Builders run it before publishing a changed form, QC at every check. Headless, read-only: it never saves a scene.

## Run (Blender 4.2 or newer; uses Blender's own `pxr` to read the strokes)
```
blender -b --factory-startup -P tools/sketch_overlay/sketch_overlay.py -- review/overlay/<name>_config.json
blender -b --factory-startup -P tools/sketch_overlay/sketch_overlay.py -- --selftest
```
`--selftest` builds tubes and a panel along drawn lines: true copies must pass; a line built shifted, straightened, flattened, missing or a panel edge built lower must fail. It prints `SELFTEST PASS`. Typical run: 20–30 s for a whole object of about 700 lines in 18 views.

## What it measures – per line, per view
What the line shows in that view decides what the build must show:
- **an edge of the sketched form** (outline or crease of the artist's surfaces) → an edge of the build nearby;
- **a line on a sketched surface** → the built surface at the same place (the depth difference counts);
- **a free line** (frame, rod) → a tube around it (its middle counts) or an edge nearby.

Then three numbers, all scale-free:
- **distance** – typical offset (80th percentile over the line, ends left out) as a share of the line's own length in that view;
- **direction** – how much the build's run differs from the line's, in degrees (75th percentile);
- **curves** – a drawn bow must stay a bow in the same direction (not flattened below 40 %, not flipped), a straight must stay straight.

**A finding counts when an orthographic view or two views agree** (distance also when one view sees most of the line beyond twice the tolerance): a single perspective view can mislead – a line grazing a silhouette, a view nearly along the line. Hidden stretches (something else in front) are not judged in that view; a line seen in no view is listed as „not seen“. Offsets below `min_px` (3 px) do not count – below the readable size nothing is judged (rule 7).

## Output (in `out_dir`, normally `review/overlay/`)
- `<name>_overlay.md` – FAIL lines first: kind, what fails, worst distance, direction, curve, where (view and pixel);
- `overlay_<name>.json` – everything per line and view;
- `ov_<name>_<view>.png` – the build in grey with the strokes: **green** within tolerance, **red** beyond, **orange** nothing built there, **blue** hidden in this view.

Numbers sort, pictures judge (rule 11): open the picture of every FAIL line before acting on it.

## Config (JSON)
| Key | Meaning |
|---|---|
| `name` | names the output files (e.g. `U4_b052`) |
| `scene_usd`, `brief_json` | the newest `scene.usd` (strokes, sketched surfaces) and `brief.json` (hero cameras): those of the latest review round (`review_rounds/review_NN_<date>/`) if there is one – marks drawn in a review exist only there, and line ids may shift between exports. A name that occurs twice gets its parent added (`L476@S30_board`) |
| `geo_files` | the build: `.usd/.usdc/.usda`, `.obj`, `.fbx`, `.abc`, `.glb`, `.ply`, `.stl` (USD subdivision is applied) |
| `blend` | instead or in addition: a `.blend`, opened read-only (modifiers and instances evaluated) |
| `brief_scale` | the build is the sketch scaled by this factor about the origin (like `tools/vis_map`); strokes and cameras follow. Default 1 |
| `geo_rotate_x` | `"auto"` (default): a file whose up axis did not carry over (a Y-up export imported raw lies on its side) is turned 0, +90 or −90° about X, whichever puts it into the sketch's box – printed as `OVERLAY_GEO` and in the report; or a fixed number for all files |
| `marks_on_imports` | `true` (default): marks the artist drew on an **imported copy of the build** in Mule (a review on the last round's model, placed beside the sketch) are mapped back onto the build with that import's placement from `scene.usd`. Mule's mirrored copies of such marks lie beside the build and are left out – judge the drawn side |
| `objects`, `hide` | regex on object names: only these / not these (reference figures, ground, helpers) |
| `lines`, `exclude_lines` | regex on the stroke's USD path (`…/S12_frame/L345`): which lines to judge – normally the unit's parts |
| `kinds` | `{regex on the path: "precise" \| "gesture" \| "route" \| "ignore"}` from the readings (rule 10); default `default_kind` = `precise` |
| `tolerance` | overrides per kind from key `tolerance`, e.g. `{"precise": {"dist": 0.03, "angle": 10}}` |
| `views` | `"all"` (default), `"hero"` or `"ortho"`; `hero_names: [ids]` picks hero cameras |
| `ortho_frame` | regex on line paths that frames the three orthographic views (default: all judged lines) |
| `sketch_meshes` | `true`: imported meshes M# of the sketch count as sketched surfaces too (default: only the F# surfaces) |
| `use_sketch_surfaces` | `false`: every line counts as a free line |
| `include_paint` | painted strokes count too (default: left out – painting marks, it does not draw form) |
| `res_x` (1200), `min_px` (3), `crease_deg` (35), `min_line_px` (40) | picture width; offsets that do not count; crease angle; shorter lines in a view are not judged there |
| `out_dir` | `review/overlay` |

## Known limits – say them in the report when they matter
- Rest state only: the sketch is drawn at rest. Moving parts are judged in that state.
- Kinks are judged on the pictures (a kink that became a round bend shows as a short red stretch).
- A tube's centre line far beside its tube is measured to the tube's middle only when the tube is narrow (under 20 % of the line's length); otherwise to its near edge.
- Mirrored and arrayed copies are separate lines (`…__copyN`); judge one side if both are built by mirroring.
- Short marks (a few cm) are below `min_line_px` in views of the whole object: limit `lines` to the unit – the orthographic views then frame those lines closely.
- Lines the artist replaced by later marks, departures the artist approved, and parts the artist approved **as built** („great“, „keep“): mark them `ignore` with the decision as the reason – the overlay never pulls an approved part back to the sketch.
- Lines the artist drew for construction or reference (a scale figure, a ground line, size helpers) are not built – mark them `ignore` in `kinds` or leave them out with `lines`.

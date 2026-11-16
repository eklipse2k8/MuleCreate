## Your role: QC (fresh, did not build)
You check the result, not the process – on pictures, at the level in GATE (`levels.md`).

### `STAGE: targets` – at unit start
Read the unit's notes and readings, the references, the latest pictures and `review/vis/<unit>_vis.md`. Write `review/units/<unit>_targets.md`: per hero view and per component view (`review/components.md`, pictures `pic_<unit>_view_*`) as many targets as the level allows, each about one tier-A area; a component view is judged down to its readable size, never finer:
`hero view · area · what must read there, by function (parts, count, relation) · state of motion`

Never „like the generated image“ (rule 9); generated images may only show how dense. For taste, ask the stand-in through the main chat. You do not judge this unit later.

### Check – at unit end and before every showing
Read the rules, the unit's work lines and targets with their sources, `readings.md`, the latest sheet, the previous version, the builder's claims and the visibility map. Work from the builder's sheet and the review scene first; render your own pictures only for what they do not show, headless or on a copy, never in the artist's live session. Never change, save or export scene files.
1. **Targets:** each one reached or not, with a picture.
2. **Work lines:** visible in their camera and state; do they pass „fails if …“? **Judge against the artist's words in the line, not only its wording:** a result that meets the wording but misses the artist's intent fails (severity 3) – also when the cause lies in another unit. Then name that unit and the work line it needs; the gate is not passed as done.
3. **Shape** against notes, sketch, references and the previous version: silhouette, proportions, character, what was lost.
   - **Sketch overlay** (`tools/sketch_overlay`, hero cameras + three orthographic views; run it yourself if the builder's is older than the build): every FAIL line, judged on its picture. A precise line visibly beyond its tolerance (rule 10) in a camera of the level, without `DEPART:` in the builder's report, is severity 3 – fit never excuses form (rule 4). A declared `DEPART:` is listed for the artist, not vetoed – unless it is plainly not needed or not the smallest: then it counts as undeclared. Lines the artist approved as built or replaced are not judged against the old strokes.
   - **Surface quality:** tier-A surfaces whose reference is smooth (painted metal, polished stone, glass, plastic, a calm water surface) in a shaded render with reflections (matcap or zebra stripes): a dent, fold, stretched or lumpy area seen from a camera of the level is severity 3.
4. **Categorical errors** visible in the cameras of the level: floating, unconnected, broken, impossible.
5. **Waste:** detail in tiers C, S or D (rule 7), severity 2 – name the largest pieces and their polygons from the map.
6. **Uncovered notes:** notes on the unit's parts that no work line or reading covers.

Hidden contacts and hidden logic gaps are notes, never severity 3.

**Findings:** positions on the picture, severity 1–3. Only severity 3 (rule 4, or a failed work line) is a VETO. A missed target is not a veto, but the unit is not done until its targets are reached or two rounds have passed (rule 15).
**Instead of „not dense enough“ give at most 3 work lines:** where · what · for which view. They go straight into the work list.

Write at most one page to the file named in GATE. First line `VERDICT: PASS` or `VERDICT: VETO - <severity-3 findings>`, second line `TARGETS: <reached>/<total>`.

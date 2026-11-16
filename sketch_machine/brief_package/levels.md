## Levels – how deep this round builds (rule 2)
The artist sets `LEVEL` in gate.conf, or by a message line `SET: level=<scout|study|final>` (the hook writes it). The gate adds the row of the current level to every agent prompt. Each level is complete in itself; nothing of the next level is owed.

| | **scout** – try ideas | **study** – a true impression | **final** – production-ready |
|---|---|---|---|
| Purpose | compare ideas and variants fast, decide direction | looks convincing in the hero views; small faults are fine | the asset as delivered |
| First round | keys `goal`, `level`, `units`, `approach`; marks only where they change the main form; everything else `ASSUMED` | all keys; marks of the first units now, the others when their unit starts | all keys; marks of the first units now, the others when their unit starts |
| Units | 1–2 for the whole goal | by hero-view areas (3–6) | by hero-view areas (3–6) |
| Visibility map (rule 7) | hero cameras only, rest and one extreme state | heroes + hero-like cloud, at least 4 states (rest, middle, end, one extreme) | heroes + cloud + control cameras, all main states |
| Component views (rule 7) | none; ranks only | rank 1 | ranks 1 and 2 |
| Detail by tier | A: main structure legible; B–D: blockout | A full; B main structure; S and D form only (no tier C: control cameras are not in the map) | A full; B moderate; C clean form; S simple and light; D blockout and carrier only |
| Picture targets (QC) | none | 1 per hero view | up to 3 per hero view |
| Sketch overlay (rule 10) | none; departures allowed as named variants (`DEPART:`) | hero cameras + 3 orthos: builder before publishing, QC at every check | as study, plus the control cameras; surface quality on tier A |
| Referee | once per unit, over all its runs | after every builder run | after every builder run |
| QC | once per unit, at its end, before showing | at unit end and before showing, 1 round | at unit end and before showing, up to 2 rounds (rule 15) |
| Veto counts | broken or missing in a hero view | floating, broken, obvious intersection, a drawn line clearly off in a hero view | everything in rule 4, in hero and control cameras |
| Collisions | ignored | hero views, rest state | as the key `collision` says |
| Engineer | none | once per round | after every unit |
| Materials | colour ids | preview materials | as the project asks |
| Procedural assets, kits | placeholders; reuse only | reuse; new ones only after a pilot | as rule 12 |
| Builder report | half a page | one page | one page and the sheet |

**Moving up:** a later round may raise the level on the same work. `study` → `final` keeps units, files, readings, decisions and the visibility map; the final round adds the detail of tiers B and C, the full picture targets and the full checks, unit by unit, starting with the units the artist names. `scout` → `study` or `final` keeps goal, readings, decisions and units; its geometry serves as blockout (binding level `basis`) and may be rebuilt.

**Recommended path for a new asset:** `study` over the whole goal, artist review, then `final` unit by unit where the review says so. `scout` when the direction itself is still open.

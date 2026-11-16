# Tests

## Three levels

| Level | What | Duration | When | Command |
|---|---|---|---|---|
| 1 Core | data model and calculation without a window | seconds | after every change | `python tests/run.py --core` |
| 2 Operation | the real program in a real window, real mouse events | minutes | the affected area while working, everything before every commit to the shared core | `python tests/run.py [name part …]` |
| 3 Large | review run and measurement on the harbour scene | minutes | after every step of the rebuild plan, before every package | `python tests/run.py --gross`, `python bench/hafen.py` |

Without arguments, levels 1 and 2 run, the fast ones first.

A test file belongs to level 1 if it carries the line `LEVEL = "core"`. Its tests get `h = None` and no window is
opened; the harness check modes still apply. Everything else is level 2.

Level 3 needs the frozen harbour scene (`Feedback/2026-11-11_architektur/messlatte/hafen_messlatte.mule`); it is not
in Git.

## Results

`OK`, `FAIL`, `EXPECTED` (known problem, marked with `@expected_failure("reason")`), `FIXED`
(the known problem works again – remove the marker). A full run is green if it has no `FAIL`.

Level 2 runs in real windows: if you work on the machine meanwhile, you occasionally get false alarms (focus). Recheck
them individually.

## Check modes

In every test the harness switches on check modes that compare a fast path against the safe, slow one
(`SM_FAST=1` turns them off for measurements):

| Check mode | compares |
|---|---|
| `Renderer.VERIFY_STROKES` | partial upload of the strokes and the remembered surface table against the full preparation |
| `DisplayListMixin.VERIFY_LISTS` | remembered stroke entries per line object against freshly assembled ones |
| `SurfaceSyncMixin.VERIFY_SYNC` | skipped and co-moved surfaces against the full reconciliation; report book against the stamp |
| `Scene.VERIFY_UNDO` | shared undo copy against the full copy |
| `Scene.VERIFY_INDEX` | directories (object, line to an id) against the search over all lists |
| `SurfaceObject.VERIFY_KEY` | remembered surface key against the recomputed one |

A check mode only catches what a test plays through. Every change to reconciliation, undo or display is therefore also
reviewed by a second, independent agent (this is how two gaps in the report book were found on 12 Nov. that all tests
had let through).

## Rules for new tests

- What can be checked without a window goes into level 1.
- Read the scene through the harness queries (`h.world(line)`, `h.object_of(line)`, `h.connected(a, ka, b, kb)`,
  `h.surfaces_of(obj)`, `h.shape(surface)`), not through inner fields such as `curve.points` or `curve.pids`. With the
  object islands and the placement per object (rebuild plan, stage 2), where points live and how connections are
  stored will change; then the harness is adapted instead of every test. Old tests are converted when they break.
- Never check speed by the clock, but by the work counters (`sketch_machine/counters.py`, example
  `tests/test_messlatte.py`): times depend on the machine, counters do not.
- Never compare nets by point count or `np.allclose` without a shape check (the subdivision depends on curvature).
- Compare images only with a fixed texture offset (`surface.seed = 1.0`).

## Benchmark ("Messlatte")

`tests/test_messlatte.py` keeps in `BEKANNT` which counters still grow with the size of the scene. If a new one grows,
the test fails; if a known one stops growing, it fails too (remove the entry). The list is the work list of the
rebuild.

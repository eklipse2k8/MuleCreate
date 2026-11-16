"""Random strokes: many random strokes through all input paths, then fixed rules (not just the cases the artist
found). Rules:

  R1 No new line end lies closer than the snap tolerance (12 px on screen, at the depth of the end) to a
     visible line and still stays loose (it must be a shared point).
  R2 Where the stroke leaves a surface, enters it or switches to the neighbouring surface, a line end lies on a
     border line of the surface (connected); on a switch both pieces share the point.
  R3 Every crossing with a line of the same surface/plane or one of its border lines is a shared point.

Input paths: single and multi mode, curve surfaces, fill surface, loft, ground plane; smoothing on/off; slow/fast;
holding still at the end (straight line/recognized shape). Count: environment variable SKETCH_FUZZ (default 120), random sequence:
SKETCH_FUZZ_SEED (default 7). Before the connection rule (v0.84.6): 29 violations with 120 strokes; since v0.85: none
(also 5 × 300 strokes with other sequences). Report with examples: tests/_out/zufall.txt.
"""
import os
import random

import numpy as np

from tests.harness import H, QPointF
from sketch_machine import network
from sketch_machine.scene import SurfaceObject

N = int(os.environ.get("SKETCH_FUZZ", "120"))
# Surface seen almost edge-on: a few pixels are a long way in the world there, exit and border can no longer be
# assigned from the path – R2 does not apply there (status: a stroke start may stay unconnected there).
GRAZING = 0.2


def _grazing(h, surface, w):
    """|cos| between view and surface normal at the triangle near w (1: head-on, 0: edge-on); no surface: 1."""
    if not isinstance(surface, SurfaceObject):
        return 1.0
    verts, tris = surface.fill_mesh()[:2]
    corners = np.asarray(verts)[np.asarray(tris)]
    near = corners[np.argmin(np.linalg.norm(corners.mean(axis=1) - np.asarray(w, float), axis=1))]
    n = np.cross(near[1] - near[0], near[2] - near[0])
    view = h.v.cam.eye - np.asarray(w, float)
    return float(abs(n @ view) / max(np.linalg.norm(n) * np.linalg.norm(view), 1e-12))
SEED = int(os.environ.get("SKETCH_FUZZ_SEED", "7"))
R1_FACTOR = 0.75  # check rule 1 with some margin to the tolerance (rounding, smoothing)
SNAP_PX = 12


def _surface(h, name):
    return next(s for s in h.sc.surfaces if s.name == name)


def _setup(h, kind, rng):
    """Load scene, set mode; returns (target surfaces, multi?, range (lo, hi) for the strokes)."""
    sc_path = {"v002": "tests/scenes/netz_multi_v002.sketch.json", "task5": "tests/scenes/topologie.sketch.json",
               "fill": "tests/scenes/netz_fuellflaeche_kreuz.sketch.json"}.get(kind)
    if kind == "loft":  # curved loft from three cross sections with side lines
        from tests.test_topology import _loft3
        h.new_scene()
        lo, _ = _loft3(h)
        h.draw_mode()
        h.v._activate(lo)
        verts = lo.fill_mesh()[0]
        lo_, hi_ = verts.min(axis=0), verts.max(axis=0)
        h.camera((lo_ + hi_) / 2, float(np.linalg.norm(hi_ - lo_)) * 1.6, [0.05, 1.0, 0.05])
        return [lo], False, (lo_, hi_)
    if kind == "plane":
        h.new_scene()
        sc = h.sc
        sc.new_stroke()
        for a, b in (([0, 0, 0], [8, 0, 0]), ([8, 0, 0], [8, 0, 6]), ([2, 0, -1], [3, 0, 7]), ([0, 0, 4], [9, 0, 3])):
            sc.add_curve(np.linspace(a, b, 30), sc.planes[0].id)
        h.v._changed()
        h.v._activate(sc.planes[0])
        lo, hi = np.array([-1.0, 0, -2]), np.array([10.0, 0, 8])
        h.camera((lo + hi) / 2, float(np.linalg.norm(hi - lo)) * 1.2, [0.0, 1.0, 0.01])
        return [sc.planes[0]], False, (lo, hi)
    h.load(sc_path)
    sc = h.sc
    if kind == "task5":
        surfs = [_surface(h, n) for n in ("Kurvenfläche 7", "Kurvenfläche 8", "Kurvenfläche 9")]
    else:
        surfs = list(sc.surfaces)
    verts = np.vstack([s.fill_mesh()[0] for s in surfs])
    lo, hi = verts.min(axis=0), verts.max(axis=0)
    h.draw_mode()
    h.camera((lo + hi) / 2, float(np.linalg.norm(hi - lo)) * 1.5, [0.0, 1.0, 0.01])
    multi = kind in ("task5",) or (kind == "v002" and rng.random() < 0.5)
    if multi:
        h.v.set_multi_mode(True)
        sc.multi_ids = [s.id for s in surfs]
    else:
        target = rng.choice(surfs)
        h.v._activate(target)
        surfs = [target]
    h.v._changed()
    return surfs, multi, (lo, hi)


def _path(rng, lo, hi):
    """Random, slightly bent path; start and end also outside the surfaces."""
    pad = (hi - lo) * 0.3
    a = lo - pad + rng.random() * (hi - lo + 2 * pad) * np.array([1, 0, 1])
    b = lo - pad + rng.random() * (hi - lo + 2 * pad) * np.array([1, 0, 1])
    a[1] = b[1] = (lo[1] + hi[1]) / 2
    mid = (a + b) / 2 + np.array([rng.uniform(-1, 1), 0, rng.uniform(-1, 1)]) * np.linalg.norm(b - a) * 0.25
    t = np.linspace(0, 1, 24)[:, None]
    return (1 - t) ** 2 * a + 2 * (1 - t) * t * mid + t ** 2 * b


def _tol(h, p, factor=1.0):
    depth = float((p - h.v.cam.eye) @ -h.v.cam.back)
    return factor * SNAP_PX * float(h.v._world_per_px(depth))


def _edge_pids(h, surf):
    if not isinstance(surf, SurfaceObject):
        return set()
    return {pid for c in h.v._edge_lines(surf) for pid in (c.pids or {}).values()}


def _events(h, screen, surfs, multi, step=3):
    """Where the path leaves/enters/switches surfaces: [(kind, world point, surface(s))] – only between longer pieces.
    Single mode: evaluated at the mouse positions (distance step) like the app; it bridges dropouts up to END_GAP_PX,
    and discards pieces under 24 px (corner grazed)."""
    dense = []
    spacing = 3 if multi else step
    for a, b in zip(screen[:-1], screen[1:]):
        n = max(1, int(np.hypot(b.x() - a.x(), b.y() - a.y()) / spacing))
        dense += [QPointF(a.x() + (b.x() - a.x()) * k / n, a.y() + (b.y() - a.y()) * k / n) for k in range(n)]
    dense.append(screen[-1])
    if multi:
        hits = h.v._multi_samples(dense)
    else:
        hits = [(h.v._surface_hit(q), surfs[0]) for q in dense]
        hits = [(p, s if p is not None else None) for p, s in hits]
    labels = [id(s) if p is not None else None for p, s in hits]
    # pieces of the same surface; very short pieces (<5 samples) do not count (border grazed)
    runs, start = [], 0
    for i in range(1, len(labels) + 1):
        if i == len(labels) or labels[i] != labels[start]:
            runs.append((start, i - 1, labels[start]))
            start = i
    if not multi:
        # the app bridges dropouts up to END_GAP_PX (10 px); it discards pieces under 24 px on the surface
        gap_n = int(np.ceil(10 / spacing)) + 1
        runs = [r for r in runs if not (r[2] is None and 0 < r[0] and r[1] < len(labels) - 1 and r[1] - r[0] + 1 < gap_n)]
        merged = []
        for r in runs:
            if merged and merged[-1][2] == r[2]:
                merged[-1] = (merged[-1][0], r[1], r[2])
            else:
                merged.append(r)
        runs = [r for r in merged if r[2] is None or (r[1] - r[0]) * spacing >= 24]
        merged = []
        for r in runs:
            if merged and merged[-1][2] == r[2]:
                merged[-1] = (merged[-1][0], r[1], r[2])
            else:
                merged.append(r)
        runs = merged
    else:
        runs = [r for r in runs if r[1] - r[0] >= 4 or r[2] is None]
    events = []
    first_exit = False
    for (s0, e0, l0), (s1, e1, l1) in zip(runs[:-1], runs[1:]):
        if not multi and first_exit:
            break  # single mode: the stroke ends as soon as it leaves the surface
        if l0 is not None and l1 is None:
            events.append(("exit", hits[e0][0], hits[e0][1]))
            first_exit = True
        elif l0 is None and l1 is not None:
            events.append(("enter", hits[s1][0], hits[s1][1]))
        elif l0 is not None and l1 is not None and l0 != l1 and s1 - e0 <= 2:
            events.append(("switch", (hits[e0][0] + hits[s1][0]) / 2, (hits[e0][1], hits[s1][1])))
    return events


def _check(h, new, events, held, report, step=4):
    sc = h.sc
    refs = network.refs_by_pid(sc)
    visible = [c for c in h.v._visible_curves() if not c.paint]
    for c in new:
        for k in (0, len(c.points) - 1):  # R1
            e = c.points[k]
            pid = network.pid_of(c, k)
            tol = _tol(h, e, R1_FACTOR)
            if network.degree(refs[pid]) >= 2:
                continue  # connected (to the nearest line; two close lines at once is not possible)
            for other in visible:
                if other is c:
                    continue
                lo, hi = other.points.min(axis=0) - tol, other.points.max(axis=0) + tol
                if np.any(e < lo) or np.any(e > hi):
                    continue
                d = sc._closest_on(other, e)[0]
                if d < tol:
                    report("R1 end near line, not connected", f"end {e.round(2)} {d:.3f} from line {other.id}")
                    break
    if not held:  # R2 (with recognized shapes the geometry deviates from the path)
        ends = [(c, k) for c in new for k in (0, len(c.points) - 1)]
        for kind, w, surf in events:
            s = surf[0] if kind == "switch" else surf
            size = float(np.linalg.norm(np.ptp(s.fill_mesh()[0], axis=0))) if isinstance(s, SurfaceObject) else 10.0
            reach = max(_tol(h, w, 3.0), 0.03 * size)
            # the exit is only known to within ~1 mouse step: measure on screen (steep surfaces!)
            w_s = h.v.project(np.asarray(w, float).reshape(1, 3))[0][0]
            px = lambda p: float(np.linalg.norm(h.v.project(p.reshape(1, 3))[0][0] - w_s))
            near = [(c, k) for c, k in ends
                    if np.linalg.norm(c.points[k] - w) < reach or px(c.points[k]) < step + 3 * SNAP_PX]
            if kind == "switch":
                pids = [network.pid_of(c, k) for c, k in near]
                edge = _edge_pids(h, surf[0]) | _edge_pids(h, surf[1])
                # both pieces share the point on the border line – or the piece on the neighbouring surface was too
                # short for a line, then one end on the border line suffices
                ok = any(pids.count(p) >= 2 and p in edge for p in pids) or                     (len(near) == 1 and pids[0] in edge)
            else:
                edge = _edge_pids(h, s)
                ok = any(network.pid_of(c, k) in edge for c, k in near) or not isinstance(s, SurfaceObject)
            if not ok and _grazing(h, s, w) > GRAZING:
                report(f"R2 {kind} without a point on the border", f"at {np.asarray(w).round(2)} ({getattr(s, 'name', s)})")
    for c in new:  # R3
        surf = sc.object_by_id(c.plane_id)
        others = [o for o in visible if o is not c and (o.plane_id == c.plane_id or
                                                         (isinstance(surf, SurfaceObject) and o in h.v._edge_lines(surf)))]
        for o in others:
            tol = h.v._cross_tol(c, o)
            for pa, pb in network.crossings(c, o, tol):
                if min(np.linalg.norm(pa - c.points[0]), np.linalg.norm(pa - c.points[-1])) < _tol(h, pa):
                    continue  # at the line end: R1
                if _angle(c, pa) is not None and _angle(o, pb) is not None and                         abs(float(_angle(c, pa) @ _angle(o, pb))) > np.cos(np.radians(10)):
                    continue  # run side by side (overlap), not a crossing
                if not set((c.pids or {}).values()) & set((o.pids or {}).values()):
                    report("R3 crossing without a point", f"line {c.id} x {o.id} at {pa.round(2)}")


def _angle(curve, p):
    """Direction of the line at the place p (unit vector) or None."""
    d = np.linalg.norm(curve.points - p, axis=1)
    i = int(np.argmin(d))
    a, b = curve.points[max(i - 2, 0)], curve.points[min(i + 2, len(curve.points) - 1)]
    v = b - a
    n = float(np.linalg.norm(v))
    return v / n if n > 1e-12 else None


def test_random_strokes(h: H):
    rng = random.Random(SEED)
    nrng = np.random.default_rng(SEED)
    failures = {}
    examples = []

    def report(kind, detail):
        failures[kind] = failures.get(kind, 0) + 1
        if len(examples) < 60:
            examples.append(f"{label}: {kind}: {detail}")

    kinds = ["v002", "task5", "fill", "plane", "loft"]
    done = 0
    while done < N:
        kind = kinds[(done // 10) % len(kinds)]
        surfs, multi, (lo, hi) = _setup(h, kind, rng)
        for _ in range(10):
            if done >= N:
                break
            smooth = rng.choice([0.0, 0.0, 0.5])
            step = rng.choice([4, 4, 18])
            held = rng.random() < 0.2
            label = f"#{done} {kind} {'multi' if multi else 'single'} smooth={smooth} step={step}{' hold' if held else ''}"
            path = _path(nrng, lo, hi)
            screen = [h.scrf(p) for p in path]
            events = _events(h, screen, surfs, multi, step)
            h.v.set_smooth(smooth)
            before = {c.id for c in h.curves()}
            h.stroke(screen, hold=held, step_px=step)
            h.v.set_smooth(0.0)
            new = [c for c in h.curves() if c.id not in before and not c.paint]
            _check(h, new, events, held, report, step)
            done += 1
        h.v.set_multi_mode(False)
    summary = ", ".join(f"{k}: {v}" for k, v in sorted(failures.items()))
    from tests.harness import OUT
    with open(os.path.join(OUT, "zufall.txt"), "w", encoding="utf-8") as f:
        f.write(f"{N} strokes – {summary}\n" + "\n".join(examples) + "\n")
    assert not failures, f"{N} strokes – {summary} (examples: tests/_out/zufall.txt)"
    return f"{N} strokes without a rule violation"

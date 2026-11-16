"""Test scenes watering_can, teacup and horse_head: can clean mesh models be built from them?

Each scene is built with today's tools (lofts from cross-section lines, side lines, fill surfaces), saved under
tests/scenes/ (to look at in the app) and checked:
  - Build: every surface has a valid net and longitudinal lines, saving/loading loses nothing.
  - Joints: the attachment ring of spout, handle, ears is drawn onto the body; where it crosses lines of the body,
    they share a point (connection rule), the loft of the part follows the ring.

Built scenes end up in tests/_out; the fixed scenes in tests/scenes (basis of the pixel comparison) are rewritten by the
test only with SKETCH_UPDATE_SCENES=1 (afterwards: tests/run.py render --update-baseline).
"""
import os

import numpy as np

from tests.harness import H, OUT, SCENES
from sketch_machine import components
from sketch_machine.scene import LoftSurface, Scene


# --- building blocks ---
def ring(center, normal, rx, ry=None, n=33, side=(1.0, 0.0, 0.0)):
    """Closed ellipse around center perpendicular to normal; rx along side (projected onto the plane)."""
    c, nrm = np.asarray(center, float), np.asarray(normal, float)
    nrm = nrm / np.linalg.norm(nrm)
    u = np.asarray(side, float) - nrm * (np.asarray(side, float) @ nrm)
    if np.linalg.norm(u) < 1e-6:
        u = np.cross(nrm, [0.0, 0.0, 1.0])
    u /= np.linalg.norm(u)
    v = np.cross(nrm, u)
    t = np.linspace(0, 2 * np.pi, n)
    return c + np.outer(np.cos(t), u) * rx + np.outer(np.sin(t), v) * (rx if ry is None else ry)


def smooth_path(points, n=40, rounds=4):
    """Smooth path through support points (Chaikin), resampled evenly."""
    p = np.asarray(points, float)
    for _ in range(rounds):
        q = np.empty((2 * len(p) - 2, 3))
        q[0::2] = 0.75 * p[:-1] + 0.25 * p[1:]
        q[1::2] = 0.25 * p[:-1] + 0.75 * p[1:]
        p = np.vstack([points[0], q, points[-1]])
    arc = np.concatenate([[0], np.cumsum(np.linalg.norm(np.diff(p, axis=0), axis=1))])
    t = np.linspace(0, arc[-1], n)
    return np.stack([np.interp(t, arc, p[:, i]) for i in range(3)], axis=1)


class Builder:
    def __init__(self, sc):
        self.sc, self.parts = sc, {}

    def loft(self, name, sections, rails=True, view=(0.3, 0.4, 1.0)):
        st = self.sc.new_stroke()
        st.name = name
        lines = []
        for s in sections:
            self.sc.add_curve(np.asarray(s, float), None)
            lines.append(self.sc.curves[-1])
        lo = self.sc.create_loft([("lines", [c.id]) for c in lines], [c.points for c in lines], prefix=name)
        if rails:
            self.sc.add_loft_rails(lo, np.asarray(view, float), owner=st)
        self.parts[name] = (lo, lines)
        return lo, lines

    def along(self, name, path, radii, count=7, side=(0.0, 0.0, 1.0)):
        """Loft from rings perpendicular to a path (spout, handle, ear); radii: (rx, ry) per ring or a number."""
        idx = np.linspace(0, len(path) - 1, count).round().astype(int)
        secs = []
        for j, i in enumerate(idx):
            tangent = path[min(i + 1, len(path) - 1)] - path[max(i - 1, 0)]
            r = radii[j]
            rx, ry = (r, r) if np.isscalar(r) else r
            secs.append(ring(path[i], tangent, rx, ry, n=25, side=side))
        return self.loft(name, secs)

    def fill(self, curve):
        return self.sc.create_fill([(curve, False)])


def build_watering_can(sc):
    b = Builder(sc)
    y_up = (0, 1.0, 0)
    body = [(0.0, 1.0), (0.12, 1.06), (0.9, 1.12), (1.55, 1.0), (1.8, 0.72)]
    _, lines = b.loft("Body", [ring((0, y, 0), y_up, r, r * 0.8) for y, r in body])
    b.fill(lines[0])  # bottom
    b.loft("Neck", [lines[-1].points, ring((0, 1.95, 0), y_up, 0.6, 0.5), ring((0, 2.02, 0), y_up, 0.64, 0.54)], rails=False)
    spout = smooth_path([[0.8, 0.45, 0], [1.6, 1.0, 0], [2.3, 1.75, 0], [2.6, 2.1, 0]])
    b.along("Spout", spout, [0.24, 0.2, 0.16, 0.13, 0.11, 0.09, 0.08])
    tip, d = spout[-1], spout[-1] - spout[-3]
    b.loft("Rose", [ring(tip, d, 0.08), ring(tip + d * 0.6, d, 0.2), ring(tip + d * 0.9, d, 0.24)])
    handle = smooth_path([[-0.85, 1.55, 0], [-1.5, 1.6, 0], [-1.65, 1.05, 0], [-1.45, 0.45, 0], [-1.0, 0.35, 0]])
    b.along("Handle", handle, [(0.09, 0.07)] * 7)
    return b, "Body", ["Spout", "Handle"]


def build_teacup(sc):
    b = Builder(sc)
    y_up = (0, 1.0, 0)
    cup = [(0.0, 0.45), (0.05, 0.5), (0.4, 0.62), (0.8, 0.75), (0.9, 0.78)]
    _, lines = b.loft("Cup", [ring((0, y, 0), y_up, r) for y, r in cup])
    b.fill(lines[0])
    b.loft("Saucer", [ring((0, -0.06, 0), y_up, 0.5), ring((0, -0.03, 0), y_up, 1.0), ring((0, 0.06, 0), y_up, 1.25)])
    handle = smooth_path([[0.68, 0.75, 0], [0.98, 0.8, 0], [1.1, 0.55, 0], [0.95, 0.3, 0], [0.56, 0.2, 0]])
    b.along("Handle", handle, [(0.07, 0.05)] * 7)
    return b, "Cup", ["Handle"]


def build_horse_head(sc):
    b = Builder(sc)
    axis = smooth_path([[0, 0, -0.7], [0, 0.9, -0.45], [0, 1.6, 0.0], [0, 1.5, 0.6], [0, 1.1, 1.2], [0, 0.8, 1.65]], n=60)
    sizes = [(0.5, 0.7), (0.42, 0.62), (0.4, 0.56), (0.37, 0.5), (0.3, 0.4), (0.27, 0.33), (0.25, 0.28)]
    idx = np.linspace(0, len(axis) - 1, len(sizes)).round().astype(int)
    secs = []
    for (rx, ry), i in zip(sizes, idx):
        tangent = axis[min(i + 1, len(axis) - 1)] - axis[max(i - 1, 0)]
        secs.append(ring(axis[i], tangent, rx, ry, side=(1.0, 0, 0)))
    _, lines = b.loft("Head", secs)
    b.fill(lines[-1])  # muzzle
    for sx, name in ((1, "Right ear"), (-1, "Left ear")):
        ear = smooth_path([[0.2 * sx, 1.75, -0.05], [0.26 * sx, 2.05, -0.02], [0.3 * sx, 2.3, -0.08]], n=20)
        b.along(name, ear, [(0.11, 0.07), (0.1, 0.06), (0.07, 0.04), (0.02, 0.012)], count=4, side=(0, 0, 1.0))
    return b, "Head", ["Right ear", "Left ear"]


BUILDERS = {"watering_can": build_watering_can, "teacup": build_teacup, "horse_head": build_horse_head}


def _materials(sc):
    """Every surface a different material (display), so that the images show them all."""
    from sketch_machine import theme
    keys = [k for k, _ in theme.MATERIALS]
    for k, s in enumerate(sc.surfaces):
        s.material = keys[k % len(keys)]
        s.seed = 17.0 * (k + 1)  # fixed offset: the images stay the same


def _make(h: H, key):
    sc = h.new_scene()
    b, body, parts = BUILDERS[key](sc)
    sc.sync_lofts()
    _materials(sc)
    h.v._changed()
    verts = np.vstack([s.fill_mesh()[0] for s in sc.surfaces])
    h.frame(verts, back=[0.75, 0.35, 0.9], margin=1.25)
    return b, body, parts


def _check_build(h: H, key):
    b, body, parts = _make(h, key)
    sc = h.sc
    for s in sc.surfaces:
        verts = s.fill_mesh()[0]
        assert len(verts) and np.isfinite(verts).all(), f"{s.name}: no valid net"
    lofts = [lo for lo, _ in b.parts.values() if lo.rails]
    assert lofts and all(len(lo.rails) >= 2 for lo in lofts), "longitudinal lines missing"
    # rewrite the fixed test scenes (tests/scenes, basis of the pixel comparison) only on request – otherwise the
    # pixel comparison would depend on which code the previous run built them with
    target = SCENES if os.environ.get("SKETCH_UPDATE_SCENES") else OUT
    os.makedirs(target, exist_ok=True)
    path = os.path.join(target, f"{key}.sketch.json")
    sc.save(path, extra={"views": h.w.views.state()})
    s2, _ = Scene.load(path)
    assert len(s2.surfaces) == len(sc.surfaces) and len(s2.curves) == len(sc.curves), "saving/loading loses nothing"
    h.save_image(f"szene_{key}.png")
    n_loft = sum(isinstance(s, LoftSurface) for s in sc.surfaces)
    return f"{len(sc.curves)} lines, {n_loft} lofts, {len(sc.surfaces) - n_loft} fill surfaces"


def _check_joints(h: H, key):
    """Attached parts (minimal variant, artist 18.10.): the attachment ring is drawn onto the body – laid onto its
    surface, then the connection rule runs as after every stroke. The ring then belongs to the body surface, the
    loft of the part follows it, and wherever it touches or crosses a line of the body, both share a point.
    (If it crosses none – handle of the watering can – there is nothing to connect.)"""
    from sketch_machine import loft, netsurf, network
    b, body, parts = _make(h, key)
    sc = h.sc
    lo, lines = b.parts[body]
    body_lines = lines + [sc.curve_by_id(cid) for cid, _ in lo.rails]
    g = lo.grid()
    size = float(np.linalg.norm(np.ptp(g.reshape(-1, 3), axis=0)))
    loose, joined = [], 0
    for name in parts:
        plo, plines = b.parts[name]
        ring = plines[0]
        ring.points = loft.evaluate_grid(netsurf.locate(g, ring.points)[0], g, lo.closed)  # drawn onto the body
        ring.plane_id = lo.id
        h.v._changed()
        h.v._resolve_stroke([ring], [("hit", "hit")])
        sc.sync_lofts()
        network.sync(sc)
        assert np.allclose(plo.curves[0].points[0], ring.points[0], atol=1e-3 * size) or             np.linalg.norm(plo.grid()[0] - ring.points[:1], axis=1).min() < 1e-3 * size, f"{name}: loft follows the ring"
        mine = set((ring.pids or {}).values())
        for c in body_lines:
            touch = min(min(sc._closest_on(c, p)[0] for p in ring.points),
                        min(sc._closest_on(ring, p)[0] for p in c.points))
            if touch < 2e-3 * size:
                if not mine & set((c.pids or {}).values()):
                    loose.append(name)
                    break
                joined += 1
    assert not loose, "crosses the body without a shared point: " + ", ".join(loose)
    return f"{joined} joint crossing(s), all connected"


def test_watering_can_build(h: H):
    return _check_build(h, "watering_can")


def test_watering_can_joints(h: H):
    return _check_joints(h, "watering_can")


def test_teacup_build(h: H):
    return _check_build(h, "teacup")


def test_teacup_joints(h: H):
    return _check_joints(h, "teacup")


def test_horse_head_build(h: H):
    return _check_build(h, "horse_head")


def test_horse_head_joints(h: H):
    return _check_joints(h, "horse_head")

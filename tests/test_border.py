"""Strokes at the surface border (the artist's topo-problem-z_shape): a stroke on a surface that touches its border or
briefly slips over the edge onto the neighbouring surface is split at the border – every line lies entirely on one
surface and never hangs on the border in the middle; a short slip is dropped, a longer piece becomes a line of the
neighbouring surface. A new stroke never moves existing lines. Applies equally to fill and curve surfaces."""
import numpy as np

from tests.harness import H, line
from tests.test_loft import _size
from sketch_machine import network
from sketch_machine.scene import PatchSurface
from sketch_machine.vp.snapping import _point_mesh_distance


def _poly_dist(pts, poly):
    """Largest distance of the points pts to the polyline poly."""
    a, ab = poly[:-1], np.diff(poly, axis=0)
    t = np.clip(np.einsum("pij,ij->pi", pts[:, None] - a[None], ab) / np.maximum(np.einsum("ij,ij->i", ab, ab), 1e-18), 0, 1)
    return float(np.linalg.norm(a[None] + t[..., None] * ab[None] - pts[:, None], axis=2).min(axis=1).max())


def _join_ends(sc, curves):
    """Make line ends at the same place into shared points (as drawn and snapped)."""
    network.sync(sc)
    ends = [(c, k) for c in curves for k in (0, len(c.points) - 1)]
    for i, (a, ka) in enumerate(ends):
        for b, kb in ends[i + 1:]:
            if a is not b and np.linalg.norm(a.points[ka] - b.points[kb]) < 1e-9 and \
                    network.pid_of(a, ka) != network.pid_of(b, kb):
                network.join(sc, a, ka, b, kb)
                network.sync(sc)


def _body(h: H, top_kind):
    """Top surface (L-shaped fill surface or square curve surface, y = 0) with a wall at the front edge z = 0
    (curve surface going down, shared border line). -> (top surface, wall, all lines)"""
    sc = h.new_scene()
    sc.new_stroke()
    if top_kind == "fill":
        P = [[0, 0, 0], [6, 0, 0], [6, 0, 2], [2, 0, 2], [2, 0, 6], [0, 0, 6]]
    else:
        P = [[0, 0, 0], [6, 0, 0], [6, 0, 4], [0, 0, 4]]
    P = [np.array(p, float) for p in P]
    top_lines = []
    for a, b in zip(P, P[1:] + P[:1]):
        sc.add_curve(line(a, b, 25), None)
        top_lines.append(sc.curves[-1])
    edge = top_lines[0]  # front edge, shared with the wall
    wall_lines = [edge]
    for a, b in (([6, 0, 0], [6, -2, 0]), ([6, -2, 0], [0, -2, 0]), ([0, -2, 0], [0, 0, 0])):
        sc.add_curve(line(np.array(a, float), np.array(b, float), 13), None)
        wall_lines.append(sc.curves[-1])
    _join_ends(sc, top_lines + wall_lines[1:])
    top = sc.create_fill([(c, False) for c in top_lines]) if top_kind == "fill" else sc.create_patch(top_lines)
    wall = sc.create_patch(wall_lines)
    sc.sync_lofts()
    return top, wall, top_lines + wall_lines[1:]


def _draw_z(h: H, top, tip_y):
    """Zigzag stroke on the top surface with the mouse: from inside to the front edge (tip at y = tip_y: < 0 means over
    the edge onto the wall), briefly back, onward, end inside. -> new lines"""
    h.draw_mode()
    h.v._activate(top)
    h.camera([3.0, -0.5, 1.0], 9.0, [0.0, 0.7, -0.7])  # in front of the wall, from obliquely above
    pts = [[2.6, 0, 1.7], [3.0, 0, 0.9], [3.4, 0, 0.05]]
    pts += [[3.5, tip_y, 0.0]] if tip_y < 0 else [[3.5, 0, 0.0 if tip_y == 0 else 0.1]]
    pts += [[3.6, 0, 0.6], [3.9, 0, 0.4], [4.4, 0, 1.0]]
    world = []
    for a, b in zip(pts[:-1], pts[1:]):
        for t in np.linspace(0, 1, 8)[:-1]:
            world.append(np.array(a) + t * (np.array(b) - np.array(a)))
    world.append(np.array(pts[-1], float))
    before = {c.id for c in h.curves()}
    h.stroke_world(np.array(world, float))
    h.sc.sync_lofts()
    return [c for c in h.curves() if c.id not in before and not c.paint]


def _check(h: H, top, wall, existing, new):
    sc = h.sc
    for c, before in existing:  # same shape (an inserted connection point lies on it)
        d = max(_poly_dist(c.points, before), _poly_dist(before, c.points))
        assert d < 1e-9, f"existing line {c.id} moved ({d:.2g})"
    hosts = {s.id: s for s in (top, wall)}
    for c in new:
        s = hosts.get(c.plane_id)
        assert s is not None, f"line {c.id} belongs to none of the surfaces"
        verts, tris = s.fill_mesh()[:2]
        size = _size(verts)
        off = max(_point_mesh_distance(p, verts, tris) for p in c.points) / size
        assert off < 0.005, f"line {c.id} runs {off:.1%} beside its surface ({s.name})"
        border = sc.patch_border(s) if isinstance(s, PatchSurface) else \
            [sc.curve_by_id(i) for cid, _ in s.links for i in sc.link_ids(cid)]
        border_pids = {p for b in border if b is not None for p in (b.pids or {}).values()}
        inner = [k for k, pid in (c.pids or {}).items() if 0 < k < len(c.points) - 1 and pid in border_pids]
        assert not inner, f"line {c.id} hangs on the border in the middle (point {inner})"


def _run(h: H, kind, tip_y, expect):
    top, wall, lines = _body(h, kind)
    existing = [(c, c.points.copy()) for c in lines]
    new = _draw_z(h, top, tip_y)
    _check(h, top, wall, existing, new)
    on_top = sum(c.plane_id == top.id for c in new)
    on_wall = sum(c.plane_id == wall.id for c in new)
    assert (on_top, on_wall) == expect, f"{kind}, tip {tip_y}: {on_top} lines on top, {on_wall} on the wall, expected {expect}"


def test_z_stroke_stays_before_the_edge(h: H):
    for kind in ("fill", "patch"):
        _run(h, kind, 0.1, (1, 0))


def test_z_stroke_touches_the_edge(h: H):
    """Tip exactly on the edge: two lines, split at the border point (no line hangs on the border in the middle)."""
    for kind in ("fill", "patch"):
        _run(h, kind, 0.0, (2, 0))


def test_z_stroke_slips_briefly_over_the_edge(h: H):
    """Tip just over the edge: the slip is dropped, two lines remain on top, both end at the border."""
    for kind in ("fill", "patch"):
        _run(h, kind, -0.04, (2, 0))


def test_z_stroke_runs_onto_the_wall(h: H):
    """Tip clearly on the wall: the piece there becomes a line of the wall, two lines on top."""
    for kind in ("fill", "patch"):
        _run(h, kind, -0.6, (2, 1))


def test_crossing_does_not_move_existing_line(h: H):
    """A new stroke crosses an existing line (just beside it, within tolerance): the shared point lies
    on the existing line, it stays as it was – the new stroke comes to it."""
    sc = h.sc
    sc.new_stroke()
    sc.add_curve(line([0, 0, 0], [4, 0, 0], 41), None)
    old = sc.curves[-1]
    sc.add_curve(line([2.03, 0.004, -1], [2.0, 0.004, 1], 21), None)
    new = sc.curves[-1]
    network.sync(sc)
    before = old.points.copy()
    assert network.connect_crossings(sc, new, [old], 0.01) == 1
    k = next(j for j, p in old.pids.items() if p in set(new.pids.values()))
    pts = old.points
    seg = np.linalg.norm(np.cross(pts[k] - before[0], before[-1] - before[0])) / np.linalg.norm(before[-1] - before[0])
    assert seg < 1e-9, "crossing point lies on the existing line (it stays straight)"
    assert np.allclose(np.delete(pts, k, axis=0)[[0, -1]], before[[0, -1]])

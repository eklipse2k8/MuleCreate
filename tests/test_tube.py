"""Tubes and rings as a curve net: cross sections and longitudinal lines form the rest shape (closed Gordon surface).
A dragged longitudinal line shapes the surface exactly and round – no rib only at the line, the neighbourhood follows
smoothly; the cross sections stay where they are, and the seam is smooth."""
import numpy as np

from tests.harness import H
from tests.test_loft import _dist_to_mesh, _size


def _tube(h: H, ring=False):
    sc = h.sc
    sc.new_stroke()
    t = np.linspace(0, 2 * np.pi, 33)
    secs = []
    if ring:  # ring around the y axis made of four circles
        for a in np.arange(4) * np.pi / 2:
            rad = np.array([np.cos(a), 0, np.sin(a)])
            sc.add_curve(3 * rad + np.cos(t)[:, None] * rad + np.sin(t)[:, None] * np.array([0, 1.0, 0]), None)
            secs.append(sc.curves[-1])
    else:
        for y in (0.0, 2.0, 4.0):
            sc.add_curve(np.stack([np.cos(t), np.full_like(t, y), np.sin(t)], 1), None)
            secs.append(sc.curves[-1])
    lo = sc.create_loft([("lines", [c.id]) for c in secs], [c.points for c in secs], wrap=ring)
    sc.add_loft_rails(lo, np.array([0.3, 1.0, 0.2]) if ring else np.array([0.3, 0.4, 1.0]))
    sc.sync_lofts()
    h.v._changed()
    return lo, secs


def _pull(h: H, lo, ring):
    """Pull the first longitudinal line outwards between the first and second cross section (it stays at the cross sections).
    -> (longitudinal line, pull direction)"""
    rail = h.sc.curve_by_id(lo.rails[0][0])
    p = rail.points
    if ring:
        s = (np.arctan2(p[:, 2], p[:, 0]) % (2 * np.pi)) / (np.pi / 2)
        d = np.array([0, 1.0, 0])
    else:
        s = p[:, 1] / 2
        d = p[len(p) // 4] * np.array([1, 0, 1])
        d /= np.linalg.norm(d)
    w = np.where(s < 1, np.sin(np.pi * s) ** 2, 0.0)
    rail.points = p + 0.8 * w[:, None] * d
    h.sc.sync_lofts()
    h.v._changed()
    return rail, d


def _check(h: H, lo, secs, ring):
    assert lo._gordon is not None, "tube/ring as a curve net (all longitudinal lines connected to the cross sections)"
    assert all(len(set(h.sc.curve_by_id(cid).pids.values()) & set(s.pids.values())) for cid, _ in lo.rails for s in secs)
    before = lo.grid().copy()
    rail, d = _pull(h, lo, ring)
    verts, tris = lo.fill_mesh()[:2]
    size = _size(verts)
    off = _dist_to_mesh(rail.points, verts, tris).max() / size
    assert off < 0.005, f"surface passes through the dragged longitudinal line (grid resolution) ({off:.2%} off)"
    for s in secs:
        assert _dist_to_mesh(s.points, verts, tris).max() / size < 0.002, "cross sections stay on the surface"
    # round instead of rib: at the longitudinal line the surface bends across hardly more than next to it (old: 1.4 to 3.7 times;
    # measured over two columns – the drawn circles are polygons, which is noisy from column to column)
    g = lo.grid()
    col, row = lo.rails[0][1], lo.span // 2
    bend = lambda c: float(np.linalg.norm(g[row, c - 2] - 2 * g[row, c] + g[row, c + 2]))
    near = max(bend(c) for c in (col - 6, col - 4, col - 2, col + 2, col + 4, col + 6))
    assert float(np.dot(g[row, col] - before[row, col], d)) > 0.5, "the surface follows the drag"
    assert bend(col) < 1.35 * near, f"bulge instead of rib (kink {bend(col):.3f}, next to it {near:.3f})"
    # seam (last column -> first) without a kink: neighbour distances even
    step = np.linalg.norm(np.diff(np.concatenate([g, g[:, :1]], axis=1), axis=1), axis=2)
    assert step[:, -1].max() < 2.5 * np.median(step), "seam smooth"


def test_tube_longitudinal_line_shapes_round(h: H):
    lo, secs = _tube(h)
    _check(h, lo, secs, False)


def test_ring_longitudinal_line_shapes_round(h: H):
    lo, secs = _tube(h, ring=True)
    _check(h, lo, secs, True)


def test_donut_from_four_circles(h: H):
    """Four circles around an axis, ring loft: a round donut (circular arcs blended – with Catmull-Rom it was a
    rhombus, 46 % off the torus), without a kink at the cross sections and at the seam."""
    lo, secs = _tube(h, ring=True)
    assert lo._gordon is not None
    v = lo.fill_mesh()[0]
    rho = np.hypot(v[:, 0], v[:, 2])
    err = np.abs(np.hypot(rho - 3, v[:, 1]) - 1).max()
    assert err < 0.015, f"{err:.1%} off the torus (the drawn circles are polygons of 33 points)"
    g = lo.grid()  # lengthwise: row 0 = last row (seam); kink across the cross sections and the seam
    ring = np.concatenate([g[:-1], g[:1]])
    for r in range(0, len(g) - 1, lo.span):
        prev, nxt = ring[(r - 1) % (len(g) - 1)], ring[r + 1]
        ang = np.degrees(np.arccos(np.clip(np.einsum("ij,ij->i", ring[r] - prev, nxt - ring[r])
                                           / np.linalg.norm(ring[r] - prev, axis=1)
                                           / np.linalg.norm(nxt - ring[r], axis=1), -1, 1)))
        step = 360 / (len(g) - 1)
        assert ang.max() < 2.5 * step, f"kink at the cross section (row {r}): {ang.max():.1f}° (circle: {step:.1f}° per row)"

"""Curve net (patchnet): every curve surface – whether created with Alt+F, F or as a loft – is the result of its lines.
Lines from border to border (connected to the border at both ends) are net lines: they form the rest shape (Gordon surface,
without them the Coons surface of the border) and lie on a grid row or column; all other lines bend the
surface in between. Shared points have a position on the surface, derived from the net."""
import numpy as np

from tests.harness import H, line
from tests.test_loft import _dist_to_mesh, _size
from sketch_machine import components, network
from sketch_machine.scene import PatchSurface


def _square_patch(h: H, size=4.0, n=21):
    """Flat square curve surface (y = 0) made of four border lines."""
    sc = h.sc
    sc.new_stroke()
    P = [np.array(p, float) for p in ([0, 0, 0], [size, 0, 0], [size, 0, size], [0, 0, size])]
    border = []
    for a, b in zip(P, P[1:] + P[:1]):
        sc.add_curve(line(a, b, n), None)
        border.append(sc.curves[-1])
    surf = sc.create_patch(border)
    sc.sync_lofts()
    return surf, border


def _on_border(sc, border, c, k):
    """Connect line end k of c to the border line it lies on (shared point)."""
    network.sync(sc)
    p = c.points[k]
    b = min(border, key=lambda o: float(np.linalg.norm(o.points - p, axis=1).min()))
    kb = network.knot_at(b, p, tol=1e-6)
    network.join(sc, b, kb, c, k)


def _line_on(h: H, surf, border, pts, ends=(0, -1)):
    """Real line on the surface; the given ends connected to the border."""
    sc = h.sc
    sc.add_curve(np.asarray(pts, float), surf.id)
    c = sc.curves[-1]
    for e in ends:
        _on_border(sc, border, c, e % len(c.points))
    sc.sync_lofts()
    return c


def _arch(a, b, height, n=41, axis_up=1):
    t = np.linspace(0, 1, n)
    pts = np.asarray(a, float)[None] * (1 - t[:, None]) + np.asarray(b, float)[None] * t[:, None]
    pts[:, axis_up] += height * np.sin(np.pi * t)
    return pts


def test_cross_line_becomes_net_line_and_shapes_round(h: H):
    """Alt+F surface, a raised line across from border to border: it becomes a net line (grid row), the surface passes
    exactly through it and swings round across it – no tent (before: Coons surface + tight bending)."""
    surf, border = _square_patch(h)
    c = _line_on(h, surf, border, _arch([0, 0, 2.0], [4, 0, 2.0], 1.2))
    assert surf.net and len(surf.net["u"]) + len(surf.net["v"]) == 1, "cross line is a net line"
    verts, tris = surf.fill_mesh()[:2]
    size = _size(verts)
    assert _dist_to_mesh(c.points[::2], verts, tris).max() < 0.002 * size, "surface passes through the line"
    g = surf.grid()
    att = surf.attached[c.id]["uv"]
    if surf.net["u"]:
        row = surf.net["u"][0][1]
        assert np.ptp(att[:, 0]) < 1e-9 and att[0, 0] == row, "line lies on a grid row"
        prof = g[:, g.shape[1] // 2]
    else:
        row = surf.net["v"][0][1]
        assert np.ptp(att[:, 1]) < 1e-9 and att[0, 1] == row, "line lies on a grid column"
        prof = g[g.shape[0] // 2]
    k = components.kink_deg(prof[row::-1], prof[row:])
    # round: from 0 to 1.2 and back over 2 + 2 units – a parabola has no kink at the top
    assert k < 12, f"tent: {k:.0f}° kink at the line"


def test_net_in_both_directions(h: H):
    """One line across and one lengthwise, crossing at a shared point: both are net lines, the grid
    follows both (row and column), the surface passes through both."""
    sc = h.sc
    surf, border = _square_patch(h)
    a = _line_on(h, surf, border, _arch([0, 0, 2.0], [4, 0, 2.0], 1.0))
    b = _line_on(h, surf, border, _arch([2.0, 0, 0], [2.0, 0, 4], 1.0))
    network.connect_crossings(sc, b, [a], 1e-3)
    sc.sync_lofts()
    assert surf.net and len(surf.net["u"]) == 1 and len(surf.net["v"]) == 1, (surf.net["u"], surf.net["v"])
    verts, tris = surf.fill_mesh()[:2]
    size = _size(verts)
    for c in (a, b):
        assert _dist_to_mesh(c.points[::2], verts, tris).max() < 0.002 * size, f"surface passes through line {c.id}"
    uv = {c.id: surf.attached[c.id]["uv"] for c in (a, b)}
    assert any(np.ptp(u[:, 0]) < 1e-9 for u in uv.values()) and any(np.ptp(u[:, 1]) < 1e-9 for u in uv.values()), \
        "one line on a row, the other on a column"


def test_shared_point_on_the_border_lies_exactly(h: H):
    """A free line ends at a border point (only one end at the border – not a net line). If this point is dragged, the
    surface still lies exactly at it and at the line end: the position of the point on the surface comes from the net, not from
    what the line remembered while it was drawn."""
    sc = h.sc
    surf, border = _square_patch(h)
    c = _line_on(h, surf, border, _arch([0, 0, 1.3], [2.5, 0, 1.6], 0.0), ends=(0,))  # drawn on the surface
    assert not (surf.net["u"] or surf.net["v"]), "free line, not a net line"
    pid = network.pid_of(c, 0)
    refs = network.refs_by_pid(sc)
    b, kb = next((o, j) for o, j in refs[pid] if o is not c)
    components.ComponentGroup(sc, [(b, kb)], []).translate(np.array([0.0, 0.8, 0.3]))
    sc.sync_lofts()
    verts, tris = surf.fill_mesh()[:2]
    size = _size(verts)
    for name, pts in (("border point", b.points[kb:kb + 1]), ("line", c.points[::2])):
        d = _dist_to_mesh(pts, verts, tris).max()
        assert d < 0.003 * size, f"{name}: surface {d / size:.2%} off"


def test_new_net_line_everything_stays_in_place(h: H):
    """When a net line is added, the grid is laid out again – a free line on it keeps its place and the surface
    still lies on it."""
    sc = h.sc
    surf, border = _square_patch(h)
    free = _line_on(h, surf, border, _arch([0.6, 0, 0.8], [1.6, 0, 1.0], 0.0), ends=())
    before = free.points.copy()
    _line_on(h, surf, border, _arch([0, 0, 2.6], [4, 0, 2.6], 0.8))
    assert surf.net["u"] or surf.net["v"]
    assert np.array_equal(free.points, before), "lines never move the surface"
    verts, tris = surf.fill_mesh()[:2]
    assert _dist_to_mesh(free.points[::2], verts, tris).max() < 0.003 * _size(verts), "surface lies on the free line"


def test_old_curve_surfaces_become_net(h: H):
    """Older scene (the artist's topology test): all curve surfaces with a complete border get their net on loading
    and lie on all their lines."""
    h.load("tests/scenes/topologie.sketch.json")
    sc = h.sc
    sc.sync_lofts()
    patches = [s for s in sc.surfaces if isinstance(s, PatchSurface)]
    assert patches and all(s.net for s in patches)
    for s in patches:
        verts, tris = s.fill_mesh()[:2]
        size = _size(verts)
        for c in sc.patch_border(s) + [sc.curve_by_id(cid) for cid in s.attached]:
            if c is None or c.paint:
                continue
            d = _dist_to_mesh(c.points[::4], verts, tris).max()
            assert d < 0.01 * size, f"{s.name}: line {c.id} {d / size:.2%} off"


def _l_fill(h: H):
    """Flat L-shaped fill surface (y = 0) made of six border lines (F makes a fill surface for it)."""
    sc = h.sc
    sc.new_stroke()
    P = [np.array(p, float) for p in ([0, 0, 0], [6, 0, 0], [6, 0, 2], [2, 0, 2], [2, 0, 6], [0, 0, 6])]
    border = []
    for a, b in zip(P, P[1:] + P[:1]):
        sc.add_curve(line(a, b, 25), None)
        border.append(sc.curves[-1])
    surf = sc.create_fill([(c, False) for c in border])
    sc.sync_lofts()
    return surf, border


def _fill_dist(surf, pts):
    verts, tris = surf.netmesh[0], surf.netmesh[1]
    return _dist_to_mesh(pts, verts, tris), _size(verts)


def test_fill_surface_net_line_shapes_round(h: H):
    """L-shaped fill surface, a raised line from border to border (both ends connected): it shapes the surface like
    a net line – exactly through it and round across it (no tent like before with tightness)."""
    sc = h.sc
    surf, border = _l_fill(h)
    c = _line_on(h, surf, border, _arch([4.0, 0, 0], [4.0, 0, 2], 0.0, n=21))  # across the short arm
    pts = c.points.copy()
    pts[:, 1] = 0.8 * np.sin(np.linspace(0, np.pi, len(pts)))
    c.points = pts
    sc.sync_lofts()
    assert c.id in sc._fill_net_ids(surf, network.refs_by_pid(sc)), "line from border to border is a net line"
    d, size = _fill_dist(surf, c.points[::2])
    assert d.max() < 0.003 * size, f"surface {d.max() / size:.2%} off the line"
    # profile along the arm (across the line) at z = 1: round, no kink at the line
    verts = surf.netmesh[0]
    rest = surf.netmesh[2]
    xs = np.linspace(2.4, 5.6, 33)
    from sketch_machine import netfill
    dom = netfill.domain(surf.rest, netfill.DENSITY * surf.resolution)
    from sketch_machine import cage
    uv = cage.bind(np.stack([xs, np.zeros_like(xs), np.ones_like(xs)], 1), cage.build(
        sc._fill_pieces(surf), surf.counts), surf.rest)
    prof = netfill.evaluate(dom, verts, uv, lambda q: np.zeros((len(q), 3)))
    k = int(np.argmin(np.abs(xs - 4.0)))
    kink = components.kink_deg(prof[k::-1], prof[k:])
    assert prof[k, 1] > 0.75, f"surface does not reach the line ({prof[k, 1]:.2f})"
    assert kink < 15, f"tent at the line: {kink:.0f}° kink"  # with tightness (before): 19°, pure sheet: 11°

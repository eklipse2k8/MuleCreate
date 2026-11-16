"""The pen hits the surface as it is now (the artist's zshape_test): Z-shaped fill surface laid flat and
clicked, then outline lines raised or lowered, then straight strokes over it from above. Formerly the pen hit the
old, flat shape (the grid of exact hits hung only on the triangle array, and net surfaces keep that through every
shape change): the lines lay beside the surface, were split in the wrong places (spikes), pieces fell off the
surface, and the surface bent towards the wrong points."""
import numpy as np

from tests.harness import H, line
from tests.test_border import _join_ends
from tests.test_loft import _size
from sketch_machine import network
from sketch_machine.scene import PatchSurface
from sketch_machine.vp.snapping import _point_mesh_distance

# Z in plan view (x, z): upper bar, diagonal, lower bar
Z = [[0, 0], [6, 0], [6, 1.5], [2.5, 4.5], [6, 4.5], [6, 6], [0, 6], [0, 4.5], [3.5, 1.5], [0, 1.5]]
UP, DOWN = 2, 7  # raise the diagonal at top right, lower it at bottom left (outline line k: Z[k] -> Z[k+1])


def _z_fill(h: H, kind="fill"):
    """Flat Z fill surface (y = 0) or curve surface from a square, active, clicked once. -> (surface, outline)"""
    sc = h.new_scene()
    sc.new_stroke()
    P = [np.array([x, 0.0, z]) for x, z in Z] if kind == "fill" else \
        [np.array(p, float) for p in ([0, 0, 0], [6, 0, 0], [6, 0, 6], [0, 0, 6])]
    lines = []
    for a, b in zip(P, P[1:] + P[:1]):
        sc.add_curve(line(a, b, 31), None)
        lines.append(sc.curves[-1])
    _join_ends(sc, lines)
    surf = sc.create_fill([(c, False) for c in lines]) if kind == "fill" else sc.create_patch(lines)
    sc.sync_lofts()
    h.v._changed()
    h.draw_mode()
    h.v._activate(surf)
    h.camera([3, 0, 3], 13.0, [0.0, 1.0, 0.15])  # from above
    h.v._surface_hit(h.scrf(np.array([1.0, 0.0, 0.75])))  # clicked while flat
    return surf, lines


def _bend(h: H, lines, which=((UP, 0.8), (DOWN, -1.1))):
    """Raise/lower outline lines in the middle (ends stay, as when dragging a point)."""
    for k, amount in which:
        c = lines[k]
        c.points = c.points.copy()
        c.points[:, 1] += amount * np.sin(np.linspace(0, np.pi, len(c.points)))
    h.v._changed()
    h.sc.sync_lofts()
    h.grab()


def test_pen_hits_the_current_shape(h: H):
    for kind, bend in (("fill", ((UP, 0.8), (DOWN, -1.1))), ("patch", ((0, 0.8), (2, -1.1)))):
        surf, lines = _z_fill(h, kind)
        for step in range(3):
            _bend(h, lines, tuple((k, a * (step + 1) / 3) for k, a in bend))
            verts, tris = surf.fill_mesh()[:2]
            for x, z in ((1.0, 0.75), (3.0, 3.0), (5.0, 5.25), (4.0, 0.6)):
                hit = h.v._surface_hit(h.scrf(np.array([x, 0.0, z])))
                assert hit is not None, f"{kind}: no hit at {x}, {z}"
                d = _point_mesh_distance(hit, verts, tris)
                assert d < 1e-4 * _size(verts), f"{kind}, step {step}: hit {d:.3f} beside the surface (old shape)"


def _straight(h: H, a, b, over=0.3):
    """Straight stroke from above, extending a little past the edge at both ends. -> new lines"""
    a, b = np.array(a, float), np.array(b, float)
    d = (b - a) / np.linalg.norm(b - a)
    a, b = a - over * d, b + over * d
    before = {c.id for c in h.curves()}
    h.stroke_world(np.array([a + t * (b - a) for t in np.linspace(0, 1, 40)]))
    h.sc.sync_lofts()
    return [c for c in h.curves() if c.id not in before and not c.paint]


def test_straight_strokes_over_the_deformed_z_surface(h: H):
    """The artist's zshape_test: every straight stroke becomes exactly one line on the surface, from edge to edge, without jumps;
    the surface stays as it was (the line lies on it, after all)."""
    sc = h.sc
    surf, lines = _z_fill(h)
    _bend(h, lines)
    border_pids = lambda: {p for c in lines for p in (c.pids or {}).values()}
    for a, b in (([0, 0, 0.75], [6, 0, 0.75]),       # across the upper bar
                 ([1.75, 0, 3.0], [4.25, 0, 3.0]),   # across the diagonal (over both slanted edges)
                 ([0, 0, 5.25], [6, 0, 5.25])):      # across the lower bar
        verts0 = surf.fill_mesh()[0].copy()
        new = _straight(h, a, b)
        assert len(new) == 1, f"stroke {a}->{b}: {len(new)} lines instead of one ({[c.plane_id for c in new]})"
        c = new[0]
        assert c.plane_id == surf.id, "the line belongs to the surface"
        verts, tris = surf.fill_mesh()[:2]
        size = _size(verts)
        off = max(_point_mesh_distance(p, verts, tris) for p in c.points) / size
        assert off < 0.002, f"stroke {a}->{b} runs {off:.1%} beside the surface"
        steps = np.linalg.norm(np.diff(c.points, axis=0), axis=1)
        assert steps.max() < 0.1 * steps.sum(), f"stroke {a}->{b} jumps ({steps.max():.2f} of {steps.sum():.2f})"
        network.sync(sc)
        n = len(c.points)
        assert c.pids.get(0) in border_pids() and c.pids.get(n - 1) in border_pids(), "ends at the edge"
        inner = [k for k, p in c.pids.items() if 0 < k < n - 1 and p in border_pids()]
        assert not inner, f"line is attached to the edge in the middle ({inner})"
        moved = float(np.abs(verts - verts0).max()) / size if verts.shape == verts0.shape else 1.0
        assert moved < 0.005, f"stroke {a}->{b} deforms the surface ({moved:.1%})"


def test_stroke_stays_on_the_active_surface(h: H):
    """Two surfaces with a shared edge (slightly bent, like two wing panels): a stroke from the active surface
    across the edge that ends outside is cut off at the edge (the artist's glider_owl: stroke on
    curve surface 8 continued onto curve surface 3). A detour that comes back stays (test_border, Z stroke).
    Applies to freehand and straight (hold still at the end)."""
    for hold in (False, True):
        sc = h.new_scene()
        sc.new_stroke()
        a = [np.array(p, float) for p in ([0, 0, 0], [3, 0, 0], [3, 0, 3], [0, 0, 3])]
        b = [np.array(p, float) for p in ([3, 0, 0], [6, 0.6, 0], [6, 0.6, 3], [3, 0, 3])]
        surfs = []
        for quad in (a, b):
            lines = []
            for p, q in zip(quad, quad[1:] + quad[:1]):
                sc.add_curve(line(p, q, 16), None)
                lines.append(sc.curves[-1])
            _join_ends(sc, lines)
            surfs.append(sc.create_fill([(c, False) for c in lines]))
        sc.sync_lofts()
        h.v._changed()
        h.draw_mode()
        h.camera([3, 0, 1.5], 12.0, [0.0, 1.0, 0.15])
        h.v._activate(surfs[0])
        h.v._surface_hit(h.scrf(np.array([1.0, 0.0, 1.5])))
        before = {c.id for c in h.curves()}
        h.stroke([h.scrf(np.array([0.8, 0.0, 1.5])), h.scrf(np.array([5.2, 0.42, 1.6]))], hold=hold)
        new = [c for c in h.curves() if c.id not in before and not c.paint]
        assert new, "stroke on the active surface"
        x = max(float(c.points[:, 0].max()) for c in new)
        assert x < 3.05, f"{'straight' if hold else 'freehand'}: stroke runs to x = {x:.2f} onto the neighbouring surface"

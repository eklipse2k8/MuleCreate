"""Displayed mesh by curvature: a flat surface gets few triangles, a curved one as many as its shape needs –
independent of the size and of the point count of its lines. The shape itself (compute grid, painting, border)
stays untouched; the surface's slider sets finer or coarser from there."""
import numpy as np

from sketch_machine import loft, network
from sketch_machine.scene import SurfaceObject
from sketch_machine.viewport import _dist_to_triangles_fast
from tests.harness import H, line
from tests.test_material import _square


def _patch(h, sides):
    sc = h.sc
    sc.new_stroke()
    lines = []
    for sd in sides:
        sc.add_curve(sd, None)
        lines.append(sc.curves[-1])
    network.sync(sc)
    patch = sc.create_patch(lines)
    h.v._changed()
    return patch


def _flat_sides(size, n):
    p = [np.array(q, float) * size for q in ([0, 0, 0], [1, 0, 0], [1, 0, 1], [0, 0, 1])]
    return [line(p[k], p[(k + 1) % 4], n) for k in range(4)]


def test_flat_surface_few_triangles_regardless_of_size_and_drawing(h: H):
    h.new_scene()
    counts = []
    for size, n in ((1.0, 8), (500.0, 8), (1.0, 120)):  # small, large, drawn with very many points
        patch = _patch(h, _flat_sides(size, n))
        counts.append(len(patch.fill_mesh()[1]))
    assert max(counts) <= 8, f"flat: few triangles ({counts})"
    assert counts[0] == counts[1] == counts[2], "independent of size or point count of the lines"


def test_curved_surface_stays_on_the_shape(h: H):
    h.new_scene()
    t = np.linspace(0, 1, 24)
    arc = lambda z: np.stack([np.cos(t * np.pi) * 2, np.sin(t * np.pi) * 2, np.full_like(t, z)], 1)  # half pipe
    patch = _patch(h, [arc(0.0), line([-2, 0, 0], [-2, 0, 3], 8), arc(3.0)[::-1], line([2, 0, 3], [2, 0, 0], 8)])
    verts, tris = patch.fill_mesh()[:2]
    full = loft.build(None, False, g=patch.grid())  # the compute grid itself
    size = float(np.linalg.norm(np.ptp(full[0], axis=0)))
    assert len(tris) < len(full[1]) / 3, f"clearly fewer triangles than the compute grid ({len(tris)} instead of {len(full[1])})"
    assert len(tris) >= 20, "the bend needs its subdivisions"
    dist = _dist_to_triangles_fast(full[0], verts[tris]).max()
    assert dist <= 1.5 * loft.ADAPT_TOL * size, f"at most a thousandth of the size away from the shape ({dist / size:.5f})"
    # straight direction: not subdivided – the points along the straight line lie on one line
    assert len(verts) <= len(full[0]) / 3


def test_slider_sets_finer_and_coarser(h: H):
    h.new_scene()
    t = np.linspace(0, 1, 24)
    arc = lambda z: np.stack([np.cos(t * np.pi) * 2, np.sin(t * np.pi) * 2, np.full_like(t, z)], 1)
    patch = _patch(h, [arc(0.0), line([-2, 0, 0], [-2, 0, 3], 8), arc(3.0)[::-1], line([2, 0, 3], [2, 0, 0], 8)])
    n1 = len(patch.fill_mesh()[1])
    h.v.set_surface_resolution(patch.id, 2.0)
    h.v._changed()
    n2 = len(patch.fill_mesh()[1])
    h.v.set_surface_resolution(patch.id, 0.5)
    h.v._changed()
    n05 = len(patch.fill_mesh()[1])
    h.v.set_surface_resolution(patch.id, 1.0)
    h.v._changed()
    assert n05 < n1 < n2 and len(patch.fill_mesh()[1]) == n1, (n05, n1, n2)


def test_flat_fill_surface_shows_only_its_border_until_it_bulges(h: H):
    h.new_scene()
    sc = h.sc
    f = _square(h, y=0.0, x0=0.0, size=3.0)
    dense = len(f.netmesh[1])
    verts, tris = f.fill_mesh()[:2]
    assert len(tris) <= 8 and dense > 100 * len(tris), f"flat: {len(tris)} instead of {dense} triangles"
    area = lambda v, t: float(np.linalg.norm(np.cross(v[t[:, 1]] - v[t[:, 0]], v[t[:, 2]] - v[t[:, 0]]), axis=1).sum() / 2)
    assert abs(area(verts, tris) - 9.0) < 1e-9, "same border, same area (corners stay corners)"
    edge = next(c for c in sc.curves if any(i == c.id for cid, _ in f.links for i in sc.link_ids(cid)))
    bent = edge.points.copy()
    bent[len(bent) // 2] += [0.0, 0.6, 0.0]
    edge.points = bent
    h.v._changed()
    assert len(f.fill_mesh()[1]) > 1000, "bulged: the dense mesh"


def test_can_be_switched_off_as_before(h: H):
    h.new_scene()
    patch = _patch(h, _flat_sides(2.0, 12))
    try:
        SurfaceObject.auto_res = False
        h.v._changed()
        assert len(patch.fill_mesh()[1]) > 100, "off: the mesh at the density of the compute grid"
    finally:
        SurfaceObject.auto_res = True
    h.v._changed()
    assert len(patch.fill_mesh()[1]) <= 8


def test_layout_still_applies_to_the_moved_surface(h: H):
    """Moved or uniformly scaled: the same shape – the same layout, without searching for it again."""
    u, v = np.meshgrid(np.linspace(0, 1, 40), np.linspace(0, 1, 30), indexing="ij")
    g = np.stack([u, 0.3 * np.sin(3 * u) * np.cos(2 * v), v], axis=2)
    for k, off in ((1.0, np.array([120.0, -40.0, 7.0])), (2.5, np.array([-3.0, 0.5, 11.0]))):
        moved = k * g + off
        loft._PLANS.clear()
        first = loft.adaptive_grid(g, 1.0, False)
        assert len(loft._PLANS) == 1
        again = loft.adaptive_grid(moved, 1.0, False)
        assert len(loft._PLANS) == 1, "moved/scaled: remembered layout hits"
        loft._PLANS.clear()
        fresh = loft.adaptive_grid(moved, 1.0, False)
        assert again.shape == fresh.shape == first.shape and np.allclose(again, fresh), "as if searched anew"
        assert np.allclose(again, k * first + off, atol=1e-6)
    bent = g.copy()
    bent[20:, :, 1] += 0.2  # different shape: its own layout
    loft.adaptive_grid(g, 1.0, False)
    loft.adaptive_grid(bent, 1.0, False)
    assert len(loft._PLANS) == 2
    a = np.radians(35.0)  # rotated: correct, even if it is searched anew
    rot = np.array([[np.cos(a), -np.sin(a), 0], [np.sin(a), np.cos(a), 0], [0, 0, 1]])
    turned = loft.adaptive_grid(g @ rot.T, 1.0, False)
    loft._PLANS.clear()
    assert np.allclose(turned, loft.adaptive_grid(g @ rot.T, 1.0, False))

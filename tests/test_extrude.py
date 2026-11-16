"""Extrude (X): side surfaces like a loft, split at hard points; extruding surfaces in surface mode."""
import numpy as np

from tests.harness import H, Qt, circle, line
from sketch_machine import network
from sketch_machine.scene import LoftSurface, PatchSurface, SurfaceObject


def _rect(h: H, size=2.0):
    """Rectangle of four lines (connected) on the ground -> lines."""
    sc = h.new_scene()
    sc.new_stroke()
    c = [[0, 0, 0], [size, 0, 0], [size, 0, size], [0, 0, size]]
    for a, b in zip(c, c[1:] + c[:1]):
        sc.add_curve(line(a, b, 20), sc.planes[0].id)
    h.v._changed()
    network.sync(sc)
    return list(sc.curves)


def _extrude(h: H, length=1.0, axis="y"):
    v = h.v
    v.start_extrude()
    assert v._mode == "extrude", "extrusion is running"
    v._extrude_set_axis(axis)
    v._extrude["length"] = length
    v._finish_extrude()
    v._extrude = None
    v._mode = None
    v._changed()


def _select_lines(h: H, curves):
    h.edit_mode("edge")
    h.v.edge_selection = [("line", h.sc.owner_of(c).id, c.id) for c in curves]
    h.v._changed()


def _flat(surface):
    v = surface.fill_mesh()[0]
    p = v - v.mean(axis=0)
    return np.linalg.svd(p, full_matrices=False)[1][2] < 1e-6 * max(1.0, np.ptp(v, axis=0).max())


def test_rectangle_gives_four_flat_walls(h: H):
    curves = _rect(h)
    h.frame(np.vstack([c.points for c in curves]))
    _select_lines(h, curves)
    _extrude(h)
    walls = list(h.sc.surfaces)
    assert len(walls) == 4, f"{len(walls)} surfaces instead of 4 (one per side)"
    assert all(isinstance(s, PatchSurface) for s in walls), [type(s).__name__ for s in walls]
    assert all(_flat(s) for s in walls), "walls are flat (angular box)"
    h.save_image("extrude_rechteck.png")


def test_circle_gives_a_tube(h: H):
    sc = h.new_scene()
    sc.new_stroke()
    sc.add_curve(circle([0, 0, 0], 1.0, 65), sc.planes[0].id)
    h.v._changed()
    _select_lines(h, sc.curves)
    _extrude(h)
    assert len(sc.surfaces) == 1 and isinstance(sc.surfaces[0], LoftSurface), [type(s).__name__ for s in sc.surfaces]


def test_l_profile_two_surfaces_and_soft_corner_one(h: H):
    for hard, expect in ((None, 2), (0.0, 1)):
        sc = h.new_scene()
        sc.new_stroke()
        sc.add_curve(np.vstack([line([0, 0, 0], [2, 0, 0], 20), line([2, 0, 0], [2, 0, 2], 20)[1:]]), sc.planes[0].id)
        c = sc.curves[-1]
        h.v._changed()
        network.sync(sc)
        if hard is not None:  # make the corner soft (K rounds it): one continuous surface
            k = [j for j in c.pids if 0 < j < len(c.points) - 1][0]
            h.edit_mode("point")
            h.v.point_selection = [("pt", sc.owner_of(c).id, c.id, k)]
            h.v.set_hardness(hard)
        _select_lines(h, [c])
        _extrude(h)
        assert len(sc.surfaces) == expect, f"hardness {hard}: {len(sc.surfaces)} surfaces instead of {expect}"


def test_without_surfaces_only_lines(h: H):
    curves = _rect(h)
    _select_lines(h, curves)
    h.v.ws.extrude_surface = False
    try:
        _extrude(h)
    finally:
        h.v.ws.extrude_surface = True
    assert not h.sc.surfaces
    assert len(h.curves()) == 4 + 4 + 4, len(h.curves())  # original, copy, four connecting lines


def test_extruding_surface_moves_up(h: H):
    curves = _rect(h)
    _select_lines(h, curves)
    h.v.do_surface()
    face = h.sc.surfaces[0]
    assert isinstance(face, (PatchSurface, SurfaceObject))
    face.material = "holz"
    bottom = [c.points.copy() for c in curves]
    h.edit_mode("face")
    h.v.selection = [face.id]
    h.v._changed()
    _extrude(h, 1.5)
    face = next(s for s in h.sc.surfaces if s.id == face.id)
    v = face.fill_mesh()[0]
    assert np.allclose(v[:, 1], 1.5, atol=1e-6), f"surface is on top (y {v[:, 1].min():.3f} .. {v[:, 1].max():.3f})"
    walls = [s for s in h.sc.surfaces if s is not face]
    assert len(walls) == 4, f"{len(walls)} side walls"
    assert all(s.material == "holz" for s in walls), "walls take over the material"
    # the bottom ring stays (the original lines are still at the bottom)
    low = [c for c in h.curves() if np.allclose(c.points[:, 1], 0)]
    assert sum(len(c.points) for c in low) >= sum(len(b) for b in bottom) - 4, "bottom ring stays"
    # the surface now follows the upper copy: lifting an upper corner point deforms it
    top = [c for c in h.curves() if np.allclose(c.points[:, 1], 1.5)]
    assert top, "upper copy"
    h.save_image("extrude_flaeche.png")


def test_inner_line_moves_with_the_surface(h: H):
    curves = _rect(h)
    _select_lines(h, curves)
    h.v.do_surface()
    face = h.sc.surfaces[0]
    h.draw_mode()
    h.frame([[0, 0, 0], [2, 0, 2]], back=(0.01, 1, 0.01))
    h.sc.activate_mesh(face)
    h.v._changed()
    h.stroke_world([[-0.3, 0, 1.0], [2.3, 0, 1.0]])  # across the surface, beyond the border
    inner = [c for c in h.curves() if c.plane_id == face.id and not c.paint]
    assert inner, "line on the surface"
    h.edit_mode("face")
    h.v.selection = [face.id]
    h.v._changed()
    _extrude(h, 1.0)
    for c in inner:
        c2 = h.sc.curve_by_id(c.id)
        assert c2 is not None and np.allclose(c2.points[:, 1], 1.0, atol=1e-6), "inner line moved along"
    network.sync(h.sc)
    refs = network.refs_by_pid(h.sc)
    c2 = h.sc.curve_by_id(inner[0].id)
    for k in (0, len(c2.points) - 1):
        assert len(refs[network.pid_of(c2, k)]) > 1, "ends stay connected to the (upper) border"


def test_delete_point_surface_follows_the_bridge(h: H):
    """Ctrl+Del on a lifted point of a line across the surface: the neighboring points are connected
    straight, and the surface settles onto this straight line (as if the line had been straight before)."""
    from sketch_machine import components, netedit
    curves = _rect(h)
    _select_lines(h, curves)
    h.v.do_surface()
    face = h.sc.surfaces[0]
    h.draw_mode()
    h.frame([[0, 0, 0], [2, 0, 2]], back=(0.01, 1, 0.01))
    h.sc.activate_mesh(face)
    h.v._changed()
    h.stroke_world([[-0.3, 0, 1.0], [2.3, 0, 1.0]])
    line_ = next(c for c in h.curves() if c.plane_id == face.id and not c.paint)
    for x in (0.5, 1.0, 1.5):  # three points on the line
        h.sc.insert_knot_at(line_.points[np.argmin(np.abs(line_.points[:, 0] - x))])
        line_ = h.sc.curve_by_id(line_.id) or line_
    h.v._changed()
    network.sync(h.sc)
    ks = [k for k in components.knots(line_) if 0 < k < len(line_.points) - 1]
    mid = min(ks, key=lambda k: abs(line_.points[k, 0] - 1.0))
    components.ComponentGroup(h.sc, [(line_, mid)], []).translate(np.array([0, 0.8, 0]))
    h.v._changed()
    g = face.grid()
    assert g[..., 1].max() > 0.6, "surface follows the lifted point"
    netedit.delete_points(h.sc, [network.pid_of(line_, mid)])
    h.v._changed()
    face = next(s for s in h.sc.surfaces if s.id == face.id)
    bridge = [c for c in h.curves() if len(c.points) == netedit.BRIDGE_POINTS]
    assert bridge and bridge[0].id in face.attached, "bridge shapes the surface"
    v = face.fill_mesh()[0]
    near = v[np.linalg.norm(v[:, [0, 2]] - [1.0, 1.0], axis=1) < 0.08]
    assert len(near) and np.abs(near[:, 1]).max() < 0.08, f"surface lies on the straight line (y {near[:, 1].max():.3f})"


def test_soft_connecting_line_is_a_net_line(h: H):
    """Open arc extruded: the soft connecting line in the middle (original -> copy, two points) runs from
    border to border of the wall and is its net line – it shapes the surface exactly (before, it counted as a border duplicate)."""
    from tests.test_loft import _dist_to_mesh, _size
    sc = h.new_scene()
    sc.new_stroke()
    t = np.linspace(0, np.pi, 49)
    sc.add_curve(np.stack([2 * np.cos(t), np.zeros_like(t), 2 * np.sin(t)], 1), sc.planes[0].id)
    h.v._changed()
    network.sync(sc)
    _select_lines(h, sc.curves)
    _extrude(h)
    sc.sync_lofts()
    wall = sc.surfaces[0]
    assert isinstance(wall, PatchSurface) and wall.net and len(wall.net["v"]) == 1, wall.net
    mid = next(c for c in h.curves() if len(c.points) == 2 and abs(c.points[0, 0]) < 0.1)
    from sketch_machine import components
    components.ComponentGroup(sc, [(mid, 1)], []).translate(np.array([0, 0, 0.6]))  # upper point outward (border goes along)
    sc.sync_lofts()
    verts, tris = wall.fill_mesh()[:2]
    pts = mid.points[0] + np.linspace(0, 1, 9)[:, None] * (mid.points[1] - mid.points[0])
    assert _dist_to_mesh(pts, verts, tris).max() < 0.003 * _size(verts), "wall passes through the connecting line"


def _kink_line(h: H, deg):
    """Open line of two straight pieces with a node in the middle that kinks by deg."""
    sc = h.new_scene()
    sc.new_stroke()
    a = np.linspace([-2.0, 0, 0], [0.0, 0, 0], 21)
    t = np.radians(deg)
    b = np.linspace([0.0, 0, 0], [2 * np.cos(t), 0, 2 * np.sin(t)], 21)[1:]
    sc.add_curve(np.vstack([a, b]), sc.planes[0].id)
    c = sc.curves[-1]
    c.knots = (len(c.points), (20,))  # point in the middle (as if inserted)
    h.v._changed()
    network.sync(sc)
    return c


def _verticals(sc):
    out = 0
    for c in sc.curves:
        d = c.points[-1] - c.points[0]
        if np.linalg.norm(d) > 1e-6 and abs(d[1]) > 0.99 * np.linalg.norm(d):
            out += 1
    return out


def test_node_rule_5_and_15_degrees(h: H):
    """Node below 5°: no connecting line; from 5°: line, surface stays one; from 15°: line and split."""
    for deg, rails, faces in ((3.0, 2, 1), (10.0, 3, 1), (20.0, 3, 2)):
        c = _kink_line(h, deg)
        h.frame(c.points)
        _select_lines(h, [c])
        _extrude(h)
        assert _verticals(h.sc) == rails, f"{deg}°: {_verticals(h.sc)} connecting lines instead of {rails}"
        assert len(h.sc.surfaces) == faces, f"{deg}°: {len(h.sc.surfaces)} surfaces instead of {faces}"

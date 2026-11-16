"""Topology: what the curve net (F3-F5) is meant to solve. Known problems are marked as expected failures -
as soon as one of them reports BEHOBEN, remove the marker."""
import numpy as np

from tests.harness import H, Qt, expected_failure, line
from sketch_machine import components, edges, network


def _loft3(h: H, rails=True):
    sc = h.sc
    sc.new_stroke()
    t = np.linspace(0, 1, 12)
    secs = []
    for z, lift in ((0.0, 0.0), (1.0, 0.8), (2.0, 0.0)):
        sc.add_curve(np.stack([t * 2, 0.4 * np.sin(t * np.pi) + lift, np.full_like(t, z)], axis=1), None)
        secs.append(sc.curves[-1])
    lo = sc.create_loft([("lines", [c.id]) for c in secs], [c.points for c in secs])
    if rails:
        sc.add_loft_rails(lo, np.array([0, 0, 1.0]))
    sc.sync_lofts()
    h.v._changed()
    return lo, secs


def _delete_lines(h: H, curves):
    h.v.edge_selection = [("line", h.sc.owner_of(c).id, c.id) for c in curves]
    h.v.selection = []
    h.v.select_mode = True
    h.v.ws.component = "edge"
    h.v.delete_selection()
    h.sc.sync_lofts()


def test_loft_loses_deleted_profile(h: H):
    lo, secs = _loft3(h)
    _delete_lines(h, [secs[1]])
    assert len(lo.curves) == 2, f"loft still has {len(lo.curves)} cross-sections"


def test_rails_stay_after_deleting_a_profile(h: H):
    """Topology concept: rails are real lines - if a cross-section is deleted, they stay as they are, and
    the loft keeps passing through them (it is formed from cross-sections and rails)."""
    lo, secs = _loft3(h)
    rail = h.sc.curve_by_id(lo.rails[0][0])
    before = rail.points.copy()
    _delete_lines(h, [secs[1]])
    h.v._changed()
    assert np.array_equal(h.sc.curve_by_id(rail.id).points, before), "rail stays put"
    verts = lo.fill_mesh()[0]
    mid = before[np.argmin(np.abs(before[:, 2] - 1.0))]
    assert np.linalg.norm(verts - mid, axis=1).min() < 0.05, "loft passes through the rail"


def test_rails_follow_the_profile_at_the_shared_point(h: H):
    """Rails attach to the cross-sections at shared points: if the end point of a cross-section is dragged,
    the rail goes along there (the loft does not move it - the net does)."""
    from sketch_machine import network
    lo, secs = _loft3(h)
    rail = h.sc.curve_by_id(lo.rails[0][0])
    end = rail.points[-1].copy()
    refs = network.refs_by_pid(h.sc)
    pid = network.pid_of(rail, len(rail.points) - 1)
    assert any(c is secs[2] for c, _ in refs[pid]), "rail is connected to the cross-section"
    group = components.ComponentGroup(h.sc, [refs[pid][0]], [])
    group.translate(np.array([0.0, 0.5, 0.0]))
    h.v._changed()
    rail = h.sc.curve_by_id(rail.id)
    assert np.linalg.norm(rail.points[-1] - (end + [0, 0.5, 0])) < 1e-6, "rail follows at the shared point"


def test_dissolved_corner_stays_dissolved(h: H):
    sc = h.sc
    sc.new_stroke()
    sc.add_curve(np.vstack([line([0, 0, 0], [1, 0, 0], 20), line([1, 0, 0], [1, 0, 1], 20)[1:]]), None)
    c = sc.curves[-1]
    corner = components.knots(c)[1]
    assert components.dissolve(c, corner)
    assert components.knots(c) == [0, len(c.points) - 1]
    arc = np.concatenate([[0], np.cumsum(np.linalg.norm(np.diff(c.points, axis=0), axis=1))])
    t = np.linspace(0, arc[-1], 60)  # point count changes (e.g. smoothing, resampling)
    c.points = np.stack([np.interp(t, arc, c.points[:, i]) for i in range(3)], axis=1)
    c.widths = np.full(60, c.widths.mean())
    assert components.knots(c) == [0, 59], f"knots {components.knots(c)}"


def _corner_lines(h: H):
    sc = h.sc
    sc.new_stroke()
    sc.add_curve(line([0, 0, 0], [1, 0, 0], 12), sc.planes[0].id)
    sc.add_curve(line([1, 0, 0], [1, 0, 1], 12), sc.planes[0].id)
    h.v._changed()
    h.camera([0.5, 0, 0.5], 4, [0, 1, 0.01])
    return sc.curves[-2:]


def test_dissolving_a_point_joins_two_lines(h: H):
    a, b = _corner_lines(h)
    h.edit_mode("point")
    h.click(h.scr([1, 0, 0]))
    assert h.v.point_selection, "corner point selected"
    h.key(Qt.Key_Delete)  # Del: dissolve (Ctrl+Del deletes the point)
    assert len(h.curves()) == 1, f"{len(h.curves())} lines - expected one continuous line"
    pts = h.curves()[0].points
    assert np.linalg.norm(pts - [1, 0, 0], axis=1).min() < 1e-6, "shape stays (corner still lies on it)"


def test_removing_a_point_reinterpolates(h: H):
    sc = h.sc
    sc.new_stroke()
    sc.add_curve(np.vstack([line([0, 0, 0], [1, 0, 1], 20), line([1, 0, 1], [2, 0, 0], 20)[1:]]), sc.planes[0].id)
    c = sc.curves[-1]
    h.v._changed()
    h.camera([1, 0, 0.5], 4, [0, 1, 0.01])
    h.edit_mode("point")
    h.click(h.scr([1, 0, 1]))
    assert hasattr(h.v, "remove_points"), "command Remove Point is missing"
    h.v.remove_points()
    c = h.curves()[0]
    assert np.linalg.norm(c.points - [1, 0, 1], axis=1).min() > 0.2, "the peak is gone, the line runs anew"


def test_shared_point_drags_both_lines(h: H):
    a, b = _corner_lines(h)
    h.edit_mode("point")
    h.click(h.scr([1, 0, 0]))
    group = components.ComponentGroup(h.sc, [(c, r[3]) for r, c in h.v._valid_points()], [])
    group.translate(np.array([0.0, 0.0, -0.3]))
    assert np.allclose(a.points[-1], b.points[0]), "both line ends stay together"


def test_double_click_curve_surface_finds_boundary_lines(h: H):
    sc = h.sc
    sc.new_stroke()
    t = np.linspace(0, 1, 12)
    sides = [np.stack([t * 2, 0.3 * np.sin(t * np.pi), t * 0], 1), np.stack([np.full_like(t, 2), 0.3 * np.sin(t * np.pi), t * 2], 1),
             np.stack([2 - t * 2, 0.3 * np.sin(t * np.pi), np.full_like(t, 2)], 1), np.stack([t * 0, 0.3 * np.sin(t * np.pi), 2 - t * 2], 1)]
    lines = []
    for s in sides:
        sc.add_curve(s, None)
        lines.append(sc.curves[-1])
    ps = sc.create_patch(lines)
    sc.sync_lofts()
    h.v._changed()
    h.camera([1, 0.2, 1], 5, [0.2, 0.9, 0.4])
    h.edit_mode("face")
    h.v.select_loop(h.scrf(ps.fill_mesh()[0].mean(axis=0)), "replace")
    found = {r[2] for r in h.v.edge_selection}
    assert h.v.selection == [ps.id] and found == {c.id for c in lines}, f"{len(found)} of 4 boundary lines"


def test_no_duplicate_rails(h: H):
    lo, secs = _loft3(h)
    h.sc.add_loft_rails(lo, np.array([0, 0, 1.0]))
    h.sc.sync_lofts()
    pts = [c.points for c in h.curves()]
    dup = sum(1 for i in range(len(pts)) for j in range(i) if pts[i].shape == pts[j].shape and np.allclose(pts[i], pts[j]))
    assert dup == 0, f"{dup} duplicate lines"


def test_edges_of_a_line_at_corners(h: H):
    sc = h.sc
    sc.new_stroke()
    sc.add_curve(np.vstack([line([0, 0, 0], [1, 0, 0], 20), line([1, 0, 0], [1, 0, 1], 20)[1:]]), None)
    assert len(components.segments(sc.curves[-1])) == 2
    assert len(edges.all_edges(sc)) == 1, "one line, two edges"


def _bow(h: H):
    """Straight line with an inserted (soft) point in the middle."""
    sc = h.sc
    sc.new_stroke()
    sc.add_curve(line([0, 0, 0], [4, 0, 0], 41), sc.planes[0].id)
    c = sc.curves[-1]
    components.insert_point(c, 20, 0.0)
    h.v._changed()
    network.sync(sc)
    k = [j for j in components.knots(c) if 0 < j < len(c.points) - 1][0]
    return c, k


def _rot_y(deg):
    a = np.radians(deg)
    return np.array([[np.cos(a), 0, np.sin(a)], [0, 1, 0], [-np.sin(a), 0, np.cos(a)]])


def test_rotating_a_point_rotates_the_line_there(h: H):
    """F4 orient: rotate a point - it stays, the neighbouring points stay, the line runs through it in the new
    direction; the point remembers the rotation (quaternion), also across save/load."""
    import os, tempfile
    from sketch_machine.scene import Scene
    c, k = _bow(h)
    p, ends = c.points[k].copy(), c.points[[0, -1]].copy()
    group = components.ComponentGroup(h.sc, [(c, k)], [])
    for _ in range(6):  # like the gizmo: in small steps
        group.rotate(_rot_y(5), p)
    assert np.allclose(c.points[k], p) and np.allclose(c.points[[0, -1]], ends), "point and neighbours stay"
    d = c.points[k + 2] - c.points[k - 2]
    angle = np.degrees(np.arctan2(-d[2], d[0]))
    assert abs(angle - 30) < 3, f"direction at the point {angle:.1f}° instead of 30°"
    q = network.get_attr(h.sc, network.pid_of(c, k))
    assert np.allclose(q[:4], network.quat_of(_rot_y(30)), atol=1e-6), q
    path = os.path.join(tempfile.mkdtemp(), "orient.sketch.json")
    h.sc.save(path)
    new = Scene.load(path)[0]
    c2 = next(x for st in new.strokes for x in st.curves)
    assert np.allclose(network.get_attr(new, network.pid_of(c2, k))[:4], q[:4]), "orient stays on loading"


def test_scaling_a_point_stretches_the_line_there(h: H):
    """F4 pscale: scale up a point of a curve - the line gets wider around it (the curve
    bulgier), point and neighbours stay; pscale remembers the factor."""
    sc = h.sc
    sc.new_stroke()
    t = np.linspace(0, 1, 41)
    sc.add_curve(np.stack([t * 4, np.zeros_like(t), np.sin(t * np.pi)], 1), sc.planes[0].id)
    c = sc.curves[-1]
    components.insert_point(c, 20, 0.0)
    h.v._changed()
    network.sync(sc)
    k = [j for j in components.knots(c) if 0 < j < len(c.points) - 1][0]
    p, ends = c.points[k].copy(), c.points[[0, -1]].copy()
    before = c.points[k - 8].copy()
    group = components.ComponentGroup(sc, [(c, k)], [])
    group.scale(np.full(3, 1.5), np.eye(3), p)
    assert np.allclose(c.points[k], p) and np.allclose(c.points[[0, -1]], ends)
    assert np.linalg.norm(c.points[k - 8] - p) > 1.15 * np.linalg.norm(before - p), "surroundings stretched"
    assert abs(network.get_attr(sc, network.pid_of(c, k))[4] - 1.5) < 1e-6


def test_removing_a_point_with_shift_del_soft(h: H):
    """Shift+Del removes a point of a curved line: at soft neighbours the new line continues without a kink,
    the neighbours stay."""
    sc = h.sc
    sc.new_stroke()
    t = np.linspace(0, 1, 61)
    pts = np.stack([t * 6, np.zeros_like(t), np.sin(t * 2 * np.pi)], 1)
    pts[:, 2] += 0.8 * np.exp(-((np.arange(61) - 30) / 5.0) ** 2)  # soft bump in the middle
    sc.add_curve(pts, sc.planes[0].id)
    c = sc.curves[-1]
    where = [pts[j].copy() for j in (15, 30, 45)]
    c.knots = (len(pts), (15, 30, 45))  # three inserted (soft) points
    h.v._changed()
    network.sync(sc)
    a, k, b = 15, 30, 45
    assert components.knots(c) == [0, 15, 30, 45, 60]
    pa, pb = c.points[a].copy(), c.points[b].copy()
    h.camera([3, 0, 0], 8, [0, 1, 0.01])
    h.edit_mode("point")
    h.click(h.scr(c.points[k]))
    h.key(Qt.Key_Delete, Qt.ShiftModifier)
    c = h.curves()[0]
    assert np.allclose(c.points[a], pa) and np.allclose(c.points[b], pb), "neighbours stay"
    assert not any(np.linalg.norm(c.points[j] - where[1]) < 1e-6 for j in components.knots(c)), "point is gone"
    assert np.linalg.norm(c.points - where[1], axis=1).min() > 0.3, "bump is gone, the line runs anew"
    for j in (a, b):  # no kink at the neighbour
        u, v = c.points[j] - c.points[j - 2], c.points[j + 2] - c.points[j]
        cos = u @ v / np.linalg.norm(u) / np.linalg.norm(v)
        assert cos > np.cos(np.radians(12)), f"kink at the neighbour {np.degrees(np.arccos(cos)):.1f}°"


def test_export_with_orient_and_pscale(h: H):
    """Sketch Brief: lines with point attributes get primvars:orient (quatf) and primvars:pscale per point."""
    import os, tempfile
    from sketch_machine import brief
    c, k = _bow(h)
    group = components.ComponentGroup(h.sc, [(c, k)], [])
    group.rotate(_rot_y(20), c.points[k].copy())
    group.scale(np.full(3, 2.0), np.eye(3), c.points[k].copy())
    path = os.path.join(tempfile.mkdtemp(), "scene.usda")
    brief.write_usd(h.sc, brief.analyse(h.sc), path)
    text = open(path, encoding="utf-8").read()
    assert "quatf[] primvars:orient" in text and "float[] primvars:pscale" in text
    assert " 2," in text.split("float[] primvars:pscale")[1].split("\n")[0], "pscale 2 at the point"

"""Point tools: hardness (K), sliding (S held), scaling several points."""
import os
import tempfile

import numpy as np

from PySide6.QtTest import QTest

from tests.harness import H, QPoint, QPointF, Qt, line
from sketch_machine import components, network


def _bow(h: H, n=41):
    """Arc with an inserted point in the middle -> (line, knot)."""
    sc = h.new_scene()
    sc.new_stroke()
    t = np.linspace(0, 1, n)
    sc.add_curve(np.stack([t * 4, np.zeros_like(t), np.sin(t * np.pi)], 1), sc.planes[0].id)
    c = sc.curves[-1]
    components.insert_point(c, n // 2, 0.0)
    h.v._changed()
    network.sync(sc)
    k = [j for j in components.knots(c) if 0 < j < len(c.points) - 1][0]
    return c, k


def _select_point(h: H, c, k):
    h.camera([2, 0, 0.5], 7, [0, 1, 0.01])
    h.edit_mode("point")
    h.v.point_selection = [("pt", h.sc.owner_of(c).id, c.id, k)]
    h.v._changed()


def _sharp(h: H, c, k):
    return components.point_sharpness(network.refs_by_pid(h.sc).get(network.pid_of(c, k), []))


def test_hardness_keys_and_dragging(h: H):
    """K shapes the line at the point: Shift+K fully hard (kink), Alt+K fully soft (round); dragging sets the angularity
    continuously - the value is the hardness the shape has (nothing stored, the same after loading)."""
    c, k = _bow(h)
    _select_point(h, c, k)
    h.key(Qt.Key_K, Qt.ShiftModifier)
    assert _sharp(h, c, k) == 1.0, "Shift+K: hard"
    h.key(Qt.Key_K, Qt.AltModifier)
    assert _sharp(h, c, k) == 0.0, "Alt+K: soft"
    # K = tool on: dragging (here in empty space, the selection stays) sets the hardness of the selection
    p0 = QPointF(40, 40)
    h.key(Qt.Key_K)
    assert h.v.ws.value_tool == "hardness"
    h.move(p0)
    h.grab()  # hint at the cursor, squares at angular points
    h.stroke([p0, QPointF(p0.x() + 100, p0.y())])
    v = _sharp(h, c, k)
    assert abs(v - 0.5) < 0.03, f"half way = 0.5, is {v}"
    assert h.v.ws.value_tool == "hardness", "tool stays on"
    h.grab()
    h.wheel(2, pos=p0)
    assert abs(_sharp(h, c, k) - 0.6) < 0.03, "mouse wheel"
    # Esc in the middle of a drag cancels
    QTest.mousePress(h.v, Qt.LeftButton, Qt.NoModifier, p0.toPoint())
    h.move(QPointF(p0.x() + 300, p0.y()), Qt.LeftButton)
    h.key(Qt.Key_Escape)
    QTest.mouseRelease(h.v, Qt.LeftButton, Qt.NoModifier, QPoint(int(p0.x()) + 300, int(p0.y())))
    h.pump(0.02)
    assert abs(_sharp(h, c, k) - 0.6) < 0.03, "Esc cancels"
    h.key(Qt.Key_K)
    assert h.v.ws.value_tool is None, "K again: off"
    path = os.path.join(tempfile.mkdtemp(), "haerte.sketch.json")
    h.sc.save(path)
    from sketch_machine.scene import Scene
    new = Scene.load(path)[0]
    c2 = next(x for st in new.strokes for x in st.curves)
    pid = network.pid_of(c2, k)
    assert abs(components.point_sharpness(network.refs_by_pid(new)[pid]) - 0.6) < 0.03, "hardness stays (in the shape)"


def test_hardness_takes_effect_when_dragging(h: H):
    """Hard point: the line runs straight to the neighbours (kink at the point); soft: round."""
    shapes = {}
    for value in (0.0, 1.0):
        c, k = _bow(h)
        _select_point(h, c, k)
        h.v.set_hardness(value)
        group = components.ComponentGroup(h.sc, [(c, k)], [])
        group.translate(np.array([0, 0, 1.0]))
        shapes[value] = c.points.copy()
    soft, hard = shapes[0.0], shapes[1.0]
    k = len(soft) // 2
    # right next to the point: soft almost as high as the point (flat), hard clearly lower (kink)
    assert soft[k - 3, 2] - hard[k - 3, 2] > 0.05, (soft[k - 3, 2], hard[k - 3, 2])


def _cross(h: H, kinked=True):
    """Straight line E (x axis) and a cross line M that crosses it in the middle (shared point) - kinked (V)
    or round (arc). -> (E, M, point ID of the crossing)."""
    sc = h.new_scene()
    sc.new_stroke()
    sc.add_curve(line([0, 0, 0], [4, 0, 0], 41), None)
    e = sc.curves[-1]
    t = np.linspace(-1, 1, 41)
    sc.add_curve(np.stack([np.full_like(t, 2.0), np.abs(t) if kinked else t * t, t * 1.5], 1), None)
    m = sc.curves[-1]
    h.v._changed()
    network.sync(sc)
    p = np.array([2.0, 0, 0])
    je, jm = network.knot_at(e, p), network.knot_at(m, p)
    network.join(sc, e, je, m, jm)
    return e, m, network.pid_of(e, je)


def test_edge_hard_where_the_cross_line_kinks(h: H):
    """An edge is hard where the lines that cross it kink - proportional in between up to its ends. The
    cross line itself is soft there (the edge runs straight through)."""
    e, m, pid = _cross(h)
    refs = network.refs_by_pid(h.sc)
    ce, cm = components.crease_along(e, refs), components.crease_along(m, refs)
    k = network.knot_at(e, np.array([2.0, 0, 0]))
    assert ce[k] == 1.0 and ce[0] == 0.0 and 0.3 < ce[k // 2] < 0.7, ce[[0, k // 2, k]]
    assert not cm.any(), "cross line: the edge does not kink"
    e, m, pid = _cross(h, kinked=False)
    assert not components.crease_along(e, network.refs_by_pid(h.sc)).any(), "round cross line: soft"


def test_hardness_on_edge_kinks_the_cross_lines(h: H):
    """Edge mode, K: the lines that cross the edge kink at it - the edge itself stays as it is."""
    e, m, pid = _cross(h, kinked=False)
    before = e.points.copy()
    h.camera([2, 0, 0], 7, [0.3, 1, 0.4])
    h.edit_mode("edge")
    h.v.edge_selection = [("line", h.sc.owner_of(e).id, e.id)]
    h.v.set_hardness(1.0)
    k = network.knot_at(e, np.array([2.0, 0, 0]))
    assert np.array_equal(e.points, before), "the edge stays"
    assert components.crease_along(e, network.refs_by_pid(h.sc))[k] == 1.0, "edge is hard"
    h.v.set_hardness(0.0)
    assert components.crease_along(e, network.refs_by_pid(h.sc))[k] == 0.0, "soft again"


def test_point_slides_along_the_line(h: H):
    c, k = _bow(h)
    _select_point(h, c, k)
    shape = c.points.copy()
    start = h.scrf(c.points[k])
    h.key(Qt.Key_S)  # hold S pressed (keyClick presses and releases - hence by hand)
    h.v._slide_key = True
    target = QPointF(start.x() + 60, start.y())
    h.stroke([start, target])
    h.v._slide_key = False
    c = h.curves()[0]
    k2 = [j for j in components.knots(c) if 0 < j < len(c.points) - 1]
    assert len(k2) == 1, k2
    q = c.points[k2[0]]
    assert q[0] > shape[k][0] + 0.2, f"point slid to the right ({q[0]:.2f})"
    d = np.min(np.linalg.norm(np.diff(shape, axis=0), axis=1))
    a, b = shape[:-1], shape[1:]
    t = np.clip(np.einsum("ij,ij->i", q - a, b - a) / np.einsum("ij,ij->i", b - a, b - a), 0, 1)
    assert np.min(np.linalg.norm(a + (b - a) * t[:, None] - q, axis=1)) < 1e-6, "point lies on the old line"
    assert d > 0
    assert h.v.point_selection[0][3] == k2[0], "selection follows the point"


def test_several_points_scale_only_the_position(h: H):
    sc = h.new_scene()
    sc.new_stroke()
    sc.add_curve(line([0, 0, 0], [4, 0, 0], 41), sc.planes[0].id)
    c = sc.curves[-1]
    components.insert_point(c, 10, 0.0)
    components.insert_point(c, 30, 0.0)
    h.v._changed()
    network.sync(sc)
    ks = [j for j in components.knots(c) if 0 < j < len(c.points) - 1]
    group = components.ComponentGroup(sc, [(c, j) for j in ks], [])
    p = c.points[ks].mean(axis=0)
    gap = np.linalg.norm(c.points[ks[1]] - c.points[ks[0]])
    group.scale(np.full(3, 2.0), np.eye(3), p)
    for j in ks:
        assert abs(network.get_attr(sc, network.pid_of(c, j))[4] - 1.0) < 1e-9, "pscale stays"
    assert abs(np.linalg.norm(c.points[ks[1]] - c.points[ks[0]]) - 2 * gap) < 1e-6, "distance doubled"


def test_hard_line_kinks_the_surface(h: H):
    """Net surface: a raised line across the surface. Soft, the surface goes smoothly (round) over it, hard it kinks
    at the line (roof); half hardness lies in between."""
    from sketch_machine import netsurf
    n = 41
    u, v = np.meshgrid(np.linspace(0, 4, n), np.linspace(0, 4, n), indexing="ij")
    base = np.stack([u, np.zeros_like(u), v], axis=2)
    cols = np.linspace(1, n - 2, 30)
    uv = np.stack([np.full_like(cols, 20.0), cols], axis=1)
    targets = np.stack([np.full_like(cols, 2.0), np.ones_like(cols), cols * 0.1], axis=1)
    groups = np.zeros(len(cols))
    kink = {}
    for value in (0.0, 0.5, 1.0):
        y = netsurf.solve(base, uv, targets, groups, hard=np.full(len(cols), value))[..., 1]
        row = y[:, n // 2]
        kink[value] = (row[20] - row[18]) - (row[22] - row[20])  # slope jump at the line
    assert kink[1.0] > 1.5 * kink[0.0], kink
    assert kink[0.0] < kink[0.5] < kink[1.0], kink


def test_export_with_hardness(h: H):
    """Sketch Brief: lines along which the surface kinks get primvars:hardness per point (proportional)."""
    from sketch_machine import brief
    e, m, pid = _cross(h)
    k = network.knot_at(e, np.array([2.0, 0, 0]))
    path = os.path.join(tempfile.mkdtemp(), "scene.usda")
    brief.write_usd(h.sc, brief.analyse(h.sc), path)
    text = open(path, encoding="utf-8").read()
    assert text.count("float[] primvars:hardness") == 1, "only the edge with a kinking cross line"
    values = [float(x) for x in text.split("primvars:hardness = [")[1].split("]")[0].split(",")]
    assert len(values) == len(e.points) and values[k] == 1.0 and values[0] == 0.0


def test_smoothing_down_to_straight(h: H):
    """J: half smoothed, the jitter disappears (the shape stays roughly), fully smoothed the edge is straight; the ends
    stay."""
    sc = h.new_scene()
    sc.new_stroke()
    t = np.linspace(0, 1, 121)
    rng = np.random.default_rng(3)
    pts = np.stack([t * 4, np.zeros_like(t), 0.8 * np.sin(t * np.pi) + 0.03 * rng.standard_normal(len(t))], 1)
    sc.add_curve(pts, sc.planes[0].id)
    c = sc.curves[-1]
    c.knots = (len(pts), ())
    h.v._changed()
    ends = c.points[[0, -1]].copy()
    h.camera([2, 0, 0.4], 7, [0, 1, 0.01])
    h.edit_mode("edge")
    h.v.edge_selection = [("line", sc.owner_of(c).id, c.id)]
    h.v._changed()
    p0 = QPointF(40, 40)
    h.key(Qt.Key_J)
    assert h.v.ws.value_tool == "smooth"
    QTest.mousePress(h.v, Qt.LeftButton, Qt.NoModifier, p0.toPoint())
    h.move(QPointF(p0.x() + 30, p0.y()), Qt.LeftButton)
    h.move(QPointF(p0.x() + 60, p0.y()), Qt.LeftButton)  # 0,3
    jitter = lambda p: float(np.abs(np.diff(p[:, 2], 2)).mean())
    c = h.curves()[0]
    assert jitter(c.points) < 0.3 * jitter(pts) and c.points[:, 2].max() > 0.5, "jitter gone, arc stays"
    h.key(Qt.Key_Escape)
    QTest.mouseRelease(h.v, Qt.LeftButton, Qt.NoModifier, QPoint(int(p0.x()) + 60, int(p0.y())))
    h.pump(0.02)
    assert np.allclose(h.curves()[0].points, pts), "Esc: unchanged"
    h.stroke([p0, QPointF(p0.x() + 260, p0.y())])
    c = h.curves()[0]
    d = ends[1] - ends[0]
    off = np.cross(c.points - ends[0], d / np.linalg.norm(d))
    assert np.allclose(c.points[[0, -1]], ends) and np.abs(off).max() < 1e-9, "straight"


def test_hardness_shapes_the_line_at_the_point(h: H):
    """Harden a point on a curve: the line gets a kink there (each side runs straighter towards the point);
    point and ends stay; soft again: the curve is back."""
    c, k = _bow(h)
    _select_point(h, c, k)
    pts = c.points.copy()

    def kink(p):
        u, v = p[k] - p[k - 2], p[k + 2] - p[k]
        return np.degrees(np.arccos(np.clip(u @ v / np.linalg.norm(u) / np.linalg.norm(v), -1, 1)))
    assert kink(pts) < 10, "round at first"
    h.key(Qt.Key_K, Qt.ShiftModifier)
    c = h.curves()[0]
    assert kink(c.points) > 40, f"hard: kink at the point ({kink(c.points):.0f}°)"
    assert np.allclose(c.points[[0, k, -1]], pts[[0, k, -1]]), "point and ends stay"
    h.key(Qt.Key_K, Qt.AltModifier)
    c = h.curves()[0]
    # K reads the original shape from the line (nothing stored): round as before except for an invisible remainder
    assert kink(c.points) < 10 and np.abs(c.points - pts).max() < 2e-3 * np.ptp(pts, axis=0).max(), \
        "soft again: as before"


def test_tool_off_on_transform_and_on_second_click(h: H):
    c, k = _bow(h)
    _select_point(h, c, k)
    h.key(Qt.Key_K)
    assert h.v.ws.value_tool == "hardness"
    h.key(Qt.Key_T)
    assert h.v.ws.value_tool is None and h.v.gizmo.tool == "translate", "T ends hardness"
    h.v.set_transform_tool(None)
    h.key(Qt.Key_J)  # edge mode
    h.key(Qt.Key_J)
    h.edit_mode("point")
    h.v.point_selection = [("pt", h.sc.owner_of(c).id, c.id, k)]
    h.key(Qt.Key_K)
    h.click(h.scr(c.points[k]))  # again on the selected point
    assert h.v.ws.value_tool is None, "a second click on the selection ends the tool"
    assert h.v.point_selection, "selection stays"


def test_drag_points_auto_soft_hard(h: H):
    """Bar \"Drag points\": Auto/Soft/Hard. A point on a curve: Auto and Soft pull it up round (the
    line does not kink there), Hard with a kink at the point; Auto is the default, the buttons appear in point/edge mode."""
    results = {}
    for mode in ("auto", "soft", "hard"):
        c, k = _bow(h)
        _select_point(h, c, k)
        assert h.w.knot_actions[mode].isVisible() or not h.w.isVisible()
        h.w.knot_actions[mode].trigger()
        assert h.v.ws.knot_mode == mode and h.w.knot_actions[mode].isChecked()
        h.v.transform_target.translate(np.array([0.0, 0.0, 0.6]))
        h.v._changed()
        results[mode] = _sharp(h, c, k)
    h.w.knot_actions["auto"].trigger()
    assert results["auto"] < 0.2 and results["soft"] < 0.2, f"pulled up round: {results}"
    assert results["hard"] > 0.3, f"hard: kink at the point ({results})"

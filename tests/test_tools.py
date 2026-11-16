"""Tools: drawing, line thickness, Ctrl+Shift erasing per surface, light levels, stroke ends in shadow."""
import numpy as np

from tests.harness import H, Qt, line
from sketch_machine import light as L


def test_drawing_creates_a_line(h: H):
    h.camera([0, 0, 0], 8, [0, 0.8, 0.6])
    h.stroke_world([[x, 0, 0.4 * np.sin(x)] for x in np.linspace(-2, 2, 20)])
    assert len(h.curves()) == 1 and len(h.curves()[0].points) > 5


def test_straight_line_by_holding_still(h: H):
    h.camera([0, 0, 0], 8, [0, 0.8, 0.6])
    h.stroke_world([[x, 0, 0.3 * np.sin(x * 3)] for x in np.linspace(-2, 2, 20)], hold=True)
    c = h.curves()[-1]
    chord = c.points[-1] - c.points[0]
    off = np.linalg.norm(np.cross(c.points - c.points[0], chord / np.linalg.norm(chord)), axis=1)
    assert float(off.max()) < 0.02, "holding still yields a straight line"


def test_scale_line_thickness(h: H):
    sc = h.sc
    sc.new_stroke()
    for k in range(3):
        sc.add_curve(line([k, 0, 0], [k, 0, 2], 10), sc.planes[0].id)
    h.v._changed()
    w0 = {c.id: c.widths.copy() for c in h.curves()}
    h.wheel(2, Qt.ControlModifier | Qt.ShiftModifier)
    ratio = np.mean([c.widths.mean() / w0[c.id].mean() for c in h.curves()])
    assert abs(ratio - 1.21) < 0.01, ratio
    h.key(Qt.Key_Z, Qt.ControlModifier)
    assert all(np.allclose(c.widths, w0[c.id]) for c in h.curves()), "one undo restores everything"


def test_light_levels_slider(h: H):
    assert [L.bands_from_slider(v) for v in (0, 50, 100)] == [3, 10, 0]
    assert [L.slider_from_bands(b) for b in (3, 10, 0)] == [0, 50, 100]


def test_stroke_ends_in_shadow(h: H):
    """The round ends get the same shadow as the line segment beside them."""
    sc = h.sc
    sc.new_stroke()
    t = np.linspace(0, 1, 40)
    sc.add_curve(np.stack([t * 4 - 2, np.zeros_like(t), np.zeros_like(t)], 1), None, np.full(40, 0.12))
    sc.curves[-1].style, sc.curves[-1].color = "brush", (0.75, 0.25, 0.15)
    corners = [np.array(p) for p in ([-3.0, 1.0, -0.6], [-0.6, 1.0, -0.6], [-0.6, 1.0, 0.6], [-3.0, 1.0, 0.6])]
    roof = []
    for k in range(4):  # roof as a surface: casts the shadow
        sc.add_curve(np.linspace(corners[k], corners[(k + 1) % 4], 8), None)
        roof.append(sc.curves[-1])
    sc.create_fill([(c, False) for c in roof])
    sc.sun = (0.0, 89.0)
    h.v.ws.light_on = True
    h.v.set_planes_visible(False)
    h.camera([-1.6, 0, 0], 2.6, [0.2, 0.25, 0.9])
    img = h.save_image("cap_schatten.png")
    end = h.scr(sc.curves[-1].points[0])
    beside = h.scr(sc.curves[-1].points[3])
    cap = h.pixel(img, h.scrf(sc.curves[-1].points[0] - np.array([0.04, 0, 0])).toPoint())
    rib = h.pixel(img, beside)
    h.v.ws.light_on = False
    assert abs(sum(cap) - sum(rib)) < 120, f"cap {cap} vs. ribbon {rib} (end at {end.x()}, {end.y()})"


def test_pencil_and_chalk_colour(h: H):
    from sketch_machine import theme
    sc = h.new_scene()
    sc.new_stroke()
    sc.add_curve(np.linspace([0, 0, 1], [2, 0, 1], 10), sc.planes[0].id, np.full(10, 0.06))
    h.v._changed()
    h.camera([1, 0, 1], 3, [0, 1, 0.01])
    try:
        theme.set_stroke_colors((30, 60, 160), (240, 200, 60))
        h.v._changed()
        r, g, b = h.pixel(h.grab(), h.scr([1, 0, 1]))
        assert b > r + 60, f"pencil blue ({r}, {g}, {b})"
        h.w._set_dark(True, persist=False)
        h.v._changed()
        r, g, b = h.pixel(h.grab(), h.scr([1, 0, 1]))
        assert r > b + 60, f"chalk yellow ({r}, {g}, {b})"
        assert theme.GRAPHITE.getRgb()[:3] != (30, 60, 160), "overlay colours stay"
    finally:
        h.w._set_dark(False, persist=False)
        theme.set_stroke_colors(theme.PENCIL_DEFAULT, theme.CHALK_DEFAULT)


def test_normal_smoothing_follows_the_light_levels(h: H):
    from sketch_machine.renderer import calm_for_bands
    assert calm_for_bands(0) == 0.0, "continuous light: no smoothing"
    assert calm_for_bands(3) == calm_for_bands(5) == 1.0, "up to 5 levels: full"
    assert calm_for_bands(30) == calm_for_bands(50) == 0.0, "from 30 levels: none"
    assert abs(calm_for_bands(17.5) - 0.5) < 1e-9, "proportional in between"


def test_cleanup_snap_distance(h: H):
    """Cleanup menu, snap distance in space: a 5 cm gap stays open at 2 cm and is welded at 10 cm -
    independent of zoom (far away the same as near)."""
    from sketch_machine.workspace import CLEANUP_DIST_DEFAULT
    sc = h.sc
    sc.new_stroke()
    sc.add_curve(line([0, 0, 0], [1, 0, 0], 8), None)
    a = sc.curves[-1]
    sc.add_curve(line([1.05, 0, 0], [2, 0, 0], 8), None)
    b = sc.curves[-1]
    h.v._changed()
    h.camera([1, 0, 0], 200, [0.0, 1.0, 0.02])  # far away: under one pixel on screen
    h.edit_mode("edge")
    h.v.edge_selection = [("line", sc.strokes[-1].id, c.id) for c in (a, b)]
    try:
        h.v.ws.cleanup_dist = 0.02
        h.v.weld()
        assert np.linalg.norm(a.points[-1] - b.points[0]) > 0.04, "2 cm: gap stays"
        h.camera([1, 0, 0], 0.3, [0.0, 1.0, 0.02])  # very close
        h.v.edge_selection = [("line", sc.strokes[-1].id, c.id) for c in (a, b)]
        h.v.ws.cleanup_dist = 0.1
        h.v.weld()
        assert np.linalg.norm(a.points[-1] - b.points[0]) < 1e-6, "10 cm: welded"
    finally:
        h.v.ws.cleanup_dist = CLEANUP_DIST_DEFAULT

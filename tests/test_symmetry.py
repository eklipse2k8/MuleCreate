"""Symmetry: instances (display only) – the original cut at the mirror plane, plus the mirror image."""
import numpy as np

import os

from tests.harness import H, OUT, line
from sketch_machine import generators


def _sym_with_line(h, a, b):
    sc = h.sc
    st = sc.new_stroke(parent=None)
    sc.add_curve(line(a, b, 31), None)
    h.edit_mode("edge")
    h.v.set_selection([st.id])
    sym = h.v.create_null("symmetry")
    return st, sym


def _lines_near(entries, x_lo, x_hi):
    return [e for e in entries if len(e[0]) >= 2 and x_lo - 1e-9 <= e[0][:, 0].min() and e[0][:, 0].max() <= x_hi + 1e-9]


def test_line_cut_and_mirrored(h: H):
    st, sym = _sym_with_line(h, [-1, 0, 0.5], [2, 0, 0.5])
    assert sym.params["side"] == 1, "kept side: where the line mostly lies"
    entries = [e for e in h.v._stroke_draw_list() if len(e[0]) > 1]
    right = _lines_near(entries, 0, 2)
    left = _lines_near(entries, -2, 0)
    assert len(right) == 1 and len(left) == 1, f"original (cut) + mirror image: {len(entries)} entries"
    assert abs(right[0][0][:, 0].min()) < 1e-9, "cut exactly on the plane"
    assert np.allclose(np.sort(left[0][0][:, 0]), np.sort(-right[0][0][:, 0])), "mirror image"
    assert len(st.curves[0].points) == 31 and st.curves[0].points[0, 0] == -1, "the real line stays unchanged"


def test_side_and_plane(h: H):
    st, sym = _sym_with_line(h, [0.5, 0, 0], [2, 0, 1])
    sym.params["side"] = -1  # keep the other side: the line lies entirely over there -> nothing to see
    assert not [e for e in h.v._stroke_draw_list() if len(e[0]) > 1]
    sym.params.update(side=1, plane="xy")  # mirror along z: line z 0..1 stays whole, mirror image at z <= 0
    entries = [e for e in h.v._stroke_draw_list() if len(e[0]) > 1]
    assert len(entries) == 2 and min(e[0][:, 2].min() for e in entries) < -0.9


def _fill_square(sc, x0, x1):
    st = sc.new_stroke(parent=None)
    P = [np.array(p, float) for p in ([x0, 0, 0], [x1, 0, 0], [x1, 0, 1], [x0, 0, 1])]
    for p, q in zip(P, P[1:] + P[:1]):
        sc.add_curve(line(p, q, 9), None)
    f = sc.create_fill([(c, False) for c in st.curves])
    sc.sync_lofts()
    return st, f


def _area(verts, tris):
    v = np.asarray(verts)[np.asarray(tris)]
    return float(np.linalg.norm(np.cross(v[:, 1] - v[:, 0], v[:, 2] - v[:, 0]), axis=1).sum() / 2)


def test_surface_cut_with_winding_order(h: H):
    sc = h.sc
    st, f = _fill_square(sc, -0.5, 1.5)
    h.edit_mode("face")
    h.v.set_selection([st.id, f.id])
    sym = h.v.create_null("symmetry")
    assert f.parent == sym.id
    entries = h.v._surface_draw_list()
    orig = [e for e in entries if e["id"] == f.id]
    copy = [e for e in entries if e["id"] != f.id]
    assert len(orig) == 1 and len(copy) == 1
    assert orig[0]["verts"][:, 0].min() > -1e-9 and copy[0]["verts"][:, 0].max() < 1e-9
    assert abs(_area(orig[0]["verts"], orig[0]["tris"]) - 1.5) < 1e-6, "cut: surface 1.5 x 1"
    n0 = np.cross(*(orig[0]["verts"][orig[0]["tris"][0]][1:] - orig[0]["verts"][orig[0]["tris"][0]][0]))
    n1 = np.cross(*(copy[0]["verts"][copy[0]["tris"][0]][1:] - copy[0]["verts"][copy[0]["tris"][0]][0]))
    assert np.sign(n0[1]) == np.sign(n1[1]), "mirrored: winding order reversed, normal points the same way"


def test_line_belongs_to_the_copy_of_its_surface(h: H):
    sc = h.sc
    st, f = _fill_square(sc, 0, 1)
    st.curves[0].plane_id = f.id  # line lies on the surface
    h.edit_mode("face")
    h.v.set_selection([st.id, f.id])
    sym = h.v.create_null("symmetry")
    surf_ids = {e["id"] for e in h.v._surface_draw_list()}
    lines = [e for e in h.v._stroke_draw_list() if len(e) > 4 and e[4]]
    copy_lines = [e for e in lines if e[0][:, 0].min() < -0.5]  # entirely over there (the edge on the plane is both)
    assert copy_lines and all(set(e[4]) <= surf_ids and f.id not in e[4] for e in copy_lines), \
        "mirrored lines belong to the mirrored surface"


def test_nested_and_hidden(h: H):
    sc = h.sc
    st, sym = _sym_with_line(h, [0.5, 0, 0], [1, 0, 0])
    sym2 = sc.new_null("symmetry")
    sym2.params.update(plane="xy", side=1)
    sym2.origin = np.array([0, 0, -1.0])
    sc.set_parent([sym], sym2)
    entries = [e for e in h.v._stroke_draw_list() if len(e[0]) > 1]
    assert len(entries) == 4, f"symmetry in symmetry: 2 x 2 copies, {len(entries)}"
    assert any(e[0][:, 2].max() < -1.9 for e in entries), "outer mirror acts on the result of the inner one"
    h.v.set_hidden(sym2.id, True)
    assert not [e for e in h.v._stroke_draw_list() if len(e[0]) > 1]


def test_clip_mesh_net_stays_together(h: H):
    g = np.linspace(-1, 1, 7)
    X, Z = np.meshgrid(g, g)
    verts = np.column_stack([X.ravel(), np.zeros(X.size), Z.ravel()]) + [0.13, 0, 0]
    tris = []
    for i in range(6):
        for j in range(6):
            a = i * 7 + j
            tris += [(a, a + 1, a + 8), (a, a + 8, a + 7)]
    v, t = generators.clip_mesh(verts, np.array(tris), np.array([1.0, 0, 0]), np.zeros(3))
    assert abs(_area(v, t) - 2 * 1.13) < 1e-9
    assert v[:, 0].min() > -1e-12
    edges = {}
    for tri in t:
        for k in range(3):
            e = tuple(sorted((tri[k], tri[(k + 1) % 3])))
            edges[e] = edges.get(e, 0) + 1
    border = [e for e, n in edges.items() if n == 1]
    on_plane = [e for e in border if abs(v[e[0], 0]) < 1e-9 and abs(v[e[1], 0]) < 1e-9]
    assert len(on_plane) >= 6, "cut border made of shared points (no cracks)"


def test_image_shows_mirror_image(h: H):
    sc = h.sc
    st, f = _fill_square(sc, 0.2, 1.2)
    h.edit_mode("face")
    h.v.set_selection([st.id, f.id])
    h.v.create_null("symmetry")
    h.v.set_selection([])
    h.draw_mode()
    h.sc.activate(h.sc.presets[1])  # drawing plane elsewhere: both halves at rest
    h.camera([0, 0, 0.5], 4, (0, 1, 0.001))
    img = h.grab()
    img.save(os.path.join(OUT, "symmetrie_bild.png"))
    lx, rx = h.scr([-0.7, 0, 0.5]), h.scr([0.7, 0, 0.5])
    mid = h.scr([0.0, 0, 0.5])
    bg = h.pixel(img, h.scr([0, 0, 2.5]))
    left, right, gap = h.pixel(img, lx), h.pixel(img, rx), h.pixel(img, mid)
    assert max(abs(a - b) for a, b in zip(left, right)) <= 12, f"both halves drawn the same: {left} vs {right}"
    assert max(abs(a - b) for a, b in zip(left, bg)) > 12, f"mirrored surface is visible: {left} vs {bg}"


def test_drawing_in_new_symmetry_snaps_to_the_plane(h: H):
    sc = h.sc
    sym = h.v.create_null("symmetry")  # without a selection: empty stroke object below it, drawing goes there
    assert sc.active_stroke.parent == sym.id
    h.draw_mode()
    h.camera([0.5, 0, 0.5], 4, (0, 1, 0.001))
    h.v.ws.magnet = True
    h.stroke_world([[1.0, 0, 0.8], [0.5, 0, 0.6], [0.03, 0, 0.5]])
    c = sc.active_stroke.curves[-1]
    assert abs(c.points[-1, 0]) < 1e-9, f"end lies exactly on the mirror plane: {c.points[-1]}"
    h.stroke_world([[1.0, 0, 0.2], [0.4, 0, 0.2]])
    assert abs(sc.active_stroke.curves[-1].points[-1, 0] - 0.4) < 0.05, "far away: no snapping"


def test_setting_with_undo(h: H):
    st, sym = _sym_with_line(h, [0.5, 0, 0], [1, 0, 0])
    h.v.set_null_param(sym.id, "plane", "xy")
    assert h.sc.null_by_id(sym.id).params["plane"] == "xy"
    h.v.undo()
    assert h.sc.nulls[0].params["plane"] == "zy"


def test_click_on_copy_selects_generator(h: H):
    sc = h.sc
    st, f = _fill_square(sc, 0.2, 1.2)
    h.edit_mode("face")
    h.v.set_selection([st.id, f.id])
    sym = h.v.create_null("symmetry")
    h.camera([0, 0, 0.5], 4, (0, 1, 0.001))
    h.click(h.scr([-0.7, 0, 0.5]))  # center of the mirrored surface
    assert h.v.selection == [sym.id], f"copy clicked: generator selected ({h.v.selection})"
    h.click(h.scr([0.7, 0, 0.5]))
    assert h.v.selection == [f.id], "original clicked: the surface itself"
    h.edit_mode("edge")
    h.click(h.scr([-1.2, 0, 0.5]))  # mirrored border line
    assert h.v.selection == [sym.id], f"line copy clicked: generator ({h.v.selection})"


def test_light_xray_painting_with_instances(h: H):
    from tests.harness import QT_ERRORS
    sc = h.sc
    st, f = _fill_square(sc, 0.2, 1.2)
    h.edit_mode("face")
    h.v.set_selection([st.id, f.id])
    h.v.create_null("symmetry")
    h.draw_mode()
    sc.activate_mesh(f)
    h.camera([0, 0, 0.5], 4, (0.3, 1, 0.3))
    h.v.set_paint_mode(True)
    h.stroke_world([[0.4, 0, 0.3], [1.0, 0, 0.7]])
    h.v.set_paint_mode(False)
    paints = [e for e in h.v._stroke_draw_list() if len(e) > 5]
    assert len(paints) == 2 and min(e[0][:, 0].min() for e in paints) < -0.3, "painting is mirrored too"
    n_before = len(QT_ERRORS)
    h.v.set_light(True)
    h.grab()
    h.v.set_light(False)
    h.v.set_xray(True)
    h.grab()
    h.v.set_xray(False)
    h.w._set_dark(True, persist=False)
    h.grab()
    h.w._set_dark(False, persist=False)
    assert len(QT_ERRORS) == n_before, QT_ERRORS[-1:]


def test_generator_takes_over_position_and_rotation_of_the_null(h: H):
    sc = h.sc
    st = sc.new_stroke(parent=None)
    sc.add_curve(line([1.0, 0, 0], [1.5, 0.5, 0], 11), None)
    h.edit_mode("edge")
    h.v.set_selection([st.id])
    null = h.v.create_null("null")
    c, s = np.cos(0.6), np.sin(0.6)
    null.axes = np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])
    null.origin = np.array([0.3, 0.2, -0.4])
    h.v.set_selection([null.id])
    sym = h.v.create_null("symmetry")  # selected null: symmetry takes over its transform
    assert np.allclose(sym.origin, null.origin) and np.allclose(sym.axes, null.axes)
    assert sym.axes is not null.axes and sym.origin is not null.origin
    h.v.set_selection([st.id])  # line in the null: array takes over its transform
    arr = h.v.create_null("array")
    assert np.allclose(arr.origin, sym.origin) and np.allclose(arr.axes, sym.axes)
    lone = sc.new_stroke(parent=None)
    sc.add_curve(line([2.0, 0, 0], [2.5, 0, 0], 5), None)
    h.v.set_selection([lone.id])
    sym2 = h.v.create_null("symmetry")  # without a null: world origin as before
    assert np.allclose(sym2.origin, 0) and np.allclose(sym2.axes, np.eye(3))


def test_thick_lines_cast_wide_shadows(h: H):
    from sketch_machine.renderer import shadow_ribbons
    pts = np.array([[0.0, 0, 0], [1.0, 0, 0], [1.0, 0, 1.0]])
    sun, r = np.array([0.0, 1, 0]), np.array([1.0, 0, 0])
    thin = shadow_ribbons([(pts, 0.001)], sun, 0.01, r)
    thick = shadow_ribbons([(pts, np.array([0.2, 0.2, 0.2]))], sun, 0.01, r)
    assert np.ptp(thin[:6, 2]) == np.float32(0.01), "thin line: minimum width"
    assert abs(np.ptp(thick[:6, 2]) - 0.2) < 1e-6, "shadow ribbon as wide as the stroke"


def test_generator_off_shows_original_uncut(h: H):
    st, sym = _sym_with_line(h, [-1, 0, 0.5], [2, 0, 0.5])
    h.v.set_null_param(sym.id, "on", False)  # off: nothing cut, nothing mirrored
    entries = [e for e in h.v._stroke_draw_list() if len(e[0]) > 1]
    assert len(entries) == 1 and np.isclose(entries[0][0][:, 0].min(), -1), "only the original, uncut"
    assert not h.v._active_syms(), "off: no snapping to the mirror plane"
    h.v.set_null_param(sym.id, "on", True)
    assert len([e for e in h.v._stroke_draw_list() if len(e[0]) > 1]) == 2, "on again: original + mirror image"


def test_clean_image_tints_brush_line_including_mirror_image(h: H):
    """Brief focus (clean_image select+lines): the brush line of a selected object is tinted – its mirror image
    too, not only the original."""
    from sketch_machine.vp.common import SELECTED_STROKE_COLOR, _rgba
    st, sym = _sym_with_line(h, [-1, 0, 0.5], [2, 0, 0.5])
    c = st.curves[0]
    c.style, c.color = "brush", (0.9, 0.1, 0.1)
    v = h.v
    v.ws.selection = [st.id]
    v._clean_frame, v._extra_tint = True, {("line", st.id, c.id): SELECTED_STROKE_COLOR}
    try:
        entries = [e for e in v._stroke_draw_list() if len(e[0]) > 1]
    finally:
        v._clean_frame, v._extra_tint = False, {}
    assert len(entries) == 2 and all(tuple(e[2]) == tuple(_rgba(SELECTED_STROKE_COLOR)) for e in entries), \
        [e[2] for e in entries]
    plain = [e for e in v._stroke_draw_list() if len(e[0]) > 1]  # in the normal image: copy neutral, brush color stays
    assert any(tuple(e[2]) != tuple(_rgba(SELECTED_STROKE_COLOR)) for e in plain)

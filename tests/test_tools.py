"""Werkzeuge: Zeichnen, Liniendicke, Strg+Shift-Radieren je Fläche, Licht-Stufen, Strichenden im Schatten."""
import numpy as np

from tests.harness import H, Qt, line
from sketch_machine import light as L


def test_zeichnen_erzeugt_linie(h: H):
    h.camera([0, 0, 0], 8, [0, 0.8, 0.6])
    h.stroke_world([[x, 0, 0.4 * np.sin(x)] for x in np.linspace(-2, 2, 20)])
    assert len(h.curves()) == 1 and len(h.curves()[0].points) > 5


def test_gerade_durch_stillhalten(h: H):
    h.camera([0, 0, 0], 8, [0, 0.8, 0.6])
    h.stroke_world([[x, 0, 0.3 * np.sin(x * 3)] for x in np.linspace(-2, 2, 20)], hold=True)
    c = h.curves()[-1]
    chord = c.points[-1] - c.points[0]
    off = np.linalg.norm(np.cross(c.points - c.points[0], chord / np.linalg.norm(chord)), axis=1)
    assert float(off.max()) < 0.02, "Stillhalten ergibt eine Gerade"


def test_liniendicke_skalieren(h: H):
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
    assert all(np.allclose(c.widths, w0[c.id]) for c in h.curves()), "ein Undo stellt alles her"


def test_licht_stufen_regler(h: H):
    assert [L.bands_from_slider(v) for v in (0, 50, 100)] == [3, 10, 0]
    assert [L.slider_from_bands(b) for b in (3, 10, 0)] == [0, 50, 100]


def test_strichenden_im_schatten(h: H):
    """Die runden Enden bekommen denselben Schatten wie das Linienstück daneben."""
    sc = h.sc
    sc.new_stroke()
    t = np.linspace(0, 1, 40)
    sc.add_curve(np.stack([t * 4 - 2, np.zeros_like(t), np.zeros_like(t)], 1), None, np.full(40, 0.12))
    sc.curves[-1].style, sc.curves[-1].color = "brush", (0.75, 0.25, 0.15)
    corners = [np.array(p) for p in ([-3.0, 1.0, -0.6], [-0.6, 1.0, -0.6], [-0.6, 1.0, 0.6], [-3.0, 1.0, 0.6])]
    roof = []
    for k in range(4):  # Dach als Fläche: wirft den Schatten
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
    assert abs(sum(cap) - sum(rib)) < 120, f"Kappe {cap} vs. Band {rib} (Ende bei {end.x()}, {end.y()})"


def test_bleistift_und_kreidefarbe(h: H):
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
        assert b > r + 60, f"Bleistift blau ({r}, {g}, {b})"
        h.w._set_dark(True, persist=False)
        h.v._changed()
        r, g, b = h.pixel(h.grab(), h.scr([1, 0, 1]))
        assert r > b + 60, f"Kreide gelb ({r}, {g}, {b})"
        assert theme.GRAPHITE.getRgb()[:3] != (30, 60, 160), "Overlay-Farben bleiben"
    finally:
        h.w._set_dark(False, persist=False)
        theme.set_stroke_colors(theme.PENCIL_DEFAULT, theme.CHALK_DEFAULT)


def test_normalenglaettung_folgt_den_lichtstufen(h: H):
    from sketch_machine.renderer import calm_for_bands
    assert calm_for_bands(0) == 0.0, "fließendes Licht: keine Glättung"
    assert calm_for_bands(3) == calm_for_bands(5) == 1.0, "bis 5 Stufen: ganz"
    assert calm_for_bands(30) == calm_for_bands(50) == 0.0, "ab 30 Stufen: keine"
    assert abs(calm_for_bands(17.5) - 0.5) < 1e-9, "dazwischen anteilig"


def test_cleanup_fangweite(h: H):
    """Cleanup-Menü, Fangweite im Raum: eine Lücke von 5 cm bleibt bei 2 cm offen und wird bei 10 cm verschweißt –
    unabhängig vom Zoom (weit weg wie nah dasselbe)."""
    from sketch_machine.workspace import CLEANUP_DIST_DEFAULT
    sc = h.sc
    sc.new_stroke()
    sc.add_curve(line([0, 0, 0], [1, 0, 0], 8), None)
    a = sc.curves[-1]
    sc.add_curve(line([1.05, 0, 0], [2, 0, 0], 8), None)
    b = sc.curves[-1]
    h.v._changed()
    h.camera([1, 0, 0], 200, [0.0, 1.0, 0.02])  # weit weg: auf dem Bildschirm unter einem Pixel
    h.edit_mode("edge")
    h.v.edge_selection = [("line", sc.strokes[-1].id, c.id) for c in (a, b)]
    try:
        h.v.ws.cleanup_dist = 0.02
        h.v.weld()
        assert np.linalg.norm(a.points[-1] - b.points[0]) > 0.04, "2 cm: Lücke bleibt"
        h.camera([1, 0, 0], 0.3, [0.0, 1.0, 0.02])  # ganz nah
        h.v.edge_selection = [("line", sc.strokes[-1].id, c.id) for c in (a, b)]
        h.v.ws.cleanup_dist = 0.1
        h.v.weld()
        assert np.linalg.norm(a.points[-1] - b.points[0]) < 1e-6, "10 cm: verschweißt"
    finally:
        h.v.ws.cleanup_dist = CLEANUP_DIST_DEFAULT

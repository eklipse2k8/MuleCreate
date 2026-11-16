"""Symmetrie: Instanzen (nur Anzeige) – das Original an der Spiegelebene geschnitten, die Spiegelung dazu."""
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


def test_linie_geschnitten_und_gespiegelt(h: H):
    st, sym = _sym_with_line(h, [-1, 0, 0.5], [2, 0, 0.5])
    assert sym.params["side"] == 1, "behaltene Seite: wo die Linie überwiegend liegt"
    entries = [e for e in h.v._stroke_draw_list() if len(e[0]) > 1]
    right = _lines_near(entries, 0, 2)
    left = _lines_near(entries, -2, 0)
    assert len(right) == 1 and len(left) == 1, f"Original (geschnitten) + Spiegelung: {len(entries)} Einträge"
    assert abs(right[0][0][:, 0].min()) < 1e-9, "Schnitt genau auf der Ebene"
    assert np.allclose(np.sort(left[0][0][:, 0]), np.sort(-right[0][0][:, 0])), "Spiegelbild"
    assert len(st.curves[0].points) == 31 and st.curves[0].points[0, 0] == -1, "die echte Linie bleibt unverändert"


def test_seite_und_ebene(h: H):
    st, sym = _sym_with_line(h, [0.5, 0, 0], [2, 0, 1])
    sym.params["side"] = -1  # die andere Seite behalten: die Linie liegt ganz drüben -> nichts zu sehen
    assert not [e for e in h.v._stroke_draw_list() if len(e[0]) > 1]
    sym.params.update(side=1, plane="xy")  # Spiegeln entlang z: Linie z 0..1 bleibt ganz, Spiegelung bei z <= 0
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


def test_flaeche_geschnitten_mit_umlaufsinn(h: H):
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
    assert abs(_area(orig[0]["verts"], orig[0]["tris"]) - 1.5) < 1e-6, "geschnitten: Fläche 1.5 x 1"
    n0 = np.cross(*(orig[0]["verts"][orig[0]["tris"][0]][1:] - orig[0]["verts"][orig[0]["tris"][0]][0]))
    n1 = np.cross(*(copy[0]["verts"][copy[0]["tris"][0]][1:] - copy[0]["verts"][copy[0]["tris"][0]][0]))
    assert np.sign(n0[1]) == np.sign(n1[1]), "gespiegelt: Umlaufsinn umgedreht, Normale zeigt gleich"


def test_linie_gehoert_zur_kopie_ihrer_flaeche(h: H):
    sc = h.sc
    st, f = _fill_square(sc, 0, 1)
    st.curves[0].plane_id = f.id  # Linie liegt auf der Fläche
    h.edit_mode("face")
    h.v.set_selection([st.id, f.id])
    sym = h.v.create_null("symmetry")
    surf_ids = {e["id"] for e in h.v._surface_draw_list()}
    lines = [e for e in h.v._stroke_draw_list() if len(e) > 4 and e[4]]
    copy_lines = [e for e in lines if e[0][:, 0].min() < -0.5]  # ganz drüben (die Kante auf der Ebene ist beides)
    assert copy_lines and all(set(e[4]) <= surf_ids and f.id not in e[4] for e in copy_lines), \
        "gespiegelte Linien gehören zur gespiegelten Fläche"


def test_verschachtelt_und_ausgeblendet(h: H):
    sc = h.sc
    st, sym = _sym_with_line(h, [0.5, 0, 0], [1, 0, 0])
    sym2 = sc.new_null("symmetry")
    sym2.params.update(plane="xy", side=1)
    sym2.origin = np.array([0, 0, -1.0])
    sc.set_parent([sym], sym2)
    entries = [e for e in h.v._stroke_draw_list() if len(e[0]) > 1]
    assert len(entries) == 4, f"Symmetrie in Symmetrie: 2 x 2 Kopien, {len(entries)}"
    assert any(e[0][:, 2].max() < -1.9 for e in entries), "äußere Spiegelung wirkt auf das Ergebnis der inneren"
    h.v.set_hidden(sym2.id, True)
    assert not [e for e in h.v._stroke_draw_list() if len(e[0]) > 1]


def test_clip_mesh_netz_bleibt_zusammen(h: H):
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
    assert len(on_plane) >= 6, "Schnittrand aus geteilten Punkten (keine Risse)"


def test_bild_zeigt_spiegelung(h: H):
    sc = h.sc
    st, f = _fill_square(sc, 0.2, 1.2)
    h.edit_mode("face")
    h.v.set_selection([st.id, f.id])
    h.v.create_null("symmetry")
    h.v.set_selection([])
    h.draw_mode()
    h.sc.activate(h.sc.presets[1])  # Zeichenfläche woanders: beide Hälften im Ruhezustand
    h.camera([0, 0, 0.5], 4, (0, 1, 0.001))
    img = h.grab()
    img.save(os.path.join(OUT, "symmetrie_bild.png"))
    lx, rx = h.scr([-0.7, 0, 0.5]), h.scr([0.7, 0, 0.5])
    mid = h.scr([0.0, 0, 0.5])
    bg = h.pixel(img, h.scr([0, 0, 2.5]))
    left, right, gap = h.pixel(img, lx), h.pixel(img, rx), h.pixel(img, mid)
    assert max(abs(a - b) for a, b in zip(left, right)) <= 12, f"beide Hälften gleich gezeichnet: {left} vs {right}"
    assert max(abs(a - b) for a, b in zip(left, bg)) > 12, f"gespiegelte Fläche ist zu sehen: {left} vs {bg}"


def test_zeichnen_in_neue_symmetrie_rastet_an_der_ebene(h: H):
    sc = h.sc
    sym = h.v.create_null("symmetry")  # ohne Auswahl: leeres Stroke-Objekt darunter, dorthin wird gezeichnet
    assert sc.active_stroke.parent == sym.id
    h.draw_mode()
    h.camera([0.5, 0, 0.5], 4, (0, 1, 0.001))
    h.v.ws.magnet = True
    h.stroke_world([[1.0, 0, 0.8], [0.5, 0, 0.6], [0.03, 0, 0.5]])
    c = sc.active_stroke.curves[-1]
    assert abs(c.points[-1, 0]) < 1e-9, f"Ende liegt genau auf der Spiegelebene: {c.points[-1]}"
    h.stroke_world([[1.0, 0, 0.2], [0.4, 0, 0.2]])
    assert abs(sc.active_stroke.curves[-1].points[-1, 0] - 0.4) < 0.05, "weit weg: kein Einrasten"


def test_einstellung_mit_undo(h: H):
    st, sym = _sym_with_line(h, [0.5, 0, 0], [1, 0, 0])
    h.v.set_null_param(sym.id, "plane", "xy")
    assert h.sc.null_by_id(sym.id).params["plane"] == "xy"
    h.v.undo()
    assert h.sc.nulls[0].params["plane"] == "zy"


def test_klick_auf_kopie_waehlt_generator(h: H):
    sc = h.sc
    st, f = _fill_square(sc, 0.2, 1.2)
    h.edit_mode("face")
    h.v.set_selection([st.id, f.id])
    sym = h.v.create_null("symmetry")
    h.camera([0, 0, 0.5], 4, (0, 1, 0.001))
    h.click(h.scr([-0.7, 0, 0.5]))  # Mitte der gespiegelten Fläche
    assert h.v.selection == [sym.id], f"Kopie angeklickt: Generator gewählt ({h.v.selection})"
    h.click(h.scr([0.7, 0, 0.5]))
    assert h.v.selection == [f.id], "Original angeklickt: die Fläche selbst"
    h.edit_mode("edge")
    h.click(h.scr([-1.2, 0, 0.5]))  # gespiegelte Randlinie
    assert h.v.selection == [sym.id], f"Linien-Kopie angeklickt: Generator ({h.v.selection})"


def test_licht_xray_malerei_mit_instanzen(h: H):
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
    assert len(paints) == 2 and min(e[0][:, 0].min() for e in paints) < -0.3, "Malerei wird mitgespiegelt"
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


def test_generator_uebernimmt_lage_und_drehung_des_nulls(h: H):
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
    sym = h.v.create_null("symmetry")  # gewähltes Null: Symmetrie übernimmt seinen Transform
    assert np.allclose(sym.origin, null.origin) and np.allclose(sym.axes, null.axes)
    assert sym.axes is not null.axes and sym.origin is not null.origin
    h.v.set_selection([st.id])  # Linie im Null: Array übernimmt dessen Transform
    arr = h.v.create_null("array")
    assert np.allclose(arr.origin, sym.origin) and np.allclose(arr.axes, sym.axes)
    lone = sc.new_stroke(parent=None)
    sc.add_curve(line([2.0, 0, 0], [2.5, 0, 0], 5), None)
    h.v.set_selection([lone.id])
    sym2 = h.v.create_null("symmetry")  # ohne Null: Weltursprung wie bisher
    assert np.allclose(sym2.origin, 0) and np.allclose(sym2.axes, np.eye(3))


def test_dicke_linien_werfen_breite_schatten(h: H):
    from sketch_machine.renderer import shadow_ribbons
    pts = np.array([[0.0, 0, 0], [1.0, 0, 0], [1.0, 0, 1.0]])
    sun, r = np.array([0.0, 1, 0]), np.array([1.0, 0, 0])
    thin = shadow_ribbons([(pts, 0.001)], sun, 0.01, r)
    thick = shadow_ribbons([(pts, np.array([0.2, 0.2, 0.2]))], sun, 0.01, r)
    assert np.ptp(thin[:6, 2]) == np.float32(0.01), "dünne Linie: Mindestbreite"
    assert abs(np.ptp(thick[:6, 2]) - 0.2) < 1e-6, "Schattenband so breit wie der Strich"


def test_generator_aus_zeigt_original_ungeschnitten(h: H):
    st, sym = _sym_with_line(h, [-1, 0, 0.5], [2, 0, 0.5])
    h.v.set_null_param(sym.id, "on", False)  # aus: nichts geschnitten, nichts gespiegelt
    entries = [e for e in h.v._stroke_draw_list() if len(e[0]) > 1]
    assert len(entries) == 1 and np.isclose(entries[0][0][:, 0].min(), -1), "nur das Original, ungeschnitten"
    assert not h.v._active_syms(), "aus: kein Einrasten an der Spiegelebene"
    h.v.set_null_param(sym.id, "on", True)
    assert len([e for e in h.v._stroke_draw_list() if len(e[0]) > 1]) == 2, "wieder an: Original + Spiegelung"


def test_sauberes_bild_faerbt_pinsellinie_samt_spiegelung(h: H):
    """Brief-Fokus (clean_image select+lines): die Pinsellinie eines gewählten Objekts wird eingefärbt – auch ihre
    Spiegelung, nicht nur das Original."""
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
    plain = [e for e in v._stroke_draw_list() if len(e[0]) > 1]  # im normalen Bild: Kopie neutral, Pinselfarbe bleibt
    assert any(tuple(e[2]) != tuple(_rgba(SELECTED_STROKE_COLOR)) for e in plain)

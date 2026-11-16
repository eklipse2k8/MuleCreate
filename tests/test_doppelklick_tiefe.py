"""Doppelklick/Klick im Edit-Modus wählt nur Sichtbares: eine Kante, die hinter der vorderen Fläche durchscheint, gewinnt
nicht mehr, nur weil sie näher am Cursor liegt (Hafentest 09.11.: Doppelklick traf die Fläche dahinter)."""
from tests.harness import H, line


def _square(h, sc, x0, y, x1):
    st = sc.new_stroke()
    pts = [[x0, y, 0], [x1, y, 0], [x1, y, 2], [x0, y, 2], [x0, y, 0]]
    for p, q in zip(pts[:-1], pts[1:]):
        sc.add_curve(line(p, q, 8), None)
    h.v.edge_selection = [("line", st.id, c.id) for c in st.curves]
    h.v.do_patch()
    return st, sc.surfaces[-1]


def _setup(h, comp):
    sc = h.new_scene()
    front, fs = _square(h, sc, 0, 0.0, 2)
    back, bs = _square(h, sc, 1, -1.0, 3)
    h.v._changed()
    h.camera([1.5, 0, 1], 8, [0.0, 1.0, 0.03])
    h.edit_mode(comp)
    h.v._apply_selection([fs.id, front.id], [], "replace")
    h.v._changed()
    h.grab()
    # Mitte der vorderen Fläche; 1 m dahinter verläuft dort die linke Kante der hinteren
    return h.scr([1.0, -1.0, 1.0]), front, fs, back, bs


def test_doppelklick_bleibt_auf_der_vorderen_flaeche(h: H):
    for comp in ("face", "edge"):
        p, front, fs, back, bs = _setup(h, comp)
        assert h.v._mesh_under(p)[0] is fs, "Cursor liegt über der vorderen Fläche"
        h.dclick(p)
        h.pump(0.05)
        owners = {r[1] for r in h.v.edge_selection} | {r[1] for r in h.v.seg_selection}
        assert back.id not in owners and bs.id not in h.v.selection, \
            f"{comp}: Doppelklick wählte Linien/Fläche dahinter"


def test_kante_dahinter_nicht_unter_dem_cursor(h: H):
    p, front, fs, back, bs = _setup(h, "edge")
    hit = h.v._edge_under(p, tolerance=3, visible=True)
    assert hit is None or hit[0][1] != back.id, "verdeckte Kante zählt nicht"
    h.v.set_xray(True)
    hit = h.v._edge_under(p, tolerance=3, visible=True)
    h.v.set_xray(False)
    assert hit is not None and hit[0][1] == back.id, "X-Ray: auch Verdecktes ist wählbar"

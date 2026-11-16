"""Punkt-Marken im Edit-Modus schrumpfen, wenn sie im Bild dicht stehen (Artist 12.11.: herausgezoomt verklumpten sie zu
schwarzen Flecken über dem Objekt)."""
import numpy as np

from tests.harness import H


def _gitter(h: H, n=14):
    sc = h.new_scene()
    st = sc.new_stroke()
    st.parent = None
    for i in range(n):
        sc.add_curve(np.linspace([0.0, 0.0, 0.1 * i], [1.0, 0.0, 0.1 * i], 4), None)
    h.v._changed()
    return st


def test_marken_voll_wenn_nah_und_kleiner_wenn_fern(h: H):
    st = _gitter(h)
    v = h.v
    pts = np.vstack([c.points for c in st.curves])
    h.edit_mode("point")
    v.selection = [st.id]
    v._changed()
    h.frame(pts, back=(0.0, 1.0, 0.05), margin=1.3)
    shared, free, rest = v._net_marks()
    alle = shared + free + rest
    assert len(alle) >= 20, "Voraussetzung des Tests: Punkte werden gezeigt"
    nah = v._mark_crowd(alle)
    assert nah == 1.0, f"nah herangezoomt haben die Marken ihre volle Größe ({nah:.2f})"
    h.frame(pts, back=(0.0, 1.0, 0.05), margin=60)
    fern = v._mark_crowd(alle)
    assert v.MARK_CROWD_MIN <= fern < 0.6, f"weit herausgezoomt schrumpfen die Marken deutlich ({fern:.2f})"
    h.frame(pts, back=(0.0, 1.0, 0.05), margin=8)
    mitte = v._mark_crowd(alle)
    assert fern <= mitte <= nah, f"dazwischen liegt die Größe dazwischen ({fern:.2f} ≤ {mitte:.2f} ≤ {nah:.2f})"
    h.grab()  # zeichnet mit geschrumpften Marken, ohne Fehler


def test_wenige_punkte_bleiben_immer_voll(h: H):
    sc = h.new_scene()
    st = sc.new_stroke()
    st.parent = None
    sc.add_curve(np.linspace([0.0, 0.0, 0.0], [1.0, 0.0, 0.0], 4), None)
    h.v._changed()
    h.edit_mode("point")
    h.v.selection = [st.id]
    h.v._changed()
    h.frame(st.curves[0].points, margin=80)
    shared, free, rest = h.v._net_marks()
    assert h.v._mark_crowd(shared + free + rest) == 1.0, "eine einzelne Linie: ihre zwei Punkte bleiben groß"

"""Gemischte Auswahl (ganze Linien + Teilkanten) bewegt jeden gewählten Punkt genau einmal (Hafentest 09.11.: gemeinsame
Punkte liefen doppelt so weit, die Linien dehnten sich dorthin)."""
import numpy as np

from sketch_machine import components, network
from tests.harness import H, line

D = np.array([0, 1.0, 0])


def _build(h, polys):
    sc = h.new_scene()
    sc.new_stroke()
    out = []
    for p in polys:
        sc.add_curve(np.asarray(p, float), None)
        out.append(sc.strokes[-1].curves[-1])
    network.sync(sc)
    return sc, out


def _ref(sc, c):
    return ("line", sc.owner_of(c).id, c.id)


def _move(h, sc, curves, edge=(), segs=(), steps=10):
    v = h.v
    if not v.select_mode:
        v.set_select_mode(True)
    v.ws.component = "edge"
    v.selection, v.point_selection = [], []
    v.edge_selection = [_ref(sc, c) for c in edge]
    v.seg_selection = [("seg",) + _ref(sc, c)[1:] + (a, b) for c, a, b in segs]
    v._changed()
    olds = [c.points.copy() for c in curves]
    target = v.transform_target
    for _ in range(steps):  # wie das Gizmo: viele kleine Schritte
        target.translate(D / steps)
        network.sync(sc)
    return [(c.points - o)[:, 1] for c, o in zip(curves, olds)]


def _corner_scene(h):
    corner = np.vstack([line([1, 0, 0], [1.5, 0, 0], 6), line([1.5, 0, 0], [1.5, 0, 0.5], 6)[1:]])
    return _build(h, [line([0, 0, 0], [1, 0, 0]), corner, line([1.5, 0, 0.5], [3, 0, 0.5])])


def test_ganze_linie_und_teilkanten_einmal_bewegt(h: H):
    sc, cs = _corner_scene(h)
    segs = [(cs[1], a, b) for a, b in components.segments(cs[1])]
    assert len(segs) >= 2, "Linie mit Ecke hat Teilkanten"
    d0, d1, _ = _move(h, sc, cs, edge=[cs[0]], segs=segs)
    for name, d in (("ganze Linie", d0), ("Linie aus Teilkanten", d1)):
        assert np.allclose(d, 1.0, atol=1e-6), f"{name}: Verschiebung {d.min():.2f}..{d.max():.2f} statt 1,00"


def test_linie_als_ganzes_und_als_teilkante_gewaehlt(h: H):
    sc, cs = _corner_scene(h)
    segs = [(cs[1], a, b) for a, b in components.segments(cs[1])]
    _d0, d1, _ = _move(h, sc, cs, edge=[cs[1]], segs=segs[:1])
    assert np.allclose(d1, 1.0, atol=1e-6), f"doppelt gewählte Linie: {d1.min():.2f}..{d1.max():.2f} statt 1,00"


def test_nur_ganze_linien_unveraendert(h: H):
    sc, cs = _build(h, [line([0, 0, 0], [1, 0, 0]), line([1, 0, 0], [2, 0, 0]), line([2, 0, 0], [3, 0, 0])])
    d0, d1, _ = _move(h, sc, cs, edge=cs[:2])
    assert np.allclose(d0, 1.0) and np.allclose(d1, 1.0)


def test_ganze_linien_bleiben_eingefaerbt_neben_teilkante(h: H):
    """Alpaka-Lenker 14.11.: Ringauswahl aus ganzen Linien plus einer Teilkante – das Gizmo bewegt alle, gezeichnet war
    aber nur die Teilkante in Auswahlfarbe (die Einfärbung las nur ganze Linien aus dem Transform-Ziel)."""
    from sketch_machine.vp.display_lists import SELECTED_STROKE_COLOR, _rgba
    sc, cs = _corner_scene(h)
    segs = [(cs[1], a, b) for a, b in components.segments(cs[1])]
    v = h.v
    if not v.select_mode:
        v.set_select_mode(True)
    v.ws.component = "edge"
    v.selection, v.point_selection = [], []
    v.edge_selection = [_ref(sc, cs[0]), _ref(sc, cs[2])]
    v.seg_selection = [("seg",) + _ref(sc, cs[1])[1:] + segs[0][1:]]
    v._changed()
    assert v.seg_selection and v.edge_selection, "gemischte Auswahl steht"
    sel = _rgba(SELECTED_STROKE_COLOR)[:3]
    entries = v._scene_stroke_list()
    for name, c in (("erste Linie", cs[0]), ("letzte Linie", cs[2])):
        hit = [e for e in entries if len(e[0]) == len(c.points) and np.allclose(e[0], c.points)]
        assert hit, f"{name}: nicht in der Strichliste"
        assert np.allclose(hit[0][2][:3], sel), f"{name}: gewählt, aber nicht in Auswahlfarbe gezeichnet"

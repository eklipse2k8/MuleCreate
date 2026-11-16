"""Handling: Doppelklick springt zum Objekt, Einrasten auf Flächen wie im Frei-Modus, eingefrorene Hilfsfläche."""
import os
import tempfile

import numpy as np

from tests.harness import H, Qt
from sketch_machine import components, network
from sketch_machine.scene import Scene


def _square(h: H, y=0.0, x0=0.0, size=2.0):
    sc = h.sc
    sc.new_stroke()
    pts = [np.array(p, float) for p in ([x0, y, 0], [x0 + size, y, 0], [x0 + size, y, size], [x0, y, size])]
    lines = []
    for k in range(4):
        sc.add_curve(np.linspace(pts[k], pts[(k + 1) % 4], 12), None)
        lines.append(sc.curves[-1])
    network.sync(sc)
    for k in range(4):
        network.join(sc, lines[k], 11, lines[(k + 1) % 4], 0)
    s = sc.create_fill([(c, False) for c in lines])
    h.v._changed()
    return s, lines


def _mesh(s):
    return np.asarray(s.fill_mesh()[0], float).copy()


def _lift(h: H, curve, k, delta):
    """Punkt k der Linie ziehen wie im Punktmodus (mit allen Linien, die ihn teilen)."""
    network.sync(h.sc)
    h.sc.checkpoint()
    components.ComponentGroup(h.sc, [(curve, k)], []).translate(np.asarray(delta, float))
    h.v._changed()
    h.sc.sync_lofts()


def test_hilfsflaeche_folgt_keiner_linie(h: H):
    s, lines = _square(h)
    before = _mesh(s)
    h.v.set_surface_aid(s.id, True)
    assert s.frozen is not None, "Hilfsfläche eingefroren"
    _lift(h, lines[2], 0, [0, 0.7, 0])
    assert np.allclose(_mesh(s), before), "weggezogene Randlinie verformt die Hilfsfläche nicht"
    h.camera([1, 0, 1], 5, [0.05, 1, 0.1])
    h.draw_mode()
    h.v._activate(s)
    h.stroke_world([np.array([0.3, 0, 0.5]), np.array([1.0, 0, 1.4]), np.array([1.7, 0, 0.6])])
    h.sc.sync_lofts()
    assert np.allclose(_mesh(s), before), "darauf gezeichnete Linie verformt die Hilfsfläche nicht"
    h.v.set_surface_aid(s.id, False)
    assert not s.aid and s.frozen is not None, "Linie liegt nicht mehr an ihr: Fläche bleibt fest"
    _lift(h, lines[0], 0, [0, -0.5, 0])
    assert np.allclose(_mesh(s), before), "feste Fläche springt nicht zu ihren alten Linien"


def test_hilfsflaeche_zurueck_haengt_wieder_an_ihren_linien(h: H):
    s, lines = _square(h)
    h.v.set_surface_aid(s.id, True)
    h.v.set_surface_aid(s.id, False)
    assert s.frozen is None, "Linien an Ort und Stelle: wieder verbunden"
    before = _mesh(s)
    _lift(h, lines[2], 0, [0, 0.5, 0])
    assert _mesh(s)[:, 1].max() > before[:, 1].max() + 0.3, "Fläche folgt ihrer Ecke wieder"


def test_hilfsflaeche_gizmo_bewegt_nur_sie(h: H):
    s, lines = _square(h)
    h.v.set_surface_aid(s.id, True)
    before, line_before = _mesh(s), lines[0].points.copy()
    h.edit_mode("face")
    h.v.selection, h.v.edge_selection = [s.id], []
    target = h.v.transform_target
    h.sc.checkpoint()
    target.translate(np.array([0, 0.5, 0]))
    h.v._changed()
    h.sc.sync_lofts()
    assert np.allclose(_mesh(s), before + [0, 0.5, 0]), "Hilfsfläche verschoben"
    assert np.allclose(lines[0].points, line_before), "ihre Linien bleiben stehen"
    path = os.path.join(tempfile.mkdtemp(), "aid.sketch.json")
    h.sc.save(path)
    loaded = Scene.load(path)[0].surfaces[0]
    assert loaded.aid and loaded.frozen is not None, "eingefroren gespeichert"
    assert np.allclose(np.asarray(loaded.fill_mesh()[0]), before + [0, 0.5, 0], atol=1e-4), "Form kommt mit"
    h.v.set_surface_aid(s.id, False)
    assert s.frozen is not None, "bewegt: bleibt beim Ausschalten fest (springt nicht zurück)"


def test_einrasten_auf_flaeche_an_ecke_einer_linie(h: H):
    """Zeichnen auf einer Fläche: Ecken mitten in Linien sind Fangpunkte (wie im Frei-Modus); Punkte, die nicht an der
    Fläche hängen, nicht."""
    s, lines = _square(h)
    h.sc.add_curve(np.vstack([np.linspace([0.5, 0, 0.5], [1.0, 0, 1.0], 8),
                              np.linspace([1.0, 0, 1.0], [1.5, 0, 0.5], 8)[1:]]), s.id)
    bent = h.sc.curves[-1]
    corner = bent.points[7].copy()
    assert 7 in components.knots(bent), "Knick ist ein Punkt"
    h.sc.add_curve(np.linspace([0.2, 1.5, 0.2], [0.6, 1.5, 0.6], 6), None)  # in der Luft über der Fläche
    h.camera([1, 0, 1], 5, [0.05, 1, 0.1])
    h.draw_mode()
    h.v._activate(s)
    h.v._changed()
    pts = h.v._surface_snap_points()
    assert any(np.allclose(p, corner) for p in pts), "Ecke an der Fläche ist Fangpunkt"
    assert not any(abs(p[1] - 1.5) < 1e-6 for p in pts), "Punkte über der Fläche nicht"
    start = h.scrf(corner)
    start.setX(start.x() + 5)
    end = h.scrf(np.array([1.0, 0, 0.2]))
    n = len(h.curves())
    h.stroke([start, end])
    assert len(h.curves()) > n
    new = h.curves()[-1]
    first = new.points[0] if np.linalg.norm(new.points[0] - corner) < np.linalg.norm(new.points[-1] - corner) \
        else new.points[-1]
    assert np.allclose(first, corner, atol=1e-6), f"beginnt genau an der Ecke: {first} statt {corner}"
    network.sync(h.sc)
    k = 0 if np.allclose(new.points[0], corner) else len(new.points) - 1
    assert network.pid_of(new, k) == network.pid_of(bent, 7), "derselbe Punkt (verbunden, kein zweiter)"


def test_einrasten_am_strichende_auf_flaeche(h: H):
    s, lines = _square(h)
    h.sc.add_curve(np.vstack([np.linspace([0.5, 0, 0.5], [1.0, 0, 1.0], 8),
                              np.linspace([1.0, 0, 1.0], [1.5, 0, 0.5], 8)[1:]]), s.id)
    bent = h.sc.curves[-1]
    corner = bent.points[7].copy()
    h.camera([1, 0, 1], 5, [0.05, 1, 0.1])
    h.draw_mode()
    h.v._activate(s)
    h.v._changed()
    end = h.scrf(corner)
    end.setY(end.y() + 6)
    h.stroke([h.scrf(np.array([1.0, 0, 1.8])), end])
    new = h.curves()[-1]
    assert np.allclose(new.points[-1], corner, atol=1e-6), "Ende genau auf der Ecke"
    network.sync(h.sc)
    assert network.pid_of(new, len(new.points) - 1) == network.pid_of(bent, 7), "verbunden"


def test_doppelklick_springt_zum_anderen_objekt(h: H):
    sc = h.sc
    a = sc.new_stroke()
    sc.add_curve(np.linspace([0, 0, 0], [2, 0, 0], 12), None)
    b = sc.new_stroke()
    sc.add_curve(np.linspace([0, 0, 1], [2, 0, 1], 12), None)
    line_b = sc.curves[-1]
    sc.active_stroke = a
    h.camera([1, 0, 0.5], 5, [0.05, 1, 0.1])
    h.edit_mode("point")
    assert h.v._active_strokes() == frozenset({a.id})
    h.dclick(h.scr(line_b.points[5]))
    assert sc.active_stroke is b, "Doppelklick: das andere Objekt wird bearbeitet"
    assert b.id in h.v.selection, "auch im Outliner gewählt"
    assert b.id in h.v._active_strokes(), "seine Punkte erscheinen"


# --- Verschweißen gewählter Punkte (Cleanup: Aufräumen / Verschweißen) ---
def _weld_lines(h: H, *specs):
    out = []
    for pts in specs:
        h.sc.new_stroke()
        h.sc.add_curve(np.asarray(pts, float), None)
        out.append(h.sc.curves[-1])
    network.sync(h.sc)
    return out


def _weld_selected(h: H, chosen, what="all"):
    network.sync(h.sc)
    h.edit_mode("point")
    h.v.selection, h.v.edge_selection, h.v.seg_selection = [], [], []
    h.v.point_selection = [("pt", h.sc.owner_of(c).id, c.id, k % len(c.points)) for c, k in chosen]
    h.v.ws.cleanup_global = False
    h.v.run_cleanup(what)
    network.sync(h.sc)


def _points_near(h: H, center, r=0.05):
    knots = [(c, k) for c in h.curves() for k in components.knots(c) if np.linalg.norm(c.points[k] - center) < r]
    return {network.pid_of(c, k) for c, k in knots}, knots


def test_verschweissen_verbundene_punkte_und_ende(h: H):
    """Zwei schon verbundene Punkte (je zwei Linien) und ein loses Ende nah beieinander: ein Punkt, alle Linien daran
    (vorher wanderte je Punkt nur eine Linie – drei getrennte Punkte)."""
    a, b = _weld_lines(h, np.linspace([0, 0, 0], [-1, 0, 0], 8), np.linspace([0, 0, 0], [0, -1, 0], 8))
    network.join(h.sc, a, 0, b, 0)
    c, d = _weld_lines(h, np.linspace([0.012, 0, 0], [1, 0, 0.2], 8), np.linspace([0.012, 0, 0], [0, 1, 0.3], 8))
    network.join(h.sc, c, 0, d, 0)
    e, = _weld_lines(h, np.linspace([0.006, 0.01, 0], [0.5, 1, 1], 8))
    _weld_selected(h, [(a, 0), (c, 0), (e, 0)])
    pids, knots = _points_near(h, np.array([0.006, 0, 0]))
    assert len(pids) == 1 and len(knots) == 5, f"{len(pids)} Punkte, {len(knots)} Linien daran"
    assert all(np.allclose(cc.points[k], knots[0][0].points[knots[0][1]]) for cc, k in knots), "alle an einer Stelle"


def test_verschweissen_ecken_mitten_in_linien(h: H):
    corner = lambda x: np.vstack([np.linspace([x - 1, -1, 0], [x, 0, 0], 8), np.linspace([x, 0, 0], [x - 1, 1, 0], 8)[1:]])
    a, b = _weld_lines(h, corner(0.0), corner(0.008))
    end, = _weld_lines(h, np.linspace([0.004, -0.008, 0.004], [0.3, -1, 0], 6))
    _weld_selected(h, [(a, 7), (b, 7), (end, 0)])
    pids, knots = _points_near(h, np.array([0.004, 0, 0]))
    assert len(pids) == 1 and len(knots) == 3, f"{len(pids)} Punkte, {len(knots)} Linien daran"


def test_verschweissen_laesst_ungewaehlte_enden_in_ruhe(h: H):
    a, b, c = _weld_lines(h, np.linspace([-1, 0, 0], [0, 0, 0], 8), np.linspace([0.008, 0, 0], [1, 0, 0.3], 8),
                          np.linspace([1.005, 0, 0.3], [2, 0, 0], 8))
    _weld_selected(h, [(a, -1), (b, 0)])
    assert network.pid_of(a, 7) == network.pid_of(b, 0), "gewählte Enden verbunden"
    assert network.pid_of(b, 7) != network.pid_of(c, 0), "anderes Ende von b (nicht gewählt) bleibt lose"
    assert np.allclose(c.points[0], [1.005, 0, 0.3])

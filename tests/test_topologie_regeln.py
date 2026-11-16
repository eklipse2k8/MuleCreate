"""Topologie-Regel: zwischen zwei Punkten höchstens eine Linie gleicher Form (topology.py). L-Wand des Artists aus dem
Hafentest 09.11.: je Schenkel einzeln extrudiert bzw. geloftet -> an der Ecke eine doppelte senkrechte Linie."""
import numpy as np

from sketch_machine import network
from tests.harness import H


def _line(sc, a, b, n=20):
    sc.add_curve(np.linspace(a, b, n), None)
    return sc.curves[-1]


def _extrude(h, lines, length=1.0, axis="z"):
    v, sc = h.v, h.sc
    if not v.select_mode:
        v.set_select_mode(True)
    v.ws.component = "edge"
    v.selection, v.seg_selection, v.point_selection = [], [], []
    v.edge_selection = [("line", sc.owner_of(c).id, c.id) for c in lines]
    v.start_extrude()
    assert v._mode == "extrude"
    v._extrude_set_axis(axis)
    v._extrude["length"] = length
    v._finish_extrude()
    v._extrude, v._mode = None, None


def _vertical_at(sc, xy):
    network.sync(sc)
    return [c for c in network.net_curves(sc)
            if np.allclose(c.points[0][:2], xy, atol=1e-3) and np.allclose(c.points[-1][:2], xy, atol=1e-3)
            and abs(c.points[0][2] - c.points[-1][2]) > 0.5]


def _corner_scene(h):
    h.new_scene()
    sc = h.sc
    sc.new_stroke()
    a = _line(sc, [0, 0, 0], [1, 0, 0])
    b = _line(sc, [1, 0, 0], [1, 1, 0])
    network.sync(sc)
    h.v._changed()
    assert network.pid_of(a, len(a.points) - 1) == network.pid_of(b, 0), "Ecke unten verbunden"
    return sc, a, b


def test_l_wand_je_schenkel_extrudiert_keine_doppellinie(h: H):
    sc, a, b = _corner_scene(h)
    _extrude(h, [a])
    _extrude(h, [sc.curve_by_id(b.id) or b])
    h.v._changed()
    vert = _vertical_at(sc, [1, 0])
    assert len(vert) == 1, f"an der Ecke {len(vert)} senkrechte Linien statt einer"
    tops = [c for c in network.net_curves(sc) if abs(c.points[0][2] - 1) < 1e-6 and abs(c.points[-1][2] - 1) < 1e-6]
    corner_pids = {network.pid_of(c, k) for c in tops for k in (0, len(c.points) - 1)
                   if np.allclose(c.points[k], [1, 0, 1], atol=1e-6)}
    assert len(corner_pids) == 1, f"obere Ecke nicht verbunden: {corner_pids}"


def test_flaechen_folgen_nach_dem_zusammenlegen(h: H):
    """Die zweite Wand hing an der entfernten Doppellinie: sie folgt der behaltenen, auch beim Bewegen."""
    sc, a, b = _corner_scene(h)
    _extrude(h, [a])
    _extrude(h, [sc.curve_by_id(b.id) or b])
    h.v._changed()
    walls = [s for s in sc.surfaces if not s.aid]
    assert len(walls) >= 2, f"{len(walls)} Wände"
    vert = _vertical_at(sc, [1, 0])[0]
    before = [s.fill_mesh()[0].copy() for s in walls]
    pts = vert.points.copy()
    pts[len(pts) // 2] += [0.2, -0.2, 0]  # Ecklinie ausbeulen
    vert.points = pts
    h.v._changed()
    moved = [float(np.abs(s.fill_mesh()[0] - b0).max()) if s.fill_mesh()[0].shape == b0.shape else 1.0
             for s, b0 in zip(walls, before)]
    assert all(m > 1e-3 for m in moved), f"nicht jede Wand folgt der gemeinsamen Ecklinie: {moved}"


def test_vorhandene_fremde_linien_bleiben(h: H):
    """Zusammengelegt werden nur neu entstandene Linien – eine vorhandene Doppellinie bleibt unangetastet."""
    sc, a, b = _corner_scene(h)
    dup = _line(sc, [1, 1, 0], [1, 1, 1])
    dup2 = _line(sc, [1, 1, 0], [1, 1, 1])
    n = len(sc.curves)
    _extrude(h, [a])
    assert dup in sc.curves and dup2 in sc.curves and len(sc.curves) > n


def test_doppellinien_entfernen_haengt_flaeche_um(h: H):
    """„Doppelte Linien entfernen“: andere Punktzahl zählt auch als doppelt; entfernt die Randlinie einer Fläche, folgt
    die Fläche der behaltenen Linie (vorher löste sie sich ab)."""
    from sketch_machine import cleanup
    h.new_scene()
    sc = h.sc
    dup_owner = sc.new_stroke()
    dup = _line(sc, [0, 0, 0], [1, 0, 0], 13)  # liegt auf der unteren Randlinie, steht aber vorn in der Liste
    sc.new_stroke()
    edge = [_line(sc, *ab) for ab in (([0, 0, 0], [1, 0, 0]), ([1, 0, 0], [1, 0, 1]), ([1, 0, 1], [0, 0, 1]),
                                      ([0, 0, 1], [0, 0, 0]))]
    network.sync(sc)
    v = h.v
    v.edge_selection = [("line", sc.owner_of(c).id, c.id) for c in edge]
    v.do_patch()
    patch = sc.surfaces[-1]
    h.v._changed()
    n = cleanup.remove_duplicates(sc, list(sc.curves), 1.0)
    assert n == 1 and dup in dup_owner.curves and edge[0] not in sc.curves
    before = patch.fill_mesh()[0].copy()
    pts = dup.points.copy()
    pts[len(pts) // 2] += [0, 0.3, 0]
    dup.points = pts
    h.v._changed()
    after = sc.object_by_id(patch.id).fill_mesh()[0]
    assert after.shape != before.shape or float(np.abs(after - before).max()) > 1e-3, "Fläche folgt der behaltenen Linie"

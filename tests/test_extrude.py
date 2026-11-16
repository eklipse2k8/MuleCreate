"""Extrudieren (X): Seitenflächen wie ein Loft, an harten Punkten geteilt; Flächen extrudieren im Flächenmodus."""
import numpy as np

from tests.harness import H, Qt, circle, line
from sketch_machine import network
from sketch_machine.scene import LoftSurface, PatchSurface, SurfaceObject


def _rect(h: H, size=2.0):
    """Rechteck aus vier Linien (verbunden) auf dem Boden -> Linien."""
    sc = h.new_scene()
    sc.new_stroke()
    c = [[0, 0, 0], [size, 0, 0], [size, 0, size], [0, 0, size]]
    for a, b in zip(c, c[1:] + c[:1]):
        sc.add_curve(line(a, b, 20), sc.planes[0].id)
    h.v._changed()
    network.sync(sc)
    return list(sc.curves)


def _extrude(h: H, length=1.0, axis="y"):
    v = h.v
    v.start_extrude()
    assert v._mode == "extrude", "Extrusion läuft"
    v._extrude_set_axis(axis)
    v._extrude["length"] = length
    v._finish_extrude()
    v._extrude = None
    v._mode = None
    v._changed()


def _select_lines(h: H, curves):
    h.edit_mode("edge")
    h.v.edge_selection = [("line", h.sc.owner_of(c).id, c.id) for c in curves]
    h.v._changed()


def _flat(surface):
    v = surface.fill_mesh()[0]
    p = v - v.mean(axis=0)
    return np.linalg.svd(p, full_matrices=False)[1][2] < 1e-6 * max(1.0, np.ptp(v, axis=0).max())


def test_rechteck_gibt_vier_ebene_waende(h: H):
    curves = _rect(h)
    h.frame(np.vstack([c.points for c in curves]))
    _select_lines(h, curves)
    _extrude(h)
    walls = list(h.sc.surfaces)
    assert len(walls) == 4, f"{len(walls)} Flächen statt 4 (je Seite eine)"
    assert all(isinstance(s, PatchSurface) for s in walls), [type(s).__name__ for s in walls]
    assert all(_flat(s) for s in walls), "Wände sind eben (kantiger Quader)"
    h.save_image("extrude_rechteck.png")


def test_kreis_gibt_eine_roehre(h: H):
    sc = h.new_scene()
    sc.new_stroke()
    sc.add_curve(circle([0, 0, 0], 1.0, 65), sc.planes[0].id)
    h.v._changed()
    _select_lines(h, sc.curves)
    _extrude(h)
    assert len(sc.surfaces) == 1 and isinstance(sc.surfaces[0], LoftSurface), [type(s).__name__ for s in sc.surfaces]


def test_l_profil_zwei_flaechen_und_weich_gestellte_ecke_eine(h: H):
    for hard, expect in ((None, 2), (0.0, 1)):
        sc = h.new_scene()
        sc.new_stroke()
        sc.add_curve(np.vstack([line([0, 0, 0], [2, 0, 0], 20), line([2, 0, 0], [2, 0, 2], 20)[1:]]), sc.planes[0].id)
        c = sc.curves[-1]
        h.v._changed()
        network.sync(sc)
        if hard is not None:  # die Ecke weich stellen (K formt sie rund): eine durchgehende Fläche
            k = [j for j in c.pids if 0 < j < len(c.points) - 1][0]
            h.edit_mode("point")
            h.v.point_selection = [("pt", sc.owner_of(c).id, c.id, k)]
            h.v.set_hardness(hard)
        _select_lines(h, [c])
        _extrude(h)
        assert len(sc.surfaces) == expect, f"Härte {hard}: {len(sc.surfaces)} Flächen statt {expect}"


def test_ohne_flaechen_nur_linien(h: H):
    curves = _rect(h)
    _select_lines(h, curves)
    h.v.ws.extrude_surface = False
    try:
        _extrude(h)
    finally:
        h.v.ws.extrude_surface = True
    assert not h.sc.surfaces
    assert len(h.curves()) == 4 + 4 + 4, len(h.curves())  # Original, Kopie, vier Verbindungslinien


def test_flaeche_extrudieren_wandert_nach_oben(h: H):
    curves = _rect(h)
    _select_lines(h, curves)
    h.v.do_surface()
    face = h.sc.surfaces[0]
    assert isinstance(face, (PatchSurface, SurfaceObject))
    face.material = "holz"
    bottom = [c.points.copy() for c in curves]
    h.edit_mode("face")
    h.v.selection = [face.id]
    h.v._changed()
    _extrude(h, 1.5)
    face = next(s for s in h.sc.surfaces if s.id == face.id)
    v = face.fill_mesh()[0]
    assert np.allclose(v[:, 1], 1.5, atol=1e-6), f"Fläche liegt oben (y {v[:, 1].min():.3f} .. {v[:, 1].max():.3f})"
    walls = [s for s in h.sc.surfaces if s is not face]
    assert len(walls) == 4, f"{len(walls)} Seitenwände"
    assert all(s.material == "holz" for s in walls), "Wände übernehmen das Material"
    # der Boden-Ring bleibt (die Original-Linien liegen noch unten)
    low = [c for c in h.curves() if np.allclose(c.points[:, 1], 0)]
    assert sum(len(c.points) for c in low) >= sum(len(b) for b in bottom) - 4, "Boden-Ring bleibt"
    # die Fläche folgt jetzt der oberen Kopie: einen oberen Eckpunkt anheben verformt sie
    top = [c for c in h.curves() if np.allclose(c.points[:, 1], 1.5)]
    assert top, "obere Kopie"
    h.save_image("extrude_flaeche.png")


def test_innere_linie_wandert_mit_der_flaeche(h: H):
    curves = _rect(h)
    _select_lines(h, curves)
    h.v.do_surface()
    face = h.sc.surfaces[0]
    h.draw_mode()
    h.frame([[0, 0, 0], [2, 0, 2]], back=(0.01, 1, 0.01))
    h.sc.activate_mesh(face)
    h.v._changed()
    h.stroke_world([[-0.3, 0, 1.0], [2.3, 0, 1.0]])  # quer über die Fläche, über den Rand hinaus
    inner = [c for c in h.curves() if c.plane_id == face.id and not c.paint]
    assert inner, "Linie auf der Fläche"
    h.edit_mode("face")
    h.v.selection = [face.id]
    h.v._changed()
    _extrude(h, 1.0)
    for c in inner:
        c2 = h.sc.curve_by_id(c.id)
        assert c2 is not None and np.allclose(c2.points[:, 1], 1.0, atol=1e-6), "innere Linie ist mitgewandert"
    network.sync(h.sc)
    refs = network.refs_by_pid(h.sc)
    c2 = h.sc.curve_by_id(inner[0].id)
    for k in (0, len(c2.points) - 1):
        assert len(refs[network.pid_of(c2, k)]) > 1, "Enden bleiben mit dem (oberen) Rand verbunden"


def test_punkt_loeschen_flaeche_folgt_der_bruecke(h: H):
    """Strg+Entf auf einem angehobenen Punkt einer Linie quer über die Fläche: die Nachbarpunkte werden gerade
    verbunden, und die Fläche legt sich an diese Gerade (als wäre die Linie vorher gerade gewesen)."""
    from sketch_machine import components, netedit
    curves = _rect(h)
    _select_lines(h, curves)
    h.v.do_surface()
    face = h.sc.surfaces[0]
    h.draw_mode()
    h.frame([[0, 0, 0], [2, 0, 2]], back=(0.01, 1, 0.01))
    h.sc.activate_mesh(face)
    h.v._changed()
    h.stroke_world([[-0.3, 0, 1.0], [2.3, 0, 1.0]])
    line_ = next(c for c in h.curves() if c.plane_id == face.id and not c.paint)
    for x in (0.5, 1.0, 1.5):  # drei Punkte auf der Linie
        h.sc.insert_knot_at(line_.points[np.argmin(np.abs(line_.points[:, 0] - x))])
        line_ = h.sc.curve_by_id(line_.id) or line_
    h.v._changed()
    network.sync(h.sc)
    ks = [k for k in components.knots(line_) if 0 < k < len(line_.points) - 1]
    mid = min(ks, key=lambda k: abs(line_.points[k, 0] - 1.0))
    components.ComponentGroup(h.sc, [(line_, mid)], []).translate(np.array([0, 0.8, 0]))
    h.v._changed()
    g = face.grid()
    assert g[..., 1].max() > 0.6, "Fläche folgt dem angehobenen Punkt"
    netedit.delete_points(h.sc, [network.pid_of(line_, mid)])
    h.v._changed()
    face = next(s for s in h.sc.surfaces if s.id == face.id)
    bridge = [c for c in h.curves() if len(c.points) == netedit.BRIDGE_POINTS]
    assert bridge and bridge[0].id in face.attached, "Brücke formt die Fläche"
    v = face.fill_mesh()[0]
    near = v[np.linalg.norm(v[:, [0, 2]] - [1.0, 1.0], axis=1) < 0.08]
    assert len(near) and np.abs(near[:, 1]).max() < 0.08, f"Fläche liegt an der Geraden (y {near[:, 1].max():.3f})"


def test_weiche_verbindungslinie_ist_netzlinie(h: H):
    """Offener Bogen extrudiert: die weiche Verbindungslinie in der Mitte (Original -> Kopie, zwei Punkte) läuft von
    Rand zu Rand der Wand und ist ihre Netzlinie – sie formt die Fläche genau (vorher galt sie als Randduplikat)."""
    from tests.test_loft import _dist_to_mesh, _size
    sc = h.new_scene()
    sc.new_stroke()
    t = np.linspace(0, np.pi, 49)
    sc.add_curve(np.stack([2 * np.cos(t), np.zeros_like(t), 2 * np.sin(t)], 1), sc.planes[0].id)
    h.v._changed()
    network.sync(sc)
    _select_lines(h, sc.curves)
    _extrude(h)
    sc.sync_lofts()
    wall = sc.surfaces[0]
    assert isinstance(wall, PatchSurface) and wall.net and len(wall.net["v"]) == 1, wall.net
    mid = next(c for c in h.curves() if len(c.points) == 2 and abs(c.points[0, 0]) < 0.1)
    from sketch_machine import components
    components.ComponentGroup(sc, [(mid, 1)], []).translate(np.array([0, 0, 0.6]))  # oberer Punkt nach außen (Rand geht mit)
    sc.sync_lofts()
    verts, tris = wall.fill_mesh()[:2]
    pts = mid.points[0] + np.linspace(0, 1, 9)[:, None] * (mid.points[1] - mid.points[0])
    assert _dist_to_mesh(pts, verts, tris).max() < 0.003 * _size(verts), "Wand geht durch die Verbindungslinie"


def _knick_linie(h: H, deg):
    """Offene Linie aus zwei geraden Stücken mit einem Knoten in der Mitte, der um deg knickt."""
    sc = h.new_scene()
    sc.new_stroke()
    a = np.linspace([-2.0, 0, 0], [0.0, 0, 0], 21)
    t = np.radians(deg)
    b = np.linspace([0.0, 0, 0], [2 * np.cos(t), 0, 2 * np.sin(t)], 21)[1:]
    sc.add_curve(np.vstack([a, b]), sc.planes[0].id)
    c = sc.curves[-1]
    c.knots = (len(c.points), (20,))  # Punkt in der Mitte (wie eingefügt)
    h.v._changed()
    network.sync(sc)
    return c


def _senkrechte(sc):
    out = 0
    for c in sc.curves:
        d = c.points[-1] - c.points[0]
        if np.linalg.norm(d) > 1e-6 and abs(d[1]) > 0.99 * np.linalg.norm(d):
            out += 1
    return out


def test_knoten_regel_5_und_15_grad(h: H):
    """Knoten unter 5°: keine Verbindungslinie; ab 5°: Linie, Fläche bleibt eine; ab 15°: Linie und geteilt."""
    for deg, rails, faces in ((3.0, 2, 1), (10.0, 3, 1), (20.0, 3, 2)):
        c = _knick_linie(h, deg)
        h.frame(c.points)
        _select_lines(h, [c])
        _extrude(h)
        assert _senkrechte(h.sc) == rails, f"{deg}°: {_senkrechte(h.sc)} Verbindungslinien statt {rails}"
        assert len(h.sc.surfaces) == faces, f"{deg}°: {len(h.sc.surfaces)} Flächen statt {faces}"

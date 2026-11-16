"""Topologie: was das Kurvennetz (F3–F5) lösen soll. Bekannte Probleme sind als erwartete Fehler markiert –
sobald einer davon BEHOBEN meldet, die Markierung entfernen."""
import numpy as np

from tests.harness import H, Qt, expected_failure, line
from sketch_machine import components, edges, network


def _loft3(h: H, rails=True):
    sc = h.sc
    sc.new_stroke()
    t = np.linspace(0, 1, 12)
    secs = []
    for z, lift in ((0.0, 0.0), (1.0, 0.8), (2.0, 0.0)):
        sc.add_curve(np.stack([t * 2, 0.4 * np.sin(t * np.pi) + lift, np.full_like(t, z)], axis=1), None)
        secs.append(sc.curves[-1])
    lo = sc.create_loft([("lines", [c.id]) for c in secs], [c.points for c in secs])
    if rails:
        sc.add_loft_rails(lo, np.array([0, 0, 1.0]))
    sc.sync_lofts()
    h.v._changed()
    return lo, secs


def _delete_lines(h: H, curves):
    h.v.edge_selection = [("line", h.sc.owner_of(c).id, c.id) for c in curves]
    h.v.selection = []
    h.v.select_mode = True
    h.v.ws.component = "edge"
    h.v.delete_selection()
    h.sc.sync_lofts()


def test_loft_verliert_geloeschtes_profil(h: H):
    lo, secs = _loft3(h)
    _delete_lines(h, [secs[1]])
    assert len(lo.curves) == 2, f"Loft hat noch {len(lo.curves)} Querschnitte"


def test_seitenlinien_bleiben_nach_profil_loeschen(h: H):
    """Topologie-Konzept: Seitenlinien sind echte Linien – löscht man einen Querschnitt, bleiben sie, wie sie sind, und
    der Loft geht weiter durch sie hindurch (er formt sich aus Querschnitten und Seitenlinien)."""
    lo, secs = _loft3(h)
    rail = h.sc.curve_by_id(lo.rails[0][0])
    before = rail.points.copy()
    _delete_lines(h, [secs[1]])
    h.v._changed()
    assert np.array_equal(h.sc.curve_by_id(rail.id).points, before), "Seitenlinie bleibt stehen"
    verts = lo.fill_mesh()[0]
    mid = before[np.argmin(np.abs(before[:, 2] - 1.0))]
    assert np.linalg.norm(verts - mid, axis=1).min() < 0.05, "Loft geht durch die Seitenlinie"


def test_seitenlinien_folgen_dem_profil_am_gemeinsamen_punkt(h: H):
    """Seitenlinien hängen an den Querschnitten an gemeinsamen Punkten: zieht man den Endpunkt eines Querschnitts, geht
    die Seitenlinie dort mit (der Loft bewegt sie nicht – das Netz tut es)."""
    from sketch_machine import network
    lo, secs = _loft3(h)
    rail = h.sc.curve_by_id(lo.rails[0][0])
    end = rail.points[-1].copy()
    refs = network.refs_by_pid(h.sc)
    pid = network.pid_of(rail, len(rail.points) - 1)
    assert any(c is secs[2] for c, _ in refs[pid]), "Seitenlinie ist mit dem Querschnitt verbunden"
    group = components.ComponentGroup(h.sc, [refs[pid][0]], [])
    group.translate(np.array([0.0, 0.5, 0.0]))
    h.v._changed()
    rail = h.sc.curve_by_id(rail.id)
    assert np.linalg.norm(rail.points[-1] - (end + [0, 0.5, 0])) < 1e-6, "Seitenlinie folgt am gemeinsamen Punkt"


def test_aufgeloeste_ecke_bleibt_aufgeloest(h: H):
    sc = h.sc
    sc.new_stroke()
    sc.add_curve(np.vstack([line([0, 0, 0], [1, 0, 0], 20), line([1, 0, 0], [1, 0, 1], 20)[1:]]), None)
    c = sc.curves[-1]
    corner = components.knots(c)[1]
    assert components.dissolve(c, corner)
    assert components.knots(c) == [0, len(c.points) - 1]
    arc = np.concatenate([[0], np.cumsum(np.linalg.norm(np.diff(c.points, axis=0), axis=1))])
    t = np.linspace(0, arc[-1], 60)  # Punktzahl ändert sich (z. B. Glätten, Neuabtasten)
    c.points = np.stack([np.interp(t, arc, c.points[:, i]) for i in range(3)], axis=1)
    c.widths = np.full(60, c.widths.mean())
    assert components.knots(c) == [0, 59], f"Knoten {components.knots(c)}"


def _corner_lines(h: H):
    sc = h.sc
    sc.new_stroke()
    sc.add_curve(line([0, 0, 0], [1, 0, 0], 12), sc.planes[0].id)
    sc.add_curve(line([1, 0, 0], [1, 0, 1], 12), sc.planes[0].id)
    h.v._changed()
    h.camera([0.5, 0, 0.5], 4, [0, 1, 0.01])
    return sc.curves[-2:]


def test_punkt_aufloesen_verbindet_zwei_linien(h: H):
    a, b = _corner_lines(h)
    h.edit_mode("point")
    h.click(h.scr([1, 0, 0]))
    assert h.v.point_selection, "Eckpunkt gewählt"
    h.key(Qt.Key_Delete)  # Entf: auflösen (Strg+Entf löscht den Punkt)
    assert len(h.curves()) == 1, f"{len(h.curves())} Linien – erwartet eine durchgehende"
    pts = h.curves()[0].points
    assert np.linalg.norm(pts - [1, 0, 0], axis=1).min() < 1e-6, "Form bleibt (Ecke liegt noch drauf)"


def test_punkt_entfernen_interpoliert_neu(h: H):
    sc = h.sc
    sc.new_stroke()
    sc.add_curve(np.vstack([line([0, 0, 0], [1, 0, 1], 20), line([1, 0, 1], [2, 0, 0], 20)[1:]]), sc.planes[0].id)
    c = sc.curves[-1]
    h.v._changed()
    h.camera([1, 0, 0.5], 4, [0, 1, 0.01])
    h.edit_mode("point")
    h.click(h.scr([1, 0, 1]))
    assert hasattr(h.v, "remove_points"), "Befehl Punkt entfernen fehlt"
    h.v.remove_points()
    c = h.curves()[0]
    assert np.linalg.norm(c.points - [1, 0, 1], axis=1).min() > 0.2, "Spitze ist weg, die Linie läuft neu durch"


def test_gemeinsamer_punkt_zieht_beide_linien(h: H):
    a, b = _corner_lines(h)
    h.edit_mode("point")
    h.click(h.scr([1, 0, 0]))
    group = components.ComponentGroup(h.sc, [(c, r[3]) for r, c in h.v._valid_points()], [])
    group.translate(np.array([0.0, 0.0, -0.3]))
    assert np.allclose(a.points[-1], b.points[0]), "beide Linienenden bleiben zusammen"


def test_doppelklick_kurvenflaeche_findet_randlinien(h: H):
    sc = h.sc
    sc.new_stroke()
    t = np.linspace(0, 1, 12)
    sides = [np.stack([t * 2, 0.3 * np.sin(t * np.pi), t * 0], 1), np.stack([np.full_like(t, 2), 0.3 * np.sin(t * np.pi), t * 2], 1),
             np.stack([2 - t * 2, 0.3 * np.sin(t * np.pi), np.full_like(t, 2)], 1), np.stack([t * 0, 0.3 * np.sin(t * np.pi), 2 - t * 2], 1)]
    lines = []
    for s in sides:
        sc.add_curve(s, None)
        lines.append(sc.curves[-1])
    ps = sc.create_patch(lines)
    sc.sync_lofts()
    h.v._changed()
    h.camera([1, 0.2, 1], 5, [0.2, 0.9, 0.4])
    h.edit_mode("face")
    h.v.select_loop(h.scrf(ps.fill_mesh()[0].mean(axis=0)), "replace")
    found = {r[2] for r in h.v.edge_selection}
    assert h.v.selection == [ps.id] and found == {c.id for c in lines}, f"{len(found)} von 4 Randlinien"


def test_keine_doppelten_seitenlinien(h: H):
    lo, secs = _loft3(h)
    h.sc.add_loft_rails(lo, np.array([0, 0, 1.0]))
    h.sc.sync_lofts()
    pts = [c.points for c in h.curves()]
    dup = sum(1 for i in range(len(pts)) for j in range(i) if pts[i].shape == pts[j].shape and np.allclose(pts[i], pts[j]))
    assert dup == 0, f"{dup} doppelte Linien"


def test_kanten_einer_linie_an_ecken(h: H):
    sc = h.sc
    sc.new_stroke()
    sc.add_curve(np.vstack([line([0, 0, 0], [1, 0, 0], 20), line([1, 0, 0], [1, 0, 1], 20)[1:]]), None)
    assert len(components.segments(sc.curves[-1])) == 2
    assert len(edges.all_edges(sc)) == 1, "eine Linie, zwei Kanten"


def _bow(h: H):
    """Gerade Linie mit eingefügtem (weichem) Punkt in der Mitte."""
    sc = h.sc
    sc.new_stroke()
    sc.add_curve(line([0, 0, 0], [4, 0, 0], 41), sc.planes[0].id)
    c = sc.curves[-1]
    components.insert_point(c, 20, 0.0)
    h.v._changed()
    network.sync(sc)
    k = [j for j in components.knots(c) if 0 < j < len(c.points) - 1][0]
    return c, k


def _rot_y(deg):
    a = np.radians(deg)
    return np.array([[np.cos(a), 0, np.sin(a)], [0, 1, 0], [-np.sin(a), 0, np.cos(a)]])


def test_punkt_drehen_dreht_die_linie_dort(h: H):
    """F4 orient: einen Punkt drehen – er bleibt, die Nachbarpunkte bleiben, die Linie läuft bei ihm in der neuen
    Richtung durch; der Punkt merkt sich die Drehung (Quaternion), auch über Speichern/Laden."""
    import os, tempfile
    from sketch_machine.scene import Scene
    c, k = _bow(h)
    p, ends = c.points[k].copy(), c.points[[0, -1]].copy()
    group = components.ComponentGroup(h.sc, [(c, k)], [])
    for _ in range(6):  # wie der Gizmo: in kleinen Schritten
        group.rotate(_rot_y(5), p)
    assert np.allclose(c.points[k], p) and np.allclose(c.points[[0, -1]], ends), "Punkt und Nachbarn bleiben"
    d = c.points[k + 2] - c.points[k - 2]
    angle = np.degrees(np.arctan2(-d[2], d[0]))
    assert abs(angle - 30) < 3, f"Richtung am Punkt {angle:.1f}° statt 30°"
    q = network.get_attr(h.sc, network.pid_of(c, k))
    assert np.allclose(q[:4], network.quat_of(_rot_y(30)), atol=1e-6), q
    path = os.path.join(tempfile.mkdtemp(), "orient.sketch.json")
    h.sc.save(path)
    new = Scene.load(path)[0]
    c2 = next(x for st in new.strokes for x in st.curves)
    assert np.allclose(network.get_attr(new, network.pid_of(c2, k))[:4], q[:4]), "orient bleibt beim Laden"


def test_punkt_skalieren_streckt_die_linie_dort(h: H):
    """F4 pscale: einen Punkt einer Rundung größer skalieren – die Linie wird um ihn herum weiter (die Rundung
    bauchiger), Punkt und Nachbarn bleiben; pscale merkt sich den Faktor."""
    sc = h.sc
    sc.new_stroke()
    t = np.linspace(0, 1, 41)
    sc.add_curve(np.stack([t * 4, np.zeros_like(t), np.sin(t * np.pi)], 1), sc.planes[0].id)
    c = sc.curves[-1]
    components.insert_point(c, 20, 0.0)
    h.v._changed()
    network.sync(sc)
    k = [j for j in components.knots(c) if 0 < j < len(c.points) - 1][0]
    p, ends = c.points[k].copy(), c.points[[0, -1]].copy()
    before = c.points[k - 8].copy()
    group = components.ComponentGroup(sc, [(c, k)], [])
    group.scale(np.full(3, 1.5), np.eye(3), p)
    assert np.allclose(c.points[k], p) and np.allclose(c.points[[0, -1]], ends)
    assert np.linalg.norm(c.points[k - 8] - p) > 1.15 * np.linalg.norm(before - p), "Umgebung gestreckt"
    assert abs(network.get_attr(sc, network.pid_of(c, k))[4] - 1.5) < 1e-6


def test_punkt_entfernen_mit_shift_entf_weich(h: H):
    """Shift+Entf entfernt einen Punkt einer geschwungenen Linie: an weichen Nachbarn läuft die neue Linie ohne Knick
    weiter, die Nachbarn bleiben."""
    sc = h.sc
    sc.new_stroke()
    t = np.linspace(0, 1, 61)
    pts = np.stack([t * 6, np.zeros_like(t), np.sin(t * 2 * np.pi)], 1)
    pts[:, 2] += 0.8 * np.exp(-((np.arange(61) - 30) / 5.0) ** 2)  # weiche Beule in der Mitte
    sc.add_curve(pts, sc.planes[0].id)
    c = sc.curves[-1]
    where = [pts[j].copy() for j in (15, 30, 45)]
    c.knots = (len(pts), (15, 30, 45))  # drei eingefügte (weiche) Punkte
    h.v._changed()
    network.sync(sc)
    a, k, b = 15, 30, 45
    assert components.knots(c) == [0, 15, 30, 45, 60]
    pa, pb = c.points[a].copy(), c.points[b].copy()
    h.camera([3, 0, 0], 8, [0, 1, 0.01])
    h.edit_mode("point")
    h.click(h.scr(c.points[k]))
    h.key(Qt.Key_Delete, Qt.ShiftModifier)
    c = h.curves()[0]
    assert np.allclose(c.points[a], pa) and np.allclose(c.points[b], pb), "Nachbarn bleiben"
    assert not any(np.linalg.norm(c.points[j] - where[1]) < 1e-6 for j in components.knots(c)), "Punkt ist weg"
    assert np.linalg.norm(c.points - where[1], axis=1).min() > 0.3, "Beule ist weg, die Linie läuft neu"
    for j in (a, b):  # kein Knick am Nachbarn
        u, v = c.points[j] - c.points[j - 2], c.points[j + 2] - c.points[j]
        cos = u @ v / np.linalg.norm(u) / np.linalg.norm(v)
        assert cos > np.cos(np.radians(12)), f"Knick am Nachbarn {np.degrees(np.arccos(cos)):.1f}°"


def test_export_mit_orient_und_pscale(h: H):
    """Sketch Brief: Linien mit Punkt-Attributen bekommen primvars:orient (quatf) und primvars:pscale je Punkt."""
    import os, tempfile
    from sketch_machine import brief
    c, k = _bow(h)
    group = components.ComponentGroup(h.sc, [(c, k)], [])
    group.rotate(_rot_y(20), c.points[k].copy())
    group.scale(np.full(3, 2.0), np.eye(3), c.points[k].copy())
    path = os.path.join(tempfile.mkdtemp(), "scene.usda")
    brief.write_usd(h.sc, brief.analyse(h.sc), path)
    text = open(path, encoding="utf-8").read()
    assert "quatf[] primvars:orient" in text and "float[] primvars:pscale" in text
    assert " 2," in text.split("float[] primvars:pscale")[1].split("\n")[0], "pscale 2 am Punkt"

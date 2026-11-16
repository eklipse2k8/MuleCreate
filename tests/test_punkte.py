"""Punkt-Werkzeuge: Härte (K), Gleiten (S gehalten), Skalieren mehrerer Punkte."""
import os
import tempfile

import numpy as np

from PySide6.QtTest import QTest

from tests.harness import H, QPoint, QPointF, Qt, line
from sketch_machine import components, network


def _bow(h: H, n=41):
    """Bogen mit einem eingefügten Punkt in der Mitte -> (Linie, Knoten)."""
    sc = h.new_scene()
    sc.new_stroke()
    t = np.linspace(0, 1, n)
    sc.add_curve(np.stack([t * 4, np.zeros_like(t), np.sin(t * np.pi)], 1), sc.planes[0].id)
    c = sc.curves[-1]
    components.insert_point(c, n // 2, 0.0)
    h.v._changed()
    network.sync(sc)
    k = [j for j in components.knots(c) if 0 < j < len(c.points) - 1][0]
    return c, k


def _select_point(h: H, c, k):
    h.camera([2, 0, 0.5], 7, [0, 1, 0.01])
    h.edit_mode("point")
    h.v.point_selection = [("pt", h.sc.owner_of(c).id, c.id, k)]
    h.v._changed()


def _sharp(h: H, c, k):
    return components.point_sharpness(network.refs_by_pid(h.sc).get(network.pid_of(c, k), []))


def test_haerte_tasten_und_ziehen(h: H):
    """K formt die Linie am Punkt: Shift+K ganz hart (Knick), Alt+K ganz weich (rund); Ziehen stellt die Eckigkeit
    stufenlos ein – der Wert ist die Härte, die die Form hat (nichts gespeichert, nach dem Laden dieselbe)."""
    c, k = _bow(h)
    _select_point(h, c, k)
    h.key(Qt.Key_K, Qt.ShiftModifier)
    assert _sharp(h, c, k) == 1.0, "Shift+K: hart"
    h.key(Qt.Key_K, Qt.AltModifier)
    assert _sharp(h, c, k) == 0.0, "Alt+K: weich"
    # K = Werkzeug an: Ziehen (hier im Leeren, die Auswahl bleibt) stellt die Härte der Auswahl ein
    p0 = QPointF(40, 40)
    h.key(Qt.Key_K)
    assert h.v.ws.value_tool == "hardness"
    h.move(p0)
    h.grab()  # Hinweis am Cursor, Quadrate an eckigen Punkten
    h.stroke([p0, QPointF(p0.x() + 100, p0.y())])
    v = _sharp(h, c, k)
    assert abs(v - 0.5) < 0.03, f"halber Weg = 0.5, ist {v}"
    assert h.v.ws.value_tool == "hardness", "Werkzeug bleibt an"
    h.grab()
    h.wheel(2, pos=p0)
    assert abs(_sharp(h, c, k) - 0.6) < 0.03, "Mausrad"
    # Esc mitten im Ziehen bricht ab
    QTest.mousePress(h.v, Qt.LeftButton, Qt.NoModifier, p0.toPoint())
    h.move(QPointF(p0.x() + 300, p0.y()), Qt.LeftButton)
    h.key(Qt.Key_Escape)
    QTest.mouseRelease(h.v, Qt.LeftButton, Qt.NoModifier, QPoint(int(p0.x()) + 300, int(p0.y())))
    h.pump(0.02)
    assert abs(_sharp(h, c, k) - 0.6) < 0.03, "Esc bricht ab"
    h.key(Qt.Key_K)
    assert h.v.ws.value_tool is None, "K nochmal: aus"
    path = os.path.join(tempfile.mkdtemp(), "haerte.sketch.json")
    h.sc.save(path)
    from sketch_machine.scene import Scene
    new = Scene.load(path)[0]
    c2 = next(x for st in new.strokes for x in st.curves)
    pid = network.pid_of(c2, k)
    assert abs(components.point_sharpness(network.refs_by_pid(new)[pid]) - 0.6) < 0.03, "Härte bleibt (in der Form)"


def test_haerte_wirkt_beim_ziehen(h: H):
    """Harter Punkt: die Linie läuft geradlinig zu den Nachbarn (Knick am Punkt); weich: rund."""
    shapes = {}
    for value in (0.0, 1.0):
        c, k = _bow(h)
        _select_point(h, c, k)
        h.v.set_hardness(value)
        group = components.ComponentGroup(h.sc, [(c, k)], [])
        group.translate(np.array([0, 0, 1.0]))
        shapes[value] = c.points.copy()
    soft, hard = shapes[0.0], shapes[1.0]
    k = len(soft) // 2
    # direkt neben dem Punkt: weich fast so hoch wie der Punkt (flach), hart deutlich tiefer (Knick)
    assert soft[k - 3, 2] - hard[k - 3, 2] > 0.05, (soft[k - 3, 2], hard[k - 3, 2])


def _cross(h: H, kinked=True):
    """Gerade Linie E (x-Achse) und eine Querlinie M, die sie in der Mitte kreuzt (gemeinsamer Punkt) – geknickt (V)
    oder rund (Bogen). -> (E, M, Punkt-ID der Kreuzung)."""
    sc = h.new_scene()
    sc.new_stroke()
    sc.add_curve(line([0, 0, 0], [4, 0, 0], 41), None)
    e = sc.curves[-1]
    t = np.linspace(-1, 1, 41)
    sc.add_curve(np.stack([np.full_like(t, 2.0), np.abs(t) if kinked else t * t, t * 1.5], 1), None)
    m = sc.curves[-1]
    h.v._changed()
    network.sync(sc)
    p = np.array([2.0, 0, 0])
    je, jm = network.knot_at(e, p), network.knot_at(m, p)
    network.join(sc, e, je, m, jm)
    return e, m, network.pid_of(e, je)


def test_kante_hart_wo_die_querlinie_knickt(h: H):
    """Eine Kante ist hart, wo die Linien, die sie kreuzen, knicken – dazwischen anteilig bis zu ihren Enden. Die
    Querlinie selbst ist dort weich (die Kante läuft gerade durch)."""
    e, m, pid = _cross(h)
    refs = network.refs_by_pid(h.sc)
    ce, cm = components.crease_along(e, refs), components.crease_along(m, refs)
    k = network.knot_at(e, np.array([2.0, 0, 0]))
    assert ce[k] == 1.0 and ce[0] == 0.0 and 0.3 < ce[k // 2] < 0.7, ce[[0, k // 2, k]]
    assert not cm.any(), "Querlinie: die Kante knickt nicht"
    e, m, pid = _cross(h, kinked=False)
    assert not components.crease_along(e, network.refs_by_pid(h.sc)).any(), "runde Querlinie: weich"


def test_haerte_auf_kante_knickt_die_querlinien(h: H):
    """Kantenmodus, K: die Linien, die die Kante kreuzen, knicken an ihr – die Kante selbst bleibt, wie sie ist."""
    e, m, pid = _cross(h, kinked=False)
    before = e.points.copy()
    h.camera([2, 0, 0], 7, [0.3, 1, 0.4])
    h.edit_mode("edge")
    h.v.edge_selection = [("line", h.sc.owner_of(e).id, e.id)]
    h.v.set_hardness(1.0)
    k = network.knot_at(e, np.array([2.0, 0, 0]))
    assert np.array_equal(e.points, before), "die Kante bleibt"
    assert components.crease_along(e, network.refs_by_pid(h.sc))[k] == 1.0, "Kante ist hart"
    h.v.set_hardness(0.0)
    assert components.crease_along(e, network.refs_by_pid(h.sc))[k] == 0.0, "wieder weich"


def test_punkt_gleitet_auf_der_linie(h: H):
    c, k = _bow(h)
    _select_point(h, c, k)
    shape = c.points.copy()
    start = h.scrf(c.points[k])
    h.key(Qt.Key_S)  # S gedrückt halten (keyClick drückt und lässt los – daher von Hand)
    h.v._slide_key = True
    target = QPointF(start.x() + 60, start.y())
    h.stroke([start, target])
    h.v._slide_key = False
    c = h.curves()[0]
    k2 = [j for j in components.knots(c) if 0 < j < len(c.points) - 1]
    assert len(k2) == 1, k2
    q = c.points[k2[0]]
    assert q[0] > shape[k][0] + 0.2, f"Punkt nach rechts geglitten ({q[0]:.2f})"
    d = np.min(np.linalg.norm(np.diff(shape, axis=0), axis=1))
    a, b = shape[:-1], shape[1:]
    t = np.clip(np.einsum("ij,ij->i", q - a, b - a) / np.einsum("ij,ij->i", b - a, b - a), 0, 1)
    assert np.min(np.linalg.norm(a + (b - a) * t[:, None] - q, axis=1)) < 1e-6, "Punkt liegt auf der alten Linie"
    assert d > 0
    assert h.v.point_selection[0][3] == k2[0], "Auswahl folgt dem Punkt"


def test_mehrere_punkte_skalieren_nur_die_lage(h: H):
    sc = h.new_scene()
    sc.new_stroke()
    sc.add_curve(line([0, 0, 0], [4, 0, 0], 41), sc.planes[0].id)
    c = sc.curves[-1]
    components.insert_point(c, 10, 0.0)
    components.insert_point(c, 30, 0.0)
    h.v._changed()
    network.sync(sc)
    ks = [j for j in components.knots(c) if 0 < j < len(c.points) - 1]
    group = components.ComponentGroup(sc, [(c, j) for j in ks], [])
    p = c.points[ks].mean(axis=0)
    gap = np.linalg.norm(c.points[ks[1]] - c.points[ks[0]])
    group.scale(np.full(3, 2.0), np.eye(3), p)
    for j in ks:
        assert abs(network.get_attr(sc, network.pid_of(c, j))[4] - 1.0) < 1e-9, "pscale bleibt"
    assert abs(np.linalg.norm(c.points[ks[1]] - c.points[ks[0]]) - 2 * gap) < 1e-6, "Abstand verdoppelt"


def test_harte_linie_knickt_die_flaeche(h: H):
    """Netzfläche: eine angehobene Linie quer über die Fläche. Weich geht die Fläche glatt (rund) darüber, hart knickt
    sie an der Linie (Dach); halbe Härte liegt dazwischen."""
    from sketch_machine import netsurf
    n = 41
    u, v = np.meshgrid(np.linspace(0, 4, n), np.linspace(0, 4, n), indexing="ij")
    base = np.stack([u, np.zeros_like(u), v], axis=2)
    cols = np.linspace(1, n - 2, 30)
    uv = np.stack([np.full_like(cols, 20.0), cols], axis=1)
    targets = np.stack([np.full_like(cols, 2.0), np.ones_like(cols), cols * 0.1], axis=1)
    groups = np.zeros(len(cols))
    kink = {}
    for value in (0.0, 0.5, 1.0):
        y = netsurf.solve(base, uv, targets, groups, hard=np.full(len(cols), value))[..., 1]
        row = y[:, n // 2]
        kink[value] = (row[20] - row[18]) - (row[22] - row[20])  # Steigungssprung an der Linie
    assert kink[1.0] > 1.5 * kink[0.0], kink
    assert kink[0.0] < kink[0.5] < kink[1.0], kink


def test_export_mit_haerte(h: H):
    """Sketch Brief: Linien, entlang derer die Fläche knickt, bekommen primvars:hardness je Punkt (anteilig)."""
    from sketch_machine import brief
    e, m, pid = _cross(h)
    k = network.knot_at(e, np.array([2.0, 0, 0]))
    path = os.path.join(tempfile.mkdtemp(), "scene.usda")
    brief.write_usd(h.sc, brief.analyse(h.sc), path)
    text = open(path, encoding="utf-8").read()
    assert text.count("float[] primvars:hardness") == 1, "nur die Kante mit knickender Querlinie"
    values = [float(x) for x in text.split("primvars:hardness = [")[1].split("]")[0].split(",")]
    assert len(values) == len(e.points) and values[k] == 1.0 and values[0] == 0.0


def test_glaetten_bis_zur_geraden(h: H):
    """J: halb geglättet verschwindet das Zittern (die Form bleibt grob), voll geglättet ist die Kante gerade; die Enden
    bleiben."""
    sc = h.new_scene()
    sc.new_stroke()
    t = np.linspace(0, 1, 121)
    rng = np.random.default_rng(3)
    pts = np.stack([t * 4, np.zeros_like(t), 0.8 * np.sin(t * np.pi) + 0.03 * rng.standard_normal(len(t))], 1)
    sc.add_curve(pts, sc.planes[0].id)
    c = sc.curves[-1]
    c.knots = (len(pts), ())
    h.v._changed()
    ends = c.points[[0, -1]].copy()
    h.camera([2, 0, 0.4], 7, [0, 1, 0.01])
    h.edit_mode("edge")
    h.v.edge_selection = [("line", sc.owner_of(c).id, c.id)]
    h.v._changed()
    p0 = QPointF(40, 40)
    h.key(Qt.Key_J)
    assert h.v.ws.value_tool == "smooth"
    QTest.mousePress(h.v, Qt.LeftButton, Qt.NoModifier, p0.toPoint())
    h.move(QPointF(p0.x() + 30, p0.y()), Qt.LeftButton)
    h.move(QPointF(p0.x() + 60, p0.y()), Qt.LeftButton)  # 0,3
    jitter = lambda p: float(np.abs(np.diff(p[:, 2], 2)).mean())
    c = h.curves()[0]
    assert jitter(c.points) < 0.3 * jitter(pts) and c.points[:, 2].max() > 0.5, "Zittern weg, Bogen bleibt"
    h.key(Qt.Key_Escape)
    QTest.mouseRelease(h.v, Qt.LeftButton, Qt.NoModifier, QPoint(int(p0.x()) + 60, int(p0.y())))
    h.pump(0.02)
    assert np.allclose(h.curves()[0].points, pts), "Esc: unverändert"
    h.stroke([p0, QPointF(p0.x() + 260, p0.y())])
    c = h.curves()[0]
    d = ends[1] - ends[0]
    off = np.cross(c.points - ends[0], d / np.linalg.norm(d))
    assert np.allclose(c.points[[0, -1]], ends) and np.abs(off).max() < 1e-9, "gerade"


def test_haerte_formt_die_linie_am_punkt(h: H):
    """Punkt auf einer Rundung härten: die Linie bekommt dort einen Knick (jede Seite läuft gerader auf den Punkt zu);
    Punkt und Enden bleiben; wieder weich: die Rundung ist zurück."""
    c, k = _bow(h)
    _select_point(h, c, k)
    pts = c.points.copy()

    def kink(p):
        u, v = p[k] - p[k - 2], p[k + 2] - p[k]
        return np.degrees(np.arccos(np.clip(u @ v / np.linalg.norm(u) / np.linalg.norm(v), -1, 1)))
    assert kink(pts) < 10, "anfangs rund"
    h.key(Qt.Key_K, Qt.ShiftModifier)
    c = h.curves()[0]
    assert kink(c.points) > 40, f"hart: Knick am Punkt ({kink(c.points):.0f}°)"
    assert np.allclose(c.points[[0, k, -1]], pts[[0, k, -1]]), "Punkt und Enden bleiben"
    h.key(Qt.Key_K, Qt.AltModifier)
    c = h.curves()[0]
    # K liest die Ausgangsform aus der Linie (nichts gespeichert): rund wie vorher bis auf einen unsichtbaren Rest
    assert kink(c.points) < 10 and np.abs(c.points - pts).max() < 2e-3 * np.ptp(pts, axis=0).max(),         "wieder weich: wie vorher"


def test_werkzeug_aus_bei_transform_und_erneutem_klick(h: H):
    c, k = _bow(h)
    _select_point(h, c, k)
    h.key(Qt.Key_K)
    assert h.v.ws.value_tool == "hardness"
    h.key(Qt.Key_T)
    assert h.v.ws.value_tool is None and h.v.gizmo.tool == "translate", "T beendet Härte"
    h.v.set_transform_tool(None)
    h.key(Qt.Key_J)  # Kantenmodus
    h.key(Qt.Key_J)
    h.edit_mode("point")
    h.v.point_selection = [("pt", h.sc.owner_of(c).id, c.id, k)]
    h.key(Qt.Key_K)
    h.click(h.scr(c.points[k]))  # nochmal auf den gewählten Punkt
    assert h.v.ws.value_tool is None, "erneuter Klick auf die Auswahl beendet das Werkzeug"
    assert h.v.point_selection, "Auswahl bleibt"


def test_punkte_ziehen_auto_weich_hart(h: H):
    """Leiste „Punkte ziehen“: Auto/Weich/Hart. Ein Punkt auf einer Rundung: Auto und Weich ziehen ihn rund hoch (die
    Linie knickt dort nicht), Hart mit Knick am Punkt; Auto ist Standard, die Knöpfe stehen im Punkt-/Kantenmodus."""
    results = {}
    for mode in ("auto", "soft", "hard"):
        c, k = _bow(h)
        _select_point(h, c, k)
        assert h.w.knot_actions[mode].isVisible() or not h.w.isVisible()
        h.w.knot_actions[mode].trigger()
        assert h.v.ws.knot_mode == mode and h.w.knot_actions[mode].isChecked()
        h.v.transform_target.translate(np.array([0.0, 0.0, 0.6]))
        h.v._changed()
        results[mode] = _sharp(h, c, k)
    h.w.knot_actions["auto"].trigger()
    assert results["auto"] < 0.2 and results["soft"] < 0.2, f"rund hochgezogen: {results}"
    assert results["hard"] > 0.3, f"hart: Knick am Punkt ({results})"

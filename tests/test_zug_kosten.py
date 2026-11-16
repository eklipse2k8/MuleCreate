"""Was ein Gizmo-Zug nicht kosten darf (Aufnahme des Artists vom 12.11.: 300–650 ms je Bild, Strg+Z 1,8–2,5 s): unbeteiligte
Flächen gelten danach nicht als geändert, und die Schattenbänder aller Striche entstehen in einem Zug – mit demselben
Ergebnis wie Linie für Linie."""
import numpy as np

import sketch_machine.scene as S
from sketch_machine import network, renderer

STUFE = "kern"


def _flaeche(sc, x0):
    st = sc.new_stroke()
    st.parent = None
    q = [[x0, 0, 0], [x0 + 2, 0, 0], [x0 + 2, 0, 2], [x0, 0, 2]]
    for i in range(4):
        sc.add_curve(np.linspace(q[i], q[(i + 1) % 4], 8), None)
    network.sync(sc)
    patch = sc.create_patch(list(st.curves))
    assert patch is not None
    return st, patch


def test_unbeteiligte_flaeche_gilt_nach_starrem_zug_nicht_als_geaendert(h=None):
    """Im starren Zug wird jede Fläche der Szene festgehalten. Die Merk-Attribute dafür müssen danach wieder weg sein:
    Sonst unterscheidet sich jede Fläche von ihrem Undo-Abbild und wird bei jedem Schritt voll kopiert."""
    sc = S.Scene()
    a, pa = _flaeche(sc, 0.0)
    _b, pb = _flaeche(sc, 10.0)
    for _ in range(4):
        sc.sync_lofts()
    sc.checkpoint()
    sc.checkpoint()  # (der erste Schritt kopiert alles; ab dem zweiten hat jede Fläche ein Abbild vom Stand davor)
    vorher = set(pb.__dict__)
    t = S.TransformSet([a], scene=sc)
    t.in_drag = True
    for _ in range(3):
        t.translate(np.array([0.0, 0.5, 0.0]))
        sc.sync_lofts()
    assert pb.__dict__.get("_carried"), "Voraussetzung des Tests: die unbeteiligte Fläche wird im Zug festgehalten"
    t.in_drag = False
    t.end_rigid()
    for _ in range(3):
        sc.sync_lofts()
    neu = {k for k in set(pb.__dict__) - vorher if k.startswith("_carr") or k == "_idle_hold"}
    assert not neu, f"der Zug hat an der unbeteiligten Fläche Merk-Attribute hinterlassen: {sorted(neu)}"
    memo, _keep = sc._twin_memo()
    assert id(pb) in memo, "die unbeteiligte Fläche gilt für das Undo als geändert (würde voll kopiert)"
    assert id(pa) not in memo, "die bewegte Fläche gilt als unverändert"
    form = np.array(pb.fill_mesh()[0], float)
    sc.undo()
    pb2 = next(f for f in sc.surfaces if f.id == pb.id)
    assert pb2 is pb, "die unbeteiligte Fläche wurde beim Zurückholen ersetzt"
    assert np.allclose(np.array(pb2.fill_mesh()[0], float), form)


def _baender_einzeln(lines, sun, min_w, r):
    """Die Rechnung Linie für Linie (Fassung bis v0.99.198) als Vergleich."""
    sun = np.asarray(sun, float)
    tris = []
    for pts, w in lines:
        hw = np.maximum(np.broadcast_to(np.asarray(w, float), (len(pts),)), min_w) * 0.5
        pts = pts - sun * hw[:, None]
        a, b = pts[:-1], pts[1:]
        t = b - a
        t = t / np.maximum(np.linalg.norm(t, axis=1, keepdims=True), 1e-12)
        a, b = a - t * hw[:-1, None], b + t * hw[1:, None]
        side = np.cross(t, sun)
        ln = np.linalg.norm(side, axis=1, keepdims=True)
        side = np.where(ln > 1e-9, side / np.maximum(ln, 1e-12), r)
        sa, sb = side * hw[:-1, None], side * hw[1:, None]
        q = [a - sa, a + sa, b + sb, b - sb]
        tris.append(np.stack([q[0], q[1], q[2], q[0], q[2], q[3]], axis=1).reshape(-1, 3))
    return np.vstack(tris).astype("f4")


def test_schattenbaender_in_einem_zug_wie_einzeln(h=None):
    rng = np.random.default_rng(7)
    lines = [(rng.random((n, 3)) * 20, rng.random(n) * 0.4 if n % 2 else 0.07) for n in (2, 3, 11, 2, 60, 5, 8)]
    lines.append((np.array([[0, 0, 0], [0, 0, 0], [1, 0, 0]], float), 0.1))  # Segment ohne Länge
    sun = np.array([0.3, 0.8, 0.5])
    sun /= np.linalg.norm(sun)
    quer = np.array([1.0, 0.0, 0.0])
    alle = renderer.shadow_ribbons(lines, sun, 0.02, quer)
    assert np.array_equal(alle, _baender_einzeln(lines, sun, 0.02, quer)), "Schattenbänder weichen von der Einzelrechnung ab"
    mit_kurzer = lines[:2] + [(np.zeros((1, 3)), 0.1)] + lines[2:]  # eine Linie aus einem Punkt wirft keinen Schatten
    assert np.array_equal(renderer.shadow_ribbons(mit_kurzer, sun, 0.02, quer), alle)
    assert renderer.shadow_ribbons([], sun, 0.02, quer).shape == (0, 3)

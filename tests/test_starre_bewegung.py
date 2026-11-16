"""Starre Bewegung: Flächen, deren Linien alle mitgezogen werden, werden im Gizmo-Zug nur mitgetragen (kein Abgleich je
Bild) und folgen nach dem Loslassen wieder ihren Linien (Hafentest 09.11.: Hero-Gebäude verschieben 0,5 s je Bild)."""
import json
import os
import tempfile

import numpy as np

from sketch_machine import network
from tests.harness import H, line


def _square_in_null(h):
    h.new_scene()
    sc = h.sc
    st = sc.new_stroke()
    pts = [[0, 0, 0], [2, 0, 0], [2, 0, 2], [0, 0, 2], [0, 0, 0]]
    for p, q in zip(pts[:-1], pts[1:]):
        sc.add_curve(line(p, q, 8), None)
    network.sync(sc)
    h.v.edge_selection = [("line", st.id, c.id) for c in st.curves]
    h.v.do_patch()
    patch = sc.surfaces[-1]
    h.v.selection = [st.id, patch.id]
    h.v.create_null("null")
    null = sc.nulls[-1]
    h.v.selection = [null.id]
    h.v._changed()
    return sc, st, patch, null


def test_flaeche_wird_mitgetragen_und_folgt_danach(h: H):
    sc, st, patch, null = _square_in_null(h)
    before = patch.fill_mesh()[0].copy()
    target = h.v.transform_target
    target.in_drag = True  # wie Gizmo.begin
    d = np.array([1.0, 0.5, -0.25])
    target.translate(d / 2)
    target.translate(d / 2)
    assert getattr(patch, "_carried", False) and patch.frozen is not None, "im Zug mitgetragen"
    assert np.allclose(patch.fill_mesh()[0], before + d), "Netz läuft starr mit"
    h.v._changed()  # Abgleich im Zug: überspringt sie
    assert getattr(patch, "_carried", False)
    target.in_drag = False
    target.end_rigid()  # wie Gizmo.end
    h.v._changed()
    assert patch.frozen is None and not getattr(patch, "_carried", False), "nach dem Zug wieder frei"
    assert np.allclose(patch.fill_mesh()[0], before + d, atol=1e-6), "frisch gebaut = mitgetragen"


def test_ungleichmaessig_skalieren_verformt_normal(h: H):
    sc, st, patch, null = _square_in_null(h)
    target = h.v.transform_target
    target.in_drag = True
    target.scale(np.array([2.0, 1.0, 1.0]), np.eye(3), np.zeros(3))
    assert patch.frozen is None, "verformt: nicht mittragen"
    target.in_drag = False
    target.end_rigid()


def test_speichern_und_undo_mitten_im_zug(h: H):
    sc, st, patch, null = _square_in_null(h)
    sc.checkpoint()
    target = h.v.transform_target
    target.in_drag = True
    target.translate(np.array([1.0, 0, 0]))
    path = os.path.join(tempfile.mkdtemp(), "zug.sketch.json")
    sc.save(path)
    data = json.load(open(path, encoding="utf-8"))
    assert not any("frozen" in f for f in data["surfaces"]), "mitgetragen wird nie als eingefroren gespeichert"
    sc.undo()
    h.v._changed()
    assert all(s.frozen is None for s in sc.surfaces), "nach Undo nichts eingefroren"
    target.in_drag = False
    target.end_rigid()


def test_bild_im_zug_wie_danach(h: H):
    """Lage-Matrix auf der GPU (Netz vom Zugbeginn) zeichnet dasselbe Bild wie das danach frisch gebaute Netz."""
    sc, st, patch, null = _square_in_null(h)
    h.camera([1.5, 0.0, 1.0], 7, [0.3, 0.8, 0.5])
    h.v._changed()
    target = h.v.transform_target
    target.in_drag = True
    target.translate(np.array([0.4, 0.2, 0.1]))
    rot = np.array([[np.cos(0.3), 0, np.sin(0.3)], [0, 1, 0], [-np.sin(0.3), 0, np.cos(0.3)]])
    target.rotate(rot, np.array([1.0, 0.0, 1.0]))
    assert getattr(patch, "_carry_model", None) is not None, "Anzeige über Lage-Matrix"
    during = h.grab()
    target.in_drag = False
    target.end_rigid()
    h.v._changed()
    after = h.grab()
    n = h.diff(during, after, threshold=6)
    assert n < 200, f"Bild im Zug weicht vom frisch gebauten ab ({n} Pixel)"


def _square_with_paint(h):
    """Kurvenfläche aus vier Linien, darauf zwei Malstriche – alles in EINEM Linienobjekt, die Fläche nicht gewählt."""
    h.new_scene()
    sc = h.sc
    st = sc.new_stroke()
    pts = [[0, 0, 0], [2, 0, 0], [2, 0, 2], [0, 0, 2], [0, 0, 0]]
    for p, q in zip(pts[:-1], pts[1:]):
        sc.add_curve(line(p, q, 8), None)
    network.sync(sc)
    h.v.edge_selection = [("line", st.id, c.id) for c in st.curves]
    h.v.do_patch()
    patch = sc.surfaces[-1]
    sc.active_stroke = st
    for z in (0.6, 1.4):
        sc.add_curve(line([0.4, 0, z], [1.6, 0, z + 0.2], 10), patch.id)
        st.curves[-1].paint = True
    h.v.edge_selection = []
    h.v._changed()
    paint = [c for c in st.curves if c.paint]
    assert all(c.id in patch.attached for c in paint), "Malerei haftet an der Fläche"
    return sc, st, patch, paint


def _drag_all(h, target, patch, st):
    """Zug nachspielen (verschieben + drehen); liefert die Gesamtbewegung als Funktion."""
    before = {c.id: c.points.copy() for c in st.curves}
    mesh = patch.fill_mesh()[0].copy()
    target.in_drag = True
    d = np.array([0.7, 0.3, -0.4])
    rot = np.array([[np.cos(0.4), 0, np.sin(0.4)], [0, 1, 0], [-np.sin(0.4), 0, np.cos(0.4)]])
    piv = np.array([1.0, 0.0, 1.0])
    target.translate(d)
    h.v._changed()
    target.rotate(rot, piv)
    h.v._changed()
    move = lambda p: piv + (p + d - piv) @ rot.T
    return before, mesh, move


def _check_followed(h, sc, st, patch, paint, target, before, mesh, move):
    assert getattr(patch, "_carried", False), "im Zug mitgetragen, obwohl die Fläche nicht gewählt ist"
    assert np.allclose(patch.fill_mesh()[0], move(mesh)), "Netz läuft starr mit"
    target.in_drag = False
    target.end_rigid()
    h.v._changed()
    assert patch.frozen is None and not getattr(patch, "_carried", False)
    assert np.allclose(patch.fill_mesh()[0], move(mesh), atol=1e-6), "frisch gebaut = mitgetragen"
    for c in st.curves:
        assert np.allclose(c.points, move(before[c.id]), atol=1e-4), "Linien und Malerei starr bewegt"
    assert all(c.plane_id == patch.id and c.id in patch.attached for c in paint), "Malerei haftet weiter"


def test_linienobjekt_bewegen_traegt_flaeche_mit(h: H):
    """Talking Points 10.11.: Linienobjekt (Randlinien + Malerei) bewegen, Fläche nicht gewählt – 3,4 s je Bild, weil
    jeder Malstrich in jedem Bild neu gebunden wurde."""
    sc, st, patch, paint = _square_with_paint(h)
    h.v.selection = [st.id]
    h.v._changed()
    target = h.v.transform_target
    _check_followed(h, sc, st, patch, paint, target, *_drag_all(h, target, patch, st))


def test_alle_linien_im_kantenmodus_tragen_flaeche_mit(h: H):
    sc, st, patch, paint = _square_with_paint(h)
    h.edit_mode("edge")
    h.v.selection = []
    h.v.edge_selection = [("line", st.id, c.id) for c in st.curves]
    h.v._changed()
    target = h.v.transform_target
    _check_followed(h, sc, st, patch, paint, target, *_drag_all(h, target, patch, st))


def test_nur_malerei_bewegen_traegt_nichts_mit(h: H):
    """Nur die Malstriche gezogen: die Fläche bleibt stehen und wird nicht mitgetragen."""
    sc, st, patch, paint = _square_with_paint(h)
    mesh = patch.fill_mesh()[0].copy()
    h.edit_mode("edge")
    h.v.selection = []
    h.v.edge_selection = [("line", st.id, c.id) for c in paint]
    h.v._changed()
    target = h.v.transform_target
    target.in_drag = True
    target.translate(np.array([0.1, 0.0, 0.1]))
    h.v._changed()
    assert getattr(patch, "_carry_model", None) is None, "Fläche wandert nicht mit der Malerei"
    assert np.allclose(patch.fill_mesh()[0], mesh)
    target.in_drag = False
    target.end_rigid()
    h.v._changed()
    assert np.allclose(patch.fill_mesh()[0], mesh)


def test_weich_mitgezogene_nachbarlinie_verhindert_festhalten(h: H):
    """Eine zweite Fläche berührt die bewegte nur an einer Ecke: ihre beiden Randlinien dort ziehen weich mit. Sie hängt
    an keiner gewählten Linie, darf aber nicht festgehalten werden (sie verformt sich); die erste wird mitgetragen."""
    sc, st, patch, paint = _square_with_paint(h)
    first = list(st.curves)
    sc.active_stroke = st
    pts = [[2, 0, 2], [4, 0, 2], [4, 0, 4], [2, 0, 4], [2, 0, 2]]
    for p, q in zip(pts[:-1], pts[1:]):
        sc.add_curve(line(p, q, 8), None)
    second = [c for c in st.curves if c not in first]
    network.sync(sc)
    h.edit_mode("edge")
    h.v.selection = []
    h.v.edge_selection = [("line", st.id, c.id) for c in second]
    h.v.do_patch()
    other = sc.surfaces[-1]
    assert other is not patch
    h.v.selection = []  # do_patch wählt die neue Fläche – hier sind nur die Linien der ersten gewählt
    h.v.edge_selection = [("line", st.id, c.id) for c in first]
    h.v._changed()
    mesh = other.fill_mesh()[0].copy()
    target = h.v.transform_target
    target.in_drag = True
    target.translate(np.array([-0.5, 0.0, -0.5]))
    h.v._changed()
    assert getattr(patch, "_carried", False), "Fläche der gewählten Linien wird mitgetragen"
    assert other.frozen is None, "Nachbarfläche mit weich mitgezogenen Randlinien wird nicht festgehalten"
    assert not np.allclose(other.fill_mesh()[0], mesh), "Nachbarfläche folgt ihrer verformten Ecke schon im Zug"
    target.in_drag = False
    target.end_rigid()
    h.v._changed()
    assert patch.frozen is None and other.frozen is None


def test_unbeteiligte_flaeche_wird_nach_dem_zug_nicht_neu_abgeglichen(h: H):
    """Eine Fläche, die an nichts Bewegtem hängt, ist im Zug nur festgehalten: ihr Stempel gilt nach dem Loslassen
    weiter (vorher glich jedes Loslassen alle Flächen der Szene neu ab)."""
    sc, st, patch, null = _square_in_null(h)
    other = sc.new_stroke()
    other.parent = None  # nicht in der Gruppe, die gleich bewegt wird
    pts = [[5, 0, 0], [7, 0, 0], [7, 0, 2], [5, 0, 2], [5, 0, 0]]
    for p, q in zip(pts[:-1], pts[1:]):
        sc.add_curve(line(p, q, 8), None)
    network.sync(sc)
    h.v.edge_selection = [("line", other.id, c.id) for c in other.curves]
    h.v.do_patch()
    far = sc.surfaces[-1]
    far.parent = None
    assert far not in sc.descendants(null) and other not in sc.descendants(null)
    h.v.edge_selection = []
    h.v.selection = [null.id]
    h.v._changed()
    h.v._changed()
    stamp, mesh = far.__dict__.get("_sync_ok"), far.fill_mesh()[0]
    assert stamp is not None
    target = h.v.transform_target
    target.in_drag = True
    target.translate(np.array([0.5, 0.0, 0.25]))
    h.v._changed()
    assert far.__dict__.get("_idle_hold") and not patch.__dict__.get("_idle_hold")
    assert far.frozen is not None and patch.frozen is not None, "im Zug beide festgehalten"
    target.in_drag = False
    target.end_rigid()
    assert far.frozen is None and far.__dict__.get("_sync_ok") == stamp, "Stempel der unbeteiligten gilt weiter"
    assert patch.__dict__.get("_sync_ok") is not None, "die bewegte ist mitverschoben und gilt als abgeglichen"
    h.v._changed()
    assert far.fill_mesh()[0] is mesh, "nichts neu gerechnet"
    assert np.allclose(patch.fill_mesh()[0].mean(axis=0), [1.5, 0.0, 1.25]), "die bewegte ist ihren Linien gefolgt"
    # hängt die „unbeteiligte“ doch an etwas, das sich geändert hat, gleicht sie ab
    c = other.curves[0]
    c.points = c.points + np.array([0.0, 0.3, 0.0])
    h.v._changed()
    assert far.fill_mesh()[0] is not mesh


def test_verschobene_flaeche_wird_nach_dem_zug_nicht_neu_gerechnet(h: H):
    """Nur verschoben: der fertige Stand der Fläche wandert mit, nach dem Loslassen entsteht nichts neu aus den Linien.
    (Der Prüfmodus der Tests rechnet sie trotzdem neu und vergleicht.) Gedreht: wie bisher neu gerechnet."""
    from sketch_machine.scene import SurfaceObject
    sc, st, patch, null = _square_in_null(h)
    h.v._changed()
    rows = [c.points.copy() for c in patch.curves]
    pts = [p.copy() for p in patch._net_pts]
    target = h.v.transform_target
    target.in_drag = True
    d = np.array([0.5, 0.25, -1.0])
    target.translate(d / 2)
    target.translate(d / 2)
    target.in_drag = False
    builds = []
    real = type(patch)._build
    type(patch)._build = lambda self: (builds.append(1), real(self))[1]
    try:
        target.end_rigid()
        assert patch.frozen is None and patch.__dict__.get("_sync_ok") is not None
        mesh = patch.fill_mesh()
        assert not builds, "angezeigtes Netz ist mitverschoben, nicht neu gebaut"
    finally:
        type(patch)._build = real
    assert all(np.allclose(c.points, r + d) for c, r in zip(patch.curves, rows)), "Gitterreihen mitverschoben"
    assert all(np.allclose(p, q + d) for p, q in zip(patch._net_pts, pts)), "Netzgeometrie mitverschoben"
    h.v._changed()  # Prüfmodus: rechnet neu und vergleicht
    assert np.allclose(patch.fill_mesh()[0].mean(axis=0), np.array([1.0, 0.0, 1.0]) + d, atol=1e-6)
    # danach verformt sich eine Linie: die Fläche folgt wie immer
    c = st.curves[0]
    p = c.points.copy()
    p[len(p) // 2] += [0.0, 0.5, 0.0]
    c.points = p
    h.v._changed()
    assert patch.fill_mesh()[0][:, 1].max() > d[1] + 0.2, "folgt der verformten Linie"
    # gedreht: kein Mitverschieben
    target = h.v.transform_target
    target.in_drag = True
    a = np.radians(30.0)
    rot = np.array([[np.cos(a), 0, np.sin(a)], [0, 1, 0], [-np.sin(a), 0, np.cos(a)]])
    target.rotate(rot, np.zeros(3))
    target.in_drag = False
    target.end_rigid()
    assert patch.__dict__.get("_sync_ok") is None, "gedreht: gleicht neu ab"
    h.v._changed()

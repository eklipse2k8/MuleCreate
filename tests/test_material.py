"""Flächen als Objekte mit Material (Darstellung): Material wählen, einfärben, speichern; Flächen decken Linien."""
import os
import tempfile

import numpy as np

from tests.harness import H, Qt
from sketch_machine import network, theme
from sketch_machine.scene import Scene, StrokeObject



def _find(o, sid):
    """Eintrag eines Objekts irgendwo im Outliner (Flächen stehen unter ihrem Linienobjekt)."""
    from PySide6.QtWidgets import QTreeWidgetItemIterator
    it = QTreeWidgetItemIterator(o)
    while it.value() is not None:
        if it.value().data(0, Qt.UserRole) == sid:
            return it.value()
        it += 1
    return None


def _under(root, sid):
    stack = [root.child(i) for i in range(root.childCount())]
    while stack:
        x = stack.pop()
        if x.data(0, Qt.UserRole) == sid:
            return True
        stack += [x.child(i) for i in range(x.childCount())]
    return False

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
    s.seed = 1.0  # fester Texturversatz: Flecken und Tonstufen liegen in jedem Lauf gleich (Pixel-Vergleiche)
    h.v._changed()
    return s


def test_f_faerbt_die_aktive_flaeche_ein(h: H):
    """Zeichenmodus: F färbt die aktive Fläche in der aktuellen Farbe, Shift+F setzt zurück; je ein Undo-Schritt."""
    s = _square(h)
    h.camera([1, 0, 1], 5, [0.1, 1, 0.2])
    h.draw_mode()
    h.v._activate(s)
    h.v.set_paint_color((0.8, 0.3, 0.2))
    h.key(Qt.Key_F)
    assert s.tint == (0.8, 0.3, 0.2)
    h.key(Qt.Key_F, Qt.ShiftModifier)
    assert s.tint is None
    h.key(Qt.Key_Z, Qt.ControlModifier)
    assert h.sc.surfaces[0].tint == (0.8, 0.3, 0.2), "Undo holt die Färbung zurück"


def test_material_im_outliner(h: H):
    """Die Material-Spalte der Fläche (gemalt wie ein Dropdown, kein Widget je Zeile – Tempo) zeigt ihr Material,
    das Menü setzt es."""
    from sketch_machine.outliner import BRIEF_ROLE, MATERIAL
    s = _square(h)
    h.pump(0.05)
    o = h.w.outliner
    o.rebuild()
    item = _find(o, s.id)
    assert o.itemWidget(item, MATERIAL) is None, "kein eingebettetes Widget je Zeile"
    assert item.data(MATERIAL, BRIEF_ROLE)[0] == "Papier"
    o._set_material(s.id, "holz")  # was das Menü beim Klick aufruft
    assert h.sc.surfaces[0].material == "holz"
    h.pump(0.05)
    item = _find(o, s.id)
    assert item.data(MATERIAL, BRIEF_ROLE)[0] == "Holz"


def test_outliner_panels_erst_beim_aufklappen(h: H):
    """Flächen-Optionen (Regler) entstehen erst beim Aufklappen – nicht bei jedem Neuaufbau für alle Flächen."""
    s = _square(h)
    h.pump(0.05)
    o = h.w.outliner
    o.rebuild()
    item = _find(o, s.id)
    assert o.itemWidget(item.child(0), 0) is None, "zugeklappt: noch kein Panel"
    item.setExpanded(True)
    h.pump(0.05)
    item = _find(o, s.id)
    assert o.itemWidget(item.child(0), 0) is not None, "aufgeklappt: Panel da"
    assert item.child(0).isFirstColumnSpanned(), "Panel über die ganze Breite"
    o.rebuild()  # bleibt aufgeklappt, Panel wird wieder gebaut
    item = _find(o, s.id)
    assert item.isExpanded() and o.itemWidget(item.child(0), 0) is not None


def test_material_farbe_versatz_werden_gespeichert(h: H):
    s = _square(h)
    s.material, s.tint, s.seed = "stoff", (0.2, 0.4, 0.6), 123.4
    path = os.path.join(tempfile.mkdtemp(), "mat.sketch.json")
    h.sc.save(path)
    t = Scene.load(path)[0].surfaces[0]
    assert (t.material, t.tint, t.seed) == ("stoff", (0.2, 0.4, 0.6), 123.4)


def test_flaeche_verdeckt_linie_dahinter(h: H):
    """Flächen decken: eine Linie hinter einer Fläche ist nicht zu sehen, eine Linie auf ihr schon."""
    _square(h, y=1.0, x0=-1.0, size=3.0)
    sc = h.sc
    sc.add_curve(np.linspace([0.0, 0.0, 0.5], [1.0, 0.0, 0.5], 10), None, np.full(10, 0.05))  # unter der Fläche
    behind = sc.curves[-1]
    h.v._changed()
    h.v.set_planes_visible(False)
    try:
        h.camera([0.5, 0.5, 0.5], 5, [0.0, 1.0, 0.02])  # von oben: die Fläche liegt zwischen Kamera und Linie
        img = h.grab()
        mid = h.scr(behind.points[5])
        r, g, b = h.pixel(img, mid)[:3]
        beside = h.pixel(img, h.scr(behind.points[5] + np.array([0.0, 0.0, 0.8])))[:3]  # daneben, ohne Linie dahinter
        assert abs((r + g + b) - sum(beside)) < 40, f"Linie hinter der Fläche scheint durch: {(r, g, b)} statt {beside}"
    finally:
        h.v.set_planes_visible(True)


def test_grosses_mesh_verdeckt_kleine_linie_dicht_dahinter(h: H):
    """Meshes decken unabhängig von ihrer Größe: unter der Oberseite eines 60-m-Würfels ist eine Linie 0,3 m tiefer
    nicht zu sehen (früher Spielraum 2 % der Mesh-Diagonale), eine darauf gezeichnete Linie schon."""
    from sketch_machine.geometry import Geometry
    from sketch_machine.scene import MeshObject
    h.new_scene()
    sc = h.sc
    v = np.array([[x, y, z] for x in (-30, 30) for y in (-60, 0) for z in (-30, 30)], float)
    f = [[0, 1, 3], [0, 3, 2], [4, 6, 7], [4, 7, 5], [0, 4, 5], [0, 5, 1], [2, 3, 7], [2, 7, 6], [1, 5, 7], [1, 7, 3],
         [0, 2, 6], [0, 6, 4]]
    mesh = MeshObject("Würfel", "", Geometry(v, np.array(f)))
    sc.meshes.append(mesh)
    sc.new_stroke()
    sc.add_curve(np.linspace([0.0, -0.3, 0.5], [1.0, -0.3, 0.5], 10), None, np.full(10, 0.05))
    behind = sc.curves[-1]
    sc.add_curve(np.linspace([0.0, 0.0, -0.5], [1.0, 0.0, -0.5], 10), mesh.id, np.full(10, 0.05))
    on = sc.curves[-1]
    h.v._changed()
    h.v.set_planes_visible(False)
    try:
        h.camera([0.5, 0.0, 0.0], 5, [0.0, 1.0, 0.02])  # von oben auf die Oberseite
        img = h.grab()
        lum = lambda p: sum(h.pixel(img, h.scr(p))[:3])
        hidden = abs(lum(behind.points[5]) - lum(behind.points[5] + np.array([0.0, 0.0, 0.3])))
        shown = lum(on.points[5] + np.array([0.0, 0.0, 0.3])) - lum(on.points[5])
        assert hidden < 40, f"Linie unter der Mesh-Oberseite scheint durch ({hidden})"
        assert shown > 100, f"auf das Mesh gezeichnete Linie nicht zu sehen ({shown})"
    finally:
        h.v.set_planes_visible(True)


def test_mesh_kanten_lassen_flaeche_dahinter_nicht_durch(h: H):
    """An Tiefenkanten eines Meshes (ein Block steht auf einer Platte) deckt die Platte auch direkt neben dem Block:
    eine Fläche darunter scheint nicht als Sprenkel entlang der Kante durch (Deckkraft nur am eigenen Pixel prüfen)."""
    from sketch_machine.geometry import Geometry
    from sketch_machine.scene import MeshObject
    h.new_scene()
    sc = h.sc

    def box(lo, hi):
        v = np.array([[x, y, z] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])], float)
        f = [[0, 1, 3], [0, 3, 2], [4, 6, 7], [4, 7, 5], [0, 4, 5], [0, 5, 1], [2, 3, 7], [2, 7, 6], [1, 5, 7],
             [1, 7, 3], [0, 2, 6], [0, 6, 4]]
        return v, np.array(f)

    (v1, f1), (v2, f2) = box((-3, -0.1, -3), (4, 0.0, 4)), box((0.2, 0.0, -2), (1.2, 0.6, 3))
    sc.meshes.append(MeshObject("Platte mit Block", "", Geometry(np.vstack([v1, v2]), np.vstack([f1, f2 + 8]))))
    _square(h, y=-0.4, x0=-1.0, size=3.0)  # Fläche unter der Platte
    h.v.set_planes_visible(False)
    try:
        h.camera([0.5, 0.0, 0.5], 5, [-0.35, 1.0, 0.1])  # schräg von oben: der Block wirft eine Tiefenkante
        a = h.grab()
        sc.surfaces[0].hidden = True
        h.v._changed()
        b = h.grab()
        n = h.diff(a, b, threshold=30)
        assert n < 5, f"Fläche unter der Platte scheint an {n} Pixeln entlang der Blockkante durch"
    finally:
        sc.surfaces[0].hidden = False
        h.v.set_planes_visible(True)


def test_transparente_flaeche_laesst_linie_durchscheinen(h: H):
    """Transparenz-Regler: hinter einer halb durchsichtigen Fläche ist eine Linie zu sehen, schwächer als frei."""
    s = _square(h, y=1.0, x0=-1.0, size=3.0)
    sc = h.sc
    sc.add_curve(np.linspace([0.0, 0.0, 0.5], [1.0, 0.0, 0.5], 10), None, np.full(10, 0.08))
    behind = sc.curves[-1]
    h.v._changed()
    h.v.set_planes_visible(False)
    h.camera([0.5, 0.5, 0.5], 5, [0.0, 1.0, 0.02])
    mid = h.scr(behind.points[5])
    beside = h.scr(behind.points[5] + np.array([0.0, 0.0, 0.8]))
    lum = lambda img, p: sum(h.pixel(img, p)[:3])
    img = h.grab()
    hidden = abs(lum(img, mid) - lum(img, beside))
    h.v.set_surface_opacity(s.id, 0.5)
    img = h.grab()
    half = lum(img, beside) - lum(img, mid)
    h.v.set_surface_opacity(s.id, 0.0)
    img = h.grab()
    free = lum(img, beside) - lum(img, mid)
    h.v.set_planes_visible(True)
    assert hidden < 40, f"deckend: Linie verdeckt ({hidden})"
    assert 60 < half < free - 60, f"halb durchsichtig: Linie schwächer sichtbar ({half} statt frei {free})"


def test_aufloesung_aendert_netz_nicht_form(h: H):
    """Auflösungs-Regler: Kurvenfläche und Füllfläche bekommen ein feineres bzw. gröberes Netz, die Form bleibt."""
    from sketch_machine.viewport import _dist_to_triangles_fast
    sc = h.sc
    sc.new_stroke()
    t = np.linspace(0, 1, 16)
    sides = [np.stack([t * 4, 0.8 * np.sin(t * np.pi), t * 0], 1), np.stack([np.full_like(t, 4), 0.8 * np.sin(t * np.pi), t * 4], 1),
             np.stack([4 - t * 4, 0.8 * np.sin(t * np.pi), np.full_like(t, 4)], 1), np.stack([t * 0, 0.8 * np.sin(t * np.pi), 4 - t * 4], 1)]
    lines = []
    for sd in sides:
        sc.add_curve(sd, None)
        lines.append(sc.curves[-1])
    patch = sc.create_patch(lines)
    fill_s = _square(h, y=0.0, x0=6.0, size=3.0)
    h.v._changed()
    # gewölbt (eine Umrisslinie angehoben): eine ebene Füllfläche zeigt nur ihren Rand, daran gibt es nichts feiner
    # oder gröber zu stellen
    edge = next(c for c in sc.curves if any(i == c.id for cid, _ in fill_s.links for i in sc.link_ids(cid)))
    bent = edge.points.copy()
    bent[len(bent) // 2] += [0.0, 0.6, 0.0]
    edge.points = bent
    h.v._changed()
    for s in (patch, fill_s):
        v1, t1 = [np.array(x) for x in s.fill_mesh()[:2]]
        h.v.set_surface_resolution(s.id, 4.0)
        h.v._changed()
        v4, t4 = [np.array(x) for x in s.fill_mesh()[:2]]
        h.v.set_surface_resolution(s.id, 0.25)
        h.v._changed()
        vq, tq = [np.array(x) for x in s.fill_mesh()[:2]]
        assert len(t4) > 8 * len(t1) and len(tq) * 4 < len(t1), (s.name, len(tq), len(t1), len(t4))
        size = float(np.linalg.norm(np.ptp(v1, axis=0)))
        probe = v4[np.linspace(0, len(v4) - 1, 300).astype(int)]
        assert _dist_to_triangles_fast(probe, v1[t1]).max() < 0.01 * size, f"{s.name}: fein, Form bleibt"
        h.v.set_surface_resolution(s.id, 1.0)
        h.v._changed()
        assert len(np.array(s.fill_mesh()[1])) == len(t1)
    path = os.path.join(tempfile.mkdtemp(), "res.sketch.json")
    patch.resolution, patch.opacity = 2.0, 0.4
    sc.save(path)
    t = next(x for x in Scene.load(path)[0].surfaces if x.name == patch.name)
    assert (t.resolution, t.opacity) == (2.0, 0.4)


def test_globale_aufloesung_multipliziert_und_kehrt_exakt_zurueck(h: H):
    """Viewport-Qualität (globaler Regler): multipliziert den Regler jeder Fläche; zurückgestellt ist das Netz wieder
    genau das alte – gröber und wieder feiner hinterlässt keine Ecken (die Form wird nie aus dem groben Netz gebaut)."""
    from sketch_machine.scene import SurfaceObject
    sc = h.sc
    sc.new_stroke()
    t = np.linspace(0, 1, 16)
    sides = [np.stack([t * 4, 0.8 * np.sin(t * np.pi), t * 0], 1), np.stack([np.full_like(t, 4), 0.8 * np.sin(t * np.pi), t * 4], 1),
             np.stack([4 - t * 4, 0.8 * np.sin(t * np.pi), np.full_like(t, 4)], 1), np.stack([t * 0, 0.8 * np.sin(t * np.pi), 4 - t * 4], 1)]
    lines = []
    for sd in sides:
        sc.add_curve(sd, None)
        lines.append(sc.curves[-1])
    patch = sc.create_patch(lines)
    fill_s = _square(h, y=0.0, x0=6.0, size=3.0)
    h.v._changed()
    # gewölbt (eine Umrisslinie angehoben): eine ebene Füllfläche zeigt nur ihren Rand, daran gibt es nichts feiner
    # oder gröber zu stellen
    edge = next(c for c in sc.curves if any(i == c.id for cid, _ in fill_s.links for i in sc.link_ids(cid)))
    bent = edge.points.copy()
    bent[len(bent) // 2] += [0.0, 0.6, 0.0]
    edge.points = bent
    h.v._changed()
    before = {s.id: [np.array(x).copy() for x in s.fill_mesh()[:2]] for s in (patch, fill_s)}
    try:
        h.v.set_display_resolution(0.25)
        h.v._changed()
        h.grab()
        for s in (patch, fill_s):
            assert len(np.array(s.fill_mesh()[1])) * 4 < len(before[s.id][1]), f"{s.name}: gröber"
        h.v.set_surface_resolution(patch.id, 4.0)  # eigener Regler × global: 4 × 0,25 = wie vorher
        h.v._changed()
        assert len(np.array(patch.fill_mesh()[1])) == len(before[patch.id][1]), "Regler multiplizieren sich"
        h.v.set_surface_resolution(patch.id, 1.0)
        h.v.set_display_resolution(1.0)
        h.v._changed()
        for s in (patch, fill_s):
            v, tr = [np.array(x) for x in s.fill_mesh()[:2]]
            assert np.array_equal(tr, before[s.id][1]) and np.allclose(v, before[s.id][0]), f"{s.name}: exakt zurück"
    finally:
        SurfaceObject.display_res = 1.0


def test_frei_modus_ueber_flaeche_ohne_absturz(h: H):
    """Frei-Modus: Maus über einer Fläche – der Ansatzpunkt wird beim Bewegen gesucht (nicht beim Zeichnen des Bilds,
    dort brächte das GPU-Picking den GL-Kontext durcheinander); ein Strich setzt auf der Fläche an."""
    from PySide6.QtCore import QPointF
    s = _square(h, y=0.0, x0=-1.0, size=3.0)
    h.camera([0.5, 0, 0.5], 6, [0.2, 1.0, 0.4])
    h.draw_mode()
    h.v.set_free_draw(True)
    try:
        start = h.scrf([0.5, 0.0, 0.5])
        for k in range(5):
            h.move(start + QPointF(k * 3, 0))
            h.pump(0.02)
        assert h.v._free_hover is not None and abs(h.v._free_hover[1]) < 1e-3, "Ansatzpunkt auf der Fläche"
        n = len(h.curves())
        h.stroke([start, start + QPointF(60, -40), start + QPointF(120, -60)])
        assert len(h.curves()) == n + 1, "Frei-Strich entsteht"
        assert np.linalg.norm(h.curves()[-1].points[0] - [0.5, 0.0, 0.5]) < 0.05, "setzt auf der Fläche an"
    finally:
        h.v.set_free_draw(False)


def test_hilfsflaeche_verdeckt_nichts_und_gehoert_zu_den_zeichenhilfen(h: H):
    """Fläche -> Hilfsfläche: Linie dahinter sichtbar, Zeichenhilfen aus blendet sie aus, gespeichert; zurück: deckt."""
    s = _square(h, y=1.0, x0=-1.0, size=3.0)
    sc = h.sc
    sc.add_curve(np.linspace([0.0, 0.0, 0.5], [1.0, 0.0, 0.5], 10), None, np.full(10, 0.08))
    behind = sc.curves[-1]
    h.v._changed()
    h.camera([0.5, 0.5, 0.5], 5, [0.0, 1.0, 0.02])
    mid, beside = h.scr(behind.points[5]), h.scr(behind.points[5] + np.array([0.0, 0.0, 0.8]))
    lum = lambda img, p: sum(h.pixel(img, p)[:3])
    h.v.set_surface_aid(s.id, True)
    img = h.grab()
    assert lum(img, beside) - lum(img, mid) > 60, "Linie hinter der Hilfsfläche ist zu sehen"
    assert any(x is s for x in h.v._visible_surfaces())
    h.v.set_planes_visible(False)
    assert not any(x is s for x in h.v._visible_surfaces()), "Zeichenhilfen aus: Hilfsfläche weg"
    h.v.set_planes_visible(True)
    path = os.path.join(tempfile.mkdtemp(), "aid.sketch.json")
    h.sc.save(path)
    assert Scene.load(path)[0].surfaces[0].aid, "Hilfsfläche bleibt beim Laden"
    h.key(Qt.Key_Z, Qt.ControlModifier)
    assert not h.sc.surfaces[0].aid, "Undo"


def test_flaechen_schalter_oben_rechts(h: H):
    s = _square(h)
    h.v.set_layer_visible("surfaces", False)
    try:
        assert not h.v._visible_surfaces(), "Flächen ausgeblendet"
        h.v.set_surface_aid(s.id, True)
        assert h.v._visible_surfaces(), "Hilfsflächen hängen an den Zeichenhilfen, nicht am Flächen-Schalter"
    finally:
        h.v.set_layer_visible("surfaces", True)
    assert "surfaces" in h.w.layer_checks


def test_outliner_flaechen_optionen_zugeklappt(h: H):
    """Transparenz/Auflösung/Hilfsfläche liegen unter der Fläche, zugeklappt; aufgeklappt bleibt es beim Neuaufbau."""
    s = _square(h)
    o = h.w.outliner
    o.rebuild()
    item = lambda: _find(o, s.id)
    assert item().childCount() == 1 and not item().isExpanded(), "Optionen zugeklappt"
    item().setExpanded(True)
    o.rebuild()
    assert item().isExpanded(), "bleibt aufgeklappt"


def test_hilfsflaeche_steht_bei_den_ebenen(h: H):
    s = _square(h)
    o = h.w.outliner
    planes = lambda: _under(o.planes_root, s.id)
    o.rebuild()
    assert _find(o, s.id) is not None and not planes()
    h.v.set_surface_aid(s.id, True)
    o.rebuild()
    assert planes(), "Hilfsfläche unter Ebenen"
    h.v.set_surface_aid(s.id, False)
    o.rebuild()
    assert _find(o, s.id) is not None and not planes()


def test_flaeche_steht_unter_ihrem_linienobjekt(h: H):
    """Flächen stehen im Outliner unter dem Linienobjekt ihrer Randlinien (weniger Einträge); hängt ihr Rand auch an
    fremden Linienobjekten, zeigt die Info-Spalte ⚠ mit Hinweis."""
    from sketch_machine.outliner import INFO
    s = _square(h)
    o = h.w.outliner
    o.rebuild()
    item = _find(o, s.id)
    parent = item.parent()
    assert parent is not None and isinstance(h.sc.object_by_id(parent.data(0, Qt.UserRole)), StrokeObject), \
        "Fläche hängt unter ihrem Linienobjekt"
    assert item.text(INFO) == ""

"""Kurvennetz (F3): Punkte mit Identität – Einrasten verbindet, Nähe nicht; Kopien sind eigene Punkte; Übernahme."""
import json
import os
import time

import numpy as np

from tests.harness import H, OUT, ROOT, Qt, line
from sketch_machine import components, network
from sketch_machine.clipboard import Clipboard, paste
from sketch_machine.scene import Scene


def _ground(h: H):
    sc = h.sc
    sc.new_stroke()
    sc.add_curve(line([0, 0, 0], [2, 0, 0], 12), sc.planes[0].id)
    h.v._changed()
    h.camera([1, 0, 1], 6, [0, 1, 0.01])
    return sc.curves[-1]


def test_einrasten_am_ende_verbindet(h: H):
    a = _ground(h)
    h.stroke_world([[2, 0, 0], [2, 0, 0.7], [2, 0, 1.5]])
    b = h.curves()[-1]
    assert np.allclose(b.points[0], a.points[-1]), "Strich rastet am Linienende ein"
    assert network.pid_of(a, len(a.points) - 1) == network.pid_of(b, 0), "gemeinsamer Punkt"


def test_naehe_verbindet_nicht(h: H):
    a = _ground(h)
    h.v.ws.magnet = False  # ohne Einrasten: endet knapp daneben
    try:
        h.stroke_world([[2.0005, 0, 0.0005], [2, 0, 0.7], [2, 0, 1.5]])
    finally:
        h.v.ws.magnet = True
    b = h.curves()[-1]
    assert network.pid_of(a, len(a.points) - 1) != network.pid_of(b, 0)


def test_einrasten_mitten_auf_linie_teilt_nicht(h: H):
    a = _ground(h)
    h.stroke_world([[1.0, 0, 0], [1.0, 0, 0.7], [1.0, 0, 1.5]])
    curves = h.curves()
    assert len(curves) == 2, f"{len(curves)} Linien – die Linie bleibt ganz, der neue Strich kommt dazu"
    b = curves[-1]
    a = curves[0]
    ks = components.knots(a)
    mid = [k for k in ks[1:-1] if np.linalg.norm(a.points[k] - b.points[0]) < 1e-6]
    assert mid, "Knoten an der Einrast-Stelle"
    assert network.pid_of(a, mid[0]) == network.pid_of(b, 0), "T-Stoß ist ein gemeinsamer Punkt"
    refs = network.refs_by_pid(h.sc)[network.pid_of(b, 0)]
    assert network.degree(refs) == 3


def test_ecken_beim_zeichnen(h: H):
    h.camera([1, 0, 1], 6, [0, 1, 0.01])
    h.v.ws.magnet = False
    try:
        h.stroke_world([[0, 0, 0], [1, 0, 0], [2, 0, 0], [2, 0, 1], [2, 0, 2]])
    finally:
        h.v.ws.magnet = True
    c = h.curves()[-1]
    ks = components.knots(c)
    assert len(ks) == 3, f"eine Ecke erkannt ({ks})"
    corner = c.points[ks[1]].copy()
    arc = np.concatenate([[0], np.cumsum(np.linalg.norm(np.diff(c.points, axis=0), axis=1))])
    t = np.linspace(0, arc[-1], len(c.points) * 2 + 1)
    c.points = np.stack([np.interp(t, arc, c.points[:, i]) for i in range(3)], axis=1)
    c.widths = np.full(len(c.points), c.widths.mean())
    ks2 = components.knots(c)
    assert len(ks2) == 3 and np.linalg.norm(c.points[ks2[1]] - corner) < 0.05, "Ecke bleibt an ihrer Stelle"


def test_kopie_ist_nicht_mit_dem_original_verbunden(h: H):
    sc = h.sc
    sc.new_stroke()
    sc.add_curve(line([0, 0, 0], [1, 0, 0], 10), None)
    sc.add_curve(line([1, 0, 0], [1, 0, 1], 10), None)
    a, b = sc.curves[-2:]
    network.sync(sc)
    assert network.pid_of(a, len(a.points) - 1) == network.pid_of(b, 0)
    clip = Clipboard()
    clip.copy(sc, [], [("line", sc.owner_of(c).id, c.id) for c in (a, b)])
    paste(sc, clip, "elements")
    network.sync(sc)
    a2, b2 = sc.curves[-2:]
    assert network.pid_of(a2, len(a2.points) - 1) == network.pid_of(b2, 0), "in der Kopie verbunden"
    assert network.pid_of(a2, 0) != network.pid_of(a, 0), "mit dem Original nicht verbunden"
    group = components.ComponentGroup(sc, [(a2, 0)], [])
    group.translate(np.array([0.0, 0.5, 0.0]))
    assert np.allclose(a.points[0], [0, 0, 0]), "Ziehen an der Kopie lässt das Original stehen"


def test_teilen_behaelt_punkte(h: H):
    sc = h.sc
    sc.new_stroke()
    sc.add_curve(line([0, 0, 0], [2, 0, 0], 21), None)
    sc.add_curve(line([2, 0, 0], [2, 0, 1], 10), None)
    a, b = sc.curves[-2:]
    network.sync(sc)
    end_pid = network.pid_of(b, 0)
    sc.split_all_at(np.array([1.0, 0, 0]))
    network.sync(sc)
    first, second = sc.curves[0], sc.curves[1]
    assert network.pid_of(first, len(first.points) - 1) == network.pid_of(second, 0), "Schnitt ist gemeinsamer Punkt"
    assert network.pid_of(second, len(second.points) - 1) == end_pid, "alte Verbindung bleibt"


def test_uebernahme_alter_datei(h: H):
    # ältere Datei nachbauen: dieselbe Szene ohne Punkt-IDs an den Linien
    with open(os.path.join(ROOT, "tests", "scenes", "topologie.sketch.json"), encoding="utf-8") as f:
        raw = json.load(f)

    def strip(o):
        if isinstance(o, dict):
            o.pop("pids", None)
            for v in o.values():
                strip(v)
        elif isinstance(o, list):
            for v in o:
                strip(v)
    strip(raw)
    path = os.path.join(OUT, "net_alt.sketch.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(raw, f)
    scene, data = Scene.load(path)
    rep = scene.net_report
    assert rep["migrated"] and rep["points"] > 0, rep
    out = os.path.join(OUT, "net_rt.sketch.json")
    scene.save(out)
    s2, _ = Scene.load(out)
    rep2 = s2.net_report
    assert not rep2["migrated"] and {k: rep2[k] for k in ("points", "shared", "free_ends")} == \
        {k: rep[k] for k in ("points", "shared", "free_ends")}, (rep, rep2)
    h.v.set_scene(s2)
    t0 = time.perf_counter()
    for _ in range(20):
        network.sync(s2)
    dt = (time.perf_counter() - t0) / 20
    assert dt < 0.01, f"Abgleich ohne Änderung {dt * 1000:.1f} ms"
    return f"{rep['points']} Punkte, {rep['shared']} verbunden, {rep['free_ends']} offene Enden"


def test_verbindungsanzeige(h: H):
    a = _ground(h)
    h.stroke_world([[2, 0, 0], [2, 0, 0.7], [2, 0, 1.5]])
    h.edit_mode("point")
    shared, free, plain = h.v._net_marks()
    assert len(shared) == 1 and len(free) == 2, (len(shared), len(free), len(plain))
    h.save_image("netz_punkte.png")


def test_loop_bis_zum_t_stoss_und_fuellen(h: H):
    """Rechteck mit Mittellinie (T-Stöße oben und unten): Doppelklick auf die linke Seite wählt die linke Hälfte –
    bis zu den gemeinsamen Punkten; F füllt genau sie (erst dabei werden die Linien geteilt)."""
    sc = h.sc
    h.camera([1, 0, 1], 6, [0, 1, 0.01])
    for a, b in (([0, 0, 0], [2, 0, 0]), ([2, 0, 0], [2, 0, 2]), ([2, 0, 2], [0, 0, 2]), ([0, 0, 2], [0, 0, 0])):
        h.stroke_world([a, (np.array(a) + np.array(b)) / 2, b])
    h.stroke_world([[1, 0, 0], [1, 0, 1], [1, 0, 2]])
    assert len(h.curves()) == 5, "Mittellinie teilt die Rechteckseiten nicht"
    h.edit_mode("edge")
    h.v.select_loop(h.scrf([0, 0, 1.0]), "replace")
    assert len(h.v.edge_selection) == 2 and len(h.v.seg_selection) == 2, (h.v.edge_selection, h.v.seg_selection)
    h.key(Qt.Key_F)
    verts = sc.surfaces[-1].fill_mesh()[0]
    assert np.allclose(verts.max(axis=0), [1, 0, 2], atol=1e-3) and np.allclose(verts.min(axis=0), [0, 0, 0], atol=1e-3)


def _patch_square(h: H):
    """Kurvenfläche aus vier leicht gewölbten Randlinien auf dem Boden (wie Test des Artists: Umriss -> Fläche)."""
    sc = h.sc
    sc.new_stroke()
    t = np.linspace(0, 1, 16)
    sides = [np.stack([t * 4, 0.3 * np.sin(t * np.pi), t * 0], 1), np.stack([np.full_like(t, 4), 0.3 * np.sin(t * np.pi), t * 4], 1),
             np.stack([4 - t * 4, 0.3 * np.sin(t * np.pi), np.full_like(t, 4)], 1), np.stack([t * 0, 0.3 * np.sin(t * np.pi), 4 - t * 4], 1)]
    lines = []
    for s in sides:
        sc.add_curve(s, None)
        lines.append(sc.curves[-1])
    ps = sc.create_patch(lines)
    sc.sync_lofts()
    h.v._changed()
    h.camera([2, 0.2, 2], 9, [0.05, 1, 0.05])
    h.v._activate(ps)
    return ps, lines


def test_strich_ueber_den_flaechenrand_endet_auf_der_randlinie(h: H):
    ps, lines = _patch_square(h)
    h.stroke_world([[2.0, 0.3, 2.0], [3.0, 0.3, 2.0], [3.8, 0.3, 2.0], [4.6, 0.0, 2.0], [5.2, 0.0, 2.0]])
    c = h.curves()[-1]
    assert c.plane_id == ps.id
    right = lines[1]
    assert network.pid_of(c, len(c.points) - 1) in set(right.pids.values()), "Ende ist ein gemeinsamer Punkt der Randlinie"
    assert len([x for x in h.curves() if not x.paint]) == 5, "Randlinie bleibt ein Strich"


def test_kreuzung_auf_derselben_ebene_wird_punkt(h: H):
    h.camera([1, 0, 1], 6, [0, 1, 0.01])
    h.v.ws.magnet = False
    try:
        h.stroke_world([[0, 0, 1], [1, 0, 1], [2, 0, 1]])
        h.stroke_world([[1, 0, 0], [1, 0, 1], [1, 0, 2]])
    finally:
        h.v.ws.magnet = True
    a, b = h.curves()
    shared = set(a.pids.values()) & set(b.pids.values())
    assert len(shared) == 1, "eine gemeinsame Kreuzung"
    refs = network.refs_by_pid(h.sc)[shared.pop()]
    assert network.degree(refs) == 4 and len(h.curves()) == 2


def test_nur_scheinbare_kreuzung_bleibt_getrennt(h: H):
    sc = h.sc
    sc.new_stroke()
    sc.add_curve(line([0, 0, 1], [2, 0, 1], 20), sc.planes[0].id)
    h.v._changed()
    h.camera([1, 0, 1], 6, [0, 1, 0.01])
    other = sc.custom[0] if sc.custom else None
    lifted = np.array([[1, 1.0, 0], [1, 1.0, 2]])  # 1 über dem Boden: von oben gesehen kreuzt sie
    sc.add_curve(np.linspace(lifted[0], lifted[1], 20), sc.planes[0].id)
    h.v._connect_new_crossings([sc.curves[-1]])
    a, b = sc.curves[-2:]
    network.sync(sc)
    assert not set(a.pids.values()) & set(b.pids.values())


def test_cleanup_kreuzungen_zwischen_flaechen(h: H):
    sc = h.sc
    sc.new_stroke()
    sc.add_curve(line([0, 0, 1], [2, 0, 1], 20), sc.planes[0].id)  # auf dem Boden
    sc.add_curve(line([1, -1, 1], [1, 1, 1], 20), sc.planes[2].id)  # senkrecht, durch den Boden
    h.v._changed()
    h.v.set_cleanup_global(True)
    try:
        h.v.run_cleanup("crossings")
    finally:
        h.v.set_cleanup_global(False)
    a, b = sc.curves[-2:]
    assert set(a.pids.values()) & set(b.pids.values()), "Kreuzung im Raum verbunden"


def test_verschweissen_verbindet_aufeinanderliegende_enden(h: H):
    sc = h.sc
    sc.new_stroke()
    sc.add_curve(line([0, 0, 0], [1, 0, 0], 10), None)
    network.sync(sc)
    sc.add_curve(line([1, 0, 0], [1, 0, 1], 10), None)
    b = sc.curves[-1]
    b.pids = {0: network.new_pid(), len(b.points) - 1: network.new_pid()}  # eigener Punkt, liegt aber genau drauf
    a = sc.curves[0]
    network.sync(sc)
    assert network.pid_of(a, len(a.points) - 1) != network.pid_of(b, 0)
    h.camera([0.5, 0, 0.5], 4, [0, 1, 0.01])
    h.v.set_cleanup_global(True)
    try:
        h.v.run_cleanup("weld")
    finally:
        h.v.set_cleanup_global(False)
    assert network.pid_of(a, len(a.points) - 1) == network.pid_of(b, 0), "verschweißt = verbunden"


def test_v_einrasten_verbindet(h: H):
    sc = h.sc
    sc.new_stroke()
    sc.add_curve(line([0, 0, 0], [1, 0, 0], 10), None)
    sc.add_curve(line([1.0, 0, 0.5], [1, 0, 1], 10), None)
    a, b = sc.curves[-2:]
    network.sync(sc)
    b.translate(np.array([0.0, 0.0, -0.5]))  # wie ein V-Zug: Ende genau aufs andere Ende
    h.v._connect_at(a.points[-1])
    assert network.pid_of(a, len(a.points) - 1) == network.pid_of(b, 0)
    c = sc.curves[0]
    sc.add_curve(line([0.5, 0, 0.6], [0.5, 0, 1.5], 10), None)
    d = sc.curves[-1]
    d.translate(np.array([0.0, 0.0, -0.6]))  # auf die Linienmitte
    h.v._connect_at(d.points[0])
    assert network.pid_of(d, 0) in set(c.pids.values()), "Linienmitte bekommt einen gemeinsamen Punkt"


def test_kreuzung_auf_fuellflaeche_bleibt_ein_punkt(h: H):
    """Szene des Artists (new_topology_v002): zweiter Strich über eine Füllfläche, kreuzt den ersten und läuft über den
    Rand hinaus. Die Außenlinie bekommt dabei neue Punkte, die Fläche folgt ihr – die Kreuzung muss trotzdem ein
    gemeinsamer Punkt bleiben, und das Zeichnen darf keine Fehler im Bild werfen (bunte Kästchen)."""
    h.load("tests/scenes/netz_fuellflaeche_kreuz.sketch.json")
    sc = h.sc
    surf = sc.surfaces[0]
    h.v._activate(surf)
    a, b = np.array([0.12, 0, -9.19]), np.array([2.54, 0, 2.95])
    d = (b - a) / np.linalg.norm(b - a)
    h.stroke_frames([h.scrf(p) for p in [a + t * (b - a) for t in np.linspace(0.02, 0.98, 30)] + [b + d * 0.6]])
    new = h.curves()[-1]
    first = next(c for c in h.curves() if c.plane_id == surf.id and c is not new)
    assert set(first.pids.values()) & set(new.pids.values()), "Kreuzung ist ein gemeinsamer Punkt"
    assert len(new.widths) == len(new.points) and len(first.widths) == len(first.points)
    h.edit_mode("point")
    h.save_image("netz_fuellflaeche_kreuz.png")


def test_flaeche_kopieren_als_teilgraph(h: H):
    """Nur die Fläche kopieren (Flächenmodus) und einfügen: die Kopie nimmt ihr Netz mit – Randlinien und eine Linie
    darauf –, ist intern verbunden wie das Original, mit dem Original aber nicht; Material und Färbung kommen mit.
    Verschoben bewegt sich die ganze Kopie, das Original bleibt."""
    from sketch_machine import loft
    sc = h.sc
    ps, lines = _patch_square(h)
    h.stroke_world([[-0.5, 0.3, 2.0], [2.0, 0.3, 2.0], [4.5, 0.3, 2.0]])  # echte Linie quer über die Fläche
    across = h.curves()[-1]
    assert across.plane_id == ps.id
    ps.material, ps.tint = "holz", (0.8, 0.3, 0.2)
    n_lines = len(h.curves())
    before = {c.id: c.points.copy() for c in h.curves()}
    h.edit_mode("face")
    h.v.selection = [ps.id]
    h.v.edge_selection = []
    h.v.copy_selection()
    h.v.paste()
    copy_s = sc.surfaces[-1]
    assert copy_s is not ps and type(copy_s) is type(ps), "Kopie ist wieder eine Kurvenfläche"
    assert len(h.curves()) == n_lines + 5, f"{len(h.curves()) - n_lines} neue Linien statt 5 (Rand + Linie darauf)"
    assert copy_s.material == "holz" and copy_s.tint == ps.tint, "Material und Färbung mitkopiert"
    border = sc.patch_border(copy_s)
    assert len(border) == 4 and not any(any(c is x for x in lines) for c in border), "Rand der Kopie = kopierte Linien"
    new_across = [c for c in h.curves() if c.plane_id == copy_s.id]
    assert len(new_across) == 1, "Linie auf der Fläche gehört zur Kopie"
    network.sync(sc)
    old_pids = {p for c in lines + [across] for p in (c.pids or {}).values()}
    new_pids = {p for c in border + new_across for p in (c.pids or {}).values()}
    assert not old_pids & new_pids, "mit dem Original nicht verbunden"
    ends = {network.pid_of(new_across[0], 0), network.pid_of(new_across[0], len(new_across[0].points) - 1)}
    assert ends <= {p for c in border for p in (c.pids or {}).values()}, "intern verbunden wie das Original"
    target = h.v.transform_target
    target.translate(np.array([6.0, 0, 0]))
    h.v._changed()
    for cid, pts0 in before.items():
        assert np.allclose(sc.curve_by_id(cid).points, pts0), "Original bleibt"
    v = copy_s.fill_mesh()[0]
    assert v[:, 0].min() > 5.9, "Kopie ist ganz mitgewandert"


def test_fuellflaeche_und_roehre_kopieren_als_teilgraph(h: H):
    """Füllfläche (L-Form) und Röhre allein kopiert: Umriss bzw. Querschnitte und Seitenlinien kommen mit, die Kopie
    folgt ihren eigenen Linien (nicht dem Original)."""
    from sketch_machine.scene import LoftSurface, SurfaceObject
    sc = h.sc
    sc.new_stroke()
    poly = [[0, 0], [4, 0], [4, 1.5], [1.5, 1.5], [1.5, 4], [0, 4]]
    pts = [np.array([x, 0.0, z]) for x, z in poly]
    outline = []
    for i in range(len(pts)):
        sc.add_curve(np.linspace(pts[i], pts[(i + 1) % len(pts)], 20), None)
        outline.append(sc.curves[-1])
    fill_s = sc.create_fill([(c, False) for c in outline])
    t = np.linspace(0, 2 * np.pi, 33)
    rings = []
    for y in (0.0, 2.0, 3.0):
        sc.add_curve(np.stack([8 + np.cos(t), np.full_like(t, y), np.sin(t)], 1), None)
        rings.append(sc.curves[-1])
    tube = sc.create_loft([("lines", [c.id]) for c in rings], [c.points for c in rings])
    sc.add_loft_rails(tube, np.array([0.3, 0.4, 1.0]))
    sc.sync_lofts()
    h.v._changed()
    for s, kind, n in ((fill_s, SurfaceObject, len(outline)), (tube, LoftSurface, len(rings) + len(tube.rails))):
        before = len(h.curves())
        mesh0 = s.fill_mesh()[0].copy()
        h.edit_mode("face")
        h.v.selection = [s.id]
        h.v.edge_selection = []
        h.v.copy_selection()
        h.v.paste()
        c = sc.surfaces[-1]
        assert type(c) is kind and c is not s
        assert len(h.curves()) == before + n, f"{s.name}: {len(h.curves()) - before} neue Linien statt {n}"
        h.v.transform_target.translate(np.array([0, 0, 10.0]))
        h.v._changed()
        assert c.fill_mesh()[0][:, 2].min() > mesh0[:, 2].min() + 9.9, f"{s.name}: Kopie folgt ihren Linien"
        assert np.allclose(s.fill_mesh()[0], mesh0), f"{s.name}: Original bleibt"


def test_eingefuegter_punkt_auf_randlinie_ist_verbunden(h: H):
    """Strg+Klick auf eine Randlinie: der neue Punkt liegt mitten auf der Linie und wird als verbunden (gefüllt)
    angezeigt, nicht als offener oder heller Punkt."""
    ps, lines = _patch_square(h)
    h.edit_mode("point")
    before = len(h.v._net_marks()[0])
    p = lines[0].points[len(lines[0].points) // 3]
    h.click(h.scr(p), Qt.ControlModifier)
    shared, free, plain = h.v._net_marks()
    assert len(shared) == before + 1 and not plain, (before, len(shared), len(plain))
    assert min(np.linalg.norm(np.array(shared) - p, axis=1)) < 0.05, "der neue Punkt ist gefüllt"


def test_ganze_linie_ziehen_verbunden_nur_ueber_punkt_id(h: H):
    """Ganze Linie mit dem Gizmo ziehen: eine Linie, die mit ihrem Ende verbunden ist (gleiche Punkt-ID), geht mit; eine,
    deren Ende nur zufällig an derselben Stelle liegt, bleibt (verbunden ist, was sich einen Punkt teilt – nie die Lage)."""
    from sketch_machine import edges
    sc = h.sc
    for joined in (True, False):
        h.new_scene()
        sc = h.sc
        sc.new_stroke()
        sc.add_curve(line([0, 0, 0], [2, 0, 0], 21), None)
        sc.add_curve(line([2, 0, 0], [2, 0, 2], 21), None)
        a, b = sc.curves[-2:]
        network.sync(sc)
        if joined:
            network.join(sc, a, len(a.points) - 1, b, 0)
        else:
            b.pids = dict(b.pids)
            b.pids[0] = network.new_pid()
        network.sync(sc)
        assert (network.pid_of(a, len(a.points) - 1) == network.pid_of(b, 0)) == joined
        before = b.points.copy()
        edges.handles_for(sc, [edges.curve_to_ref(sc, a)])[0].translate(np.array([0.0, 1.0, 0.0]))
        moved = float(np.linalg.norm(b.points[0] - before[0]))
        if joined:
            assert moved > 0.99 and np.allclose(b.points[-1], before[-1]), "verbundene Linie geht mit (weich, Ende bleibt)"
        else:
            assert moved == 0.0, "nur aufeinanderliegend: bleibt stehen"


def test_abgleich_merkt_jede_aenderung_trotz_schnellweg(h: H):
    """network.sync antwortet ohne Änderung aus dem Zähler (Schnellweg) – Punkte verschieben, Linie weg, Linie
    wieder dazu: jedes Mal wird wirklich neu abgeglichen."""
    sc = h.sc
    a = _ground(h)
    sc.add_curve(line([2, 0, 0], [2, 2, 0], 12), sc.planes[0].id)
    b = sc.curves[-1]
    network.sync(sc)
    state = sc._net_sync
    assert network.sync(sc) is state[1] and sc._net_sync is state, "ohne Änderung: derselbe Stand"
    assert network.pid_of(a, len(a.points) - 1) == network.pid_of(b, 0), "Ende an Anfang: ein Punkt"
    pts = b.points.copy()
    pts[0] += [0.5, 0, 0]
    b.points = pts
    network.sync(sc)
    assert sc._net_sync is not state, "verschobene Linie: neu abgeglichen"
    assert network.pid_of(a, len(a.points) - 1) != network.pid_of(b, 0), "auseinander: zwei Punkte"
    state = sc._net_sync
    owner = sc.owner_of(b)
    owner.curves.remove(b)
    assert network.sync(sc)["points"] != state[1]["points"], "Linie weg: neu gezählt"
    owner.curves.append(b)
    sc.strokes[:] = list(sc.strokes)  # gleiche Liste, gleicher Inhalt: darf aus dem Schnellweg kommen
    stats = network.sync(sc)
    assert stats["points"] == state[1]["points"], "Linie wieder da: dieselbe Zählung wie vorher"


def test_strich_durch_zwei_fast_gleiche_punkte_verbindet_beide(h: H):
    """Zufallsfolge 3: Zwei Linien haben fast am selben Ort je einen eigenen Punkt, ein neuer Strich kreuzt beide. Sein
    einer Punkt verbindet alle drei – vorher riss die zweite Verbindung die erste wieder ab."""
    sc = h.sc
    sc.new_stroke()
    sc.add_curve(line([0, 0, 0], [4, 0, 0], 41), None)
    sc.add_curve(line([2.001, 0, -1], [2.001, 0, 1], 21), None)
    sc.add_curve(line([1, 0, -1], [3, 0, 1], 41), None)
    first, second, stroke = sc.curves[-3:]
    a, b = network.knot_at(first, [2.0, 0, 0]), network.knot_at(second, [2.001, 0, -0.001])
    network.sync(sc)
    tol = 0.0125
    network.connect_crossings(sc, stroke, [second], tol, 0.2)
    network.connect_crossings(sc, stroke, [first], tol, 0.2)
    network.sync(sc)
    a = min(components.knots(first), key=lambda k: np.linalg.norm(first.points[k] - [2.0, 0, 0]))
    b = min(components.knots(second), key=lambda k: np.linalg.norm(second.points[k] - [2.001, 0, 0]))
    shared = set(stroke.pids.values())
    assert network.pid_of(first, a) in shared and network.pid_of(second, b) in shared, "alle drei am selben Punkt"
    assert network.pid_of(first, a) == network.pid_of(second, b)
    assert np.allclose(first.points[a], second.points[b]), "gleicher Punkt: gleiche Lage"

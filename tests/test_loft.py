"""Lofts (Shift+F) als Kurvenfläche: Robustheit der Form und des Gitters (Feedback loft_test).

Ein offener Loft wird eine Kurvenfläche (Rand: erster Querschnitt, Seitenlinie, letzter Querschnitt, Seitenlinie);
die mittleren Querschnitte sind Linien darauf. Erwartet wird die Form eines Lofts: quer zu den Querschnitten glatte
Kurven durch alle Querschnitte (überblendete Kreisbögen), kein Zelt zwischen ihnen – auch nach dem Bearbeiten.
"""
import numpy as np

from tests.harness import H
from sketch_machine import components, loft, network
from sketch_machine.scene import PatchSurface


def _arc(center, rx, ry, z, n=40, flat=False, a0=0.0, a1=np.pi):
    """Bogen in der Ebene z (stehend) bzw. auf dem Boden (flat: in XZ, Scheitel in +z)."""
    t = np.linspace(a0, a1, n)
    cx, cy = center
    if flat:
        return np.stack([cx + rx * np.cos(t), np.zeros(n), z + ry * np.sin(t)], axis=1)
    return np.stack([cx + rx * np.cos(t), cy + ry * np.sin(t), np.full(n, z)], axis=1)


def _make_loft(h: H, sections):
    """Querschnitte als Linien zeichnen und wie der Artist loften (Shift+F im Kantenmodus, in dieser Reihenfolge)."""
    sc = h.sc
    sc.new_stroke()
    lines = []
    for pts in sections:
        sc.add_curve(np.asarray(pts, float), None)
        lines.append(sc.curves[-1])
    h.v._changed()
    network.sync(sc)
    st = sc.owner_of(lines[0]).id
    h.v.set_select_mode(True)
    h.v.ws.component = "edge"
    h.v.edge_selection = [("line", st, c.id) for c in lines]
    h.v._pick_rank = {c.id: k for k, c in enumerate(lines)}
    h.v._track_pick_order = lambda: None
    h.v.do_loft()
    del h.v._track_pick_order
    surf = sc.surfaces[-1]
    assert isinstance(surf, PatchSurface), f"offener Loft ist {type(surf).__name__}, keine Kurvenfläche"
    sc.sync_lofts()
    return surf, [sc.curve_by_id(c.id) for c in lines]


def _net_row(surf, k=0):
    """Gitterreihe der k-ten Quer-Netzlinie (z. B. mittlerer Querschnitt)."""
    return surf.net["u"][k][1]


def _row_hard(surf, k=1):
    """Härte entlang der k-ten Quer-Netzlinie (0: Rand unten)."""
    return surf._net_geo["hard_u"][k]


def _size(g):
    return float(np.linalg.norm(np.ptp(np.asarray(g).reshape(-1, 3), axis=0)))


def _seg_dist(p, a, b):
    ab = b - a
    t = np.clip(np.einsum("ij,ij->i", p - a, ab) / np.maximum(np.einsum("ij,ij->i", ab, ab), 1e-18), 0, 1)
    return np.linalg.norm(a + ab * t[:, None] - p, axis=1)


def _dist_to_mesh(pts, verts, tris):
    """Abstand jedes Punkts zum Dreiecksnetz (genau: Fläche innen, sonst nächste Kante)."""
    a, b, c = verts[tris[:, 0]], verts[tris[:, 1]], verts[tris[:, 2]]
    n = np.cross(b - a, c - a)
    nn = np.maximum(np.einsum("ij,ij->i", n, n), 1e-18)
    out = []
    for p in np.asarray(pts, float):
        dot = np.einsum("ij,ij->i", p - a, n)
        q = p - n * (dot / nn)[:, None]
        w0 = np.einsum("ij,ij->i", np.cross(c - b, q - b), n) / nn
        w1 = np.einsum("ij,ij->i", np.cross(a - c, q - c), n) / nn
        inside = (w0 >= 0) & (w1 >= 0) & (1 - w0 - w1 >= 0)
        d = np.where(inside, np.abs(dot) / np.sqrt(nn), np.inf)
        pp = np.broadcast_to(p, a.shape)
        d = np.minimum(d, np.minimum(_seg_dist(pp, a, b), np.minimum(_seg_dist(pp, b, c), _seg_dist(pp, c, a))))
        out.append(float(d.min()))
    return np.array(out)


def _ideal(lines):
    """So sähe der Loft aus: glatte Kurven durch die (jetzigen) Querschnitte."""
    secs, _ = loft.prepare([c.points for c in lines])
    return loft.grid(secs)


def _deviation(surf, ideal, inner=0.15):
    """Größter Abstand der Fläche von der idealen Loft-Form (ohne die Randstreifen an den Seitenlinien)."""
    m = ideal.shape[1]
    lo, hi = int(m * inner), int(m * (1 - inner))
    verts, tris = surf.fill_mesh()[:2]
    pts = ideal[:, lo:hi + 1:3].reshape(-1, 3)
    return float(_dist_to_mesh(pts, verts, tris).max()) / _size(ideal)


UNEVEN = [_arc((0, 0), 1.0, 1.0, 0.0), _arc((0.4, 0), 2.2, 2.8, 1.4, n=55), _arc((0, 0), 1.2, 0.8, 4.0, n=31)]
FELIX = [_arc((0, 0), 4.0, 3.0, 0.0, flat=True), _arc((0, 0), 4.0, 5.0, 4.0), _arc((0, 0), 4.0, 3.0, 8.0, flat=True)]


def test_loft_form_glatt_durch_ungleiche_boegen(h: H):
    """Drei ungleiche Bögen (Größe, Punktzahl, Abstand): die Fläche schwingt rund durch alle drei wie ein Loft."""
    surf, lines = _make_loft(h, UNEVEN)
    dev = _deviation(surf, _ideal(lines))
    assert dev < 0.01, f"Fläche weicht {dev:.1%} von der Loft-Form ab (Zelt statt Rundung?)"


def test_loft_form_flache_enden_hoher_mittelbogen(h: H):
    """Wie Kurvenfläche 4 des Artists: erster und letzter Bogen liegen auf dem Boden, der mittlere steht hoch – seitlich
    gesehen ein runder Bogen, keine Pyramide."""
    surf, lines = _make_loft(h, FELIX)
    dev = _deviation(surf, _ideal(lines))
    assert dev < 0.01, f"Fläche weicht {dev:.1%} von der Loft-Form ab (Zelt statt Rundung?)"


def test_loft_gitter_folgt_den_querschnitten(h: H):
    """Topologie: der mittlere Querschnitt liegt auf einer Gitterreihe, deren Enden genau auf den Punkten der
    Seitenlinien sitzen; die Gitterreihen kreuzen ihn nicht schräg."""
    surf, lines = _make_loft(h, UNEVEN)
    g = surf.grid()
    att = surf.attached[lines[1].id]
    rows = np.asarray(att["uv"])[:, 0]
    assert np.ptp(rows) < 0.05, f"mittlerer Querschnitt läuft schräg durchs Gitter (Reihen {rows.min():.2f} … {rows.max():.2f})"
    row = int(round(rows.mean()))
    ends = lines[1].points[[0, -1]]
    corner = np.array([g[row, 0], g[row, -1]])
    gap = min(np.linalg.norm(corner - ends, axis=1).max(), np.linalg.norm(corner - ends[::-1], axis=1).max())
    assert gap < 1e-3 * _size(g), f"Gitterreihe endet {gap:.4f} neben den Punkten der Seitenlinien"


def test_loft_mittelbogen_anheben_bleibt_loft(h: H):
    """Mittleren Bogen als Kante anheben: die Seitenlinien gehen an ihren Punkten mit, die Fläche bleibt an
    Bogen und Seitenlinien und schwingt weiter rund (kein Zelt, keine Lücke zur Außenlinie)."""
    surf, lines = _make_loft(h, FELIX)
    sc = h.sc
    mid = lines[1]
    sc.checkpoint()
    components.ComponentGroup(sc, [], [(mid, 0, len(mid.points) - 1)]).translate(np.array([0.0, 3.0, 0.0]))
    sc.sync_lofts()
    rails = [c for c in sc.patch_border(surf) if c.id not in (lines[0].id, lines[2].id)]
    assert len(rails) == 2
    for r in rails:
        knot = network.knot_at(r, mid.points[0]) if np.linalg.norm(r.points - mid.points[0], axis=1).min() < 1e-6 \
            else network.knot_at(r, mid.points[-1])
        assert np.linalg.norm(r.points[knot] - mid.points[[0, -1]], axis=1).min() < 1e-6, "Seitenlinie geht mit"
    verts, tris = surf.fill_mesh()[:2]
    size = _size(verts)
    for c in [mid] + rails:
        d = _dist_to_mesh(c.points, verts, tris).max()
        assert d < 0.005 * size, f"Fläche löst sich von Linie {c.id} ({d / size:.2%})"
    # rund bleiben: kein Knick am (weichen) Querschnitt quer zu ihm – die Fläche geht durch Querschnitte und die
    # weich mitgezogenen Seitenlinien (der Unterschied zum reinen Loft verteilt sich glatt über die Breite)
    # (verglichen mit dem reinen Loft durch die Querschnitte bei gleicher Einteilung: eine enge Rundung ist kein Zelt)
    g = surf.grid()
    rows = [0, _net_row(surf), g.shape[0] - 1]
    secs, _ = loft.prepare([c.points for c in lines])
    ref = loft.interp_rows(secs, rows)
    row = rows[1]
    for f in (0.25, 0.5, 0.75):
        col, cr = int(round(f * (g.shape[1] - 1))), int(round(f * (ref.shape[1] - 1)))
        k = components.kink_deg(g[row::-1, col], g[row:, col])
        k_ref = components.kink_deg(ref[row::-1, cr], ref[row:, cr])
        assert k < k_ref + 8, f"Zelt am Querschnitt: {k:.0f}° Knick, Loft {k_ref:.0f}° (Spalte {col})"


def test_loft_punkt_einfuegen_und_gleiten_aendert_nichts(h: H):
    """Punkt auf dem mittleren Bogen einfügen und gleiten lassen (S): die Linie behält ihre Form – die Fläche auch."""
    surf, lines = _make_loft(h, UNEVEN)
    sc = h.sc
    mid = lines[1]
    before = surf.grid().copy()
    k = components.insert_point(mid, len(mid.points) // 2, 0.5)
    sc.sync_lofts()
    after_insert = surf.grid()
    d = float(np.abs(after_insert - before).max()) / _size(before)
    assert d < 1e-3, f"Punkt einfügen verändert die Fläche ({d:.2%})"
    st = sc.owner_of(mid).id
    h.v.point_selection = [("pt", st, mid.id, k)]
    h.frame(before.reshape(-1, 3))
    start = h.scrf(mid.points[k])
    h.v._begin_slide(start)
    for dx in (6, 14, 25, 40, 25, -10, -30):
        h.v._slide_update(type(start)(start.x() + dx, start.y()))
        sc.sync_lofts()
        g = surf.grid()
        d = float(np.abs(g - before).max()) / _size(before)
        assert d < 2e-3, f"Gleiten um {dx} px verschiebt die Fläche um {d:.2%}"
    h.v.finish_slide(True)


def test_loft_punkt_ziehen_formt_weich(h: H):
    """Eingefügten Punkt auf dem mittleren Bogen ziehen: die Fläche folgt dem Bogen, das Gitter faltet nicht."""
    surf, lines = _make_loft(h, UNEVEN)
    sc = h.sc
    mid = lines[1]
    k = components.insert_point(mid, len(mid.points) // 3, 0.5)
    sc.sync_lofts()
    components.ComponentGroup(sc, [(mid, k)], []).translate(np.array([0.0, 0.8, 0.3]))
    sc.sync_lofts()
    verts, tris = surf.fill_mesh()[:2]
    size = _size(verts)
    d = _dist_to_mesh(mid.points, verts, tris).max()
    assert d < 0.005 * size, f"Fläche liegt {d / size:.2%} neben dem gezogenen Bogen"
    g = surf.grid()
    for axis in (0, 1):  # benachbarte Zellkanten zeigen nie gegeneinander (keine Falte)
        e = np.diff(g, axis=axis)
        dots = np.einsum("...i,...i->...", e[:-1] if axis == 0 else e[:, :-1], e[1:] if axis == 0 else e[:, 1:])
        assert dots.min() > 0, f"Gitter faltet (Richtung {axis})"


def test_loft_speichern_laden_bleibt_loft(h: H):
    """Speichern und Laden: die Kurvenfläche weiß weiter, dass sie ein Loft ist (gleiche Form, Querschnitte formen sie)."""
    import os, tempfile
    from sketch_machine.scene import Scene
    surf, lines = _make_loft(h, UNEVEN)
    g = surf.grid().copy()
    path = os.path.join(tempfile.mkdtemp(), "loft.sketch.json")
    h.sc.save(path)
    new = Scene.load(path)[0]
    new.sync_lofts()
    s2 = next(s for s in new.surfaces if isinstance(s, PatchSurface))
    assert s2.net and len(s2.net["u"]) == 1, "Querschnitt nach dem Laden bekannt"
    d = float(np.abs(s2.grid() - g).max()) / _size(g)
    assert d < 1e-3, f"Form nach dem Laden anders ({d:.2%})"


def test_loft_alte_szene_wird_wiedererkannt(h: H):
    """loft_test des Artists (gespeichert vor v0.99.4, ohne loft_rows): die Lofts werden beim Laden wiedererkannt und schwingen rund
    durch ihren mittleren Bogen. (Ihre Seitenlinien sind gespeicherte Linien – mit der damaligen Loft-Form; die Fläche
    folgt ihnen, daher hier kein Vergleich mit einer neu gerechneten Loft-Form.)"""
    import os
    path = os.path.join(os.path.dirname(__file__), "scenes", "loft_alt.sketch.json")
    h.load(path)
    sc = h.sc
    sc.sync_lofts()
    lofts = [s for s in sc.surfaces if isinstance(s, PatchSurface) and s.net and s.net["u"]]
    assert len(lofts) == 4, f"{len(lofts)} von 4 Lofts wiedererkannt"
    for s in lofts:
        verts, tris = s.fill_mesh()[:2]
        size = _size(verts)
        mids = [sc._chain_points([i for cid in ids for i in sc.split_pieces(cid)]) for ids, _ in s.net["u"]]
        for c in mids + [b.points for b in sc.patch_border(s)]:
            d = _dist_to_mesh(c, verts, tris).max() / size
            assert d < 0.005, f"{s.name}: {d:.1%} neben einer ihrer Linien"
        g = s.grid()
        row = _net_row(s)
        bend = max(components.kink_deg(g[row::-1, c], g[row:, c]) for c in range(2, g.shape[1] - 2, 4))
        # die gespeicherten Seitenlinien haben noch die Catmull-Rom-Form (vor v0.99.14): mit dem Kreisbogen-Loft
        # gemischt bleibt am Bogen ein leichter Knick (bis ~15°); frisch angelegte Lofts: siehe unten (< 5°)
        assert bend < 20, f"{s.name}: knickt am mittleren Bogen ({bend:.0f}°) statt rund hindurch"


def test_loft_frisch_rund_durch_den_mittleren_bogen(h: H):
    """Frisch angelegter Loft (Profile des Artists: flach, hoch, flach): die Fläche läuft ohne Knick durch den mittleren
    Querschnitt (Kreisbögen überblendet; mit Catmull-Rom waren es ~19°)."""
    for sections in (FELIX, UNEVEN):
        h.new_scene()
        surf, _ = _make_loft(h, sections)
        g = surf.grid()
        row = _net_row(surf)
        bend = max(components.kink_deg(g[row::-1, c], g[row:, c]) for c in range(2, g.shape[1] - 2, 4))
        assert bend < 5, f"knickt am mittleren Querschnitt ({bend:.1f}°)"


def test_loft_querschnitt_loeschen(h: H):
    """Mittleren Querschnitt löschen: die Fläche verliert ihn und liegt weiter an allen übrigen Linien (Rand), nichts
    bricht."""
    from tests.test_topology import _delete_lines
    surf, lines = _make_loft(h, UNEVEN)
    _delete_lines(h, [lines[1]])
    assert surf in h.sc.surfaces and surf.net is not None and not surf.net["u"]
    g = surf.grid()
    assert np.isfinite(g).all()
    verts, tris = surf.fill_mesh()[:2]
    size = _size(verts)
    for c in h.sc.patch_border(surf):
        d = _dist_to_mesh(c.points, verts, tris).max()
        assert d < 0.005 * size, f"Fläche löst sich von Randlinie {c.id} ({d / size:.2%})"


def test_loft_anheben_rueckgaengig(h: H):
    """Anheben und rückgängig: dieselbe Form wie vorher."""
    surf, lines = _make_loft(h, FELIX)
    sc = h.sc
    before = surf.grid().copy()
    sc.checkpoint()
    components.ComponentGroup(sc, [], [(lines[1], 0, len(lines[1].points) - 1)]).translate(np.array([0.0, 2.0, 1.0]))
    sc.sync_lofts()
    sc.undo()
    sc.sync_lofts()
    s = next(x for x in sc.surfaces if x.id == surf.id)
    d = float(np.abs(s.grid() - before).max()) / _size(before)
    assert d < 1e-6, f"nach Rückgängig {d:.2%} anders"


def test_linie_auf_flaeche_gleiten_aendert_nichts(h: H):
    """Eine gewöhnliche Linie auf der Fläche (längs, von Querschnitt zu Querschnitt): Punkt einfügen und gleiten – die
    Fläche bleibt, wie sie ist (die Linie behält ihre Form)."""
    surf, lines = _make_loft(h, UNEVEN)
    sc = h.sc
    g = surf.grid()
    col = g[:, g.shape[1] // 3].copy()
    sc.add_curve(col, surf.id)
    line = sc.curves[-1]
    sc.sync_lofts()
    assert line.id in surf.attached
    before = surf.grid().copy()
    k = components.insert_point(line, len(line.points) // 2, 0.5)
    sc.sync_lofts()
    st = sc.owner_of(line).id
    h.v.point_selection = [("pt", st, line.id, k)]
    h.frame(before.reshape(-1, 3))
    start = h.scrf(line.points[k])
    h.v._begin_slide(start)
    for dy in (5, 12, 20, -8):
        h.v._slide_update(type(start)(start.x(), start.y() + dy))
        sc.sync_lofts()
        d = float(np.abs(surf.grid() - before).max()) / _size(before)
        assert d < 2e-3, f"Gleiten um {dy} px verschiebt die Fläche um {d:.2%}"
    h.v.finish_slide(True)


def test_loft_harter_querschnitt_knickt_die_flaeche(h: H):
    """Mittleren Querschnitt hart stellen (Kantenmodus, Shift+K): die Seitenlinien knicken an ihm, der Loft wird dort
    geteilt – die Fläche hat eine Falte genau am Querschnitt und liegt weiter an allen Linien. Weich (Alt+K): wieder rund."""
    surf, lines = _make_loft(h, UNEVEN)
    sc = h.sc
    mid = lines[1]

    def kink():
        g = surf.grid()
        col, row = g.shape[1] // 2, _net_row(surf)
        return components.kink_deg(g[row::-1, col], g[row:, col])
    soft_kink = kink()
    # grobes Gitter, starke Rundung: ein paar Grad zwischen zwei Gitterstücken sind kein Knick (hart erst ab 15°)
    assert soft_kink < 12 and not _row_hard(surf).any(), f"anfangs rund ({soft_kink:.0f}°)"
    h.frame(surf.grid().reshape(-1, 3))
    h.edit_mode("edge")
    h.v.edge_selection = [("line", sc.owner_of(mid).id, mid.id)]
    before = mid.points.copy()
    h.v.set_hardness(1.0)
    sc.sync_lofts()
    assert np.array_equal(mid.points, before), "der Querschnitt selbst bleibt"
    # ganz hart = beide Seiten gerade auf den Punkt zu; wie hart das ist, sagt der Winkel (eine flache Seitenlinie
    # knickt dabei nur ~31° -> 0,55), über den Querschnitt anteilig
    assert _row_hard(surf).max() > 0.99 and _row_hard(surf).min() > 0.5, "Querschnitt ist hart"
    assert kink() > 30, f"Falte am Querschnitt ({kink():.0f}°)"
    verts, tris = surf.fill_mesh()[:2]
    size = _size(verts)
    for c in [mid] + sc.patch_border(surf):
        d = _dist_to_mesh(c.points, verts, tris).max()
        assert d < 0.005 * size, f"Fläche löst sich von Linie {c.id} ({d / size:.2%})"
    h.v.set_hardness(0.0)
    sc.sync_lofts()
    assert not _row_hard(surf).any() and kink() < 12, f"wieder rund ({kink():.0f}°)"


def test_loft_querschnitt_als_ganze_linie_anheben(h: H):
    """loft_test_v002: den mittleren Querschnitt als ganze Linie wählen (Kantenmodus) und mit dem Gizmo anheben – die
    Seitenlinien laufen mittendurch seine Enden und müssen mitgehen (gleiche Punkte bleiben verbunden), die Fläche
    bleibt an allen Linien."""
    from sketch_machine import edges
    surf, lines = _make_loft(h, FELIX)
    sc = h.sc
    mid = lines[1]
    network.sync(sc)
    ends = [network.pid_of(mid, 0), network.pid_of(mid, len(mid.points) - 1)]
    group = edges.handles_for(sc, [edges.curve_to_ref(sc, mid)])[0]
    for _ in range(3):  # wie das Gizmo: in Schritten
        group.translate(np.array([0.0, 1.0, 0.3]))
    sc.sync_lofts()
    network.sync(sc)
    assert [network.pid_of(mid, 0), network.pid_of(mid, len(mid.points) - 1)] == ends, "Enden bleiben dieselben Punkte"
    refs = network.refs_by_pid(sc)
    for pid in ends:
        pts = [o.points[j] for o, j in refs[pid]]
        assert len(pts) >= 2 and max(np.linalg.norm(p - pts[0]) for p in pts) < 1e-9, "Seitenlinie ging mit"
    verts, tris = surf.fill_mesh()[:2]
    size = _size(verts)
    for c in [mid] + sc.patch_border(surf):
        d = _dist_to_mesh(c.points, verts, tris).max()
        assert d < 0.005 * size, f"Fläche löst sich von Linie {c.id} ({d / size:.2%})"


def test_falte_bekommt_hartes_licht(h: H):
    """Licht-Normalen je Dreiecksecke: an einer Falte (Knick ab 45°) bekommt jede Seite ihre eigene Normale, eine
    glatte Rundung bleibt glatt (wie gemittelt)."""
    from sketch_machine import renderer
    u, v = np.meshgrid(np.linspace(-1, 1, 21), np.linspace(0, 1, 11), indexing="ij")
    roof = np.stack([u, 0.8 * (1 - np.abs(u)), v], axis=2)  # Dach: 77° Knick in der Mitte
    tube = np.stack([np.cos(u * 1.5), np.sin(u * 1.5), v], axis=2)  # glatte Rundung
    for grid, folded in ((roof, True), (tube, False)):
        verts, tris, _ = loft.build(None, False, g=grid)
        corner, split = renderer._corner_normals(verts, tris)
        smooth = renderer._smooth_normals(verts, tris)[tris]
        dev = np.degrees(np.arccos(np.clip(np.einsum("tki,tki->tk", corner, smooth), -1, 1)))
        if folded:
            on_ridge = np.abs(verts[tris][..., 0]) < 1e-9
            a, b, c = verts[tris[:, 0]], verts[tris[:, 1]], verts[tris[:, 2]]
            own = np.cross(b - a, c - a)
            own = np.repeat((own / np.linalg.norm(own, axis=1, keepdims=True))[:, None], 3, axis=1)
            off = np.degrees(np.arccos(np.clip(np.einsum("tki,tki->tk", corner, own), -1, 1)))
            assert off[on_ridge].max() < 1.0 and dev[on_ridge].min() > 20, "an der Falte: Normale der eigenen Seite"
            assert split[on_ridge].min() > 0.3 and dev[~on_ridge].max() < 1e-3, (split[on_ridge].min(), dev[~on_ridge].max())
        else:
            assert dev.max() < 0.5 and split.max() < 1e-9, "glatt bleibt glatt"


def test_loft_harter_querschnitt_mit_laengslinie(h: H):
    """loft_test_v002: harter Querschnitt, darüber eine Linie längs von Querschnitt zu Querschnitt, verbunden an der
    Kreuzung. Die Querschnitts-Reihe bleibt genau auf dem Querschnitt (keine Beule zwischen Stützstellen), und den
    Kreuzungspunkt anheben verformt die Fläche weich – keine Nadel, die Fläche bleibt an allen Linien. Der Querschnitt
    hat mehr Punkte als Stützstellen genommen werden (wie in der Szene)."""
    surf, lines = _make_loft(h, [FELIX[0], _arc((0, 0), 4.0, 5.0, 4.0, n=60), FELIX[2]])
    sc = h.sc
    mid = lines[1]
    h.frame(surf.grid().reshape(-1, 3))
    h.edit_mode("edge")
    h.v.edge_selection = [("line", sc.owner_of(mid).id, mid.id)]
    h.v.set_hardness(1.0)
    sc.sync_lofts()
    g = surf.grid()
    col = g[:, g.shape[1] // 2 + 3].copy()  # längs, kreuzt den Querschnitt
    sc.add_curve(col, surf.id)
    line = sc.curves[-1]
    sc.sync_lofts()
    network.connect_crossings(sc, line, [mid], 1e-3 * _size(g))
    sc.sync_lofts()
    g, b = surf.grid(), surf.base_grid()
    size = _size(g)
    row = _net_row(surf)
    dev = float(np.linalg.norm(g[row] - b[row], axis=1).max()) / size
    assert dev < 1e-3, f"Querschnitts-Reihe weicht {dev:.2%} ab"
    shared = set(line.pids.values()) & set(mid.pids.values())
    assert len(shared) == 1, "Kreuzung ist ein gemeinsamer Punkt"
    k = next(j for j, p in line.pids.items() if p in shared)
    top = g[..., 1].max()
    sc.checkpoint()
    components.ComponentGroup(sc, [(line, k)], []).translate(np.array([0.0, 1.0, 0.0]))
    sc.sync_lofts()
    g = surf.grid()
    assert g[..., 1].max() < top + 1.0 + 0.02 * size, f"Nadel: Fläche steigt {g[..., 1].max() - top:.2f} statt 1"
    verts, tris = surf.fill_mesh()[:2]
    for c in [mid, line] + sc.patch_border(surf):
        d = _dist_to_mesh(c.points[::2], verts, tris).max()
        assert d < 0.01 * size, f"Fläche löst sich von Linie {c.id} ({d / size:.2%})"


def test_kreuzung_neben_ecke_ein_punkt(h: H):
    """Kreuzt eine neue Linie eine andere ganz nah an ihrer eigenen Ecke (Strich knickt über eine Falte), wird daraus
    ein Punkt – kein zweiter direkt daneben (der sich beim Ziehen zur Nadel auszöge)."""
    sc = h.sc
    sc.new_stroke()
    t = np.linspace(0, 1, 81)
    sc.add_curve(np.stack([t * 4, 1 - np.abs(t * 4 - 2) * 0.5, np.zeros_like(t)], 1), None)  # Dach, Ecke bei x = 2
    roof = sc.curves[-1]
    sc.add_curve(np.stack([np.full(21, 2.06), np.linspace(-1, 2, 21), np.zeros(21)], 1), None)  # kreuzt bei x = 2,06
    other = sc.curves[-1]
    network.sync(sc)
    inner = [k for k in components.knots(roof) if 0 < k < len(roof.points) - 1]
    assert len(inner) == 1 and abs(roof.points[inner[0], 0] - 2.0) < 0.06, "Ecke erkannt"
    network.connect_crossings(sc, roof, [other], 0.05, radius=0.2)
    network.sync(sc)
    inner = [k for k in components.knots(roof) if 0 < k < len(roof.points) - 1]
    assert len(inner) == 1, f"{len(inner)} Punkte an der Kreuzung"
    assert network.pid_of(roof, inner[0]) in set(other.pids.values()), "der eine Punkt ist die Kreuzung"


def test_loft_v002_querschnitts_reihe_ohne_beule(h: H):
    """loft_test_v002 des Artists (harter Querschnitt mit 53 Punkten, Längslinie darüber): die Querschnitts-Reihe liegt genau
    auf dem Querschnitt – vorher beulte ein Gitterpunkt zwischen zwei Stützstellen 0,39 aus."""
    import os
    h.load(os.path.join(os.path.dirname(__file__), "scenes", "loft_v002.sketch.json"))
    sc = h.sc
    sc.sync_lofts()
    s = next(x for x in sc.surfaces if isinstance(x, PatchSurface) and x.net and x.net["u"])
    g, b = s.grid(), s.base_grid()
    row = _net_row(s)
    dev = float(np.linalg.norm(g[row] - b[row], axis=1).max())
    assert dev < 0.01, f"Querschnitts-Reihe weicht {dev:.3f} ab"


def test_strich_ueber_harten_querschnitt(h: H):
    """Strich mit der Maus über einen Loft mit hartem Querschnitt (Vorgehen des Artists): jeder Punkt des Strichs bekommt
    seine eigene Lage auf der Fläche – auch auf der Außenseite der Falte, wo die senkrechte Projektion neben beide
    angrenzenden Dreiecke fällt (vorher: nächster Gitterpunkt, mehrere Punkte auf derselben Stelle, Fläche verzerrt)."""
    surf, lines = _make_loft(h, FELIX)
    sc = h.sc
    mid = lines[1]
    h.frame(surf.grid().reshape(-1, 3))
    h.edit_mode("edge")
    h.v.edge_selection = [("line", sc.owner_of(mid).id, mid.id)]
    h.v.set_hardness(1.0)
    sc.sync_lofts()
    h.v.edge_selection = []
    h.draw_mode()
    h.v._activate(surf)
    h.frame(surf.grid().reshape(-1, 3), back=(0.15, 1.0, 0.1), margin=1.4)
    g = surf.grid()
    col = g[:, g.shape[1] // 2 + 4]
    before = {c.id for c in h.curves()}
    h.stroke_world(np.vstack([(col[0] + (col[0] - col[2]) * 0.6)[None], col, (col[-1] + (col[-1] - col[-3]) * 0.6)[None]]))
    sc.sync_lofts()
    new = [c for c in h.curves() if c.id not in before and not c.paint and c.id in surf.attached]
    assert new, "Strich liegt auf der Fläche"
    size = _size(surf.grid())
    for c in new:
        uv = surf.attached[c.id]["uv"]
        dup = len(uv) - len(np.unique(np.round(uv, 6), axis=0))
        assert dup == 0, f"{dup} Punkte teilen sich eine Stelle der Fläche"
        dev = np.linalg.norm(loft.evaluate_grid(uv, surf.grid(), False) - c.points, axis=1).max() / size
        assert dev < 0.002, f"Strich {dev:.2%} neben der Fläche"


def test_loft_teilen_auf_kurvenflaeche(h: H):
    """Alt+D bei einem offenen Loft (Kurvenfläche): ganze Fläche gewählt -> zwischen allen benachbarten Querschnitten je
    eine neue Querlinie, genau auf der Fläche, als Netzlinie verbunden; die Form bleibt. Zwei benachbarte Querschnitte
    gewählt -> nur zwischen ihnen."""
    from tests.harness import Qt
    surf, lines = _make_loft(h, UNEVEN)
    sc = h.sc
    before = surf.grid().copy()
    h.edit_mode("face")
    h.v.selection = [surf.id]
    h.v.edge_selection = []
    h.v.divide_loft()
    assert len(surf.net["u"]) == 3, f"{len(surf.net['u'])} Querlinien statt 3"
    verts, tris = surf.fill_mesh()[:2]
    dev = float(_dist_to_mesh(before.reshape(-1, 3)[::7], verts, tris).max()) / _size(before)
    assert dev < 0.005, f"Form ändert sich ({dev:.2%})"
    h.edit_mode("edge")
    h.v.selection = []
    h.v.edge_selection = [("line", sc.owner_of(c).id, c.id) for c in (lines[1],)] + \
        [("line", sc.owner_of(sc.curve_by_id(i)).id, i) for i in sorted(sc.net_rows_lines(surf)[3])]
    h.v.divide_loft()
    assert len(surf.net["u"]) == 4, f"{len(surf.net['u'])} Querlinien statt 4"


def test_falte_bleibt_bei_feinerem_netz(h: H):
    """Netzauflösung feiner/gröber (auch krumme Faktoren): die Falte an einem harten Querschnitt bleibt genau auf einer
    Gitterreihe (vorher rundete das Neuabtasten sie ab, wenn keine neue Reihe auf ihr lag)."""
    surf, lines = _make_loft(h, UNEVEN)
    sc = h.sc
    mid = lines[1]
    h.frame(surf.grid().reshape(-1, 3))
    h.edit_mode("edge")
    h.v.edge_selection = [("line", sc.owner_of(mid).id, mid.id)]
    h.v.set_hardness(1.0)
    sc.sync_lofts()
    g = surf.grid()
    found = {}
    for factor in (1.0, 1.7, 0.7):
        surf.resolution = factor
        verts = surf.fill_mesh()[0]
        m2 = int(round((g.shape[1] - 1) * factor)) + 1
        g2 = verts.reshape(-1, m2, 3)
        col = m2 // 2
        found[factor] = max(components.kink_deg(g2[i::-1, col], g2[i:, col]) for i in range(2, len(g2) - 2))
        dist = _dist_to_mesh(mid.points[::3], *surf.fill_mesh()[:2]).max() / _size(verts)
        assert dist < 0.003, f"Netz x{factor}: Fläche {dist:.2%} neben dem Querschnitt"
    assert found[1.0] > 30, found
    for factor in (1.7, 0.7):
        assert found[factor] > 0.8 * found[1.0], f"Netz x{factor}: Falte {found[factor]:.0f}° statt {found[1.0]:.0f}°"


def test_loft_laengslinien_an_knoten_ab_5_grad(h: H):
    """Querschnitte mit einem Punkt in der Mitte: Knick 3° -> nur die Seitenkanten, eine Fläche; 10° -> auch dort eine
    Längslinie, eine Fläche; 20° -> Längslinie und an ihr in zwei Kurvenflächen geteilt."""
    for deg, rails, faces in ((3.0, 2, 1), (10.0, 3, 1), (20.0, 3, 2)):
        h.new_scene()
        t = np.radians(deg)
        secs = []
        for z in (0.0, 2.0):
            a = np.linspace([-2.0, 0, z], [0.0, 0, z], 21)
            b = np.linspace([0.0, 0, z], [2 * np.cos(t), 2 * np.sin(t), z], 21)[1:]
            secs.append(np.vstack([a, b]))
        sc = h.sc
        sc.new_stroke()
        lines = []
        for pts in secs:
            sc.add_curve(pts, None)
            lines.append(sc.curves[-1])
            lines[-1].knots = (len(pts), (20,))
        h.v._changed()
        network.sync(sc)
        st = sc.owner_of(lines[0]).id
        h.v.set_select_mode(True)
        h.v.ws.component = "edge"
        h.v.edge_selection = [("line", st, c.id) for c in lines]
        h.v._pick_rank = {c.id: k for k, c in enumerate(lines)}
        h.v._track_pick_order = lambda: None
        h.v.do_loft()
        del h.v._track_pick_order
        along = [c for c in sc.curves if abs((c.points[-1] - c.points[0])[2]) > 1.9]
        assert len(along) == rails, f"{deg}°: {len(along)} Längslinien statt {rails}"
        assert len(sc.surfaces) == faces, f"{deg}°: {len(sc.surfaces)} Flächen statt {faces}"
        assert all(isinstance(f, PatchSurface) for f in sc.surfaces)


def test_loft_quadrat_vier_flaechen_kreis_eine_roehre(h: H):
    """Geschlossen: Quadrat-Querschnitte (Ecken 90°) -> vier Kurvenflächen; Kreise ohne harten Punkt -> eine Röhre."""
    from tests.harness import circle
    for shape, faces in (("quadrat", 4), ("kreis", 1)):
        h.new_scene()
        secs = []
        for y in (0.0, 2.0):
            if shape == "quadrat":
                q = [[0, y, 0], [1, y, 0], [1, y, 1], [0, y, 1], [0, y, 0]]
                secs.append(np.vstack([np.linspace(a, b, 11)[:-1] for a, b in zip(q, q[1:])] + [np.array([q[0]], float)]))
            else:
                secs.append(circle([0, y, 0], 1.0, 65))
        surf, _lines = _make_loft_any(h, secs)
        assert len(h.sc.surfaces) == faces, f"{shape}: {len(h.sc.surfaces)} Flächen statt {faces}"
        if shape == "quadrat":
            for f in h.sc.surfaces:
                v = f.fill_mesh()[0]
                p = v - v.mean(axis=0)
                assert np.linalg.svd(p, full_matrices=False)[1][2] < 1e-4, f"Wand {f.name} nicht eben"


def _make_loft_any(h: H, sections):
    sc = h.sc
    sc.new_stroke()
    lines = []
    for pts in sections:
        sc.add_curve(np.asarray(pts, float), None)
        lines.append(sc.curves[-1])
    h.v._changed()
    network.sync(sc)
    st = sc.owner_of(lines[0]).id
    h.v.set_select_mode(True)
    h.v.ws.component = "edge"
    h.v.edge_selection = [("line", st, c.id) for c in lines]
    h.v._pick_rank = {c.id: k for k, c in enumerate(lines)}
    h.v._track_pick_order = lambda: None
    h.v.do_loft()
    del h.v._track_pick_order
    sc.sync_lofts()
    return sc.surfaces[-1], lines

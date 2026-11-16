"""Kurvennetz (patchnet): jede Kurvenfläche – ob mit Alt+F, F oder als Loft entstanden – ist das Ergebnis ihrer Linien.
Linien von Rand zu Rand (an beiden Enden mit dem Rand verbunden) sind Netzlinien: sie bilden die Ruheform (Gordon-Fläche,
ohne sie die Coons-Fläche des Rands) und liegen auf einer Gitterreihe bzw. -spalte; alle anderen Linien verbiegen die
Fläche dazwischen. Gemeinsame Punkte haben eine Lage auf der Fläche, aus dem Netz abgeleitet."""
import numpy as np

from tests.harness import H, line
from tests.test_loft import _dist_to_mesh, _size
from sketch_machine import components, network
from sketch_machine.scene import PatchSurface


def _square_patch(h: H, size=4.0, n=21):
    """Ebene quadratische Kurvenfläche (y = 0) aus vier Randlinien."""
    sc = h.sc
    sc.new_stroke()
    P = [np.array(p, float) for p in ([0, 0, 0], [size, 0, 0], [size, 0, size], [0, 0, size])]
    border = []
    for a, b in zip(P, P[1:] + P[:1]):
        sc.add_curve(line(a, b, n), None)
        border.append(sc.curves[-1])
    surf = sc.create_patch(border)
    sc.sync_lofts()
    return surf, border


def _on_border(sc, border, c, k):
    """Linienende k von c mit der Randlinie verbinden, auf der es liegt (gemeinsamer Punkt)."""
    network.sync(sc)
    p = c.points[k]
    b = min(border, key=lambda o: float(np.linalg.norm(o.points - p, axis=1).min()))
    kb = network.knot_at(b, p, tol=1e-6)
    network.join(sc, b, kb, c, k)


def _line_on(h: H, surf, border, pts, ends=(0, -1)):
    """Echte Linie auf der Fläche; die genannten Enden mit dem Rand verbunden."""
    sc = h.sc
    sc.add_curve(np.asarray(pts, float), surf.id)
    c = sc.curves[-1]
    for e in ends:
        _on_border(sc, border, c, e % len(c.points))
    sc.sync_lofts()
    return c


def _arch(a, b, height, n=41, axis_up=1):
    t = np.linspace(0, 1, n)
    pts = np.asarray(a, float)[None] * (1 - t[:, None]) + np.asarray(b, float)[None] * t[:, None]
    pts[:, axis_up] += height * np.sin(np.pi * t)
    return pts


def test_querlinie_wird_netzlinie_und_formt_rund(h: H):
    """Alt+F-Fläche, eine angehobene Linie quer von Rand zu Rand: sie wird Netzlinie (Gitterreihe), die Fläche geht
    genau durch sie und schwingt quer dazu rund – kein Zelt (früher: Coons-Fläche + straffes Hinbiegen)."""
    surf, border = _square_patch(h)
    c = _line_on(h, surf, border, _arch([0, 0, 2.0], [4, 0, 2.0], 1.2))
    assert surf.net and len(surf.net["u"]) + len(surf.net["v"]) == 1, "Querlinie ist Netzlinie"
    verts, tris = surf.fill_mesh()[:2]
    size = _size(verts)
    assert _dist_to_mesh(c.points[::2], verts, tris).max() < 0.002 * size, "Fläche geht durch die Linie"
    g = surf.grid()
    att = surf.attached[c.id]["uv"]
    if surf.net["u"]:
        row = surf.net["u"][0][1]
        assert np.ptp(att[:, 0]) < 1e-9 and att[0, 0] == row, "Linie liegt auf einer Gitterreihe"
        prof = g[:, g.shape[1] // 2]
    else:
        row = surf.net["v"][0][1]
        assert np.ptp(att[:, 1]) < 1e-9 and att[0, 1] == row, "Linie liegt auf einer Gitterspalte"
        prof = g[g.shape[0] // 2]
    k = components.kink_deg(prof[row::-1], prof[row:])
    # rund: von 0 auf 1,2 und zurück auf 2 + 2 Einheiten – eine Parabel knickt an der Spitze nicht
    assert k < 12, f"Zelt: {k:.0f}° Knick an der Linie"


def test_netz_in_beiden_richtungen(h: H):
    """Eine Linie quer und eine längs, die sich in einem gemeinsamen Punkt kreuzen: beide sind Netzlinien, das Gitter
    folgt beiden (Reihe und Spalte), die Fläche geht durch beide."""
    sc = h.sc
    surf, border = _square_patch(h)
    a = _line_on(h, surf, border, _arch([0, 0, 2.0], [4, 0, 2.0], 1.0))
    b = _line_on(h, surf, border, _arch([2.0, 0, 0], [2.0, 0, 4], 1.0))
    network.connect_crossings(sc, b, [a], 1e-3)
    sc.sync_lofts()
    assert surf.net and len(surf.net["u"]) == 1 and len(surf.net["v"]) == 1, (surf.net["u"], surf.net["v"])
    verts, tris = surf.fill_mesh()[:2]
    size = _size(verts)
    for c in (a, b):
        assert _dist_to_mesh(c.points[::2], verts, tris).max() < 0.002 * size, f"Fläche geht durch Linie {c.id}"
    uv = {c.id: surf.attached[c.id]["uv"] for c in (a, b)}
    assert any(np.ptp(u[:, 0]) < 1e-9 for u in uv.values()) and any(np.ptp(u[:, 1]) < 1e-9 for u in uv.values()), \
        "eine Linie auf einer Reihe, die andere auf einer Spalte"


def test_gemeinsamer_punkt_am_rand_liegt_genau(h: H):
    """Eine freie Linie endet an einem Randpunkt (nur ein Ende am Rand – keine Netzlinie). Zieht man diesen Punkt, liegt
    die Fläche weiter genau an ihm und am Linienende: die Lage des Punkts auf der Fläche kommt aus dem Netz, nicht aus
    dem, was sich die Linie beim Zeichnen gemerkt hat."""
    sc = h.sc
    surf, border = _square_patch(h)
    c = _line_on(h, surf, border, _arch([0, 0, 1.3], [2.5, 0, 1.6], 0.0), ends=(0,))  # auf der Fläche gezeichnet
    assert not (surf.net["u"] or surf.net["v"]), "freie Linie, keine Netzlinie"
    pid = network.pid_of(c, 0)
    refs = network.refs_by_pid(sc)
    b, kb = next((o, j) for o, j in refs[pid] if o is not c)
    components.ComponentGroup(sc, [(b, kb)], []).translate(np.array([0.0, 0.8, 0.3]))
    sc.sync_lofts()
    verts, tris = surf.fill_mesh()[:2]
    size = _size(verts)
    for name, pts in (("Randpunkt", b.points[kb:kb + 1]), ("Linie", c.points[::2])):
        d = _dist_to_mesh(pts, verts, tris).max()
        assert d < 0.003 * size, f"{name}: Fläche {d / size:.2%} daneben"


def test_neue_netzlinie_alles_bleibt_am_ort(h: H):
    """Kommt eine Netzlinie dazu, wird das Gitter neu gelegt – eine freie Linie darauf behält ihren Ort und die Fläche
    liegt weiter an ihr."""
    sc = h.sc
    surf, border = _square_patch(h)
    free = _line_on(h, surf, border, _arch([0.6, 0, 0.8], [1.6, 0, 1.0], 0.0), ends=())
    before = free.points.copy()
    _line_on(h, surf, border, _arch([0, 0, 2.6], [4, 0, 2.6], 0.8))
    assert surf.net["u"] or surf.net["v"]
    assert np.array_equal(free.points, before), "Linien bewegt die Fläche nie"
    verts, tris = surf.fill_mesh()[:2]
    assert _dist_to_mesh(free.points[::2], verts, tris).max() < 0.003 * _size(verts), "Fläche liegt an der freien Linie"


def test_alte_kurvenflaechen_werden_netz(h: H):
    """Ältere Szene (Topologie-Test des Artists): alle Kurvenflächen mit vollständigem Rand bekommen beim Laden ihr Netz
    und liegen an allen ihren Linien."""
    h.load("tests/scenes/topologie.sketch.json")
    sc = h.sc
    sc.sync_lofts()
    patches = [s for s in sc.surfaces if isinstance(s, PatchSurface)]
    assert patches and all(s.net for s in patches)
    for s in patches:
        verts, tris = s.fill_mesh()[:2]
        size = _size(verts)
        for c in sc.patch_border(s) + [sc.curve_by_id(cid) for cid in s.attached]:
            if c is None or c.paint:
                continue
            d = _dist_to_mesh(c.points[::4], verts, tris).max()
            assert d < 0.01 * size, f"{s.name}: Linie {c.id} {d / size:.2%} daneben"


def _l_fill(h: H):
    """Ebene L-förmige Füllfläche (y = 0) aus sechs Randlinien (F nimmt dafür eine Füllfläche)."""
    sc = h.sc
    sc.new_stroke()
    P = [np.array(p, float) for p in ([0, 0, 0], [6, 0, 0], [6, 0, 2], [2, 0, 2], [2, 0, 6], [0, 0, 6])]
    border = []
    for a, b in zip(P, P[1:] + P[:1]):
        sc.add_curve(line(a, b, 25), None)
        border.append(sc.curves[-1])
    surf = sc.create_fill([(c, False) for c in border])
    sc.sync_lofts()
    return surf, border


def _fill_dist(surf, pts):
    verts, tris = surf.netmesh[0], surf.netmesh[1]
    return _dist_to_mesh(pts, verts, tris), _size(verts)


def test_fuellflaeche_netzlinie_formt_rund(h: H):
    """L-förmige Füllfläche, eine angehobene Linie von Rand zu Rand (beide Enden verbunden): sie formt die Fläche wie
    eine Netzlinie – genau durch sie und quer dazu rund (kein Zelt wie früher mit Straffheit)."""
    sc = h.sc
    surf, border = _l_fill(h)
    c = _line_on(h, surf, border, _arch([4.0, 0, 0], [4.0, 0, 2], 0.0, n=21))  # quer über den kurzen Arm
    pts = c.points.copy()
    pts[:, 1] = 0.8 * np.sin(np.linspace(0, np.pi, len(pts)))
    c.points = pts
    sc.sync_lofts()
    assert c.id in sc._fill_net_ids(surf, network.refs_by_pid(sc)), "Linie von Rand zu Rand ist Netzlinie"
    d, size = _fill_dist(surf, c.points[::2])
    assert d.max() < 0.003 * size, f"Fläche {d.max() / size:.2%} neben der Linie"
    # Profil längs des Arms (quer zur Linie) bei z = 1: rund, kein Knick an der Linie
    verts = surf.netmesh[0]
    rest = surf.netmesh[2]
    xs = np.linspace(2.4, 5.6, 33)
    from sketch_machine import netfill
    dom = netfill.domain(surf.rest, netfill.DENSITY * surf.resolution)
    from sketch_machine import cage
    uv = cage.bind(np.stack([xs, np.zeros_like(xs), np.ones_like(xs)], 1), cage.build(
        sc._fill_pieces(surf), surf.counts), surf.rest)
    prof = netfill.evaluate(dom, verts, uv, lambda q: np.zeros((len(q), 3)))
    k = int(np.argmin(np.abs(xs - 4.0)))
    kink = components.kink_deg(prof[k::-1], prof[k:])
    assert prof[k, 1] > 0.75, f"Fläche erreicht die Linie nicht ({prof[k, 1]:.2f})"
    assert kink < 15, f"Zelt an der Linie: {kink:.0f}° Knick"  # mit Straffheit (früher): 19°, reines Blech: 11°

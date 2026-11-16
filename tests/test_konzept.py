"""Topologie-Konzept (Plan-Dokument, Abschnitt „Prüfkriterien“): Testszene des Artists topologie.sketch.json, Task 1–5.

Hierarchie: Punkte -> echte Linien -> Flächen -> Nebel/Malerei; nichts weiter unten bewegt etwas weiter oben.
Die roten Pinselstriche der Szene sind die Vorlagen: entlang ihrer wird mit echten Linien gezeichnet, so wie der Artist es
tun würde (Strich etwas über den Flächenrand hinaus). Alle Prüfungen eines Tasks müssen stimmen.
"""
import numpy as np

from PySide6.QtCore import QPointF

from sketch_machine.i18n import tr
from tests.harness import H, Qt
from sketch_machine import components, network
from sketch_machine.scene import PatchSurface

SCENE = "tests/scenes/topologie.sketch.json"
MOVE_TOL = 1e-6  # so weit dürfen sich nicht bewegte Punkte verschieben
ON_TOL = 0.01  # Anteil der Flächengröße: so nah muss die Fläche an ihren Linien liegen


# --- Szene und Abfragen ---

def _surface(h: H, name):
    return next(s for s in h.sc.surfaces if s.name == name)


def _guides(h: H, surface, red_only=True):
    """Rote Pinselstriche (Malerei) über der Fläche, nach Lage sortiert."""
    lo, hi = _box(surface)
    out = []
    for c in h.curves():
        if not c.paint or len(c.points) < 10:
            continue
        if red_only and c.color is not None and c.color[1] > 0.4:  # gelbe Schraffur
            continue
        m = c.points.mean(axis=0)
        if np.all(m[[0, 2]] >= lo[[0, 2]]) and np.all(m[[0, 2]] <= hi[[0, 2]]):
            out.append(c)
    return out


def _box(surface):
    v = surface.fill_mesh()[0]
    return v.min(axis=0), v.max(axis=0)


def _size(surface):
    lo, hi = _box(surface)
    return float(np.linalg.norm(hi - lo))


def _border(h: H, surface):
    """Randlinien einer Kurvenfläche (geteilte als ihre Stücke)."""
    out = []
    for cid in surface.patch_lines:
        for sub in h.sc.split_pieces(cid) or []:
            c = h.sc.curve_by_id(sub)
            if c is not None:
                out.append(c)
    return out


def _border_pids(h: H, surface):
    return {pid for c in _border(h, surface) for pid in (c.pids or {}).values()}


def _positions(h: H):
    """{Punkt-ID: Lage} aller Netzpunkte."""
    return {pid: refs[0][0].points[refs[0][1]].copy() for pid, refs in network.refs_by_pid(h.sc).items()}


def _top_view(h: H, surface):
    lo, hi = _box(surface)
    h.camera((lo + hi) / 2, float(np.linalg.norm(hi - lo)) * 1.6, [0.0, 1.0, 0.01])


def _draw_along(h: H, surface, guide, over=0.06):
    """Echte Linie entlang einer Vorlage auf der Fläche zeichnen, an beiden Enden etwas über die Vorlage hinaus
    (wie über den Rand gezogen). Liefert die neue Linie."""
    h.draw_mode()
    h.v._activate(surface)
    _top_view(h, surface)
    pts = guide.points
    size = _size(surface)
    a = pts[0] + (pts[0] - pts[min(4, len(pts) - 1)]) / max(np.linalg.norm(pts[0] - pts[min(4, len(pts) - 1)]), 1e-9) * over * size
    b = pts[-1] + (pts[-1] - pts[-min(5, len(pts))]) / max(np.linalg.norm(pts[-1] - pts[-min(5, len(pts))]), 1e-9) * over * size
    idx = np.linspace(0, len(pts) - 1, 24).astype(int)
    before = {c.id for c in h.curves()}
    h.stroke_world(np.vstack([a[None], pts[idx], b[None]]))
    new = [c for c in h.curves() if c.id not in before and not c.paint]
    assert len(new) == 1, f"{len(new)} neue Linien statt einer"
    return new[0]


def _members(h: H, surface):
    """Echte Linien der Fläche: Rand und darauf gezeichnete."""
    return _border(h, surface) + [c for c in h.curves() if not c.paint and c.plane_id == surface.id]


def _dist_to_mesh(points, verts, tris):
    """Abstand jedes Punkts zur Dreiecksfläche (grob genug für Tests: nächster Punkt auf jedem Dreieck)."""
    a, b, c = verts[tris[:, 0]], verts[tris[:, 1]], verts[tris[:, 2]]
    out = []
    for p in points:
        out.append(float(np.min(_point_tri(p, a, b, c))))
    return np.array(out)


def _point_tri(p, a, b, c):
    ab, ac, ap = b - a, c - a, p - a
    d1, d2 = np.einsum("ij,ij->i", ab, ap), np.einsum("ij,ij->i", ac, ap)
    n = np.cross(ab, ac)
    nn = np.einsum("ij,ij->i", n, n)
    ok = nn > 1e-18
    # Projektion in die Ebene, dann baryzentrisch; außerhalb: nächster Punkt der Kanten
    best = np.full(len(a), np.inf)
    w = np.where(ok[:, None], np.cross(ab, ap), 0)
    v = np.where(ok[:, None], np.cross(ap, ac), 0)
    s = np.einsum("ij,ij->i", v, n) / np.maximum(nn, 1e-18)
    t = np.einsum("ij,ij->i", w, n) / np.maximum(nn, 1e-18)
    inside = ok & (s >= 0) & (t >= 0) & (s + t <= 1)
    proj = a + s[:, None] * ab + t[:, None] * ac
    best[inside] = np.linalg.norm(proj[inside] - p, axis=1)
    for x, y in ((a, b), (b, c), (c, a)):
        xy = y - x
        u = np.clip(np.einsum("ij,ij->i", p - x, xy) / np.maximum(np.einsum("ij,ij->i", xy, xy), 1e-18), 0, 1)
        best = np.minimum(best, np.linalg.norm(x + u[:, None] * xy - p, axis=1))
    del d1, d2
    return best


def _off_surface(h: H, surface):
    """Größter Abstand der Fläche zu ihren echten Linien (Anteil der Flächengröße)."""
    verts, tris = surface.fill_mesh()[:2]
    worst = 0.0
    for c in _members(h, surface):
        pts = c.points[np.linspace(0, len(c.points) - 1, min(len(c.points), 15)).astype(int)]
        worst = max(worst, float(_dist_to_mesh(pts, verts, tris).max()))
    return worst / _size(surface)


def _covers(surface, point, tol=0.05):
    """Liegt die Fläche (von oben gesehen) über diesem Punkt?"""
    verts, tris = surface.fill_mesh()[:2]
    p = np.asarray(point, float)
    flat = verts.copy()
    flat[:, 1] = 0
    q = p.copy()
    q[1] = 0
    return float(_dist_to_mesh([q], flat, tris)[0]) < tol


def _move_point(h: H, pid, delta):
    """Einen Netzpunkt ziehen wie im Punktmodus (mit allen Linien, die ihn teilen)."""
    refs = network.refs_by_pid(h.sc)[pid]
    h.sc.checkpoint()
    group = components.ComponentGroup(h.sc, [refs[0]], [])
    group.translate(np.asarray(delta, float))
    h.v._changed()


def _pid_at(h: H, point, tol=0.05):
    pos = _positions(h)
    pid = min(pos, key=lambda p: np.linalg.norm(pos[p] - point))
    assert np.linalg.norm(pos[pid] - point) < tol, f"kein Netzpunkt bei {point}"
    return pid


def _check_connected(h: H, surface, lines):
    """Jedes Ende jeder neuen Linie ist ein gemeinsamer Punkt (Rand oder andere Linie); Kreuzungen sind Punkte."""
    refs = network.refs_by_pid(h.sc)
    border = _border_pids(h, surface)
    for c in lines:
        for k in (0, len(c.points) - 1):
            pid = network.pid_of(c, k)
            assert pid in border or network.degree(refs[pid]) > 1, f"Linienende {c.points[k].round(2)} hängt lose"
    for i, a in enumerate(lines):
        for b in lines[:i]:
            near = network.crossings(a, b, 0.01 * _size(surface))
            if near:
                assert set(a.pids.values()) & set(b.pids.values()), "Kreuzung ist kein gemeinsamer Punkt"


def _lift_and_check(h: H, surface, pid, delta):
    before = _positions(h)
    count = len(before)
    _move_point(h, pid, delta)
    after = _positions(h)
    assert len(after) == count, f"{len(after) - count:+d} Punkte"
    moved = [p for p in before if p in after and np.linalg.norm(after[p] - before[p]) > MOVE_TOL]
    assert moved == [pid], f"{len(moved)} Punkte bewegt, erwartet nur den gezogenen"
    off = _off_surface(h, surface)
    assert off < ON_TOL, f"Fläche liegt {off * 100:.1f} % neben ihren Linien"


# --- Task 1: Ecke anheben ---

def test_task1_ecke_anheben(h: H):
    h.load(SCENE)
    surf = _surface(h, "Kurvenfläche 1")
    lines = [_draw_along(h, surf, g) for g in _guides(h, surf)]
    assert len(lines) == 2
    _check_connected(h, surf, lines)
    corner = _pid_at(h, [22.76, 0.0, 3.83])
    _lift_and_check(h, surf, corner, [0, 2.0, 0])
    _check_connected(h, surf, lines)
    h.save_image("konzept_task1.png")


# --- Task 2: Kreuzung anheben ---

def test_task2_kreuzung_anheben(h: H):
    h.load(SCENE)
    surf = _surface(h, "Kurvenfläche 3")
    lines = [_draw_along(h, surf, g) for g in _guides(h, surf)[:2]]
    _check_connected(h, surf, lines)
    shared = set(lines[0].pids.values()) & set(lines[1].pids.values())
    assert len(shared) == 1, "eine Kreuzung"
    _lift_and_check(h, surf, shared.pop(), [0, 1.5, 0])
    _check_connected(h, surf, lines)
    h.save_image("konzept_task2.png")


# --- Task 3 und 4: Ecke löschen ---

def _delete_point(h: H, point):
    h.edit_mode("point")
    h.click(h.scr(point))
    assert h.v.point_selection, "Punkt gewählt"
    h.key(Qt.Key_Delete, Qt.ControlModifier)  # Strg+Entf: löschen (Entf löst auf)


def test_task3_ecke_loeschen_bruecke(h: H):
    h.load(SCENE)
    surf = _surface(h, "Kurvenfläche 5")
    _top_view(h, surf)
    a, b, gone = np.array([-18.88, 0, 3.83]), np.array([-13.0, 0, -6.7]), np.array([-21.18, 0, -1.74])
    _delete_point(h, gone)
    near = [c for c in h.curves() if not c.paint and np.linalg.norm(c.points - gone, axis=1).min() < 0.3]
    assert not near, "anliegende Stücke sind weg"
    bridge = [c for c in h.curves() if not c.paint and {tuple(np.round(c.points[0], 1)), tuple(np.round(c.points[-1], 1))}
              == {tuple(np.round(a, 1)), tuple(np.round(b, 1))}]
    assert len(bridge) == 1, "Nachbarpunkte durch eine neue Linie verbunden"
    assert not _covers(surf, [-17.7, 0, -1.5]), "Fläche ohne die gelöschte Ecke"
    assert _covers(surf, [-12.0, 0, 0.0]), "Rest der Fläche bleibt"


def test_task4_ecke_loeschen_umriss_ueber_gitterlinien(h: H):
    h.load(SCENE)
    surf = _surface(h, "Kurvenfläche 6")
    guides = [g for g in _guides(h, surf) if np.linalg.norm(np.ptp(g.points, axis=0)) > 0.3 * _size(surf)]  # ohne Kreis
    lines = [_draw_along(h, surf, g) for g in guides]
    assert len(lines) == 2, f"{len(lines)} Gitterlinien"
    _check_connected(h, surf, lines)
    _delete_point(h, np.array([-47.38, 0, -1.74]))
    assert not _covers(surf, [-43.4, 0, -0.8]), "gelber Bereich ist weg"
    assert _covers(surf, [-38.0, 0, -2.0]), "Rest der Fläche bleibt"
    a, b = np.array([-45.1, 0, 3.8]), np.array([-39.2, 0, -6.7])
    bridge = [c for c in h.curves() if not c.paint and np.linalg.norm(c.points[0] - a) < 0.2 and np.linalg.norm(c.points[-1] - b) < 0.2]
    assert not bridge, "keine Brücke: der Umriss über die Gitterlinien gilt"
    _check_connected(h, surf, [c for c in lines if h.sc.curve_by_id(c.id) is not None])


# --- Task 5: mehrere verbundene Flächen ---

def test_task5_jeden_punkt_bewegen(h: H):
    h.load(SCENE)
    names = ("Kurvenfläche 7", "Kurvenfläche 8", "Kurvenfläche 9")
    surfs = [_surface(h, n) for n in names]
    lo = np.min([_box(s)[0] for s in surfs], axis=0)
    hi = np.max([_box(s)[1] for s in surfs], axis=0)
    guides = [c for c in h.curves() if c.paint and len(c.points) > 60
              and np.all(c.points.mean(axis=0)[[0, 2]] >= lo[[0, 2]]) and np.all(c.points.mean(axis=0)[[0, 2]] <= hi[[0, 2]])]
    assert len(guides) == 7, f"{len(guides)} Vorlagen"
    lines = []
    for g in guides:  # jede Vorlage liegt auf einer Fläche
        mid = g.points[len(g.points) // 2]
        surf = min(surfs, key=lambda s: float(_dist_to_mesh([mid], *s.fill_mesh()[:2])[0]))
        lines.append((surf, _draw_along(h, surf, g, over=0.01)))
    for surf in surfs:
        _check_connected(h, surf, [c for s, c in lines if s is surf])
    pids = set()
    for surf in surfs:
        for c in _members(h, surf):
            pids |= set((c.pids or {}).values())
    for k, pid in enumerate(sorted(pids)):
        before = _positions(h)
        _move_point(h, pid, [0.0, 0.4 if k % 2 else -0.3, 0.0])
        after = _positions(h)
        assert len(after) == len(before), "keine neuen Punkte"
        moved = [p for p in before if np.linalg.norm(after[p] - before[p]) > MOVE_TOL]
        assert moved == [pid], f"Punkt {k}: {len(moved)} Punkte bewegt"
        for surf in surfs:
            off = _off_surface(h, surf)
            assert off < ON_TOL, f"{surf.name} liegt {off * 100:.1f} % neben ihren Linien"
    for surf in surfs:
        _check_connected(h, surf, [c for s, c in lines if s is surf])
    h.save_image("konzept_task5.png")


def test_szene_laedt_alle_flaechen(h: H):
    h.load(SCENE)
    assert sum(isinstance(s, PatchSurface) for s in h.sc.surfaces) == 9


def test_rand_verbindet_auch_mit_glaettung_und_schnellem_strich(h: H):
    """debugging_topo: mit Glättung endet der Strich an der nachlaufenden Spitze, schnelle Striche treffen die Fläche
    zuletzt ein Stück vor dem Rand – trotzdem müssen Anfang (außerhalb angesetzt) und Ende (über den Rand gezogen) auf
    der Randlinie landen."""
    h.load(SCENE)
    surf = _surface(h, "Kurvenfläche 1")
    h.draw_mode()
    h.v._activate(surf)
    _top_view(h, surf)
    h.v.set_smooth(0.7)
    try:
        guide = _guides(h, surf)[0]
        pts = guide.points
        size = _size(surf)
        a = pts[0] + (pts[0] - pts[6]) / np.linalg.norm(pts[0] - pts[6]) * 0.08 * size
        b = pts[-1] + (pts[-1] - pts[-7]) / np.linalg.norm(pts[-1] - pts[-7]) * 0.05 * size
        before = {c.id for c in h.curves()}
        h.stroke([h.scrf(p) for p in np.vstack([a[None], pts[::6], b[None]])], step_px=25)
    finally:
        h.v.set_smooth(0.0)
    new = [c for c in h.curves() if c.id not in before and not c.paint]
    assert len(new) == 1
    _check_connected(h, surf, new)
    border = _border_pids(h, surf)
    c = new[0]
    assert network.pid_of(c, 0) in border and network.pid_of(c, len(c.points) - 1) in border, "beide Enden auf dem Rand"


def test_nahe_linien_ohne_starke_wellen(h: H):
    """debugging_topo (Artist): vier kurze Linien dicht nebeneinander, eine 0,184 angehoben. Auf dem groben Gitter
    (bis v0.84.1) schwang die Fläche von -2,6 bis +1,1 aus; auf dem vollen Gitter bleibt nur das kleine Überschwingen
    der glatten Fläche."""
    from sketch_machine import netsurf
    assert netsurf.sparse is not None, "scipy fehlt (requirements.txt)"
    h.load("tests/scenes/netz_nahe_linien.sketch.json")
    surf = h.sc.surfaces[0]
    y = surf.grid()[..., 1]
    assert -0.35 < y.min() and y.max() < 0.25, f"Fläche schwingt aus: {y.min():.2f} .. {y.max():.2f}"
    assert _off_surface(h, surf) < 0.002


def test_randpunkte_seitlich_und_ecken_ohne_ausreisser(h: H):
    """debugging_topo (2. Stand, Artist): Randpunkte seitlich ziehen, Ecken anheben, eine angehobene Linie über eine
    andere schieben (Kreuzung in verschiedener Höhe). Früher: die Fläche riss bis 18 Einheiten aus (Parameter rutschte
    unter den Linien weg, Coons-Delle, Widerspruch). Jetzt: Ruheform + glatte Verformung, Widersprüche gemittelt."""
    moves = [([4.29, 0, -6.5], [1.0, 0, 0]), ([4.29, 0, -6.5], [0, 0, 1.0]), ([8.38, 0, -10.98], [1.0, 0, 0]),
             ([8.38, 0, -10.98], [0, 1.0, 0]), ([-3.99, 0, -0.55], [0, 0, 1.0]), ([1.08, 0.57, 1.65], [0, 0, 1.0])]
    for point, delta in moves:
        h.load("tests/scenes/netz_randpunkte.sketch.json")
        surf = h.sc.surfaces[0]
        _move_point(h, _pid_at(h, point, tol=0.02), delta)
        ys = np.concatenate([c.points[:, 1] for c in _members(h, surf)])
        y = surf.grid()[..., 1]
        over = max(y.max() - ys.max(), ys.min() - y.min(), 0.0)
        assert over < 0.5, f"{point} um {delta}: Fläche schwingt {over:.2f} über die Linien hinaus"
        assert _off_surface(h, surf) < 0.01, f"{point} um {delta}: Fläche liegt neben ihren Linien"


def test_aufloesen_am_flaechenrand_behaelt_form(h: H):
    """Entf auf dem Stoß zweier Randlinien einer Kurvenfläche: die beiden Linien werden eine, Form von Linie und
    Fläche bleiben, die Fläche kennt die neue Randlinie."""
    h.load(SCENE)
    surf = _surface(h, "Kurvenfläche 5")
    _top_view(h, surf)
    lines_before = {c.id for c in h.curves() if not c.paint}
    grid_before = surf.grid().copy()
    pos = _positions(h)
    joint = pos[_pid_at(h, [-18.88, 0, 3.83])]  # Stoß zweier Randlinien, keine Ecke der Kurvenfläche
    pts_before = np.vstack([c.points for c in _border(h, surf)])
    h.edit_mode("point")
    h.click(h.scr(joint))
    assert h.v.point_selection, "Punkt gewählt"
    h.key(Qt.Key_Delete)
    border = _border(h, surf)
    assert len(border) == len(surf.patch_lines) == 4, f"{len(border)} Randlinien (vorher 5)"
    after = np.vstack([c.points for c in border])
    gap = max(np.linalg.norm(after - p, axis=1).min() for p in pts_before)
    assert gap < 1e-9, f"Linienpunkte bleiben ({gap:.2g})"
    assert np.abs(surf.grid() - grid_before).max() < 1e-3 * _size(surf), "Fläche bleibt, wie sie war"
    merged = [c for c in h.curves() if not c.paint and c.id not in lines_before]
    assert len(merged) == 1 and np.linalg.norm(merged[0].points - joint, axis=1).min() < 1e-9
    assert all(np.linalg.norm(merged[0].points[k] - joint) > 1e-6 for k in components.knots(merged[0])), \
        "kein Punkt mehr am Stoß"


def test_kreuzung_wird_nicht_aufgeloest(h: H):
    h.load(SCENE)
    surf = _surface(h, "Kurvenfläche 3")
    lines = [_draw_along(h, surf, g) for g in _guides(h, surf)[:2]]
    x = (set(lines[0].pids.values()) & set(lines[1].pids.values())).pop()
    pos = _positions(h)[x]
    n_before = len(h.curves())
    h.edit_mode("point")
    h.click(h.scr(pos))
    h.key(Qt.Key_Delete)
    assert x in _positions(h), "Kreuzung bleibt ein Punkt"
    assert len(h.curves()) == n_before


def _folded(g):
    du, dv = g[1:, :-1] - g[:-1, :-1], g[:-1, 1:] - g[:-1, :-1]
    n = np.cross(du, dv)[..., 1]
    return int(((np.sign(n) != np.sign(np.median(n))) & (np.abs(n) > 1e-9)).sum())


def test_ecke_weit_seitlich_ohne_falten(h: H):
    """Randknoten hängen an festen Stellen der Randlinien: zieht man eine Ecke weit seitlich, bleibt die Fläche
    ungefaltet (gleichmäßiges Neuverteilen am Rand verschob vorher alle Randknoten der Seite: 133 gefaltete Zellen)."""
    h.load("tests/scenes/netz_randpunkte.sketch.json")
    surf = h.sc.surfaces[0]
    rest = _folded(surf.grid())
    _move_point(h, _pid_at(h, [8.38, 0, -10.98], tol=0.02), [8.0, 0, -6.0])
    assert _folded(surf.grid()) <= rest + 2, f"{_folded(surf.grid())} gefaltete Zellen"
    assert _off_surface(h, surf) < 0.002


def test_neu_verteilen_behaelt_form(h: H):
    """Kurvennetz: die Gitterpunkte hängen an festen Stellen der Linien – nach einem weiten Zug wird nichts neu
    eingeteilt (die Fläche hängt von der Einteilung ab und spränge nach dem Loslassen)."""
    from sketch_machine import netsurf
    h.load("tests/scenes/netz_randpunkte.sketch.json")
    surf = h.sc.surfaces[0]
    _move_point(h, _pid_at(h, [8.38, 0, -10.98], tol=0.02), [8.0, 0, -6.0])
    g_old = surf.grid().copy()
    old, netsurf.REREST = netsurf.REREST, 1.0
    try:
        assert h.sc.rerest_patches() == 0
    finally:
        netsurf.REREST = old
    h.v._changed()
    verts, tris = surf.fill_mesh()[:2]
    assert _dist_to_mesh(g_old.reshape(-1, 3)[::23], verts, tris).max() < 0.005 * _size(surf), "Form bleibt"
    assert _off_surface(h, surf) < 0.002


def _multi(h: H, names):
    surfs = [_surface(h, n) for n in names]
    lo = np.min([_box(s)[0] for s in surfs], axis=0)
    hi = np.max([_box(s)[1] for s in surfs], axis=0)
    h.draw_mode()
    h.camera((lo + hi) / 2, float(np.linalg.norm(hi - lo)) * 1.4, [0.0, 1.0, 0.01])
    h.v.set_multi_mode(True)
    h.sc.multi_ids = [s.id for s in surfs]
    h.v._changed()
    return surfs


def _stroke_new(h: H, a, b, n=40):
    a, b = np.asarray(a, float), np.asarray(b, float)
    before = {c.id for c in h.curves()}
    h.stroke([h.scrf(a + t * (b - a)) for t in np.linspace(0, 1, n)])
    return [c for c in h.curves() if c.id not in before and not c.paint]


def test_multi_ueber_flaechengrenzen_verbunden(h: H):
    """Multi-Modus (Artist): ein Strich über drei Flächen mit gemeinsamen Randlinien und über den Außenrand hinaus.
    Jedes Teilstück endet auf einer Randlinie seiner Fläche; Übergänge sind gemeinsame Punkte; Kreuzungen auch."""
    h.load(SCENE)
    surfs = _multi(h, ("Kurvenfläche 7", "Kurvenfläche 8", "Kurvenfläche 9"))
    try:
        first = _stroke_new(h, [-71.0, 0, 1.0], [-49.0, 0, -7.5])
        second = _stroke_new(h, [-64.0, 0, -9.0], [-57.0, 0, 6.5])
    finally:
        h.v.set_multi_mode(False)
    assert len(first) >= 2 and len(second) >= 2, (len(first), len(second))
    for c in first + second:
        surf = h.sc.object_by_id(c.plane_id)
        border = _border_pids(h, surf)
        for k in (0, len(c.points) - 1):
            assert network.pid_of(c, k) in border, f"Ende {c.points[k].round(2)} liegt nicht auf dem Rand von {surf.name}"
    for i, a in enumerate(first):  # Übergänge: aufeinanderfolgende Teilstücke teilen einen Punkt
        for b in first[i + 1:i + 2]:
            assert set(a.pids.values()) & set(b.pids.values()), "Übergang ist kein gemeinsamer Punkt"
    for a in second:
        for b in first:
            if a.plane_id == b.plane_id and network.crossings(a, b, 0.01 * _size(h.sc.object_by_id(a.plane_id))):
                assert set(a.pids.values()) & set(b.pids.values()), "Kreuzung ist kein gemeinsamer Punkt"
    _check_connected(h, surfs[0], [c for c in first + second if c.plane_id == surfs[0].id])


def test_multi_felix_szene(h: H):
    """Multi-Szene des Artists (netz_multi): zwei Kurvenflächen mit gemeinsamer Randlinie; Strich über beide und über beide
    Außenränder hinaus, ein zweiter kreuzt eine vorhandene Linie. Alles verbunden."""
    h.load("tests/scenes/netz_multi.sketch.json")
    surfs = list(h.sc.surfaces)
    lo = np.min([_box(s)[0] for s in surfs], axis=0)
    hi = np.max([_box(s)[1] for s in surfs], axis=0)
    h.draw_mode()
    h.camera((lo + hi) / 2, float(np.linalg.norm(hi - lo)) * 1.4, [0.0, 1.0, 0.01])
    h.v.set_multi_mode(True)
    h.sc.multi_ids = [s.id for s in surfs]
    h.v._changed()
    try:
        a = _stroke_new(h, [-4.5, 0, -7.5], [11.5, 0, 12.5])  # neben der alten Linie des Artists
        b = _stroke_new(h, [2.0, 0, -6.0], [1.5, 0, 0.5])  # kreuzt die vorhandene Linie bei z ~ -3
    finally:
        h.v.set_multi_mode(False)
    assert len(a) == 2, f"{len(a)} Teilstücke"
    assert set(a[0].pids.values()) & set(a[1].pids.values()), "Übergang ist ein gemeinsamer Punkt"
    shared = (set(a[0].pids.values()) & set(a[1].pids.values())).pop()
    assert all(shared in _border_pids(h, s) for s in surfs), "Übergang liegt auf der gemeinsamen Randlinie"
    for c in a:
        surf = h.sc.object_by_id(c.plane_id)
        for k in (0, len(c.points) - 1):
            assert network.pid_of(c, k) in _border_pids(h, surf), f"Ende {c.points[k].round(2)} nicht auf dem Rand"
    old = [c for c in h.curves() if not c.paint and c not in a + b and c.plane_id == b[0].plane_id]
    hits = [o for o in old if network.crossings(b[0], o, 0.05)]
    assert hits, "Testaufbau: zweiter Strich kreuzt eine vorhandene Linie"
    assert all(set(b[0].pids.values()) & set(o.pids.values()) for o in hits), "Kreuzung ist ein gemeinsamer Punkt"


def test_erkannte_form_ueber_flaechengrenzen_verbunden(h: H):
    """netz_multi_v002 (Artist): ein Strich, am Ende stillgehalten, wird als Bogen erkannt und neu auf die Flächen
    gelegt – dabei fielen Übergänge und Ränder weg (alle Enden lose). Multi- und Einzelmodus."""
    scene = "tests/scenes/netz_multi_v002.sketch.json"
    h.load(scene)
    path = np.vstack([h.curves()[-2].points, h.curves()[-1].points])  # Bogen des Artists über beide Flächen
    d0 = (path[0] - path[5]) / np.linalg.norm(path[0] - path[5])
    d1 = (path[-1] - path[-6]) / np.linalg.norm(path[-1] - path[-6])
    pts = np.vstack([path[0] + d0 * 0.6, path[::8], path[-1] + d1 * 0.6])
    for multi in (True, False):
        h.load(scene)
        sc = h.sc
        sc.strokes[-1].curves = sc.strokes[-1].curves[:-2]  # lose Linien des Artists weg
        h.v._changed()
        surfs = list(sc.surfaces)
        lo = np.min([_box(s)[0] for s in surfs], axis=0)
        hi = np.max([_box(s)[1] for s in surfs], axis=0)
        h.draw_mode()
        h.camera((lo + hi) / 2, float(np.linalg.norm(hi - lo)) * 1.4, [0.0, 1.0, 0.01])
        if multi:
            h.v.set_multi_mode(True)
            sc.multi_ids = [s.id for s in surfs]
        else:
            h.v._activate(surfs[0])
        h.v._changed()
        before = {c.id for c in h.curves()}
        try:
            h.stroke([h.scrf(p) for p in pts], hold=True)
        finally:
            h.v.set_multi_mode(False)
        new = [c for c in h.curves() if c.id not in before and not c.paint]
        assert new, "Bogen gezeichnet"
        assert len({tuple(np.round(np.diff(c.points, axis=0).std(axis=0), 3)) for c in new}) >= 1
        for c in new:
            surf = sc.object_by_id(c.plane_id)
            border = _border_pids(h, surf)
            for k in (0, len(c.points) - 1):
                pid = network.pid_of(c, k)
                refs = network.refs_by_pid(sc)[pid]
                assert pid in border or network.degree(refs) > 1, \
                    f"{'Multi' if multi else 'Einzel'}: Ende {c.points[k].round(2)} hängt lose"
        if multi:
            assert len(new) == 2 and set(new[0].pids.values()) & set(new[1].pids.values()), "Übergang verbunden"


def test_cleanup_verbindet_lose_enden_der_alten_szenen(h: H):
    """Cleanup „Enden und Kreuzungen verbinden“ wendet die Verbindungsregel auf vorhandene Linien an: Szenen des Artists
    netz_multi_v002/_v003 (vor der Regel gezeichnet) haben danach keine losen Enden mehr nah an Linien."""
    for scene in ("tests/scenes/netz_multi_v002.sketch.json", "tests/scenes/netz_multi_v003.sketch.json"):
        h.load(scene)
        _top_view(h, h.sc.surfaces[0])
        assert network.sync(h.sc)["free_ends"] > 0, "Testaufbau: lose Enden vorhanden"
        h.v.set_cleanup_global(True)
        try:
            h.v.run_cleanup("crossings")
        finally:
            h.v.set_cleanup_global(False)
        assert network.sync(h.sc)["free_ends"] == 0, f"{scene}: {network.sync(h.sc)['free_ends']} lose Enden"


# --- Füllflächen als Netzfläche (netfill.py) ---

FILL = "tests/scenes/netz_fuellflaeche_kreuz.sketch.json"


def _fill_members(h: H, surf):
    return h.v._edge_lines(surf) + [c for c in h.curves() if not c.paint and c.plane_id == surf.id]


def _fill_off(h: H, surf):
    verts, tris = surf.fill_mesh()[:2]
    worst = 0.0
    for c in [c for c in h.curves() if not c.paint and c.plane_id == surf.id]:
        pts = c.points[np.linspace(0, len(c.points) - 1, min(len(c.points), 15)).astype(int)]
        worst = max(worst, float(_dist_to_mesh(pts, verts, tris).max()))
    return worst / _size(surf)


def _fill_draw(h: H, surf, a, b):
    h.draw_mode()
    h.v._activate(surf)
    _top_view(h, surf)
    return _stroke_new(h, a, b)


def test_fuellflaeche_kreuzung_anheben(h: H):
    """Wie Task 2, auf einer Füllfläche: zwei Linien kreuz und quer (über den Rand hinaus), Kreuzung anheben – die
    Fläche wölbt sich mit, nur der gezogene Punkt bewegt sich, alles bleibt verbunden."""
    h.load(FILL)
    surf = h.sc.surfaces[0]
    a = _fill_draw(h, surf, [-8.5, 0, -3.0], [7.0, 0, -0.5])
    b = _fill_draw(h, surf, [-3.0, 0, -9.5], [-1.0, 0, 5.0])
    lines = a + b
    assert len(a) == 1 and len(b) == 1, (len(a), len(b))
    border = {pid for c in h.v._edge_lines(surf) for pid in (c.pids or {}).values()}
    for c in lines:
        for k in (0, len(c.points) - 1):
            assert network.pid_of(c, k) in border, f"Ende {c.points[k].round(2)} nicht auf dem Umriss"
    shared = set(a[0].pids.values()) & set(b[0].pids.values())
    assert shared, "Kreuzung verbunden"
    pid = shared.pop()
    before = _positions(h)
    _move_point(h, pid, [0, 1.5, 0])
    after = _positions(h)
    moved = [p for p in before if p in after and np.linalg.norm(after[p] - before[p]) > MOVE_TOL]
    assert moved == [pid], f"{len(moved)} Punkte bewegt"
    assert surf.netmesh is not None, "Füllfläche ist eine Netzfläche"
    assert float(surf.fill_mesh()[0][:, 1].max()) > 1.2, "Fläche wölbt sich mit"
    off = _fill_off(h, surf)
    assert off < 0.01, f"Fläche liegt {off * 100:.1f} % neben ihren Linien"
    h.save_image("fuellflaeche_kreuzung.png")


def test_fuellflaeche_ecke_anheben_linien_bleiben(h: H):
    """Ecke des Umrisses anheben: die Fläche verformt sich, die Linien darauf bleiben, wo sie sind, und die Fläche geht
    weiter durch sie hindurch."""
    h.load(FILL)
    surf = h.sc.surfaces[0]
    inner = _fill_draw(h, surf, [-3.0, 0, -9.5], [-1.0, 0, 5.0])
    keep = {c.id: c.points.copy() for c in h.curves() if c.plane_id == surf.id and not c.paint}
    corner = _pid_at(h, [-6.53, 0, -8.44], tol=0.05)
    _move_point(h, corner, [0, 2.0, 0])
    for cid, pts in keep.items():
        c = h.sc.curve_by_id(cid)
        assert c is not None and np.array_equal(c.points, pts), "Linie auf der Fläche blieb stehen"
    assert float(surf.fill_mesh()[0][:, 1].max()) > 1.5, "Fläche folgt der Ecke"
    assert _fill_off(h, surf) < 0.01


def test_loft_kreuzung_anheben(h: H):
    """Wie Task 2, auf einem Loft: zwei Linien darauf kreuzen sich, Kreuzung anheben – der Loft geht mit, nur der
    gezogene Punkt bewegt sich, die Linien bleiben verbunden und auf der Fläche; Seitenlinien bleiben stehen."""
    from tests.test_topology import _loft3
    lo, secs = _loft3(h)
    rails = {cid: h.sc.curve_by_id(cid).points.copy() for cid, _ in lo.rails}
    h.draw_mode()
    h.v._activate(lo)
    h.camera([1, 1.2, 1], 5, [0.05, 1, 0.05])
    a = _stroke_new(h, [-0.3, 1.0, 0.5], [2.3, 1.0, 0.5])
    b = _stroke_new(h, [1.0, 1.0, -0.3], [1.0, 1.0, 2.3])
    assert len(a) == 1 and len(b) == 1, (len(a), len(b))
    shared = set(a[0].pids.values()) & set(b[0].pids.values())
    assert shared, "Kreuzung verbunden"
    pid = shared.pop()
    before = _positions(h)
    _move_point(h, pid, [0, 0.6, 0])
    after = _positions(h)
    moved = [p for p in before if p in after and np.linalg.norm(after[p] - before[p]) > MOVE_TOL]
    assert moved == [pid], f"{len(moved)} Punkte bewegt"
    verts, tris = lo.fill_mesh()[:2]
    for c in (h.sc.curve_by_id(a[0].id), h.sc.curve_by_id(b[0].id)):
        pts = c.points[np.linspace(0, len(c.points) - 1, 15).astype(int)]
        assert _dist_to_mesh(pts, verts, tris).max() < 0.01 * _size(lo), "Loft geht durch die Linien"
    for cid, pts in rails.items():  # Form bleibt (eingerastete Striche fügen nur Punkte ein)
        rail = h.sc.curve_by_id(cid)
        gap = max(h.sc._closest_on(type(rail)(pts, None), p)[0] for p in rail.points)
        assert gap < 1e-9, f"Seitenlinie hat sich bewegt ({gap:.2g})"


def test_fuellflaeche_ecke_loeschen_umriss_ueber_linie(h: H):
    """Wie Task 4, auf einer Füllfläche: eine Linie quer über eine Ecke, dann die Ecke löschen (Strg+Entf) – der
    Umriss läuft über die Linie, die Fläche verliert die Ecke, keine Brücke; ohne Linie: gerade Brücke (wie Task 3)."""
    h.load(FILL)
    surf = h.sc.surfaces[0]
    corner = np.array([-6.53, 0, -8.44])
    _fill_draw(h, surf, [-7.5, 0, -5.0], [-1.5, 0, -9.8])  # schneidet die Ecke ab
    assert _covers(surf, [-5.6, 0, -7.6]), "Testaufbau: Ecke gehört zur Fläche"
    n_lines = len([c for c in h.curves() if not c.paint])
    _top_view(h, surf)
    _delete_point(h, corner)
    assert not _covers(surf, [-5.6, 0, -7.6]), "Ecke ist weg"
    assert _covers(surf, [0.0, 0, -2.0]), "Rest bleibt"
    assert len([c for c in h.curves() if not c.paint]) >= n_lines - 2, "keine Brücke statt des Umrisses"
    assert not any(np.linalg.norm(c.points - corner, axis=1).min() < 0.05 for c in h.curves() if not c.paint)


def test_offener_loft_wird_kurvenflaeche_mit_ganzen_linien(h: H):
    """loft_test (Artist): ein Querschnitt hat Punkte (Stücke); gewählt ist nur ein Stück – trotzdem gehört die ganze
    Linie zum Loft. Ein offener Loft wird danach eine Kurvenfläche wie jede andere (Rand: erster Querschnitt,
    Seitenlinie, letzter Querschnitt, Seitenlinie), die mittleren Querschnitte formen sie als Linien darauf."""
    from sketch_machine import components as comp
    from sketch_machine.scene import PatchSurface
    sc = h.sc
    sc.new_stroke()
    t = np.linspace(0, 1, 40)
    rows = []
    for z, lift in ((0.0, 0.0), (3.0, 1.2), (6.0, 0.3)):
        sc.add_curve(np.stack([t * 6 - 3, lift + 0.8 * np.sin(t * np.pi), np.full_like(t, z)], axis=1), None)
        rows.append(sc.curves[-1])
    mid = rows[1]
    for k in (13, 26):  # Punkte auf dem mittleren Querschnitt -> drei Stücke
        comp.insert_point(mid, k, 0.0)
    h.v._changed()
    network.sync(sc)
    st = sc.owner_of(mid).id
    segs = comp.segments(mid)
    h.v.set_select_mode(True)
    h.v.ws.component = "edge"
    h.v.edge_selection = [("line", st, rows[0].id), ("line", st, rows[2].id)]
    h.v.seg_selection = [("seg", st, mid.id, *segs[1])]  # nur das mittlere Stück gewählt
    h.v.do_loft()
    surf = sc.surfaces[-1]
    assert isinstance(surf, PatchSurface), f"offener Loft ist {type(surf).__name__}, keine Kurvenfläche"
    assert sc.curve_by_id(mid.id) is not None and len(sc.curve_by_id(mid.id).points) == len(mid.points), \
        "mittlere Linie bleibt ganz (nicht geteilt)"
    assert sc.curve_by_id(mid.id).plane_id == surf.id, "mittlerer Querschnitt gehört als Linie zur Fläche"
    h.v._changed()
    verts, tris = surf.fill_mesh()[:2]
    size = float(np.linalg.norm(np.ptp(verts, axis=0)))
    for c in rows:
        pts = sc.curve_by_id(c.id).points[::4]
        assert _dist_to_mesh(pts, verts, tris).max() < 0.01 * size, "Fläche geht durch alle Querschnitte (ganz)"
    border = {c.id for c in sc.patch_border(surf)}
    assert rows[0].id in border and rows[2].id in border and mid.id not in border


def test_loft_aus_profilen_in_stuecken_bleibt_regelflaeche(h: H):
    """Skyscraper: Querschnitte aus mehreren Linien (U-Profil mit Knicken). Die Kurvenflächen müssen genau so liegen wie
    die Regelfläche zwischen ihnen – Ruheform und Rand nehmen dieselben Ecken in derselben Reihenfolge."""
    from sketch_machine import loft
    sc = h.sc
    sc.new_stroke()

    def u_profile(z, w, d, shift):
        a = np.linspace([-w, 0, z], [-w, d, z], 15)
        b = np.linspace([-w, d, z], [w, d, z], 30)[1:]
        c = np.linspace([w, d, z], [w, 0, z], 15)[1:]
        return np.vstack([a, b, c]) + [shift, 0, 0]

    secs = [u_profile(0, 2, 1.5, 0), u_profile(5, 1.2, 3, 0.8)]
    lines = []
    for s in secs:
        for part in (s[:15], s[14:44], s[43:]):
            sc.add_curve(part, None)
            lines.append(sc.curves[-1])
    h.v._changed()
    network.sync(sc)
    h.v.set_select_mode(True)
    h.v.ws.component = "edge"
    h.v.edge_selection = [("line", sc.owner_of(c).id, c.id) for c in lines]
    h.v.do_loft()
    h.v._changed()
    # die Knicke des U-Profils (90°) sind harte Punkte: drei Kurvenflächen (Artist 2026-11-09), zusammen die Regelfläche
    assert len(sc.surfaces) == 3 and all(isinstance(f, PatchSurface) for f in sc.surfaces),         [type(f).__name__ for f in sc.surfaces]
    ruled = loft.grid(np.array(loft.prepare(secs)[0]), 12).reshape(-1, 3)
    size = float(np.linalg.norm(np.ptp(ruled, axis=0)))
    d = np.min([_dist_to_mesh(ruled[::3], *f.fill_mesh()[:2]) for f in sc.surfaces], axis=0).max()
    assert d < 0.01 * size, f"Flächen weichen {d / size:.1%} von der Regelfläche ab"


def test_extrudieren_offen_wird_kurvenflaeche(h: H):
    """Extrudieren mit Zeichenfläche: offenes Profil -> Kurvenfläche (Rand: Original, Verbindungslinie, Kopie,
    Verbindungslinie), geschlossenes -> Röhre (Loft)."""
    from sketch_machine.scene import LoftSurface
    sc = h.sc
    for closed in (False, True):
        sc.new_stroke()
        t = np.linspace(0, 1, 40)
        if closed:
            a = t * 2 * np.pi
            pts = np.stack([2 * np.cos(a), np.zeros_like(a), 2 * np.sin(a) + 10], axis=1)
        else:
            pts = np.stack([t * 6 - 3, np.zeros_like(t), np.sin(t * np.pi * 1.5)], axis=1)
        sc.add_curve(pts, None)
        c = sc.curves[-1]
        h.v._changed()
        h.v.ws.extrude_surface = True
        h.v.set_select_mode(True)
        h.v.ws.component = "edge"
        h.v.edge_selection = [("line", sc.owner_of(c).id, c.id)]
        h.v.start_extrude()
        h.v._extrude.update(axis=np.array([0, 1.0, 0]), axis_name="y", length=3.0)
        h.v._finish_extrude()
        h.v._mode = None
        h.v._changed()
        surf = sc.surfaces[-1]
        if closed:
            assert type(surf) is LoftSurface and surf.closed, f"geschlossen: {type(surf).__name__}"
        else:
            assert isinstance(surf, PatchSurface), f"offen: {type(surf).__name__}"
            assert c.id in {x.id for x in sc.patch_border(surf)}, "Original ist Rand der Kurvenfläche"


def test_alte_offene_lofts_werden_beim_laden_kurvenflaechen(h: H):
    """Ältere Szene mit offenem Loft: nach dem Laden eine Kurvenfläche, die Querschnitte formen sie weiter."""
    import json, os, tempfile
    from sketch_machine.scene import Scene, LoftSurface
    from sketch_machine import loft
    sc = h.sc
    sc.new_stroke()
    t = np.linspace(0, 1, 40)
    rows = []
    for z, lift in ((0.0, 0.0), (3.0, 1.2), (6.0, 0.3)):
        sc.add_curve(np.stack([t * 6 - 3, lift + 0.8 * np.sin(t * np.pi), np.full_like(t, z)], axis=1), None)
        rows.append(sc.curves[-1])
    h.v._changed()
    network.sync(sc)
    old = sc.loft_to_patch
    sc.loft_to_patch = lambda s: None  # so entstand er früher: als Loft
    try:
        h.v.set_select_mode(True)
        h.v.ws.component = "edge"
        h.v.edge_selection = [("line", sc.owner_of(c).id, c.id) for c in rows]
        h.v.do_loft()
    finally:
        del sc.loft_to_patch
    surf = sc.surfaces[-1]
    assert type(surf) is LoftSurface
    h.v._changed()
    g = surf.grid()
    path = os.path.join(tempfile.mkdtemp(), "alt.sketch.json")
    sc.save(path)
    new = Scene.load(path)[0]
    patch = next(s for s in new.surfaces if s.name.startswith(tr("Kurvenfläche")))
    assert isinstance(patch, PatchSurface) and not any(type(s) is LoftSurface for s in new.surfaces)
    new.sync_lofts()
    verts, tris = patch.fill_mesh()[:2]
    size = float(np.linalg.norm(np.ptp(g.reshape(-1, 3), axis=0)))
    assert _dist_to_mesh(g.reshape(-1, 3)[::7], verts, tris).max() < 0.01 * size, "Form bleibt"


def test_frei_strich_verbindet_ausdruecklich(h: H):
    """Frei-Modus (Q): Strich vom Ende einer Linie zu einer Linie in anderer Tiefe – beide Enden sind danach mit
    gemeinsamen Punkten verbunden (über die eine Verbindungsregel, nicht über die Lage)."""
    sc = h.sc
    sc.new_stroke()
    sc.add_curve(np.linspace([-3, 0, 0], [0, 0, 0], 20), None)
    a = sc.curves[-1]
    sc.add_curve(np.linspace([2, -2, 4], [2, 3, 4], 20), None)
    b = sc.curves[-1]
    h.v._changed()
    h.frame(np.vstack([a.points, b.points]), back=(0.2, 0.3, 1.0))
    h.draw_mode()
    h.v.ws.magnet = True
    h.v.set_free_draw(True)
    try:
        start, end = h.scrf(a.points[-1]), h.scrf(b.points[10])
        mid = (start + end) / 2 + QPointF(0, -40)
        h.stroke([start, mid, end])
    finally:
        h.v.set_free_draw(False)  # das Fenster wird von den nächsten Tests weiterbenutzt
    network.sync(sc)
    new = [c for c in h.curves() if c is not a and c is not b and not c.paint]
    assert len(new) == 1, f"{len(new)} neue Linien"
    c = new[0]
    refs = network.refs_by_pid(sc)
    p0, p1 = network.pid_of(c, 0), network.pid_of(c, len(c.points) - 1)
    assert p0 == network.pid_of(a, len(a.points) - 1), "Start teilt den Punkt mit dem Linienende"
    assert network.degree(refs[p1]) >= 2 and p1 in (b.pids or {}).values(), "Ende ist ein Punkt auf der anderen Linie"
    assert np.linalg.norm(c.points[-1] - sc.curve_by_id(b.id).points[[k for k, p in b.pids.items() if p == p1][0]]) < 1e-9


def _square_with_gap(h: H, gap):
    """Quadrat aus vier Linien (Kante 4), an einer Ecke um gap offen; die anderen Ecken sind gemeinsame Punkte."""
    sc = h.sc
    sc.new_stroke()
    c = [[0, 0, 0], [4, 0, 0], [4, 0, 4], [0, 0, 4]]
    lines = []
    for i in range(4):
        a, b = np.array(c[i], float), np.array(c[(i + 1) % 4], float)
        if i == 3:
            b = b + [gap, 0, 0]  # letzte Linie endet kurz vor der Ecke
        sc.add_curve(np.linspace(a, b, 30), None)
        lines.append(sc.curves[-1])
    network.sync(sc)
    for i in range(3):
        network.join(sc, lines[i], len(lines[i].points) - 1, lines[i + 1], 0)
    h.v._changed()
    h.v.set_select_mode(True)
    h.v.ws.component = "edge"
    h.v.edge_selection = [("line", sc.owner_of(x).id, x.id) for x in lines]
    return lines


def test_flaeche_kleine_luecke_wird_gemeinsamer_punkt(h: H):
    """Lückenregel: Lücke unter 2 % der kürzeren Linie -> die Enden werden ein gemeinsamer Punkt (in der Mitte),
    keine neue Linie; die Fläche entsteht."""
    lines = _square_with_gap(h, 0.04)  # 1 % von 4
    before = len(h.curves())
    h.v.do_fill()
    assert len(h.curves()) == before, "keine Brücke"
    a, b = lines[3], lines[0]
    assert network.pid_of(a, len(a.points) - 1) == network.pid_of(b, 0), "Ecke ist ein gemeinsamer Punkt"
    assert np.allclose(a.points[-1], [0.02, 0, 0], atol=1e-6), "Treffen in der Mitte"
    assert any(type(s).__name__ == "SurfaceObject" for s in h.sc.surfaces)


def test_flaeche_grosse_luecke_wird_echte_linie(h: H):
    """Lückenregel: größere Lücke -> eine echte gerade Linie, an beiden Enden mit gemeinsamen Punkten verbunden."""
    lines = _square_with_gap(h, 1.0)
    before = len(h.curves())
    h.v.do_fill()
    new = [c for c in h.curves() if not any(c is x for x in lines)]
    assert len(h.curves()) == before + 1 and len(new) == 1, "eine Brücke"
    br = new[0]
    ends = {network.pid_of(br, 0), network.pid_of(br, len(br.points) - 1)}
    assert ends == {network.pid_of(lines[3], len(lines[3].points) - 1), network.pid_of(lines[0], 0)}
    assert np.allclose(lines[0].points[0], [0, 0, 0]), "der Rest bleibt, wo er ist"
    surf = h.sc.surfaces[-1]
    assert br.id in {cid for cid, _ in surf.links}, "Brücke gehört zum Umriss"


def test_kurvenflaeche_mit_luecke(h: H):
    """Alt+F nimmt dieselbe Lückenregel: offenes Quadrat ergibt eine Kurvenfläche samt Brücke."""
    lines = _square_with_gap(h, 1.0)
    h.v.do_patch()
    surf = h.sc.surfaces[-1]
    assert isinstance(surf, PatchSurface), "Kurvenfläche entsteht trotz Lücke"
    assert len(h.sc.patch_border(surf)) == 5


def _outline(h: H, poly):
    """Geschlossener, verbundener Umriss aus geraden Linien in der XZ-Ebene, alle gewählt."""
    sc = h.sc
    sc.new_stroke()
    pts = [np.array([x, 0.0, z]) for x, z in poly]
    lines = []
    for i in range(len(pts)):
        sc.add_curve(np.linspace(pts[i], pts[(i + 1) % len(pts)], 25), None)
        lines.append(sc.curves[-1])
    network.sync(sc)
    for i in range(len(lines)):
        network.join(sc, lines[i], 24, lines[(i + 1) % len(lines)], 0)
    h.v._changed()
    h.camera([2, 0, 2], 9, [0, 1, 0.01])
    h.edit_mode("edge")
    h.v.edge_selection = [("line", sc.owner_of(c).id, c.id) for c in lines]
    return lines


def test_f_ist_ein_flaechen_befehl(h: H):
    """F: Kurvenfläche, wenn ihr Gitter nicht faltet (auch Drei-, Sechseck); nach innen geknickter Umriss (L-Form)
    -> Füllfläche, ohne Falten. Ein Undo-Schritt nimmt alles zurück."""
    from sketch_machine.scene import SurfaceObject
    hexagon = [[2 * np.cos(a), 2 * np.sin(a)] for a in np.linspace(0, 2 * np.pi, 7)[:-1]]
    for poly, kind in (([[0, 0], [4, 0], [2, 3.5]], PatchSurface), (hexagon, PatchSurface),
                       ([[0, 0], [4, 0], [4, 1.5], [1.5, 1.5], [1.5, 4], [0, 4]], SurfaceObject)):
        h.new_scene()
        _outline(h, poly)
        h.key(Qt.Key_F)
        assert len(h.sc.surfaces) == 1, f"{len(h.sc.surfaces)} Flächen"
        s = h.sc.surfaces[0]
        assert type(s) is kind, f"{len(poly)}-Eck: {type(s).__name__} statt {kind.__name__}"
        v, t = s.fill_mesh()[:2]
        n = np.cross(v[t][:, 1] - v[t][:, 0], v[t][:, 2] - v[t][:, 0])[:, 1]
        p = np.array(poly)
        true = 0.5 * abs(np.dot(p[:, 0], np.roll(p[:, 1], 1)) - np.dot(p[:, 1], np.roll(p[:, 0], 1)))
        assert abs(0.5 * np.abs(n).sum() - true) < 0.01 * true, "Fläche deckt genau den Umriss (keine Falte)"
    h.v.undo()
    assert not h.sc.surfaces, "ein Undo-Schritt"


def _pick_lines(h: H, lines):
    """Linien nacheinander wählen (wie Shift+Klick im Kantenmodus) – die Reihenfolge wird gemerkt."""
    h.edit_mode("edge")
    h.v.selection = []
    h.v.edge_selection = []
    h.v._track_pick_order()
    for c in lines:
        h.v.edge_selection = h.v.edge_selection + [("line", h.sc.owner_of(c).id, c.id)]
        h.v._track_pick_order()


def test_loft_reihenfolge_wie_gewaehlt_und_mitte_formt(h: H):
    """Skyscraper-Test 2 (Artist): zwei Querschnitte unten, ein stark geschwungener oben, dessen Mittelpunkt zwischen den
    anderen liegt. Gewählt unten, unten, oben -> genau diese Reihenfolge (geraten wäre der obere in der Mitte). Der
    mittlere Querschnitt liegt danach exakt auf der Kurvenfläche, auch wenn er weit von der rohen Fläche abweicht."""
    sc = h.sc
    sc.new_stroke()
    t = np.linspace(0, 1, 60)
    a = np.stack([6 + 1.5 * t, np.zeros_like(t), -0.6 + 10.6 * t], 1)
    b = np.stack([2.2 - 3.7 * t, np.full_like(t, 2.5), 1.2 + 7.9 * t], 1)
    c = np.stack([2.1 + 0.9 * t + 1.2 * np.sin(t * 3 * np.pi), np.full_like(t, 3.8), 5.4 - 5.6 * t], 1)
    for p in (a, b, c):
        sc.add_curve(p, None)
    la, lb, lc = sc.curves[-3:]
    h.v._changed()
    from sketch_machine import loft as L
    guess = L.order([la.points, lb.points, lc.points])
    assert guess[1] == 2, "Testaufbau: geraten läge der obere in der Mitte"
    _pick_lines(h, [la, lb, lc])
    h.v.do_loft()
    h.v._changed()
    s = sc.surfaces[-1]
    assert isinstance(s, PatchSurface)
    border = {x.id for x in sc.patch_border(s)}
    assert la.id in border and lc.id in border and lb.id not in border, "erster und letzter wie gewählt"
    assert sc.curve_by_id(lb.id).plane_id == s.id, "mittlerer Querschnitt formt die Fläche"
    verts, tris = s.fill_mesh()[:2]
    size = float(np.linalg.norm(np.ptp(verts, axis=0)))
    dd = _dist_to_mesh(sc.curve_by_id(lb.id).points, verts, tris)
    from sketch_machine import netsurf, components
    att = s.attached[lb.id]
    idx = netsurf.samples(lb.points, att["uv"], att.get("on"), components.knots(lb))
    d = dd.max()
    # direkt neben der Seitenlinie halten Rand und Querschnitt denselben Gitterknoten: dort mittelt die Lösung leicht
    assert d < 0.005 * size, f"mittlerer Querschnitt {d / size:.2%} neben der Fläche (an Stützstellen {dd[idx].max() / size:.2%}, bei Punkt {int(np.argmax(dd))} von {len(dd)}, Stützstellen {len(idx)})"


def test_loft_stark_gewoelbte_mitte_liegt_auf_der_flaeche(h: H):
    """Mittlerer Querschnitt weit über der rohen Fläche (Coons aus dem Rand allein): er wird nicht über die Nähe gebunden,
    sondern über seine Lage im Loft – die Kurvenfläche geht genau durch ihn, an jedem Punkt der Linie."""
    sc = h.sc
    sc.new_stroke()
    rows = []
    for z, lift in ((0.0, 0.0), (3.0, 3.0), (6.0, 0.0)):
        x = np.linspace(-3, 3, 11)  # grob gezeichnet: wenige Punkte, deutliche Ecken der Polylinie
        sc.add_curve(np.stack([x, lift * (1 - (x / 3) ** 2), np.full_like(x, z)], 1), None)
        rows.append(sc.curves[-1])
    h.v._changed()
    _pick_lines(h, rows)
    h.v.do_loft()
    h.v._changed()
    s = sc.surfaces[-1]
    mid = sc.curve_by_id(rows[1].id)
    assert mid.plane_id == s.id
    verts, tris = s.fill_mesh()[:2]
    size = float(np.linalg.norm(np.ptp(verts, axis=0)))
    d = _dist_to_mesh(mid.points, verts, tris)
    assert d.max() < 0.003 * size, f"Punkte neben der Fläche: {np.round(d / size, 4)}"


def test_loft_gewaehlte_flaeche_zaehlt_im_kantenmodus_nicht(h: H):
    """Nach einem Loft bleibt die neue Fläche gewählt. Wählt man danach im Kantenmodus Linien für den nächsten Loft,
    darf sie nicht als zusätzlicher Querschnitt mitzählen."""
    sc = h.sc
    sc.new_stroke()
    x = np.linspace(-2, 2, 20)
    lines = []
    for z in (0.0, 3.0, 10.0, 13.0):
        sc.add_curve(np.stack([x, np.zeros_like(x), np.full_like(x, z)], 1), None)
        lines.append(sc.curves[-1])
    h.v._changed()
    _pick_lines(h, lines[:2])
    h.v.do_loft()
    first = sc.surfaces[-1]
    assert h.v.selection == [first.id]
    h.v.edge_selection = []
    h.v._track_pick_order()
    for c in lines[2:]:
        h.v.edge_selection = h.v.edge_selection + [("line", sc.owner_of(c).id, c.id)]
        h.v._track_pick_order()
    h.v.do_loft()
    second = sc.surfaces[-1]
    assert second is not first
    verts = second.fill_mesh()[0]
    assert verts[:, 2].min() > 9.9, "zweiter Loft nur durch seine zwei Linien"


def test_loft_querschnitt_aus_stuecken_ueber_punkte(h: H):
    """Ein Querschnitt aus zwei Stücken, die sich einen Punkt teilen, ist ein Querschnitt – zusammengefasst über das
    Kurvennetz, auch in der Mitte der Auswahl."""
    sc = h.sc
    sc.new_stroke()
    sc.add_curve(np.linspace([-2, 0, 0], [2, 0, 0], 20), None)
    a = sc.curves[-1]
    sc.add_curve(np.linspace([-2, 1, 3], [0, 1.5, 3], 10), None)
    m1 = sc.curves[-1]
    sc.add_curve(np.linspace([0, 1.5, 3], [2, 1, 3], 10), None)
    m2 = sc.curves[-1]
    sc.add_curve(np.linspace([-2, 0, 6], [2, 0, 6], 20), None)
    b = sc.curves[-1]
    network.sync(sc)
    network.join(sc, m1, len(m1.points) - 1, m2, 0)
    h.v._changed()
    _pick_lines(h, [a, m1, m2, b])
    h.v.do_loft()
    h.v._changed()
    s = sc.surfaces[-1]
    assert isinstance(s, PatchSurface)
    border = {x.id for x in sc.patch_border(s)}
    assert a.id in border and b.id in border and m1.id not in border and m2.id not in border
    assert sc.curve_by_id(m1.id).plane_id == s.id and sc.curve_by_id(m2.id).plane_id == s.id

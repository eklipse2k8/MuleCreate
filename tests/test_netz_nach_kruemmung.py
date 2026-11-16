"""Angezeigtes Netz nach Krümmung: eine ebene Fläche bekommt wenige Dreiecke, eine gebogene so viele, wie ihre Form
braucht – unabhängig von der Größe und von der Punktzahl ihrer Linien. Die Form selbst (Rechengitter, Malerei, Rand)
bleibt unberührt; der Regler der Fläche stellt von da aus feiner oder gröber."""
import numpy as np

from sketch_machine import loft, network
from sketch_machine.scene import SurfaceObject
from sketch_machine.viewport import _dist_to_triangles_fast
from tests.harness import H, line
from tests.test_material import _square


def _patch(h, sides):
    sc = h.sc
    sc.new_stroke()
    lines = []
    for sd in sides:
        sc.add_curve(sd, None)
        lines.append(sc.curves[-1])
    network.sync(sc)
    patch = sc.create_patch(lines)
    h.v._changed()
    return patch


def _flat_sides(size, n):
    p = [np.array(q, float) * size for q in ([0, 0, 0], [1, 0, 0], [1, 0, 1], [0, 0, 1])]
    return [line(p[k], p[(k + 1) % 4], n) for k in range(4)]


def test_ebene_flaeche_wenige_dreiecke_egal_wie_gross_und_wie_gezeichnet(h: H):
    h.new_scene()
    counts = []
    for size, n in ((1.0, 8), (500.0, 8), (1.0, 120)):  # klein, groß, mit sehr vielen Punkten gezeichnet
        patch = _patch(h, _flat_sides(size, n))
        counts.append(len(patch.fill_mesh()[1]))
    assert max(counts) <= 8, f"eben: wenige Dreiecke ({counts})"
    assert counts[0] == counts[1] == counts[2], "nicht abhängig von Größe oder Punktzahl der Linien"


def test_gebogene_flaeche_bleibt_an_der_form(h: H):
    h.new_scene()
    t = np.linspace(0, 1, 24)
    arc = lambda z: np.stack([np.cos(t * np.pi) * 2, np.sin(t * np.pi) * 2, np.full_like(t, z)], 1)  # Halbrohr
    patch = _patch(h, [arc(0.0), line([-2, 0, 0], [-2, 0, 3], 8), arc(3.0)[::-1], line([2, 0, 3], [2, 0, 0], 8)])
    verts, tris = patch.fill_mesh()[:2]
    full = loft.build(None, False, g=patch.grid())  # das Rechengitter selbst
    size = float(np.linalg.norm(np.ptp(full[0], axis=0)))
    assert len(tris) < len(full[1]) / 3, f"deutlich weniger Dreiecke als das Rechengitter ({len(tris)} statt {len(full[1])})"
    assert len(tris) >= 20, "die Biegung braucht ihre Unterteilungen"
    dist = _dist_to_triangles_fast(full[0], verts[tris]).max()
    assert dist <= 1.5 * loft.ADAPT_TOL * size, f"höchstens ein Tausendstel der Größe neben der Form ({dist / size:.5f})"
    # gerade Richtung: nicht unterteilt – die Punkte entlang der Geraden liegen auf einer Linie
    assert len(verts) <= len(full[0]) / 3


def test_regler_stellt_feiner_und_groeber(h: H):
    h.new_scene()
    t = np.linspace(0, 1, 24)
    arc = lambda z: np.stack([np.cos(t * np.pi) * 2, np.sin(t * np.pi) * 2, np.full_like(t, z)], 1)
    patch = _patch(h, [arc(0.0), line([-2, 0, 0], [-2, 0, 3], 8), arc(3.0)[::-1], line([2, 0, 3], [2, 0, 0], 8)])
    n1 = len(patch.fill_mesh()[1])
    h.v.set_surface_resolution(patch.id, 2.0)
    h.v._changed()
    n2 = len(patch.fill_mesh()[1])
    h.v.set_surface_resolution(patch.id, 0.5)
    h.v._changed()
    n05 = len(patch.fill_mesh()[1])
    h.v.set_surface_resolution(patch.id, 1.0)
    h.v._changed()
    assert n05 < n1 < n2 and len(patch.fill_mesh()[1]) == n1, (n05, n1, n2)


def test_ebene_fuellflaeche_zeigt_nur_ihren_rand_bis_sie_sich_woelbt(h: H):
    h.new_scene()
    sc = h.sc
    f = _square(h, y=0.0, x0=0.0, size=3.0)
    dense = len(f.netmesh[1])
    verts, tris = f.fill_mesh()[:2]
    assert len(tris) <= 8 and dense > 100 * len(tris), f"eben: {len(tris)} statt {dense} Dreiecke"
    area = lambda v, t: float(np.linalg.norm(np.cross(v[t[:, 1]] - v[t[:, 0]], v[t[:, 2]] - v[t[:, 0]]), axis=1).sum() / 2)
    assert abs(area(verts, tris) - 9.0) < 1e-9, "derselbe Rand, dieselbe Fläche (Ecken bleiben Ecken)"
    edge = next(c for c in sc.curves if any(i == c.id for cid, _ in f.links for i in sc.link_ids(cid)))
    bent = edge.points.copy()
    bent[len(bent) // 2] += [0.0, 0.6, 0.0]
    edge.points = bent
    h.v._changed()
    assert len(f.fill_mesh()[1]) > 1000, "gewölbt: das dichte Netz"


def test_abschaltbar_wie_vorher(h: H):
    h.new_scene()
    patch = _patch(h, _flat_sides(2.0, 12))
    try:
        SurfaceObject.auto_res = False
        h.v._changed()
        assert len(patch.fill_mesh()[1]) > 100, "ohne: das Netz in der Dichte des Rechengitters"
    finally:
        SurfaceObject.auto_res = True
    h.v._changed()
    assert len(patch.fill_mesh()[1]) <= 8


def test_einteilung_gilt_fuer_die_verschobene_flaeche_weiter(h: H):
    """Verschoben oder gleichmäßig skaliert: dieselbe Form – dieselbe Einteilung, ohne sie neu zu suchen."""
    u, v = np.meshgrid(np.linspace(0, 1, 40), np.linspace(0, 1, 30), indexing="ij")
    g = np.stack([u, 0.3 * np.sin(3 * u) * np.cos(2 * v), v], axis=2)
    for k, off in ((1.0, np.array([120.0, -40.0, 7.0])), (2.5, np.array([-3.0, 0.5, 11.0]))):
        moved = k * g + off
        loft._PLANS.clear()
        first = loft.adaptive_grid(g, 1.0, False)
        assert len(loft._PLANS) == 1
        again = loft.adaptive_grid(moved, 1.0, False)
        assert len(loft._PLANS) == 1, "verschoben/skaliert: gemerkte Einteilung trifft"
        loft._PLANS.clear()
        fresh = loft.adaptive_grid(moved, 1.0, False)
        assert again.shape == fresh.shape == first.shape and np.allclose(again, fresh), "wie neu gesucht"
        assert np.allclose(again, k * first + off, atol=1e-6)
    bent = g.copy()
    bent[20:, :, 1] += 0.2  # andere Form: eigene Einteilung
    loft.adaptive_grid(g, 1.0, False)
    loft.adaptive_grid(bent, 1.0, False)
    assert len(loft._PLANS) == 2
    a = np.radians(35.0)  # gedreht: richtig, auch wenn dafür neu gesucht wird
    rot = np.array([[np.cos(a), -np.sin(a), 0], [np.sin(a), np.cos(a), 0], [0, 0, 1]])
    turned = loft.adaptive_grid(g @ rot.T, 1.0, False)
    loft._PLANS.clear()
    assert np.allclose(turned, loft.adaptive_grid(g @ rot.T, 1.0, False))

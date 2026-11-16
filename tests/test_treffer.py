"""Der Stift trifft die Fläche, wie sie jetzt ist (zshape_test des Artists): Z-förmige Füllfläche flach angelegt und
angeklickt, dann Umrisslinien angehoben bzw. abgesenkt, dann gerade Striche von oben darüber. Früher traf der Stift die
alte, flache Form (Raster der genauen Treffer hing nur am Dreiecks-Array, und Netzflächen behalten das bei jeder
Formänderung): die Linien lagen neben der Fläche, wurden an falschen Stellen geteilt (Zacken), Stücke fielen von der
Fläche ab, und die Fläche verbog sich zu den falschen Punkten hin."""
import numpy as np

from tests.harness import H, line
from tests.test_rand import _join_ends
from tests.test_loft import _size
from sketch_machine import network
from sketch_machine.scene import PatchSurface
from sketch_machine.vp.snapping import _point_mesh_distance

# Z im Grundriss (x, z): oberer Balken, Diagonale, unterer Balken
Z = [[0, 0], [6, 0], [6, 1.5], [2.5, 4.5], [6, 4.5], [6, 6], [0, 6], [0, 4.5], [3.5, 1.5], [0, 1.5]]
UP, DOWN = 2, 7  # Diagonale rechts oben anheben, links unten absenken (Umrisslinie k: Z[k] -> Z[k+1])


def _z_fill(h: H, kind="fill"):
    """Flache Z-Füllfläche (y = 0) bzw. Kurvenfläche aus einem Quadrat, aktiv, einmal angeklickt. -> (Fläche, Umriss)"""
    sc = h.new_scene()
    sc.new_stroke()
    P = [np.array([x, 0.0, z]) for x, z in Z] if kind == "fill" else \
        [np.array(p, float) for p in ([0, 0, 0], [6, 0, 0], [6, 0, 6], [0, 0, 6])]
    lines = []
    for a, b in zip(P, P[1:] + P[:1]):
        sc.add_curve(line(a, b, 31), None)
        lines.append(sc.curves[-1])
    _join_ends(sc, lines)
    surf = sc.create_fill([(c, False) for c in lines]) if kind == "fill" else sc.create_patch(lines)
    sc.sync_lofts()
    h.v._changed()
    h.draw_mode()
    h.v._activate(surf)
    h.camera([3, 0, 3], 13.0, [0.0, 1.0, 0.15])  # von oben
    h.v._surface_hit(h.scrf(np.array([1.0, 0.0, 0.75])))  # flach angeklickt
    return surf, lines


def _bend(h: H, lines, which=((UP, 0.8), (DOWN, -1.1))):
    """Umrisslinien in der Mitte anheben/absenken (Enden bleiben, wie beim Ziehen eines Punkts)."""
    for k, amount in which:
        c = lines[k]
        c.points = c.points.copy()
        c.points[:, 1] += amount * np.sin(np.linspace(0, np.pi, len(c.points)))
    h.v._changed()
    h.sc.sync_lofts()
    h.grab()


def test_stift_trifft_die_jetzige_form(h: H):
    for kind, bend in (("fill", ((UP, 0.8), (DOWN, -1.1))), ("patch", ((0, 0.8), (2, -1.1)))):
        surf, lines = _z_fill(h, kind)
        for step in range(3):
            _bend(h, lines, tuple((k, a * (step + 1) / 3) for k, a in bend))
            verts, tris = surf.fill_mesh()[:2]
            for x, z in ((1.0, 0.75), (3.0, 3.0), (5.0, 5.25), (4.0, 0.6)):
                hit = h.v._surface_hit(h.scrf(np.array([x, 0.0, z])))
                assert hit is not None, f"{kind}: kein Treffer bei {x}, {z}"
                d = _point_mesh_distance(hit, verts, tris)
                assert d < 1e-4 * _size(verts), f"{kind}, Schritt {step}: Treffer {d:.3f} neben der Fläche (alte Form)"


def _straight(h: H, a, b, over=0.3):
    """Gerader Strich von oben, an beiden Enden etwas über den Rand hinaus. -> neue Linien"""
    a, b = np.array(a, float), np.array(b, float)
    d = (b - a) / np.linalg.norm(b - a)
    a, b = a - over * d, b + over * d
    before = {c.id for c in h.curves()}
    h.stroke_world(np.array([a + t * (b - a) for t in np.linspace(0, 1, 40)]))
    h.sc.sync_lofts()
    return [c for c in h.curves() if c.id not in before and not c.paint]


def test_gerade_striche_ueber_die_verformte_z_flaeche(h: H):
    """zshape_test des Artists: jeder gerade Strich wird genau eine Linie auf der Fläche, von Rand zu Rand, ohne Sprünge;
    die Fläche bleibt, wie sie war (die Linie liegt ja auf ihr)."""
    sc = h.sc
    surf, lines = _z_fill(h)
    _bend(h, lines)
    border_pids = lambda: {p for c in lines for p in (c.pids or {}).values()}
    for a, b in (([0, 0, 0.75], [6, 0, 0.75]),       # über den oberen Balken
                 ([1.75, 0, 3.0], [4.25, 0, 3.0]),   # quer über die Diagonale (über beide schrägen Ränder)
                 ([0, 0, 5.25], [6, 0, 5.25])):      # über den unteren Balken
        verts0 = surf.fill_mesh()[0].copy()
        new = _straight(h, a, b)
        assert len(new) == 1, f"Strich {a}->{b}: {len(new)} Linien statt einer ({[c.plane_id for c in new]})"
        c = new[0]
        assert c.plane_id == surf.id, "die Linie gehört zur Fläche"
        verts, tris = surf.fill_mesh()[:2]
        size = _size(verts)
        off = max(_point_mesh_distance(p, verts, tris) for p in c.points) / size
        assert off < 0.002, f"Strich {a}->{b} läuft {off:.1%} neben der Fläche"
        steps = np.linalg.norm(np.diff(c.points, axis=0), axis=1)
        assert steps.max() < 0.1 * steps.sum(), f"Strich {a}->{b} springt ({steps.max():.2f} von {steps.sum():.2f})"
        network.sync(sc)
        n = len(c.points)
        assert c.pids.get(0) in border_pids() and c.pids.get(n - 1) in border_pids(), "Enden am Rand"
        inner = [k for k, p in c.pids.items() if 0 < k < n - 1 and p in border_pids()]
        assert not inner, f"Linie hängt mittendrin am Rand ({inner})"
        moved = float(np.abs(verts - verts0).max()) / size if verts.shape == verts0.shape else 1.0
        assert moved < 0.005, f"Strich {a}->{b} verformt die Fläche ({moved:.1%})"


def test_strich_bleibt_auf_der_aktiven_flaeche(h: H):
    """Zwei Flächen mit gemeinsamer Kante (leicht geknickt, wie zwei Flügel-Paneele): ein Strich von der aktiven Fläche
    über die Kante hinweg, der draußen endet, wird an der Kante abgeschnitten (glider_owl des Artists: Strich auf
    Kurvenfläche 8 lief auf Kurvenfläche 3 weiter). Ein Abstecher, der zurückkommt, bleibt (test_rand, Z-Strich).
    Gilt für Freihand und Gerade (am Ende stillhalten)."""
    for hold in (False, True):
        sc = h.new_scene()
        sc.new_stroke()
        a = [np.array(p, float) for p in ([0, 0, 0], [3, 0, 0], [3, 0, 3], [0, 0, 3])]
        b = [np.array(p, float) for p in ([3, 0, 0], [6, 0.6, 0], [6, 0.6, 3], [3, 0, 3])]
        surfs = []
        for quad in (a, b):
            lines = []
            for p, q in zip(quad, quad[1:] + quad[:1]):
                sc.add_curve(line(p, q, 16), None)
                lines.append(sc.curves[-1])
            _join_ends(sc, lines)
            surfs.append(sc.create_fill([(c, False) for c in lines]))
        sc.sync_lofts()
        h.v._changed()
        h.draw_mode()
        h.camera([3, 0, 1.5], 12.0, [0.0, 1.0, 0.15])
        h.v._activate(surfs[0])
        h.v._surface_hit(h.scrf(np.array([1.0, 0.0, 1.5])))
        before = {c.id for c in h.curves()}
        h.stroke([h.scrf(np.array([0.8, 0.0, 1.5])), h.scrf(np.array([5.2, 0.42, 1.6]))], hold=hold)
        new = [c for c in h.curves() if c.id not in before and not c.paint]
        assert new, "Strich auf der aktiven Fläche"
        x = max(float(c.points[:, 0].max()) for c in new)
        assert x < 3.05, f"{'Gerade' if hold else 'Freihand'}: Strich läuft bis x = {x:.2f} auf die Nachbarfläche"

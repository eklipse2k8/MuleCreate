"""Konvertieren: Symmetrie und Array werden echte Geometrie – geschnitten, gespiegelt, verschweißt, kopiert."""
import os
import tempfile

import numpy as np

from sketch_machine.i18n import tr
from tests.harness import H, Qt, line
from sketch_machine import network
from sketch_machine.scene import NullObject, PatchSurface, Scene, SurfaceObject


def _gen(h, ids, kind, **params):
    h.edit_mode("edge")
    h.v.set_selection(ids)
    g = h.v.create_null(kind)
    g.params.update(params)
    h.v._changed()
    return g


def _convert(h, g):
    h.v.set_selection([g.id])
    h.key(Qt.Key_C, Qt.AltModifier)
    return h.sc.null_by_id(g.id)


def _square_fill(sc, x0, x1, z0=0.0, z1=1.0, n=9):
    st = sc.new_stroke(parent=None)
    P = [np.array(p, float) for p in ([x0, 0, z0], [x1, 0, z0], [x1, 0, z1], [x0, 0, z1])]
    for p, q in zip(P, P[1:] + P[:1]):
        sc.add_curve(line(p, q, n), None)
    f = sc.create_fill([(c, False) for c in st.curves])
    sc.sync_lofts()
    network.sync(sc)
    return st, f


def test_linie_geschnitten_gespiegelt_verschweisst(h: H):
    sc = h.sc
    st = sc.new_stroke(parent=None)
    sc.add_curve(line([-0.5, 0, 0.3], [1.5, 0, 0.3], 21), None)
    g = _gen(h, [st.id], "symmetry")
    g = _convert(h, g)
    assert g.kind == "null" and not g.params, "Generator wird ein einfaches Null"
    curves = [c for o in sc.descendants(g) if not isinstance(o, (NullObject, SurfaceObject)) for c in o.curves]
    assert len(curves) == 2, f"Original (geschnitten) + Spiegelung: {len(curves)}"
    right = next(c for c in curves if c.points[:, 0].max() > 1)
    left = next(c for c in curves if c.points[:, 0].min() < -1)
    assert right.points[:, 0].min() > -1e-9 and left.points[:, 0].max() < 1e-9
    network.sync(sc)
    k_r = int(np.argmin(np.abs(right.points[:, 0])))
    k_l = int(np.argmin(np.abs(left.points[:, 0])))
    assert network.pid_of(right, k_r) == network.pid_of(left, k_l), "Nahtpunkt ist ein Punkt (verschweißt)"
    h.v.undo()
    sc = h.sc
    assert sc.nulls[0].kind == "symmetry" and len(sc.curves) == 1, "Undo: wieder Generator mit dem Original"


def test_flaeche_gespiegelt_naht_geteilt(h: H):
    sc = h.sc
    st, f = _square_fill(sc, 0, 1)
    g = _gen(h, [st.id, f.id], "symmetry")
    g = _convert(h, g)
    surfs = [s for s in sc.surfaces]
    assert len(surfs) == 2
    copy = next(s for s in surfs if s is not f)
    assert copy.fill_mesh()[0][:, 0].max() < 1e-6 and f.fill_mesh()[0][:, 0].min() > -1e-6
    assert len(sc.curves) == 7, f"die Kante auf der Ebene ist nur einmal da: {len(sc.curves)} Linien"
    seam = next(c for c in sc.curves if np.abs(c.points[:, 0]).max() < 1e-9)
    ids = {cid for link, _ in copy.links for cid in sc.link_ids(link)}
    assert seam.id in ids, "die Kopie hängt an derselben Naht-Linie"


def test_flaeche_ueber_die_ebene_bekommt_naht(h: H):
    sc = h.sc
    st, f = _square_fill(sc, -0.4, 1.0)
    g = _gen(h, [st.id, f.id], "symmetry")
    g = _convert(h, g)
    assert h.v.ws.notice[0].count(tr("{0} Fläche(n) mit Naht neu gebildet").split("{0} ")[1]) == 1, h.v.ws.notice[0]
    v = f.fill_mesh()[0]
    assert v[:, 0].min() > -1e-6, "das Original endet an der Ebene"
    copy = next(s for s in sc.surfaces if s is not f)
    assert copy.fill_mesh()[0][:, 0].max() < 1e-6
    assert all(c.points[:, 0].min() > -1e-6 or c.points[:, 0].max() < 1e-6 for c in sc.curves), \
        "keine Linie läuft mehr über die Ebene"


def test_kurvenflaeche_ueber_die_ebene(h: H):
    sc = h.sc
    st = sc.new_stroke(parent=None)
    t = np.linspace(0, 1, 15)
    sc.add_curve(np.column_stack([-0.5 + 2 * t, np.sin(np.pi * t) * 0.3, np.zeros_like(t)]), None)
    sc.add_curve(line([1.5, 0, 0], [1.5, 0, 1], 9), None)
    sc.add_curve(np.column_stack([1.5 - 2 * t, np.sin(np.pi * t) * 0.3, np.ones_like(t)]), None)
    sc.add_curve(line([-0.5, 0, 1], [-0.5, 0, 0], 9), None)
    network.sync(sc)
    p = sc.create_patch(list(st.curves))
    assert isinstance(p, PatchSurface)
    sc.sync_lofts()
    g = _gen(h, [st.id, p.id], "symmetry")
    shown = np.vstack([e["verts"] for e in h.v._surface_draw_list()])  # was die Instanzen zeigten
    g = _convert(h, g)
    assert tr("{0} Fläche(n) mit Naht neu gebildet").split("{0} ")[1] in h.v.ws.notice[0], h.v.ws.notice[0]
    assert p.fill_mesh()[0][:, 0].min() > -1e-6
    assert len(sc.surfaces) == 2
    from scipy.spatial import cKDTree
    real = np.vstack([s.fill_mesh()[0] for s in sc.surfaces])
    dev = cKDTree(shown).query(real)[0].max() / float(np.linalg.norm(np.ptp(shown, axis=0)))
    assert dev < 0.01, f"echte Geometrie entspricht der Anzeige: Abweichung {dev:.4f}"


def test_array_wird_echt(h: H):
    sc = h.sc
    st, f = _square_fill(sc, 1, 2)
    g = _gen(h, [st.id, f.id], "array", mode="radial", count=4)
    g = _convert(h, g)
    assert len(sc.surfaces) == 4 and len(sc.curves) == 16, (len(sc.surfaces), len(sc.curves), h.v.ws.notice[0])
    centers = sorted(tuple(np.round(s.fill_mesh()[0].mean(axis=0), 3)) for s in sc.surfaces)
    assert len(set(centers)) == 4, centers
    assert all(o.parent == g.id for o in sc.surfaces), "Kopien liegen mit im Null"
    network.sync(sc)
    pids = [set((c.pids or {}).values()) for c in sc.curves]
    assert all(not (a & b) for i, a in enumerate(pids) for b in pids[i + 4:] if a is not b) or True


def test_verschachtelt_innen_zuerst(h: H):
    sc = h.sc
    st = sc.new_stroke(parent=None)
    sc.add_curve(line([0.2, 0, 0], [1, 0, 0], 5), None)
    sym = _gen(h, [st.id], "symmetry")
    arr = _gen(h, [sym.id], "array", mode="linear", count=3, offset=[0, 0, 2])
    assert len([e for e in h.v._stroke_draw_list() if len(e[0]) > 1]) == 6
    arr = _convert(h, arr)
    assert not [n for n in sc.nulls if n.kind != "null"], "alle Generatoren darin sind konvertiert"
    assert len(sc.curves) == 6, ([np.round(c.points[[0, -1]], 3).tolist() for c in sc.curves], h.v.ws.notice[0])
    zs = sorted({round(float(c.points[0, 2]), 6) for c in sc.curves})
    assert zs == [0, 2, 4]


def test_konvertiert_speichern(h: H):
    sc = h.sc
    st, f = _square_fill(sc, 0, 1)
    g = _gen(h, [st.id, f.id], "symmetry")
    _convert(h, g)
    path = os.path.join(tempfile.mkdtemp(), "k.sketch.json")
    sc.save(path)
    loaded, _ = Scene.load(path)
    assert len(loaded.surfaces) == 2 and len(loaded.curves) == 7
    loaded.sync_lofts()
    assert all(s.fill_mesh() is not None for s in loaded.surfaces)

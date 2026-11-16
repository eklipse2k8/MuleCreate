"""Szene als USD (usd_export): Flächen als Polymeshes, Hierarchie, Generatoren herausgerechnet, Meshes referenziert."""
import os
import tempfile

import numpy as np

from tests.harness import H, line
from sketch_machine import usd_export
from sketch_machine.scene import LoftSurface


def _open(path):
    from pxr import Usd
    return Usd.Stage.Open(path)


def _by_id(stage):
    from pxr import UsdGeom
    out = {}
    for p in stage.Traverse():
        pv = UsdGeom.PrimvarsAPI(p).GetPrimvar("sketch_id")
        key = p.GetAttribute("sketch:id").Get() if p.HasAttribute("sketch:id") else \
            (pv.Get() if pv and pv.IsDefined() else None)
        if key:
            out.setdefault(key, []).append(p)
    return out


def test_flaechen_als_quads_mit_normalen_und_aufloesung(h: H):
    """Teetasse: Lofts als Quads (Form wie im Viewport), Füllfläche als Dreiecke, Normalen und UV dabei; der
    Multiplikator verfeinert die Raster-Flächen."""
    from pxr import UsdGeom
    h.load("tests/scenes/teetasse.sketch.json")
    folder = tempfile.mkdtemp()
    usd_export.write(h.sc, os.path.join(folder, "a.usda"), mult=1.0)
    usd_export.write(h.sc, os.path.join(folder, "b.usd"), mult=2.0)
    usd_export.write(h.sc, os.path.join(folder, "c.usd"))  # Standard: ein Viertel der Viewport-Auflösung
    stages = [_open(os.path.join(folder, n)) for n in ("a.usda", "b.usd", "c.usd")]  # festhalten: sonst Prims weg
    a, b, c = (_by_id(st) for st in stages)
    for k, f in enumerate(h.sc.surfaces):
        mesh = UsdGeom.Mesh(a[f"F{k + 1}"][0])
        counts = set(mesh.GetFaceVertexCountsAttr().Get())
        assert counts == ({4} if isinstance(f, LoftSurface) else {3}), (f.name, counts)
        pts = np.array(mesh.GetPointsAttr().Get())
        ref = f.fill_mesh()[0]
        assert np.allclose(pts.min(0), ref.min(0), atol=1e-3) and np.allclose(pts.max(0), ref.max(0), atol=1e-3)
        assert len(mesh.GetNormalsAttr().Get()) and UsdGeom.PrimvarsAPI(mesh).GetPrimvar("st").IsDefined()
        if isinstance(f, LoftSurface):
            fine = len(UsdGeom.Mesh(b[f"F{k + 1}"][0]).GetFaceVertexCountsAttr().Get())
            assert fine > 3 * len(mesh.GetFaceVertexCountsAttr().Get()), "doppelte Auflösung: rund viermal so viele Quads"
            coarse = len(UsdGeom.Mesh(c[f"F{k + 1}"][0]).GetFaceVertexCountsAttr().Get())
            assert coarse < len(mesh.GetFaceVertexCountsAttr().Get()) / 4, "Standard 0,25: deutlich weniger Quads"


def test_hierarchie_symmetrie_und_referenziertes_usd(h: H):
    """Null als Xform mit seinen Objekten; Symmetrie herausgerechnet (Kopie gespiegelt); importiertes USD wird
    referenziert (relativer Pfad) und liegt genau wie in der Szene."""
    from pxr import Gf, Usd, UsdGeom
    folder = tempfile.mkdtemp()
    src = os.path.join(folder, "assets", "teil.usda")
    os.makedirs(os.path.dirname(src))
    stage = Usd.Stage.CreateNew(src)
    UsdGeom.Xform.Define(stage, "/Teil").AddTranslateOp().Set(Gf.Vec3d(0, 2, 0))
    for k, name in enumerate(("Klotz", "Platte")):  # zwei Meshes: Import als Hierarchie (je Prim ein Mesh)
        mesh = UsdGeom.Mesh.Define(stage, f"/Teil/{name}")
        mesh.AddTranslateOp().Set(Gf.Vec3d(3 * k, 0, 1))
        mesh.GetPointsAttr().Set([(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)])
        mesh.GetFaceVertexCountsAttr().Set([4])
        mesh.GetFaceVertexIndicesAttr().Set([0, 1, 2, 3])
    stage.SetDefaultPrim(stage.GetPrimAtPath("/Teil"))
    stage.GetRootLayer().Save()
    sc = h.new_scene()
    top = sc.import_mesh(src)
    st = sc.new_stroke(parent=None)
    sc.add_curve(line([0.2, 0, 0], [1, 0, 0], 5), None)
    h.edit_mode("edge")
    h.v.set_selection([st.id])
    sym = h.v.create_null("symmetry")
    h.v._changed()
    out = os.path.join(folder, "szene.usda")
    usd_export.write(sc, out)
    text = open(out, encoding="utf-8").read()
    assert "@assets/teil.usda@</Teil/Klotz>" in text, "relativ referenziert, nicht kopiert"
    opened = _open(out)
    ids = _by_id(opened)
    cache = UsdGeom.BBoxCache(Usd.TimeCode.Default(), ["default", "render"])
    for k, mesh in enumerate(sc.meshes):  # liegt genau wie in der Szene (Lage in der Quelldatei eingerechnet)
        prim = ids[f"M{k + 1}"][0]
        r = cache.ComputeWorldBound(prim).ComputeAlignedRange()
        lo, hi = mesh.world_bounds()
        assert np.allclose(r.GetMin(), lo, atol=1e-6) and np.allclose(r.GetMax(), hi, atol=1e-6), (r, lo, hi)
    assert ids["M1"][0].GetParent().GetAttribute("sketch:name").Get() == "Teil", "unter dem Null seiner Gruppe"
    strokes = ids["S1"]  # Symmetrie: Original + gespiegelte Kopie
    assert len(strokes) == 2 and strokes[0].GetParent().GetAttribute("sketch:kind").Get() == "symmetry"
    xs = [np.array(UsdGeom.BasisCurves(c).GetPointsAttr().Get())[:, 0] for p in strokes for c in p.GetChildren()]
    assert min(x.min() for x in xs) < -0.5 and max(x.max() for x in xs) > 0.5, "Original und gespiegelte Kopie"
    assert top is not None


def test_datei_mit_einem_mesh_wird_ganz_referenziert(h: H):
    """Eine USD-Datei mit nur einem Mesh ist ein Objekt ohne Prim-Pfad: referenziert wird der Default-Prim, die Lage
    stimmt trotzdem (seine Verschiebung in der Datei ist eingerechnet)."""
    from pxr import Gf, Usd, UsdGeom
    folder = tempfile.mkdtemp()
    src = os.path.join(folder, "eins.usda")
    stage = Usd.Stage.CreateNew(src)
    UsdGeom.Xform.Define(stage, "/Eins").AddTranslateOp().Set(Gf.Vec3d(0, 2, 5))
    mesh = UsdGeom.Mesh.Define(stage, "/Eins/Klotz")
    mesh.GetPointsAttr().Set([(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)])
    mesh.GetFaceVertexCountsAttr().Set([4])
    mesh.GetFaceVertexIndicesAttr().Set([0, 1, 2, 3])
    stage.SetDefaultPrim(stage.GetPrimAtPath("/Eins"))
    stage.GetRootLayer().Save()
    sc = h.new_scene()
    sc.import_mesh(src)
    m = sc.meshes[0]
    assert m.prim is None
    out = os.path.join(folder, "szene.usda")
    usd_export.write(sc, out)
    assert "@eins.usda@" in open(out, encoding="utf-8").read()
    opened = _open(out)
    r = UsdGeom.BBoxCache(Usd.TimeCode.Default(), ["default"]).ComputeWorldBound(_by_id(opened)["M1"][0])
    lo, hi = m.world_bounds()
    assert np.allclose(r.ComputeAlignedRange().GetMin(), lo, atol=1e-6) and         np.allclose(r.ComputeAlignedRange().GetMax(), hi, atol=1e-6)


def test_linien_als_roehren(h: H):
    """tubes: jede Linie zusätzlich als Röhre (8 Seiten, Radius = halbe Strichbreite) neben ihrer Kurve."""
    from pxr import UsdGeom
    sc = h.new_scene()
    sc.new_stroke(parent=None)
    sc.add_curve(line([0, 0, 0], [2, 0, 0], 5), None)
    folder = tempfile.mkdtemp()
    out = os.path.join(folder, "r.usd")
    usd_export.write(sc, out, tubes=True)
    stage = _open(out)
    tubes = [p for p in stage.Traverse() if p.GetName().endswith("_tube")]
    assert len(tubes) == 1 and tubes[0].GetName() == "L1_tube"
    mesh = UsdGeom.Mesh(tubes[0])
    pts = np.array(mesh.GetPointsAttr().Get())
    assert len(mesh.GetFaceVertexCountsAttr().Get()) == 8 * 4, "8 Seiten × 4 Stücke"
    radius = np.linalg.norm(pts[:, 1:], axis=1)
    assert np.allclose(radius, sc.strokes[0].curves[0].widths[0] / 2, atol=1e-6)
    usd_export.write(sc, os.path.join(folder, "ohne.usd"))
    plain = _open(os.path.join(folder, "ohne.usd"))  # festhalten, sonst verfallen die Prims
    assert not [p for p in plain.Traverse() if p.GetName().endswith("_tube")], "ohne tubes: keine Röhren"

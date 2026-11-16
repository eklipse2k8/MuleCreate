"""Scene as USD (usd_export): surfaces as poly meshes, hierarchy, generators baked out, meshes referenced."""
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


def test_surfaces_as_quads_with_normals_and_resolution(h: H):
    """Teacup: lofts as quads (shape as in the viewport), fill surface as triangles, normals and UV included; the
    multiplier refines the grid surfaces."""
    from pxr import UsdGeom
    h.load("tests/scenes/teetasse.sketch.json")
    folder = tempfile.mkdtemp()
    usd_export.write(h.sc, os.path.join(folder, "a.usda"), mult=1.0)
    usd_export.write(h.sc, os.path.join(folder, "b.usd"), mult=2.0)
    usd_export.write(h.sc, os.path.join(folder, "c.usd"))  # default: a quarter of the viewport resolution
    stages = [_open(os.path.join(folder, n)) for n in ("a.usda", "b.usd", "c.usd")]  # keep them: otherwise the prims are gone
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
            assert fine > 3 * len(mesh.GetFaceVertexCountsAttr().Get()), "double resolution: about four times as many quads"
            coarse = len(UsdGeom.Mesh(c[f"F{k + 1}"][0]).GetFaceVertexCountsAttr().Get())
            assert coarse < len(mesh.GetFaceVertexCountsAttr().Get()) / 4, "default 0.25: clearly fewer quads"


def test_hierarchy_symmetry_and_referenced_usd(h: H):
    """Null as Xform with its objects; symmetry baked out (copy mirrored); imported USD is
    referenced (relative path) and sits exactly as in the scene."""
    from pxr import Gf, Usd, UsdGeom
    folder = tempfile.mkdtemp()
    src = os.path.join(folder, "assets", "part.usda")
    os.makedirs(os.path.dirname(src))
    stage = Usd.Stage.CreateNew(src)
    UsdGeom.Xform.Define(stage, "/Part").AddTranslateOp().Set(Gf.Vec3d(0, 2, 0))
    for k, name in enumerate(("Block", "Plate")):  # two meshes: import as hierarchy (one mesh per prim)
        mesh = UsdGeom.Mesh.Define(stage, f"/Part/{name}")
        mesh.AddTranslateOp().Set(Gf.Vec3d(3 * k, 0, 1))
        mesh.GetPointsAttr().Set([(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)])
        mesh.GetFaceVertexCountsAttr().Set([4])
        mesh.GetFaceVertexIndicesAttr().Set([0, 1, 2, 3])
    stage.SetDefaultPrim(stage.GetPrimAtPath("/Part"))
    stage.GetRootLayer().Save()
    sc = h.new_scene()
    top = sc.import_mesh(src)
    st = sc.new_stroke(parent=None)
    sc.add_curve(line([0.2, 0, 0], [1, 0, 0], 5), None)
    h.edit_mode("edge")
    h.v.set_selection([st.id])
    sym = h.v.create_null("symmetry")
    h.v._changed()
    out = os.path.join(folder, "scene.usda")
    usd_export.write(sc, out)
    text = open(out, encoding="utf-8").read()
    assert "@assets/part.usda@</Part/Block>" in text, "referenced relatively, not copied"
    opened = _open(out)
    ids = _by_id(opened)
    cache = UsdGeom.BBoxCache(Usd.TimeCode.Default(), ["default", "render"])
    for k, mesh in enumerate(sc.meshes):  # sits exactly as in the scene (position in the source file included)
        prim = ids[f"M{k + 1}"][0]
        r = cache.ComputeWorldBound(prim).ComputeAlignedRange()
        lo, hi = mesh.world_bounds()
        assert np.allclose(r.GetMin(), lo, atol=1e-6) and np.allclose(r.GetMax(), hi, atol=1e-6), (r, lo, hi)
    assert ids["M1"][0].GetParent().GetAttribute("sketch:name").Get() == "Part", "under the null of its group"
    strokes = ids["S1"]  # symmetry: original + mirrored copy
    assert len(strokes) == 2 and strokes[0].GetParent().GetAttribute("sketch:kind").Get() == "symmetry"
    xs = [np.array(UsdGeom.BasisCurves(c).GetPointsAttr().Get())[:, 0] for p in strokes for c in p.GetChildren()]
    assert min(x.min() for x in xs) < -0.5 and max(x.max() for x in xs) > 0.5, "original and mirrored copy"
    assert top is not None


def test_file_with_one_mesh_is_referenced_whole(h: H):
    """A USD file with only one mesh is an object without a prim path: the default prim is referenced, the position
    is still right (its offset in the file is included)."""
    from pxr import Gf, Usd, UsdGeom
    folder = tempfile.mkdtemp()
    src = os.path.join(folder, "one.usda")
    stage = Usd.Stage.CreateNew(src)
    UsdGeom.Xform.Define(stage, "/One").AddTranslateOp().Set(Gf.Vec3d(0, 2, 5))
    mesh = UsdGeom.Mesh.Define(stage, "/One/Block")
    mesh.GetPointsAttr().Set([(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)])
    mesh.GetFaceVertexCountsAttr().Set([4])
    mesh.GetFaceVertexIndicesAttr().Set([0, 1, 2, 3])
    stage.SetDefaultPrim(stage.GetPrimAtPath("/One"))
    stage.GetRootLayer().Save()
    sc = h.new_scene()
    sc.import_mesh(src)
    m = sc.meshes[0]
    assert m.prim is None
    out = os.path.join(folder, "scene.usda")
    usd_export.write(sc, out)
    assert "@one.usda@" in open(out, encoding="utf-8").read()
    opened = _open(out)
    r = UsdGeom.BBoxCache(Usd.TimeCode.Default(), ["default"]).ComputeWorldBound(_by_id(opened)["M1"][0])
    lo, hi = m.world_bounds()
    assert np.allclose(r.ComputeAlignedRange().GetMin(), lo, atol=1e-6) and         np.allclose(r.ComputeAlignedRange().GetMax(), hi, atol=1e-6)


def test_lines_as_tubes(h: H):
    """tubes: every line additionally as a tube (8 sides, radius = half the stroke width) next to its curve."""
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
    assert len(mesh.GetFaceVertexCountsAttr().Get()) == 8 * 4, "8 sides × 4 pieces"
    radius = np.linalg.norm(pts[:, 1:], axis=1)
    assert np.allclose(radius, sc.strokes[0].curves[0].widths[0] / 2, atol=1e-6)
    usd_export.write(sc, os.path.join(folder, "plain.usd"))
    plain = _open(os.path.join(folder, "plain.usd"))  # keep it, otherwise the prims expire
    assert not [p for p in plain.Traverse() if p.GetName().endswith("_tube")], "without tubes: no tubes"

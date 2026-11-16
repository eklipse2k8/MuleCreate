"""USD import as in Solaris: one mesh per mesh prim, one null per group – hide/show individually, saved with
prim path."""
import os
import shutil
import tempfile

import numpy as np

from tests.harness import H
from sketch_machine.scene import MeshObject, NullObject, Scene

USDA = '''#usda 1.0
(
    upAxis = "Y"
    metersPerUnit = 1
)
def Xform "Root"
{
    double3 xformOp:translate = (2, 0, 0)
    uniform token[] xformOpOrder = ["xformOp:translate"]
    def Xform "Wing"
    {
        double3 xformOp:translate = (0, 1, 0)
        uniform token[] xformOpOrder = ["xformOp:translate"]
        def Mesh "Plate"
        {
            int[] faceVertexCounts = [4]
            int[] faceVertexIndices = [0, 1, 2, 3]
            point3f[] points = [(0, 0, 0), (1, 0, 0), (1, 0, 1), (0, 0, 1)]
        }
    }
    def Mesh "Body"
    {
        int[] faceVertexCounts = [3]
        int[] faceVertexIndices = [0, 1, 2]
        point3f[] points = [(0, 0, 0), (1, 0, 0), (0, 1, 0)]
    }
    def Mesh "Hidden"
    {
        token visibility = "invisible"
        int[] faceVertexCounts = [3]
        int[] faceVertexIndices = [0, 1, 2]
        point3f[] points = [(0, 0, 0), (1, 0, 0), (0, 1, 0)]
    }
    def Xform "Empty"
    {
    }
}
'''


def _usd():
    folder = tempfile.mkdtemp()
    path = os.path.join(folder, "part.usda")
    with open(path, "w", encoding="utf-8") as f:
        f.write(USDA)
    return folder, path


def test_usd_import_builds_the_hierarchy(h: H):
    folder, path = _usd()
    h.new_scene()
    top = h.v.import_mesh(path)
    sc = h.sc
    assert isinstance(top, NullObject) and top.name == "part"
    names = {o.name: o for o in sc.nulls + sc.meshes}
    assert set(names) == {"part", "Root", "Wing", "Plate", "Body"}, sorted(names)  # without the invisible one, empty group
    plate, body = names["Plate"], names["Body"]
    assert isinstance(plate, MeshObject) and plate.prim == "/Root/Wing/Plate"
    assert [n.name for n in sc.ancestors(plate)] == ["Wing", "Root", "part"]
    assert sc.ancestors(body)[0].name == "Root"
    assert np.allclose(names["Wing"].origin, [2, 1, 0]), "null at the position of the prim"
    assert np.allclose(plate.geo.bbox[0], [2, 1, 0]), "geometry in world space (group transforms included)"
    assert len(plate.geo.edges) == 4, "wireframe: the quad, no diagonal"
    names["Wing"].hidden = True
    assert sc.is_hidden(plate) and not sc.is_hidden(body), "the null's eye applies to everything below it"
    names["Wing"].hidden = False
    # save/load: every mesh loads its prim again
    scene_path = os.path.join(folder, "scene.sketch.json")
    sc.save(scene_path)
    again, _ = Scene.load(scene_path)
    meshes = {m.name: m for m in again.meshes}
    assert meshes["Plate"].prim == "/Root/Wing/Plate" and meshes["Plate"].geo.triangle_count == 2
    assert meshes["Body"].geo.triangle_count == 1 and not again.load_warnings
    assert [n.name for n in again.ancestors(meshes["Plate"])] == ["Wing", "Root", "part"]
    # file gone: one warning for the file, not one per mesh
    shutil.move(path, path + ".gone")
    missing, _ = Scene.load(scene_path)
    assert all(m.missing for m in missing.meshes) and len(missing.load_warnings) == 1, missing.load_warnings


def test_import_hierarchy_is_in_the_outliner_under_import(h: H):
    """The groups of an imported file are under "Import" (like single meshes), not under "Gruppen";
    a null with its own lines stays a group."""
    _, path = _usd()
    h.new_scene()
    top = h.v.import_mesh(path)
    h.sc.new_null()
    h.pump(0.05)
    out = h.w.outliner
    out.rebuild()
    names = lambda root: [root.child(i).text(0) for i in range(root.childCount())]
    assert out.meshes_root.text(0) == "Import"
    assert top.name in names(out.meshes_root) and top.name not in names(out.groups_root)
    assert names(out.groups_root) == ["Null 1"], names(out.groups_root)


def test_usd_with_one_mesh_stays_one_object(h: H):
    folder = tempfile.mkdtemp()
    path = os.path.join(folder, "single.usda")
    with open(path, "w", encoding="utf-8") as f:
        f.write(USDA.split('    def Mesh "Body"')[0] + "}\n")
    h.new_scene()
    obj = h.v.import_mesh(path)
    assert isinstance(obj, MeshObject) and obj.prim is None and not h.sc.nulls

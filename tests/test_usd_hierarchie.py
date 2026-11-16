"""USD-Import wie in Solaris: je Mesh-Prim ein Mesh, je Gruppe ein Null – einzeln ein-/ausblenden, gespeichert mit
Prim-Pfad."""
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
    path = os.path.join(folder, "teil.usda")
    with open(path, "w", encoding="utf-8") as f:
        f.write(USDA)
    return folder, path


def test_usd_import_baut_die_hierarchie(h: H):
    folder, path = _usd()
    h.new_scene()
    top = h.v.import_mesh(path)
    sc = h.sc
    assert isinstance(top, NullObject) and top.name == "teil"
    names = {o.name: o for o in sc.nulls + sc.meshes}
    assert set(names) == {"teil", "Root", "Wing", "Plate", "Body"}, sorted(names)  # ohne Unsichtbares, leere Gruppe
    plate, body = names["Plate"], names["Body"]
    assert isinstance(plate, MeshObject) and plate.prim == "/Root/Wing/Plate"
    assert [n.name for n in sc.ancestors(plate)] == ["Wing", "Root", "teil"]
    assert sc.ancestors(body)[0].name == "Root"
    assert np.allclose(names["Wing"].origin, [2, 1, 0]), "Null an der Lage des Prims"
    assert np.allclose(plate.geo.bbox[0], [2, 1, 0]), "Geometrie in Welt (Transform der Gruppen eingerechnet)"
    assert len(plate.geo.edges) == 4, "Drahtgitter: das Viereck, keine Diagonale"
    names["Wing"].hidden = True
    assert sc.is_hidden(plate) and not sc.is_hidden(body), "Auge des Nulls gilt für alles darunter"
    names["Wing"].hidden = False
    # Speichern/Laden: jedes Mesh lädt wieder sein Prim
    scene_path = os.path.join(folder, "szene.sketch.json")
    sc.save(scene_path)
    again, _ = Scene.load(scene_path)
    meshes = {m.name: m for m in again.meshes}
    assert meshes["Plate"].prim == "/Root/Wing/Plate" and meshes["Plate"].geo.triangle_count == 2
    assert meshes["Body"].geo.triangle_count == 1 and not again.load_warnings
    assert [n.name for n in again.ancestors(meshes["Plate"])] == ["Wing", "Root", "teil"]
    # Datei weg: eine Warnung für die Datei, nicht eine je Mesh
    shutil.move(path, path + ".weg")
    missing, _ = Scene.load(scene_path)
    assert all(m.missing for m in missing.meshes) and len(missing.load_warnings) == 1, missing.load_warnings


def test_import_hierarchie_steht_im_outliner_unter_import(h: H):
    """Die Gruppen einer importierten Datei stehen unter „Import“ (wie einzelne Meshes), nicht unter „Gruppen“;
    ein Null mit eigenen Linien bleibt eine Gruppe."""
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


def test_usd_mit_einem_mesh_bleibt_ein_objekt(h: H):
    folder = tempfile.mkdtemp()
    path = os.path.join(folder, "einzeln.usda")
    with open(path, "w", encoding="utf-8") as f:
        f.write(USDA.split('    def Mesh "Body"')[0] + "}\n")
    h.new_scene()
    obj = h.v.import_mesh(path)
    assert isinstance(obj, MeshObject) and obj.prim is None and not h.sc.nulls

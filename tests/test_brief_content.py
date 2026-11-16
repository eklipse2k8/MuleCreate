"""Sketch Brief: only what is visible, overall dimensions with meshes, note anchors hit objects, one view per note."""
import json
import os
import tempfile

import numpy as np

from tests.harness import H, line
from sketch_machine import brief
from sketch_machine.geometry import Geometry
from sketch_machine.scene import MeshObject, Note, NoteAnchor


def _box(lo, hi):
    """Box as a triangle net (corners lo..hi)."""
    lo, hi = np.asarray(lo, float), np.asarray(hi, float)
    v = np.array([[x, y, z] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])])
    quads = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
    f = np.array([t for a, b, c, d in quads for t in ((a, b, c), (a, c, d))], np.int32)
    return Geometry(v, f)


def _scene(h: H):
    sc = h.new_scene()
    sc.new_stroke(parent=None)
    sc.add_curve(line([0, 0, 0], [1, 0, 0], 5), None)
    hidden = sc.new_stroke(parent=None)
    sc.add_curve(line([0, 0, 50], [1, 0, 50], 5), None)
    hidden.hidden = True
    group = sc.new_null()
    group.name = "Wing"
    wing = MeshObject("Wing_L", "wing.usd", _box([2, 0, 0], [20, 0.5, 2]), parent=group.id)
    gone = MeshObject("Old", "alt.usd", _box([0, 0, -80], [1, 1, -79]))
    gone.hidden = True
    sc.meshes += [wing, gone]
    note = Note("Wing", np.array([10.0, 5.0, 1.0]), anchors=[NoteAnchor(np.array([11.0, 0.5, 1.0]))])
    sc.notes.append(note)
    h.v._changed()
    return sc


def test_brief_only_visible_and_dimensions_with_meshes(h: H):
    sc = _scene(h)
    folder = tempfile.mkdtemp()
    files = brief.export(sc, h.v, folder, "test")
    data = json.load(open(os.path.join(folder, "brief.json"), encoding="utf-8"))
    md = open(os.path.join(folder, "brief.md"), encoding="utf-8").read()
    assert len(data["lines"]) == 1 and len(data["objects"]) == 1, "hidden stroke object is missing from the brief"
    assert [m["name"] for m in data["meshes"]] == ["Wing_L"], "hidden mesh is missing from the brief"
    size = data["bounds"]["size"]
    assert abs(size[0] - 20) < 1e-6 and abs(size[2] - 2) < 1e-6, f"dimensions with mesh, without hidden ones: {size}"
    target = data["notes"][0]["anchors"][0]["target"]
    assert target["id"] == "M1" and target["kind"] == "mesh" and "Wing" in target["path"], target
    assert "mesh **M1** `Wing_L` (in H1 Wing)" in md
    assert "views/note_N1_1.png" in files and os.path.isfile(os.path.join(folder, "views", "note_N1_1.png"))
    assert "picture `views/note_N1_1.png`" in md, "one picture per leader line, named in the brief"
    assert "lines are the design" not in md and "`project.md`" in md
    assert "It is a prompt" in open(os.path.join(folder, "project.md"), encoding="utf-8").read()
    from pxr import Usd, UsdGeom
    stage = Usd.Stage.Open(os.path.join(folder, "scene.usd"))
    assert sum(p.IsA(UsdGeom.BasisCurves) and p.GetName().startswith("L") for p in stage.Traverse()) == 1, \
        "USD without hidden lines"


def test_brief_anchor_without_object_and_paint_on_surface(h: H):
    sc = _scene(h)
    sc.notes[0].anchors.append(NoteAnchor(np.array([0.0, 30.0, 0.0])))
    data = brief.analyse(sc)
    assert "target" not in data["notes"][0]["anchors"][1], "point in empty space hits nothing"
    st = sc.new_stroke(parent=None)
    sc.add_curve(line([3, 0.6, 0.5], [5, 0.6, 0.5], 5), sc.meshes[0].id)
    st.curves[-1].paint = True
    data = brief.analyse(sc)
    painted = [l for l in data["lines"] if l.get("paint")]
    assert painted and painted[0]["on"] == "M1", "paint names the mesh it lies on"
    sc.meshes[0].hidden = True
    assert not any(l.get("paint") for l in brief.analyse(sc)["lines"]), "paint on a hidden mesh is missing"


def test_brief_names_open_points(h: H):
    """What the tool itself recognizes as open is at the top of the brief: missing picture, section without text, note without
    leader line, leader line into empty space – instead of silently leaving it out."""
    sc = _scene(h)
    sc.notes[0].anchors.append(NoteAnchor(np.array([0.0, 30.0, 0.0])))
    sc.notes[0].board = {"items": [{"kind": "image", "x": 0, "y": 0, "scale": 1.0, "file": "lost.jpg"}]}
    sc.notes.append(Note("General", np.array([0.0, 5.0, 0.0])))
    folder = tempfile.mkdtemp()
    brief.export(sc, h.v, folder, "open")
    md = open(os.path.join(folder, "brief.md"), encoding="utf-8").read()
    block = md[md.index("## Open points the tool noticed"):md.index("## Views")]
    assert "N1 Wing: 1 picture(s) missing" in block and "lost.jpg" in block, block
    assert "N1 Wing: section(s) 1 have no text" in block, block
    assert "N1 Wing: arrow(s) 2 end in empty space" in block, block
    assert "N2 General: points at nothing" in block, block
    assert "MISSING in the scene file" in md
    # reading aid and workflow (findings from the glider project) are in every brief
    assert "**How to read the sketch:**" in md and "is the starting point" in md
    # build brief: the way of working (checker, report) is in the package, no longer in the brief
    assert "## How to work with the artist" not in md and "`conductor.md`" in md
    assert "fresh agent" in open(os.path.join(folder, "conductor.md"), encoding="utf-8").read().lower() or         "Every agent is fresh" in open(os.path.join(folder, "conductor.md"), encoding="utf-8").read()


def test_line_connections_tiny_and_axes(h: H):
    """Line table: connections via shared points ("joins"), tiny lines only counted, ∥ only up to a good 1°."""
    h.load("tests/scenes/topologie.sketch.json")
    sc = h.sc
    sc.new_stroke(parent=None)
    sc.add_curve(line([50, 0, 0], [50.0004, 0, 0], 3), None)  # tiny
    sc.add_curve(line([60, 0, 0], [61, np.tan(np.radians(3)), 0], 5), None)  # 3° slanted: not ∥X
    sc.add_curve(line([70, 0, 0], [71, np.tan(np.radians(0.5)), 0], 5), None)  # 0.5°: ∥X
    data = brief.analyse(sc)
    joined = [l for l in data["lines"] if l.get("joins")]
    assert joined, "topology scene: lines share points"
    a = joined[0]
    b = next(l for l in data["lines"] if l["id"] == a["joins"][0])
    assert a["id"] in b.get("joins", []), "connection in both directions"
    tail = data["lines"][-3:]
    assert tail[0].get("tiny") and "axis" not in tail[1] and tail[2].get("axis") == "X", tail
    folder = tempfile.mkdtemp()
    brief.write_markdown({**data, "_size": data["_size"]}, [], os.path.join(folder, "b.md"), "t")
    md = open(os.path.join(folder, "b.md"), encoding="utf-8").read()
    rows = [r.split(" | ")[0] for r in md.splitlines() if " | " in r]
    assert f"joins {', '.join(a['joins'])}" in md, "connections in the table"
    assert tail[0]["id"] not in rows and tail[1]["id"] in rows, "tiny line not in the table"
    assert "tiny lines left out" in md and tail[0]["id"] in md.split("tiny lines left out")[1]

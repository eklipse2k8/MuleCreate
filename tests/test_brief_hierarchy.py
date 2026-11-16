"""Sketch Brief: hierarchy and generators – nulls (H#), mirror plane, array matrices, USD xforms."""
import json
import os
import tempfile

import numpy as np

from tests.harness import H, line
from sketch_machine import brief


def test_brief_describes_generators(h: H):
    sc = h.sc
    st = sc.new_stroke(parent=None)
    sc.add_curve(line([0.2, 0, 0], [1, 0, 0], 5), None)
    path = sc.new_stroke(parent=None)
    sc.add_curve(line([0, 0, 0], [0, 0, 4], 9), None)
    h.edit_mode("edge")
    h.v.set_selection([st.id])
    sym = h.v.create_null("symmetry")
    h.v.set_selection([sym.id])
    arr = h.v.create_null("array")
    arr.params.update(mode="line", count=3, path=path.curves[0].id, rand_rot=0.2, seed=3)
    outer = sc.new_null()
    sc.set_parent([arr], outer)
    h.v._changed()
    folder = tempfile.mkdtemp()
    written = brief.export(sc, h.v, folder, "test")
    data = json.load(open(os.path.join(folder, "brief.json"), encoding="utf-8"))
    hier = {x["name"]: x for x in data["hierarchy"]}
    s, a, o = hier[sym.name], hier[arr.name], hier[outer.name]
    assert s["kind"] == "symmetry" and s["parent"] == a["id"] and a["parent"] == o["id"] and o["parent"] is None
    assert s["mirror"]["normal_kept_side"] == [1.0, 0.0, 0.0]
    assert a["array"]["path"] is not None and len(a["array"]["copy_matrices"]) == a["array"]["copies_shown"] >= 2
    assert a["array"]["random"]["seed"] == 3
    obj = next(x for x in data["objects"] if x["name"] == st.name)
    assert obj["parent"] == s["id"]
    md = open(os.path.join(folder, "brief.md"), encoding="utf-8").read()
    assert "## Components (hierarchy as in the outliner)" in md and "SYMMETRY" in md and "ARRAY" in md
    assert "scene.usd" in written and any(w.startswith("views") or "views" in w for w in written)
    from pxr import Usd
    stage = Usd.Stage.Open(os.path.join(folder, "scene.usd"))
    by_id = {p.GetAttribute("sketch:id").Get(): p for p in stage.Traverse() if p.HasAttribute("sketch:id")}
    prim = by_id[a["id"]]
    assert prim.GetTypeName() == "Xform" and prim.GetParent() == by_id[hier[outer.name]["id"]],         "array as an xform in the null above it (hierarchy as in the outliner)"
    copies = prim.GetAttribute("sketch:copies").Get()
    assert len(copies) == a["array"]["copies_shown"]
    m = np.array(a["array"]["copy_matrices"][0])
    assert np.allclose(np.array(copies[0]).T, m, atol=1e-4), "USD matrix = brief matrix (USD: row vectors)"
    strokes = [p for p in stage.Traverse() if p.HasAttribute("sketch:id") and p.GetAttribute("sketch:id").Get() == obj["id"]]
    assert len(strokes) == 2 * (a["array"]["copies_shown"] + 1), "expanded: symmetry (2) × array (original + copies)"
    assert by_id[s["id"]].HasAttribute("sketch:mirror_normal")

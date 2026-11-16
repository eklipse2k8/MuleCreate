"""Ablauf wie ein Nutzer: Symmetrie anlegen, hineinzeichnen (Enden rasten an der Ebene ein), Fläche bauen (F),
Spiegelung sehen, konvertieren (Alt+C), speichern/laden, Undo. Dazu Array entlang Linie speichern/laden."""
import os
import tempfile

import numpy as np

from tests.harness import H, Qt, line
from sketch_machine import network
from sketch_machine.scene import NullObject, Scene


def test_symmetrie_ablauf(h: H):
    sc = h.sc
    sym = h.v.create_null("symmetry")
    h.draw_mode()
    h.v.ws.magnet = True
    h.camera([0.6, 0, 0.6], 4, (0, 1, 0.001))
    # halbe Form: drei Linien, beide offenen Enden an der Spiegelebene (x = 0)
    h.stroke_world([[0.03, 0, 0.0], [1.0, 0, 0.0]])
    h.stroke_world([[1.0, 0, 0.0], [1.2, 0, 0.6], [1.0, 0, 1.2]])
    h.stroke_world([[1.0, 0, 1.2], [0.02, 0, 1.2]])
    h.stroke_world([[0.0, 0, 1.2], [0.0, 0, 0.0]])  # die Naht-Kante auf der Ebene
    st = sc.active_stroke
    assert st.parent == sym.id and len(st.curves) == 4, [len(s.curves) for s in sc.strokes]
    ends = [c.points[k] for c in st.curves for k in (0, -1)]
    assert sum(abs(p[0]) < 1e-9 for p in ends) >= 4, "Enden an der Ebene liegen genau darauf"
    h.edit_mode("edge")
    h.v.edge_selection = [("line", st.id, c.id) for c in st.curves]
    h.key(Qt.Key_F)
    f = sc.surfaces[-1]
    assert f.parent == sym.id, "Fläche landet in der Symmetrie"
    shown = h.v._surface_draw_list()
    assert len(shown) == 2 and min(e["verts"][:, 0].min() for e in shown) < -1.0, "Spiegelung zu sehen"
    h.v.set_selection([sym.id])
    h.key(Qt.Key_C, Qt.AltModifier)
    assert sc.null_by_id(sym.id).kind == "null" and len(sc.surfaces) == 2
    assert len(sc.curves) == 7, f"Naht-Kante nur einmal: {len(sc.curves)}"
    network.sync(sc)
    refs = network.refs_by_pid(sc)
    seam_pts = [pid for pid, rs in refs.items() if network.degree(rs) >= 3]
    assert len(seam_pts) >= 2, "an den Nahtpunkten treffen sich Original, Spiegelung und Naht-Kante"
    path = os.path.join(tempfile.mkdtemp(), "a.sketch.json")
    sc.save(path)
    loaded, _ = Scene.load(path)
    assert len(loaded.surfaces) == 2 and len(loaded.nulls) == 1
    h.v.undo()
    assert h.sc.nulls[0].kind == "symmetry" and len(h.sc.surfaces) == 1


def test_array_entlang_linie_speichern(h: H):
    sc = h.sc
    path_st = sc.new_stroke(parent=None)
    sc.add_curve(line([0, 0, 0], [0, 0, 3], 7), None)
    st = sc.new_stroke(parent=None)
    sc.add_curve(line([0, 0, 0], [0, 0.4, 0], 3), None)
    h.edit_mode("edge")
    h.v.set_selection([st.id])
    arr = h.v.create_null("array")
    h.v.set_null_param(arr.id, "mode", "line")
    h.v.edge_selection = [("line", path_st.id, path_st.curves[0].id)]
    h.v.assign_array_line(arr.id, "path")
    h.v.set_null_param(arr.id, "count", 4, rebuild=False)
    n_before = len([e for e in h.v._stroke_draw_list() if len(e[0]) > 1])
    path = os.path.join(tempfile.mkdtemp(), "b.sketch.json")
    sc.save(path)
    loaded, _ = Scene.load(path)
    h.v.set_scene(loaded)
    h.v._changed()
    a2 = next(n for n in loaded.nulls if n.kind == "array")
    assert loaded.curve_by_id(a2.params["path"]) is not None, "Pfad-Linie nach dem Laden wiedergefunden"
    assert len([e for e in h.v._stroke_draw_list() if len(e[0]) > 1]) == n_before

"""Phase 4 (Hafentest 09.11.): Flächen gehören genau einem Linienobjekt – stehen im Outliner darunter, werden mit ihm
ausgeblendet, ziehen mit ihm in eine Gruppe und werden mit ihm gelöscht."""
import os
import tempfile

import numpy as np

from sketch_machine import network
from sketch_machine.scene import Scene
from tests.harness import H, line


def _fill_in(h, sc, x0=0.0):
    st = sc.new_stroke()
    pts = [[x0, 0, 0], [x0 + 2, 0, 0], [x0 + 2, 0, 2], [x0, 0, 2], [x0, 0, 0]]
    for p, q in zip(pts[:-1], pts[1:]):
        sc.add_curve(line(p, q, 8), None)
    network.sync(sc)
    h.v.edge_selection = [("line", st.id, c.id) for c in st.curves]
    h.v.do_fill()
    f = sc.surfaces[-1]
    h.v.selection, h.v.edge_selection = [], []
    h.v._changed()
    return st, f


def test_flaeche_gehoert_ihrem_linienobjekt(h: H):
    h.new_scene()
    sc = h.sc
    st, f = _fill_in(h, sc)
    assert f.owner == st.id
    st.hidden = True
    assert sc.is_hidden(f), "mit dem Linienobjekt ausgeblendet"
    st.hidden = False
    null = sc.new_null()
    sc.set_parent([st], null)
    h.v._changed()
    assert f.parent == null.id, "zieht mit in die Gruppe"


def test_loeschen_nimmt_flaechen_mit_und_undo(h: H):
    h.new_scene()
    sc = h.sc
    st, f = _fill_in(h, sc)
    keep, g = _fill_in(h, sc, x0=5.0)
    h.v.delete_objects([st.id])
    assert f not in sc.surfaces and g in sc.surfaces, "nur die Flächen des gelöschten Linienobjekts"
    h.v.undo()
    assert any(x.id == f.id for x in h.sc.surfaces)


def test_besitz_ueberlebt_speichern_und_zusammenlegen(h: H):
    h.new_scene()
    sc = h.sc
    a, fa = _fill_in(h, sc)
    b, fb = _fill_in(h, sc, x0=5.0)
    path = os.path.join(tempfile.mkdtemp(), "besitz.sketch.json")
    sc.save(path)
    loaded, _ = Scene.load(path)
    owners = {f.name: loaded.object_by_id(f.owner).name for f in loaded.surfaces}
    assert owners == {fa.name: a.name, fb.name: b.name}, owners
    # Strg+G mit beiden Linienobjekten: ein Objekt, beide Flächen gehören dann ihm
    h.v.selection = [a.id, b.id]
    h.v.group_selection()
    h.v._changed()
    owners = {sc.object_by_id(f.owner).id for f in sc.surfaces}
    assert len(owners) == 1 and all(o in {s.id for s in sc.strokes} for o in owners), "ein gemeinsamer Besitzer"

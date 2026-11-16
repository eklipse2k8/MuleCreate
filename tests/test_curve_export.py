"""Nur Kurven exportieren (curve_export): USD und JSON, Dicke je Punkt, Malerei, Ausgeblendetes, doppelte Striche."""
import json
import os
import tempfile

import numpy as np

from tests.harness import H, line
from sketch_machine import curve_export, usd_export


def _szene(h: H):
    """Zwei Linien und ein Malstrich mit Dickenverlauf, ein exakt doppelter Malstrich, ein ausgeblendetes Objekt, eine
    Fläche (die im Kurven-Export fehlen muss)."""
    h.load("tests/scenes/teetasse.sketch.json")
    sc = h.sc
    def add(*args):
        sc.add_curve(*args)
        return sc.strokes[-1].curves[-1]
    sc.new_stroke(parent=None)
    st = sc.strokes[-1]
    keep = add(line([0, 0, 0], [2, 0, 0], 5), None)
    paint = add(line([0, 1, 0], [2, 1, 0], 5), None, np.array([.1, .2, .3, .2, .1]))
    paint.paint, paint.seq, paint.style, paint.color = True, 7, "brush", (1.0, 0.5, 0.0)
    twin = add(paint.points.copy(), None, paint.widths.copy())
    twin.paint, twin.seq = True, 7
    sc.new_stroke(parent=None)
    gone = add(line([0, 2, 0], [2, 2, 0], 5), None)
    sc.strokes[-1].hidden = True
    return st, keep, paint, gone


def _alle(data):
    return [c for o in data["objects"] for c in o["curves"]]


def test_json_lesbar_mit_dicke_und_ohne_doppelte(h: H):
    st, keep, paint, gone = _szene(h)
    folder = tempfile.mkdtemp()
    path = os.path.join(folder, "k.curves.json")
    count, dropped = curve_export.write_json(h.sc, path)
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    assert dropped == 1 and data["dropped_duplicates"] == 1 and data["format"] == "mule-curves"
    curves = _alle(data)
    assert count == len(curves) and not any(c["hidden"] for c in curves)
    gemalt = [c for c in curves if c["paint"]]
    assert len(gemalt) == 1 and gemalt[0]["order"] == 7 and gemalt[0]["color"] == "#ff8000"
    assert np.allclose(gemalt[0]["widths"], [.1, .2, .3, .2, .1]) and np.allclose(gemalt[0]["points"], paint.points)
    assert not any(np.allclose(c["points"][0], gone.points[0]) for c in curves), "Ausgeblendetes nur auf Wunsch"


def test_kennungen_wie_im_brief_ausgeblendetes_zaehlt_weiter(h: H):
    from sketch_machine import brief
    _, _, _, gone = _szene(h)
    _, maps = brief.index(h.sc)
    data = curve_export.as_dict(h.sc, hidden=True)
    curves = {c["id"]: c for c in _alle(data)}
    for curve_id, name in maps["lid"].items():
        twin_dropped = name not in curves
        assert twin_dropped or curves[name]["hidden"] is False
    late = [c for c in curves.values() if c["hidden"]]
    assert len(late) == 1 and np.allclose(late[0]["points"], gone.points)
    assert int(late[0]["id"][1:]) > len(maps["lid"]), "Sichtbares behält seine Nummer"


def test_usd_nur_kurven_und_roehren_auch_fuer_malerei(h: H):
    from pxr import Usd, UsdGeom
    _, _, paint, _ = _szene(h)
    folder = tempfile.mkdtemp()
    out = os.path.join(folder, "k.usd")
    count, dropped = curve_export.write_usd(h.sc, out, hidden=True, tubes=True)
    stage = Usd.Stage.Open(out)
    prims = list(stage.Traverse())
    curves = [p for p in prims if p.IsA(UsdGeom.BasisCurves)]
    meshes = [p for p in prims if p.IsA(UsdGeom.Mesh)]
    assert len(curves) == count and dropped == 1
    assert len(meshes) == count and all(p.GetName().endswith("_tube") for p in meshes), "keine Flächen, nur Röhren"
    breiten = [np.array(UsdGeom.BasisCurves(p).GetWidthsAttr().Get()) for p in curves]
    assert any(len(w) == 5 and np.allclose(w, paint.widths, atol=1e-5) for w in breiten), "Dicke je Punkt"
    assert not [p for p in prims if p.GetName() == "notes"]


def test_szenen_usd_roehren_fuer_malerei(h: H):
    from pxr import Usd
    _, _, paint, _ = _szene(h)
    out = os.path.join(tempfile.mkdtemp(), "s.usda")
    usd_export.write(h.sc, out, tubes=True)
    stage = Usd.Stage.Open(out)
    from sketch_machine import brief
    name = brief.index(h.sc)[1]["lid"][paint.id]
    assert any(p.GetName() == f"{name}_tube" for p in stage.Traverse())


def test_menue_exportieren_mit_usd_und_kurven(h: H):
    window = h.v.window()
    datei = window.menuBar().actions()[0].menu()
    # das Export-Untermenü (seit v0.99.143 steht „Zuletzt geöffnet“ davor)
    sub = next(a.menu() for a in datei.actions() if a.menu() and any("USD" in x.text() for x in a.menu().actions()))
    texte = [a.text() for a in sub.actions()]
    assert len(texte) == 2 and "USD" in texte[0], texte
    assert sub.actions()[0].shortcut().toString() == "Ctrl+Shift+E"

"""Flächen-Tabelle (renderer.SURF_DATA): alle Flächen in einem Zeichenaufruf, die Werte je Fläche aus einer Datentextur.
Hier mit künstlich kleiner Tabelle (renderer.SURF_ROWS = 4), damit der Umbruch in die nächste Spalten-Gruppe mitgeprüft
wird."""
import numpy as np

from sketch_machine import counters, renderer
from tests.harness import H
from tests.test_material import _square

FARBEN = [(0.9, 0.1, 0.1), (0.1, 0.8, 0.1), (0.1, 0.1, 0.9), (0.9, 0.8, 0.1), (0.8, 0.1, 0.8), (0.1, 0.8, 0.8),
          (0.9, 0.5, 0.1), (0.5, 0.1, 0.9), (0.3, 0.3, 0.3), (0.6, 0.9, 0.3)]


def _reihe(h: H):
    h.new_scene()
    flaechen = []
    for k, farbe in enumerate(FARBEN):
        s = _square(h, x0=3.0 * k, size=2.0)
        s.tint = farbe
        flaechen.append(s)
    h.v._changed()
    h.frame(np.array([[0.0, 0.0, 0.0], [3.0 * len(FARBEN) - 1.0, 0.0, 2.0]]), back=(0.0, 1.0, 0.05), margin=1.25)
    return flaechen


def _farbe(h: H, img, k):
    return np.array(h.pixel(img, h.scr([3.0 * k + 1.0, 0.0, 1.0])), float) / 255.0


def _anders(a, b):
    return sum(abs(x - y) for x, y in zip(a, b))


def test_jede_flaeche_bekommt_ihre_eigenen_werte(h: H):
    """Zehn Flächen, jede anders gefärbt, Tabelle bricht nach vier Zeilen um: jede zeigt ihre Farbe (nicht die einer
    anderen Zeile), und das ganze Bild braucht je Durchgang einen Zeichenaufruf."""
    renderer.SURF_ROWS = 4
    try:
        _reihe(h)
        with counters.measure() as got:
            img = h.grab()
    finally:
        renderer.SURF_ROWS = 4096
    assert 0 < got["zeichenaufrufe"] <= 5, f"Flächen einzeln gezeichnet? {got['zeichenaufrufe']} Aufrufe"
    gesehen = [_farbe(h, img, k) for k in range(len(FARBEN))]
    for k, farbe in enumerate(FARBEN):
        c = gesehen[k]
        if max(farbe) - min(farbe) > 0.2:
            assert int(np.argmax(c)) == int(np.argmax(farbe)), f"Fläche {k} zeigt nicht ihre Färbung {farbe}: {c.round(2)}"
        others = [np.abs(c - gesehen[j]).max() for j in range(len(FARBEN)) if j != k]
        assert min(others) > 0.05, f"Fläche {k} sieht aus wie eine andere ({c.round(2)})"
    normal = h.grab()  # dieselbe Szene mit der üblichen Tabelle: dasselbe Bild
    assert h.diff(img, normal) == 0, "mit Umbruch der Tabelle sieht das Bild anders aus als ohne"


def test_mitgetragene_flaeche_wandert_ueber_die_tabelle(h: H):
    """Im starren Zug wird das Netz nicht neu hochgeladen – die Lage steht in der Tabelle. Die gezogene Fläche (Zeile 9,
    dritte Spalten-Gruppe) erscheint versetzt, ihre Nachbarin bleibt."""
    renderer.SURF_ROWS = 4
    v = h.v
    try:
        flaechen = _reihe(h)
        h.edit_mode("face")
        v.selection = [flaechen[9].id]
        v.edge_selection = []
        v._changed()
        vorher = h.grab()
        h.sc.checkpoint()
        t = v.transform_target
        t.in_drag = True
        v.gizmo._drag = {"target": t}
        v._mode = "transform"
        try:
            t.translate(np.array([0.0, 0.0, 4.0]))
            im_zug = h.grab()
            mitgetragen = [s for s in v.renderer._surfaces if s.get("model") is not None]
        finally:
            v.gizmo._drag = None
            v._mode = None
            t.in_drag = False
            t.end_rigid()
            v._changed()
    finally:
        renderer.SURF_ROWS = 4096
    assert mitgetragen, "im starren Zug sollte die Fläche mitgetragen werden (Lage-Matrix)"
    alt = h.scr([28.0, 0.0, 1.0])
    assert _anders(h.pixel(vorher, alt), h.pixel(im_zug, alt)) > 30, "die gezogene Fläche steht noch an ihrem alten Platz"
    nachbar = h.scr([25.0, 0.0, 1.0])
    assert _anders(h.pixel(vorher, nachbar), h.pixel(im_zug, nachbar)) < 12, "die Nachbarfläche hat sich im Zug verändert"

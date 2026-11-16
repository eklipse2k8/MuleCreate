"""Teil-Upload der Striche: ändert sich nur ein Teil der Striche (gleiche Einteilung), bereitet der Renderer nur diese
neu auf und schreibt sie an ihre Stelle im Puffer. Die Harness prüft jeden Teil-Upload gegen die volle Aufbereitung
(Renderer.VERIFY_STROKES) – hier: dass der Weg überhaupt genommen wird und das Bild dasselbe ist."""
import numpy as np

from sketch_machine import renderer
from tests.harness import H, line


def _scene(h):
    h.new_scene()
    sc = h.sc
    sc.new_stroke()
    for k in range(6):
        sc.add_curve(line([0, 0, 0.3 * k], [2, 0.2, 0.3 * k], 12), None)
    h.camera([1.0, 0.0, 0.8], 5, [0.2, 0.8, 0.5])
    h.v._changed()
    h.grab()
    return sc


def test_ein_strich_bewegt_nur_er_wird_neu_aufbereitet(h: H):
    sc = _scene(h)
    r = h.v.renderer
    assert renderer.Renderer.VERIFY_STROKES, "die Harness prüft Teil-Uploads"
    state = r._stroke_state
    c = sc.strokes[-1].curves[2]
    c.points = c.points + np.array([0.0, 0.3, 0.0])
    h.v.update()
    part = h.grab()
    assert r._stroke_state is state and "at" in state, "gleiche Einteilung: Teil-Upload statt Neuaufbau"
    r._stroke_state = None  # voller Neuaufbau desselben Stands
    r._stroke_list = None
    h.v.update()
    full = h.grab()
    assert h.diff(part, full, threshold=2) == 0, "Teil-Upload zeigt dasselbe Bild wie der volle"


def test_andere_einteilung_baut_neu(h: H):
    sc = _scene(h)
    r = h.v.renderer
    state = r._stroke_state
    sc.add_curve(line([0, 0.5, 0], [2, 0.5, 0], 9), None)
    h.v._changed()
    h.grab()
    assert r._stroke_state is not state, "ein Strich mehr: alles neu"
    state = r._stroke_state
    c = sc.strokes[-1].curves[0]
    c.points = np.vstack([c.points, c.points[-1] + [0.1, 0, 0]])
    c.widths = np.append(c.widths, c.widths[-1])
    h.v._changed()
    h.grab()
    assert r._stroke_state is not state, "andere Punktzahl: alles neu"


def test_nichts_geaendert_kein_neuer_stand(h: H):
    _scene(h)
    r = h.v.renderer
    rev = r._stroke_rev
    h.v.update()
    h.grab()
    assert r._stroke_rev == rev, "gleiche Striche: nichts hochgeladen (Schattenkarte bleibt)"

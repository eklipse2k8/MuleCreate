"""Messlatte (Umbau-Plan Schritt 1): Was eine Handlung anfasst, darf nicht mit der Größe der Szene wachsen.

Dieselbe Handlung an EINEM Objekt wird in einer kleinen und in einer sechsmal so großen Szene ausgeführt; verglichen
werden die Arbeitszähler (sketch_machine/counters.py), nicht die Zeit – das Ergebnis ist auf jedem Rechner dasselbe.

BEKANNT führt je Handlung die Zähler, die heute noch mit der Szene wachsen. Das ist die Arbeitsliste des Umbaus:
  - Wächst ein Zähler, der NICHT in BEKANNT steht, schlägt der Test fehl (ein Rundgang über die Szene ist neu dazugekommen).
  - Wächst ein Zähler aus BEKANNT nicht mehr, schlägt der Test auch fehl: Eintrag streichen – der Rundgang ist weg.
"""
import os

import numpy as np
from PySide6.QtOpenGLWidgets import QOpenGLWidget

from sketch_machine import counters, network
from tests.harness import H

KLEIN, GROSS = 6, 36
# heute wachsende Zähler je Handlung (Stand v0.99.189) – wird mit jedem Umbauschritt kürzer
BEKANNT = {
    "kamera": set(),
    "punkt_ziehen": {"netz_schluessel", "netz_linien", "netz_verweise", "flaechen_upload",
                     "strich_objekte_geprueft"},
    "linie_neu": {"netz_schluessel", "netz_linien", "netz_verweise", "strich_objekte_geprueft",
                  "strich_upload"},
    "undo_sichern": {"undo_geprueft"},
    "objekt_ziehen": {"netz_schluessel", "netz_linien", "netz_verweise"},
}


def _objekt(h: H, k):
    """Ein Linienobjekt: Quadrat mit Fläche, eine freie Linie daneben. Die Objekte stehen in einer Reihe."""
    sc = h.sc
    st = sc.new_stroke()
    st.parent = None
    x0 = 3.0 * k
    pts = [np.array(p, float) for p in ([x0, 0, 0], [x0 + 2, 0, 0], [x0 + 2, 0, 2], [x0, 0, 2])]
    lines = []
    for i in range(4):
        sc.add_curve(np.linspace(pts[i], pts[(i + 1) % 4], 8), None)
        lines.append(st.curves[-1])
    network.sync(sc)
    for i in range(4):
        network.join(sc, lines[i], 7, lines[(i + 1) % 4], 0)
    s = sc.create_fill([(c, False) for c in lines])
    s.seed = 1.0
    sc.add_curve(np.linspace([x0, 0.5, 0], [x0 + 2, 0.5, 2], 8), None)
    return st, lines


def _szene(h: H, n):
    h.new_scene()
    objs = [_objekt(h, k) for k in range(n)]
    h.v._changed()
    h.camera([1.0, 0.0, 1.0], 9, [0.3, 0.8, 0.5])  # Blick auf Objekt 0; die übrigen stehen daneben in der Szene
    h.sc.checkpoint()
    return objs


def _bild(h: H):
    QOpenGLWidget.grabFramebuffer(h.v)  # ein Bild wie in der App (h.grab erzwingt den Neubau aller Listen)


def _kamera(h, objs, i):
    h.v.cam.orbit(3, 1, None)
    h.v.update_view()
    _bild(h)


def _punkt_ziehen(h, objs, i):
    st, lines = objs[0]
    p = lines[0].points[0] + np.array([0.0, 0.0, -0.01])
    network.move_point(h.sc, lines[0], 0, p)
    h.v._changed()
    _bild(h)


def _linie_neu(h, objs, i):
    st, lines = objs[0]
    h.sc.active_stroke = st
    h.sc.add_curve(np.linspace([0.2, 0.8 + 0.05 * i, 0.2], [1.8, 0.8 + 0.05 * i, 1.8], 8), None)
    h.v._changed()
    _bild(h)


def _undo_sichern(h, objs, i):
    st, lines = objs[0]
    lines[1].points = lines[1].points + np.array([0.0, 0.001, 0.0])
    h.sc.checkpoint()


def _objekt_ziehen(h, objs, i):
    v = h.v
    t = v.transform_target
    t.translate(np.array([0.0, 0.0, 0.01]))
    _bild(h)


def _ziehen_vor(h, objs):
    v = h.v
    h.edit_mode("edge") if hasattr(h, "edit_mode") else v.set_select_mode(True)
    v.selection = [objs[0][0].id]
    v._changed()
    _bild(h)
    h.sc.checkpoint()
    t = v.transform_target
    t.in_drag = True
    v.gizmo._drag = {"target": t}
    v._mode = "transform"


def _ziehen_nach(h, objs):
    v = h.v
    t = v.transform_target
    v.gizmo._drag = None
    v._mode = None
    t.in_drag = False
    t.end_rigid()
    v._changed()


HANDLUNGEN = {
    "kamera": (_kamera, None, None),
    "punkt_ziehen": (_punkt_ziehen, None, None),
    "linie_neu": (_linie_neu, None, None),
    "undo_sichern": (_undo_sichern, None, None),
    "objekt_ziehen": (_objekt_ziehen, _ziehen_vor, _ziehen_nach),
}


def _zaehlen(h: H, name, n):
    fn, vor, nach = HANDLUNGEN[name]
    objs = _szene(h, n)
    if vor:
        vor(h, objs)
    for i in range(2):  # einlaufen lassen: was nur beim ersten Mal anfällt, zählt nicht
        fn(h, objs, i)
    with counters.measure() as got:
        fn(h, objs, 2)
    if nach:
        nach(h, objs)
    return dict(got)


def _pruefen(h: H, name):
    klein, gross = _zaehlen(h, name, KLEIN), _zaehlen(h, name, GROSS)
    waechst = {k for k in set(klein) | set(gross) if gross.get(k, 0) > 1.5 * klein.get(k, 0) + 4}
    text = ", ".join(f"{k} {klein.get(k, 0)}→{gross.get(k, 0)}" for k in sorted(set(klein) | set(gross)))
    if os.environ.get("MESSLATTE_ZEIGEN"):
        print(f"\n{name}: {text}\n   wächst: {sorted(waechst)}", flush=True)
    bekannt = BEKANNT[name]
    neu = waechst - bekannt
    assert not neu, f"„{name}“ fasst neuerdings mehr an, wenn die Szene größer ist: {sorted(neu)} ({text})"
    weg = bekannt - waechst
    assert not weg, f"„{name}“: {sorted(weg)} wächst nicht mehr mit der Szene – aus BEKANNT streichen ({text})"
    return f"wächst noch: {', '.join(sorted(waechst)) or 'nichts'}"


def test_kamera_drehen_waechst_nicht_mit_der_szene(h: H):
    return _pruefen(h, "kamera")


def test_punkt_ziehen_waechst_nicht_mit_der_szene(h: H):
    return _pruefen(h, "punkt_ziehen")


def test_neue_linie_waechst_nicht_mit_der_szene(h: H):
    return _pruefen(h, "linie_neu")


def test_undo_sichern_waechst_nicht_mit_der_szene(h: H):
    return _pruefen(h, "undo_sichern")


def test_objekt_ziehen_waechst_nicht_mit_der_szene(h: H):
    return _pruefen(h, "objekt_ziehen")

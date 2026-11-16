"""Meldebuch des Flächenabgleichs (scene._touch, scene_surfaces._sync_asked): Eine Fläche, deren Stempel sich geändert
hat, muss wieder hinsehen – auch wenn die Änderung an ihr vorbeiging. Beide Fälle stammen aus der unabhängigen
Durchsicht von v0.99.195 (12.11.); sie brauchen kein Fenster, nur die Szene."""
import numpy as np

import sketch_machine.scene as S
from sketch_machine import network

STUFE = "kern"


def _linie(a, b, n=8):
    return np.linspace(np.asarray(a, float), np.asarray(b, float), n)


def _flaeche(sc, ecken):
    st = sc.new_stroke()
    st.parent = None
    for p, q in zip(ecken, ecken[1:] + ecken[:1]):
        sc.add_curve(_linie(p, q), None)
    network.sync(sc)
    patch = sc.create_patch(list(st.curves))
    assert patch is not None
    return st, patch


def _stempel_gilt(sc, f):
    return f.__dict__.get("_sync_ok") == sc._surface_stamp(f, sc._sync_world(False), network.refs_by_pid(sc), count=False)


def _ruhe(sc, n=4):
    for _ in range(n):
        sc.sync_lofts()


def test_festgehaltene_flaeche_sieht_nach_dem_zug_wieder_hin(h=None):
    """Eine Linie M hängt an der Ecke der Fläche A und gehört zu einem Objekt, das starr gezogen wird. A selbst ist
    unbeteiligt und wird im Zug festgehalten; eine zweite Fläche verformt sich dabei (der Abgleich läuft also je Bild).
    Nach dem Loslassen muss A einmal nachgerechnet werden: ihre Nachbarlinie hat sich bewegt."""
    sc = S.Scene()
    _st, a = _flaeche(sc, [[0, 0, 0], [2, 0, 0], [2, 0, 2], [0, 0, 2]])
    st_c = sc.new_stroke()
    st_c.parent = None
    q = [[10, 0, 0], [12, 0, 0], [12, 0, 2], [10, 0, 2]]
    for i, j in ((0, 1), (1, 2), (2, 3)):
        sc.add_curve(_linie(q[i], q[j]), None)
    st_b = sc.new_stroke()
    st_b.parent = None
    sc.add_curve(_linie(q[3], q[0]), None)
    network.sync(sc)
    b = sc.create_patch(list(st_c.curves) + [st_b.curves[-1]])
    assert b is not None
    sc.active_stroke = st_b
    sc.add_curve(_linie([0, 0, 0], [-1, 0, -1]), None)  # M: an der Ecke von A, im gezogenen Objekt
    m = st_b.curves[-1]
    _ruhe(sc)
    assert any(c is m for c in a._dep_curves) and _stempel_gilt(sc, a)
    t = S.TransformSet([st_b], scene=sc)
    t.in_drag = True
    held = False
    for _ in range(3):
        t.translate(np.array([-0.5, 0.0, 0.0]))
        sc.sync_lofts()
        held |= bool(a.__dict__.get("_idle_hold"))
    t.in_drag = False
    t.end_rigid()
    assert held, "Voraussetzung des Tests: die unbeteiligte Fläche wird im Zug festgehalten"
    assert not _stempel_gilt(sc, a), "Voraussetzung des Tests: der Zug hat den Stempel der Fläche verändert"
    sc.sync_lofts()  # (mit VERIFY_SYNC schlüge hier die Prüfung an, wenn der Fläche vertraut würde)
    assert _stempel_gilt(sc, a), "nach dem Loslassen nicht nachgerechnet: der Stempel der Fläche ist veraltet"


def test_geloeschte_linie_zwei_schritte_weiter_wird_bemerkt(h=None):
    """An der Ecke der Fläche hängt M, daran M2, daran M3. M3 gehört nicht zu den Linien, von denen die Fläche abhängt,
    aber ihr Ende zählt im Stempel mit (wie viele Linien an den Punkten von M2 hängen). Wird M3 gelöscht, meldet sich
    niemand – die Fläche muss es über die Zahl der Linien am Punkt merken."""
    for kette in (2, 3):
        sc = S.Scene()
        _st, a = _flaeche(sc, [[0, 0, 0], [2, 0, 0], [2, 0, 2], [0, 0, 2]])
        st_b = sc.new_stroke()
        st_b.parent = None
        enden = [[0, 0, 0], [-1, 0, -1], [-2, 0, -1], [-3, 0, -1]]
        for p, q in zip(enden[:kette], enden[1:kette + 1]):
            sc.add_curve(_linie(p, q), None)
        _ruhe(sc)
        assert _stempel_gilt(sc, a)
        st_b.curves.remove(st_b.curves[-1])  # die letzte Linie der Kette verschwindet, ohne dass ein Feld gesetzt wird
        if _stempel_gilt(sc, a):
            continue  # (bei dieser Kettenlänge zählt die Linie nicht im Stempel: nichts zu prüfen)
        sc.sync_lofts()
        assert _stempel_gilt(sc, a), f"Kette aus {kette} Linien: das Löschen der letzten wurde nicht bemerkt"

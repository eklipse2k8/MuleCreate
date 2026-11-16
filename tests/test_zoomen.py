"""Zoomen (Alt + rechte Maustaste): stufenlos, auch weit draußen (große Ebenen) – nie ein Sprung."""
import math

from tests.harness import H
from sketch_machine.camera import Camera


def test_zoomen_aus_grosser_entfernung_springt_nicht(h: H):
    cam = Camera()
    cam.dist = 1400.0  # z. B. nach dem Einrahmen einer 1-km-Ebene
    cam.dolly(0.05)
    assert math.isclose(cam.dist, 1400.0 * math.exp(-0.05)), f"Sprung auf {cam.dist:.0f} m"
    cam.dolly(-0.05)
    assert math.isclose(cam.dist, 1400.0)


def test_zoomen_raus_bis_mehrere_kilometer_und_grenzen(h: H):
    cam = Camera()
    cam.dist = 10.0
    for _ in range(400):
        cam.dolly(-0.05)
    assert cam.dist == Camera.MAX_DIST, cam.dist
    for _ in range(800):
        cam.dolly(0.05)
    assert cam.dist == Camera.MIN_DIST, cam.dist


def test_schnittebene_waechst_mit_der_distanz(h: H):
    """Nah wie immer (5 cm), weit draußen mitwachsend: Verhältnis vorn/hinten bleibt, Kilometer-Gelände flimmert nicht."""
    import numpy as np
    from sketch_machine.vp.common import NEAR
    h.new_scene()
    h.camera([0.0, 0.0, 0.0], 10.0, [0.3, 0.8, 0.5])
    assert h.v._near() == NEAR, "normale Distanz: unverändert"
    h.camera([0.0, 0.0, 0.0], 5000.0, [0.3, 0.8, 0.5])
    assert math.isclose(h.v._near(), 5.0) and h.v._far() / h.v._near() <= 1e5 + 1
    eye = h.v.cam.eye
    pts = np.array([eye - h.v.cam.back * 2.0, eye - h.v.cam.back * 50.0])  # 2 m vor der Kamera: abgeschnitten
    _s, ok = h.v.project(pts)
    assert list(ok) == [False, True]


def test_maximale_strichbreite_einstellbar(h: H):
    """Stift in Welteinheiten wächst bis zur eingestellten Grenze (Standard 50 m, bis 5 km); kleinere Grenze nimmt den Stift mit."""
    from sketch_machine.workspace import PEN_MAX_WORLD
    v = h.v
    old = (v.pen_world_mode, v.pen_world, v.pen_max_world)
    try:
        v.pen_world_mode = True
        v.pen_world = 5.0
        v._scale_pen(10.0)
        assert math.isclose(v.pen_world, 50.0), "über die alte 10-m-Grenze"
        for _ in range(20):
            v._scale_pen(10.0)
        assert v.pen_world == PEN_MAX_WORLD == 50.0, "Standard 50 m"
        v.set_pen_max_world(5000.0)
        for _ in range(20):
            v._scale_pen(10.0)
        assert v.pen_world == 5000.0, "von Hand bis 5 km"
        v.set_pen_max_world(2.0)
        assert v.pen_world == 2.0 and v.pen_max_world == 2.0
        v._scale_pen(3.0)
        assert v.pen_world == 2.0
        v.set_pen_max_world(1e9)
        assert v.pen_max_world == 5000.0, "höchstens 5 km"
    finally:
        v.pen_world_mode, v.pen_world, v.pen_max_world = old

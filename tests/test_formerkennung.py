"""Formerkennung Rechteck (shapes.py): Seiten ausgleichen statt Umrisskasten, Ausrichtung ohne Kamera-Einfluss
(Hafentest 09.11.: große Rechtecke ungenau, Ausrichtung wirkte willkürlich)."""
import math

import numpy as np

from sketch_machine import shapes
from tests.harness import H


def _hand_rect(w, h, overshoot, angle=0.0, noise=0.0, seed=1):
    """Rechteck als ein Strich, an jeder Ecke um overshoot über die Ecke hinaus und zurück (wie von Hand)."""
    rng = np.random.default_rng(seed)
    c = [(0, 0), (w, 0), (w, h), (0, h)]
    pts = []
    for i in range(4):
        a, b = np.array(c[i], float), np.array(c[(i + 1) % 4], float)
        d = (b - a) / np.linalg.norm(b - a)
        for t in np.linspace(0, 1, 30):
            pts.append(a + (b - a) * t)
        pts.append(b + d * overshoot)  # über die Ecke hinaus
    pts.append(np.array(c[0], float) + np.array([0, 0.3 * overshoot]))
    pts = np.array(pts) + rng.normal(0, noise, (len(pts), 2))
    rot = np.array([[math.cos(angle), -math.sin(angle)], [math.sin(angle), math.cos(angle)]])
    return pts @ rot.T


def test_ueberzeichnetes_grosses_rechteck_behaelt_seine_groesse(h: H):
    shape = shapes.recognize(_hand_rect(100.0, 40.0, overshoot=8.0, noise=0.3))
    assert shape is not None and shape["kind"] == "rect", shape
    w, hh = np.abs(np.asarray(shape["p1"]) - np.asarray(shape["p0"]))
    assert abs(w - 100.0) < 2.0 and abs(hh - 40.0) < 2.0, f"Größe {w:.1f} x {hh:.1f} statt 100 x 40"


def test_ebenen_achse_statt_bildschirm(h: H):
    """Mit Ebenen-Achse (um 30° gedreht im Bild) liegt ein leicht schief gezeichnetes Rechteck auf der Achse, nicht
    am Bildschirm – auch wenn es fast bildschirmparallel wäre."""
    axis = math.radians(30)
    shape = shapes.recognize(_hand_rect(60.0, 30.0, overshoot=2.0, angle=axis + math.radians(2), noise=0.2), [axis])
    assert shape is not None and shape["kind"] == "rect", shape
    diff = (shape["angle"] - axis + math.pi / 4) % (math.pi / 2) - math.pi / 4
    assert abs(diff) < math.radians(1), f"Ausrichtung {math.degrees(shape['angle']):.1f}° statt der Ebenen-Achse 30°"

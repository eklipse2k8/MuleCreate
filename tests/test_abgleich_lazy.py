"""Abgleich vor einem Bild ohne gemeldete Änderung (Hover, Kamera, Vorschau): übersprungen, solange niemand eine Linie
oder Fläche angefasst hat – und sofort wieder voll, sobald es jemand tut (auch ohne Viewport._changed)."""
import numpy as np

from tests.harness import H
from tests.test_undo_tempo import _two_patches


def _count(sc):
    n = [0]
    real = sc._sync_lofts
    sc._sync_lofts = lambda free: (n.__setitem__(0, n[0] + 1), real(free))[1]
    return n


def test_neuzeichnen_ohne_aenderung_gleicht_nicht_ab(h: H):
    sc, st, patches = _two_patches(h)
    h.v.update()
    h.grab()
    n = _count(sc)
    for _ in range(3):
        h.v.update()
        h.grab()
    assert n[0] == 0, "nichts angefasst: kein voller Abgleich"


def test_jede_aenderung_gleicht_wieder_ab(h: H):
    sc, st, patches = _two_patches(h)
    h.v.update()
    h.grab()
    n = _count(sc)
    c = sc.curve_by_id(patches[0].patch_lines[0])
    mesh = patches[0].fill_mesh()[0].copy()
    pts = c.points.copy()
    pts[len(pts) // 2] += [0.0, 0.5, 0.0]
    c.points = pts  # wie ein Gizmo-Zug: kein _changed, nur neu zeichnen
    h.v.update()
    h.grab()
    now = patches[0].fill_mesh()[0]
    assert n[0] == 1 and not (now.shape == mesh.shape and np.allclose(now, mesh)), "Linie bewegt: Fläche folgt im nächsten Bild"
    patches[1].resolution = patches[1].resolution * 2  # Feld einer Fläche gesetzt
    h.v.update()
    h.grab()
    assert n[0] == 2, "Feld einer Fläche geändert: voller Abgleich"
    patches[1].attached[-1] = {"uv": np.zeros((2, 2)), "on": np.ones(2, bool), "last": b""}  # an Ort und Stelle ergänzt
    h.v.update()
    h.grab()
    assert n[0] == 3, "Verweis-Liste einer Fläche gewachsen: voller Abgleich"
    h.v._changed()
    assert n[0] == 4, "gemeldete Änderung gleicht immer voll ab"

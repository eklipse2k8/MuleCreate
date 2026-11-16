"""Pixelvergleich: die Testszenen (tests/scenes) in mehreren Darstellungen gegen Referenzbilder (tests/_baseline).

Fehlt eine Referenz, wird sie angelegt. Nach gewollten Änderungen an der Darstellung:
    python tests/run.py render --update-baseline
"""
import os

from PySide6.QtGui import QImage

from tests.harness import H, OUT, ROOT, SCENES

BASELINE = os.path.join(ROOT, "tests", "_baseline")
UPDATE = os.environ.get("SKETCH_UPDATE_BASELINE") == "1"
TOLERANCE = 40  # abweichende Stichproben-Pixel, die noch als gleich gelten (Kantenglättung)

MODES = {
    "normal": lambda v: None,
    "licht": lambda v: v.set_light(True),
    "xray": lambda v: v.set_xray(True),
}


def _reset(v):
    v.set_light(False)
    v.set_xray(False)


def _compare(h: H, scene):
    h.load(os.path.join(SCENES, f"{scene}.sketch.json"))
    os.makedirs(BASELINE, exist_ok=True)
    notes, bad = [], []
    for mode, setup in MODES.items():
        _reset(h.v)
        setup(h.v)
        img = h.save_image(f"render_{scene}_{mode}.png")
        ref_path = os.path.join(BASELINE, f"{scene}_{mode}.png")
        if UPDATE or not os.path.exists(ref_path):
            img.save(ref_path)
            notes.append(f"{mode}: Referenz angelegt")
            continue
        n = h.diff(QImage(ref_path), img)
        notes.append(f"{mode}: {n}")
        if n < 0 or n > TOLERANCE:
            bad.append(f"{mode} ({n} Pixel anders)")
    _reset(h.v)
    assert not bad, "Bild weicht ab: " + ", ".join(bad) + " – Bilder in tests/_out"
    return ", ".join(notes)


def test_giesskanne(h: H):
    return _compare(h, "giesskanne")


def test_teetasse(h: H):
    return _compare(h, "teetasse")


def test_pferdekopf(h: H):
    return _compare(h, "pferdekopf")

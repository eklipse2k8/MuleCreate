"""Kanten ziehen mit weich mitgezogenen Nachbarlinien: die Gruppen dafür entstehen einmal je Zug (mit einem gemeinsamen
Knoten-Verzeichnis), nicht je Bild und je Nachbar neu – in einer großen Szene kostete das Sekunden je Bild
(Hafen, import_silos, 10.11.). Das Ergebnis des Zugs bleibt dasselbe."""
import numpy as np

from sketch_machine import components
from tests.harness import H
from tests.test_gruppieren_flaechen import _two_objects


def test_knoten_verzeichnis_nur_einmal_je_zug(h: H):
    from tests.test_flaeche_bewegen import _two_sharing
    sc, st, lines, patches = _two_sharing(h)
    h.edit_mode("edge")
    h.v.selection = []
    h.v.edge_selection = [("line", st.id, lines[n].id) for n in ("ab", "be", "de", "ad")]  # bc, ef hängen an den Enden
    h.v._changed()
    target = h.v.transform_target
    built = []
    real = components.KnotIndex.__init__
    components.KnotIndex.__init__ = lambda self, scene: (built.append(1), real(self, scene))[1]
    try:
        before = {n: c.points.copy() for n, c in lines.items()}
        d = np.array([0.0, 0.25, 0.0])
        for _ in range(4):
            target.translate(d)
            h.v.update()
            h.grab()
        assert len(built) == 1, f"ein Knoten-Verzeichnis für den ganzen Zug ({len(built)} gebaut)"
    finally:
        components.KnotIndex.__init__ = real
    assert np.allclose(lines["ab"].points, before["ab"] + 4 * d), "gewählte Linien ganz bewegt"
    assert np.allclose(lines["cf"].points, before["cf"]), "ferne Linie bleibt"
    hub = lines["bc"].points[:, 1] - before["bc"][:, 1]
    assert abs(float(hub.max()) - 1.0) < 1e-6 and abs(float(hub.min())) < 1e-6, "Nachbarlinie läuft weich aus (1 bis 0)"


def test_eintraege_je_linienobjekt_bleiben_wenn_nichts_geschieht(h: H):
    sc, a, b, qa1, qa2, qb1, qb2 = _two_objects(h)
    h.v._changed()
    h.grab()
    calls = []
    real = type(h.v)._owner_lines
    type(h.v)._owner_lines = lambda self, owner, *args: (calls.append(owner.id), real(self, owner, *args))[1]
    try:
        verify = type(h.v).VERIFY_LISTS
        type(h.v).VERIFY_LISTS = False  # (die Prüfung selbst stellt neu zusammen)
        c = a.curves[0]
        c.points = c.points + [0.0, 0.1, 0.0]
        h.v.update()
        h.grab()
        assert calls == [a.id], f"nur das geänderte Linienobjekt wird neu zusammengestellt ({calls})"
    finally:
        type(h.v)._owner_lines = real
        type(h.v).VERIFY_LISTS = verify

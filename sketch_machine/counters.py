"""Work counters: how much an action touches – independent of the machine (yardstick, PLAN step 1).

Guiding rule of the rework: what an action costs depends on the size of the change, not on the size of the scene. Timings
only say this roughly (different machine, different result); these counters say it exactly. Every place that today runs over
the whole scene counts here how many things it touched:

    from . import counters
    counters.C["netz_linien"] += len(curves)

Read in tests and measurement scripts with measure():

    with counters.measure() as got:
        … action …
    got["netz_linien"]

The counters always run (one addition per place, never per point).
"""
import collections
import contextlib

C = collections.Counter()

# What the counters mean (for reports)
NAMES = {
    "netz_abgleich": "Kurvennetz neu abgeglichen (Durchläufe)",
    "netz_linien": "… dabei angefasste Linien",
    "netz_schluessel": "Linien, über die nur der Schlüssel des Kurvennetzes gebildet wurde",
    "netz_verweise": "Linien, über die das Verzeichnis Punkt → Linien neu gebaut wurde",
    "flaechen_stempel": "Flächen, deren Stempel nachgerechnet wurde",
    "flaechen_abgleich": "Flächen, die wirklich abgeglichen wurden",
    "strich_objekte": "Linienobjekte, deren Strich-Einträge neu zusammengestellt wurden",
    "strich_objekte_geprueft": "Linienobjekte, deren Stand für die Strichliste geprüft wurde",
    "strich_upload": "Striche, die neu aufbereitet und hochgeladen wurden",
    "flaechen_upload": "Flächen, deren Ecken neu hochgeladen wurden",
    "zeichenaufrufe": "Zeichenaufrufe für Flächen (je Fläche und Durchgang einer)",
    "undo_geprueft": "Linien und Flächen, die die Undo-Kopie auf Änderung geprüft hat",
    "suche_objekt": "Objekt per Durchsuchen aller Listen gefunden (object_by_id)",
    "suche_besitzer": "Besitzer einer Linie per Durchsuchen aller Objekte gefunden (owner_of)",
    "linien_index": "Linien, über die das Verzeichnis id → Linie neu gebaut wurde",
}


@contextlib.contextmanager
def measure():
    """Counts what is added inside the block; the returned Counter object is filled after the block."""
    start = C.copy()
    got = collections.Counter()
    try:
        yield got
    finally:
        for k, v in C.items():
            if v != start.get(k, 0):
                got[k] = v - start.get(k, 0)

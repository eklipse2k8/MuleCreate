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
    "netz_abgleich": "curve net re-synchronised (passes)",
    "netz_linien": "… lines touched in the process",
    "netz_schluessel": "lines over which only the key of the curve net was built",
    "netz_verweise": "lines over which the point → lines directory was rebuilt",
    "flaechen_stempel": "surfaces whose stamp was recomputed",
    "flaechen_abgleich": "surfaces that were actually synchronised",
    "strich_objekte": "line objects whose stroke entries were reassembled",
    "strich_objekte_geprueft": "line objects whose state was checked for the stroke list",
    "strich_upload": "strokes that were reprocessed and uploaded",
    "flaechen_upload": "surfaces whose corners were uploaded again",
    "zeichenaufrufe": "draw calls for surfaces (one per surface and pass)",
    "undo_geprueft": "lines and surfaces the undo copy checked for changes",
    "suche_objekt": "object found by searching all lists (object_by_id)",
    "suche_besitzer": "owner of a line found by searching all objects (owner_of)",
    "linien_index": "lines over which the id → line directory was rebuilt",
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

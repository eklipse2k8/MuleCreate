"""Testlauf: alle tests/test_*.py, jede Datei in einem eigenen Prozess (eigenes App-Fenster).

    python tests/run.py                 alle Tests (Stufe 1 und 2)
    python tests/run.py paint layers    nur Dateien, deren Name das enthält
    python tests/run.py --kern          nur Stufe 1: Kern-Tests ohne Fenster (Sekunden) – nach jeder Änderung
    python tests/run.py --gross         Stufe 3: Prüfrunde an der großen Hafenszene (Minuten) – nach jedem Planschritt
                                        und vor jedem Paket; braucht die eingefrorene Szene (bench/pruefrunde.py)

Drei Stufen (tests/LIESMICH.md):
    1 Kern      Datei trägt die Zeile  STUFE = "kern"  – kein Fenster, die Tests bekommen h = None
    2 Bedienung alle übrigen Dateien – echtes Fenster, echte Mausereignisse
    3 Groß      bench/pruefrunde.py und bench/hafen.py an der Hafenszene
    python tests/run.py --update-baseline   Referenzbilder des Pixelvergleichs neu anlegen

Ergebnisse je Test:
    OK          bestanden
    FEHLER      gescheitert (muss behoben werden)
    ERWARTET    bekanntes Problem (expected_failure), scheitert wie erwartet
    BEHOBEN     bekanntes Problem läuft plötzlich durch – Markierung entfernen
Exit-Code 1, wenn es FEHLER gibt.
"""
import glob
import json
import os
import subprocess
import sys
import time
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run_file(path, out_json):
    """Im Kindprozess: alle test_* Funktionen einer Datei nacheinander ausführen."""
    sys.path.insert(0, ROOT)
    import importlib.util
    from tests.harness import H, QT_ERRORS
    spec = importlib.util.spec_from_file_location(os.path.splitext(os.path.basename(path))[0], path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    kern = getattr(mod, "STUFE", "") == "kern"  # Stufe 1: ohne Fenster (die Prüfmodi der Harness gelten trotzdem)
    h = None if kern else H()
    results = []
    for name in [n for n in dir(mod) if n.startswith("test_")]:
        fn = getattr(mod, name)
        expected = getattr(fn, "expected_failure", None)
        t = time.perf_counter()
        try:
            if h is not None:
                h.new_scene()
            QT_ERRORS.clear()
            note = fn(h)
            if h is not None:
                h.grab()
            if QT_ERRORS:  # Fehler in paintGL o. ä.: im Viewport bunte Kästchen
                lines = QT_ERRORS[0].splitlines()
                raise RuntimeError("Fehler in einem Qt-Rückruf: " + lines[-1] + "\n" + "\n".join(lines[-4:-1]))
            status, detail = ("BEHOBEN", expected) if expected else ("OK", note or "")
        except Exception as exc:  # noqa: BLE001
            if expected:
                status, detail = "ERWARTET", f"{expected} – {type(exc).__name__}: {exc}"
            else:
                status, detail = "FEHLER", "".join(traceback.format_exception(exc)).strip().splitlines()[-1] + \
                    "\n" + "".join(traceback.format_tb(exc.__traceback__)[-2:])
        results.append({"test": name, "status": status, "detail": str(detail), "s": round(time.perf_counter() - t, 2)})
        with open(out_json, "w", encoding="utf-8") as f:
            json.dump(results, f)
    if h is not None:
        h.close()


def is_kern(path):
    """Stufe 1? (am Quelltext erkannt, ohne die Datei zu laden)"""
    with open(path, encoding="utf-8") as f:
        return any(line.startswith('STUFE = "kern"') for line in f)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if "--child" in sys.argv:
        run_file(args[0], args[1])
        return 0
    env = dict(os.environ, PYTHONPATH=ROOT, PYTHONIOENCODING="utf-8")
    if "--update-baseline" in sys.argv:
        env["SKETCH_UPDATE_BASELINE"] = "1"
    if "--gross" in sys.argv:
        scene = os.path.join(ROOT, "Feedback", "2026-11-11_architektur", "messlatte", "hafen_messlatte.mule")
        if not os.path.exists(scene):
            print("Stufe 3 braucht die eingefrorene Hafenszene:\n  " + scene + "\n(liegt nicht im Git)")
            return 1
        return subprocess.run([sys.executable, os.path.join(ROOT, "bench", "pruefrunde.py")], cwd=ROOT, env=env).returncode
    files = sorted(glob.glob(os.path.join(ROOT, "tests", "test_*.py")))
    if args:
        files = [f for f in files if any(a in os.path.basename(f) for a in args)]
    if "--kern" in sys.argv:
        files = [f for f in files if is_kern(f)]
    else:
        files.sort(key=lambda f: not is_kern(f))  # das Schnelle zuerst: ein Fehler im Kern zeigt sich in Sekunden
    out_dir = os.path.join(ROOT, "tests", "_out")
    os.makedirs(out_dir, exist_ok=True)
    totals = {}
    start = time.perf_counter()
    for f in files:
        name = os.path.basename(f)
        out_json = os.path.join(out_dir, name + ".json")
        if os.path.exists(out_json):
            os.remove(out_json)
        proc = subprocess.run([sys.executable, os.path.abspath(__file__), "--child", f, out_json], cwd=ROOT, env=env,
                              capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900)
        results = json.load(open(out_json, encoding="utf-8")) if os.path.exists(out_json) else []
        print(f"\n== {name}")
        for r in results:
            totals[r["status"]] = totals.get(r["status"], 0) + 1
            line = f"  {r['status']:9} {r['test']} ({r['s']} s)"
            if r["status"] != "OK" or r["detail"]:
                line += f"\n             {r['detail'].strip()}".replace("\n", "\n             ")
            print(line)
        if proc.returncode != 0:
            totals["FEHLER"] = totals.get("FEHLER", 0) + 1
            tail = (proc.stderr or proc.stdout).strip().splitlines()[-6:]
            print("  FEHLER    Prozess abgebrochen:\n             " + "\n             ".join(tail))
    print(f"\nGesamt ({time.perf_counter() - start:.0f} s): " +
          ", ".join(f"{k} {v}" for k, v in sorted(totals.items())))
    return 1 if totals.get("FEHLER") else 0


if __name__ == "__main__":
    sys.exit(main())

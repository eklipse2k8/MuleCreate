# PyInstaller: Mule als Ordner mit Programmdatei. Bauen im Repo-Stamm:
#   .venv/Scripts/python.exe -m PyInstaller packaging/mule.spec --noconfirm
# Ergebnis: dist/Mule. Prüfen: dist/Mule/Mule.exe --selftest ergebnis.json
# PyInstaller baut immer nur für das System, auf dem es läuft (Windows, Linux, Mac je einzeln).
import os
import sys

from PyInstaller.utils.hooks import collect_all, collect_submodules

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
ICON = os.path.join(SPECPATH, "mule.ico")  # aus dem letzten Frame der Logo-Animation (mit Schriftzug)

datas = [(os.path.join(ROOT, "bible", "sketch_machine_bible.md"), "bible"),
         (os.path.join(ROOT, "sketch_machine", "assets", "mule_start.webp"), os.path.join("sketch_machine", "assets")),
         (os.path.join(ROOT, "sketch_machine", "assets", "mule_icon.png"), os.path.join("sketch_machine", "assets")),
         # Review: läuft als eigenes Programm im Python mit faster-whisper, muss also als .py-Datei mit
         (os.path.join(ROOT, "sketch_machine", "review_transcribe.py"), "sketch_machine")]
# Arbeitsweise-Paket des Sketch Briefs (Regeln, Rollen, Hooks, Sichtkarte) – der Export kopiert es in den Brief-Ordner
for base, _dirs, files in os.walk(os.path.join(ROOT, "sketch_machine", "brief_package")):
    if os.sep + "tests" in base or "__pycache__" in base:
        continue
    datas += [(os.path.join(base, f), os.path.relpath(base, ROOT)) for f in files]
binaries = []
hidden = collect_submodules("sketch_machine") + collect_submodules("glcontext") + collect_submodules("moderngl")
for package in ("pxr",):  # USD findet seine Plugins über plugInfo.json neben den Bibliotheken
    d, b, h = collect_all(package)
    datas, binaries, hidden = datas + d, binaries + b, hidden + h

a = Analysis([os.path.join(SPECPATH, "mule_main.py")], pathex=[ROOT], datas=datas, binaries=binaries, hiddenimports=hidden,
             excludes=["tkinter", "tests", "matplotlib", "IPython", "PySide6.scripts"])
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="Mule", console=False,
          icon=ICON if os.path.exists(ICON) else None)
coll = COLLECT(exe, a.binaries, a.datas, name="Mule")
sys.path.insert(0, SPECPATH)
import third_party  # noqa: E402 – Lizenzen fremder Software neben Mule.exe (bricht ab, wenn ein Text fehlt)
third_party.write(os.path.join(DISTPATH, "Mule"), [e[0] for e in a.pure], [e[0] for e in a.binaries + a.datas])
if sys.platform == "darwin":
    app = BUNDLE(coll, name="Mule.app", icon=None, bundle_identifier="com.felixbfx.mule")

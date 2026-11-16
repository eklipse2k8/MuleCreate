"""Licenses of third-party software in the package: creates licenses/ and THIRD_PARTY_NOTICES.md next to Mule.exe.
Called by mule.spec after the build, with the modules PyInstaller actually bundled.
If no license text is found for a package, the build aborts: then add it here (OVERRIDES)."""
import importlib.metadata as md
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
GNU = os.path.join(HERE, "licenses")
OWN = {"sketch_machine"}
LICENSE_WORDS = ("licen", "copying", "notice", "authors")
# The PySide6 packages only ship the reference to the commercial Qt license; Mule uses Qt under LGPL-3.0.
QT = ("LGPL-3.0-only", ["LGPL-3.0.txt", "GPL-3.0.txt"])
OVERRIDES = {"pyside6": QT, "pyside6-essentials": QT, "pyside6-addons": QT, "pyside6-pdf": QT, "shiboken6": QT}
SKIP_FILES = ("licenseref-qt-commercial",)

QT_NOTE = """Qt for Python (PySide6, shiboken6) und die Qt-Bibliotheken stehen unter der GNU LGPL 3.0
(licenses/LGPL-3.0.txt, sie baut auf licenses/GPL-3.0.txt auf). Mule verwendet sie unverändert.
Die Bibliotheken liegen als einzelne Dateien im Ordner _internal/PySide6 und können gegen eine eigene,
kompatible Fassung ausgetauscht werden. Quellcode: https://download.qt.io/official_releases/QtForPython/
und https://download.qt.io/official_releases/qt/ (Version {version})."""
FFMPEG_NOTE = """FFmpeg (avcodec, avformat, avutil, swresample, swscale) kommt mit Qt Multimedia und steht unter der
GNU LGPL 2.1 oder später (licenses/LGPL-2.1.txt), gebaut ohne GPL- und Nonfree-Teile. Mule verwendet es
unverändert zum Abspielen von Videos im Notizbrett. Die Dateien liegen in _internal/PySide6 und können
ausgetauscht werden. Quellcode: https://ffmpeg.org/download.html; welche FFmpeg-Fassung Qt {version}
verwendet, steht in der Qt-Dokumentation zu Qt Multimedia."""

MESA_NOTE = """`opengl32sw.dll` ist Mesa (llvmpipe, Software-Rendering), von Qt vorgebaut mitgeliefert und mit LLVM gebaut.
Mesa steht unter der MIT-Lizenz (licenses/Mesa-MIT.txt), LLVM unter der University of Illinois/NCSA-Lizenz
(licenses/LLVM-NCSA.txt). Quellcode: https://archive.mesa3d.org/ und https://releases.llvm.org/."""


def _top(name):
    return name.replace("\\", "/").split("/")[0].split(".")[0]


def _norm(path):
    return path.replace("\\", "/").lower()


def distributions(modules, files=()):
    """Packages (distributions) for the bundled module names, excluding Mule itself and the standard library.
    If several packages share a folder (PySide6, -Addons, -WebEngine ...), only counts what a file in the package comes from."""
    owners = md.packages_distributions()
    packed = {_norm(f) for f in files} | {_norm(m).replace(".", "/") for m in modules}
    found = {}
    for module in {_top(m) for m in modules} | {_top(f) for f in files}:
        if module.lower() in OWN:
            continue
        dists = [md.distribution(n) for n in dict.fromkeys(owners.get(module, []))]
        if len(dists) > 1 and packed:
            dists = [d for d in dists if any(_norm(str(f)).rsplit(".", 1)[0] in packed or _norm(str(f)) in packed
                                             for f in d.files or [])]
        for d in dists:
            found[d.metadata["Name"].lower().replace("_", "-")] = d
    return found


def _license(d):
    meta = d.metadata
    text = meta.get("License-Expression") or ""
    if not text and meta.get("License") and len(meta["License"]) < 80:
        text = meta["License"].strip()
    if not text:
        text = ", ".join(c.split("::")[-1].strip() for c in meta.get_all("Classifier") or [] if c.startswith("License ::"))
    return text or "siehe Lizenztext"


def _files(d):
    out = []
    for f in d.files or []:
        low = str(f).replace("\\", "/").lower()
        base = low.rsplit("/", 1)[-1]
        if any(w in base for w in LICENSE_WORDS) and not any(s in base for s in SKIP_FILES) and not low.endswith((".py", ".pyc", ".pyi")):
            path = d.locate_file(f)
            if os.path.isfile(path):
                out.append((str(f).replace("\\", "/"), str(path)))
    return out


def write(bundle, modules, binaries=()):
    """bundle: folder with Mule.exe. modules/binaries: names from PyInstaller's analysis."""
    target = os.path.join(bundle, "licenses")
    shutil.rmtree(target, ignore_errors=True)
    os.makedirs(target)
    for name in ("LGPL-3.0.txt", "GPL-3.0.txt", "LGPL-2.1.txt", "Mesa-MIT.txt", "LLVM-NCSA.txt"):
        shutil.copy2(os.path.join(GNU, name), os.path.join(target, name))
    shutil.copy2(os.path.join(HERE, "..", "LICENSE"), os.path.join(bundle, "LICENSE.txt"))  # Mule itself: GPL-3.0
    rows, missing, qt_version = [], [], ""
    for key, d in sorted(distributions(modules, binaries).items()):
        name, version = d.metadata["Name"], d.version
        folder = f"{name}-{version}"
        if key in OVERRIDES:
            lic, texts = OVERRIDES[key]
            qt_version = version
            rows.append((name, version, lic, ", ".join(f"licenses/{t}" for t in texts)))
            continue
        files = _files(d)
        if not files:
            missing.append(name)
            continue
        for rel, src in files:
            dst = os.path.join(target, folder, rel.split(".dist-info/", 1)[-1])
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)
        rows.append((name, version, _license(d), f"licenses/{folder}/"))
    if missing:
        raise SystemExit(f"Kein Lizenztext gefunden für: {', '.join(missing)} – in packaging/third_party.py eintragen.")
    python_license = os.path.join(sys.base_prefix, "LICENSE.txt")
    if not os.path.isfile(python_license):
        python_license = os.path.join(sys.base_prefix, "LICENSE")
    shutil.copy2(python_license, os.path.join(target, "Python-LICENSE.txt"))
    rows.append(("Python", sys.version.split()[0], "PSF-2.0 (mit OpenSSL, libffi, zlib u. a.)", "licenses/Python-LICENSE.txt"))
    has_ffmpeg = any("avcodec" in _top_file(b) for b in binaries)
    if has_ffmpeg:
        rows.append(("FFmpeg (über Qt Multimedia)", "Qt-Build", "LGPL-2.1-or-later", "licenses/LGPL-2.1.txt"))
    has_mesa = any(_top_file(b) == "opengl32sw.dll" for b in binaries)
    if has_mesa:  # Qt software OpenGL (Mesa llvmpipe, built with LLVM), steps in when no driver supports OpenGL
        rows.append(("Mesa llvmpipe (opengl32sw.dll, über Qt)", "Qt-Build", "MIT; darin LLVM: NCSA",
                     "licenses/Mesa-MIT.txt, licenses/LLVM-NCSA.txt"))

    lines = ["# Fremde Software in Mule Create", "",
             "Mule Create – Copyright (C) 2026 Felix Barthel.", "",
             "Mule Create selbst ist freie Software unter der GNU General Public License v3.0 (`LICENSE.txt`).",
             "Der Name „Mule Create“ und das Mule-Logo sind davon ausgenommen und vorbehalten.", "",
             "Mule Create enthält die folgenden Programme und Bibliotheken anderer Leute. Ihre Lizenztexte liegen im",
             "Ordner `licenses/` neben dieser Datei. Diese Liste entsteht beim Bauen automatisch.", "",
             "| Paket | Version | Lizenz | Lizenztext |", "|---|---|---|---|"]
    lines += [f"| {n} | {v} | {lic} | {where} |" for n, v, lic, where in rows]
    lines += ["", "## Qt", "", QT_NOTE.format(version=qt_version or "siehe oben")]
    if has_ffmpeg:
        lines += ["", "## FFmpeg", "", FFMPEG_NOTE.format(version=qt_version or "")]
    if has_mesa:
        lines += ["", "## Mesa", "", MESA_NOTE]
    lines += ["", "## Microsoft Visual C++ Runtime", "",
              "`VCRUNTIME140.dll`, `MSVCP140.dll` und verwandte Dateien sind von Microsoft zur Weitergabe mit Programmen freigegeben.", ""]
    with open(os.path.join(bundle, "THIRD_PARTY_NOTICES.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    return rows


def _top_file(name):
    return name.replace("\\", "/").rsplit("/", 1)[-1].lower()

#!/usr/bin/env bash
# Mule unter Linux starten.
#
# Die App bringt ihr eigenes Python mit (wie Houdini oder Blender): beim ersten Start legt dieses Skript mit uv
# ein eigenständiges Python 3.14 im Projektordner an (runtime/python) und daraus die Umgebung .venv mit genau den
# Paketversionen aus requirements.txt. Das System-Python (z. B. 3.9) wird weder benutzt noch verändert, Admin-
# Rechte sind nicht nötig. Danach startet die App ohne uv und ohne Internet – auch für andere Nutzer, die den
# Projektordner lesen können.
set -u
cd "$(dirname "$(readlink -f "$0")")" || exit 1
HERE="$(pwd)"
PY_VERSION="3.14"
VENV_PY="$HERE/.venv/bin/python"

fail() {
    echo
    echo "FEHLER: $*" >&2
    if [ -t 0 ]; then read -r -p "Enter zum Schließen … " _; fi
    exit 1
}

venv_python_ok() {
    [ -x "$VENV_PY" ] && "$VENV_PY" -c "import sys; sys.exit(sys.version_info[:2] != tuple(map(int, '$PY_VERSION'.split('.'))))" \
        2>/dev/null
}

venv_ok() {
    venv_python_ok && "$VENV_PY" -c "import PySide6, numpy, moderngl, scipy" 2>/dev/null
}

find_uv() {
    UV="$(command -v uv || true)"
    for cand in "$HOME/.local/bin/uv" "$HOME/.cargo/bin/uv"; do
        [ -z "$UV" ] && [ -x "$cand" ] && UV="$cand"
    done
}

if ! venv_ok && venv_python_ok; then
    # Umgebung passt, nur neue Pakete fehlen (z. B. scipy seit v0.84.2): nachinstallieren, nichts neu anlegen
    echo "Mule: neue Pakete installieren (einmalig, braucht Internet) …"
    find_uv
    export UV_LINK_MODE=copy
    if [ -n "$UV" ]; then
        "$UV" pip install --python "$VENV_PY" -r "$HERE/requirements.txt" || fail "Die Pakete konnten nicht installiert werden."
    else
        "$VENV_PY" -m pip install -r "$HERE/requirements.txt" || fail "Die Pakete konnten nicht installiert werden."
    fi
fi

if ! venv_ok; then
    echo "Mule: eigenes Python $PY_VERSION und Pakete einrichten (einmalig, braucht Internet) …"
    find_uv
    [ -n "$UV" ] || fail "uv wurde nicht gefunden. Einmalig installieren (ohne Admin-Rechte):
    curl -LsSf https://astral.sh/uv/install.sh | sh
danach ./start.sh erneut ausführen."
    export UV_PYTHON_INSTALL_DIR="$HERE/runtime/python"  # Python liegt im Projekt, nicht im Home-Verzeichnis
    export UV_LINK_MODE=copy  # echte Kopien statt Links in den uv-Cache (Netzwerkspeicher, andere Nutzer)
    export UV_PYTHON_PREFERENCE=only-managed  # nie das System-Python nehmen
    if [ -e "$HERE/.venv" ]; then  # alte Umgebung (z. B. Python 3.10) beiseitelegen, nicht löschen
        old="$HERE/.venv.alt-$(date +%Y%m%d-%H%M%S)"
        mv "$HERE/.venv" "$old" && echo "Alte Umgebung verschoben nach: $old (kann gelöscht werden)"
    fi
    "$UV" python install "$PY_VERSION" || fail "Python $PY_VERSION konnte nicht installiert werden."
    "$UV" venv --python "$PY_VERSION" "$HERE/.venv" || fail "Die Umgebung .venv konnte nicht angelegt werden."
    "$UV" pip install --python "$VENV_PY" -r "$HERE/requirements.txt" || fail "Die Pakete konnten nicht installiert werden."
    venv_ok || fail "Die Umgebung ist unvollständig – Ausgabe oben prüfen."
    echo "Fertig eingerichtet: $("$VENV_PY" --version), Python liegt in runtime/python."
fi

export PYTHONFAULTHANDLER=1  # stürzt doch etwas ab, steht die genaue Stelle im Terminal
"$VENV_PY" -m sketch_machine "$@"
status=$?
if [ $status -ne 0 ] && [ -t 0 ]; then
    echo
    read -r -p "Mule wurde mit Fehler $status beendet – Enter zum Schließen … " _
fi
exit $status

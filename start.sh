#!/usr/bin/env bash
# Start Mule on Linux.
#
# The app brings its own Python (like Houdini or Blender): on the first start this script uses uv to set up a
# standalone Python 3.14 inside the project folder (runtime/python) and from it the environment .venv with exactly the
# package versions of requirements.txt. The system Python (e.g. 3.9) is neither used nor changed, no admin rights are
# needed. After that the app starts without uv and without internet – also for other users who can read the folder.
set -u
cd "$(dirname "$(readlink -f "$0")")" || exit 1
HERE="$(pwd)"
PY_VERSION="3.14"
VENV_PY="$HERE/.venv/bin/python"

fail() {
    echo
    echo "ERROR: $*" >&2
    if [ -t 0 ]; then read -r -p "Enter to close … " _; fi
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
    # environment fine, only new packages missing (e.g. scipy since v0.84.2): install them, create nothing new
    echo "Mule: installing new packages (once, needs internet) …"
    find_uv
    export UV_LINK_MODE=copy
    if [ -n "$UV" ]; then
        "$UV" pip install --python "$VENV_PY" -r "$HERE/requirements.txt" || fail "The packages could not be installed."
    else
        "$VENV_PY" -m pip install -r "$HERE/requirements.txt" || fail "The packages could not be installed."
    fi
fi

if ! venv_ok; then
    echo "Mule: setting up its own Python $PY_VERSION and packages (once, needs internet) …"
    find_uv
    [ -n "$UV" ] || fail "uv was not found. Install it once (no admin rights needed):
    curl -LsSf https://astral.sh/uv/install.sh | sh
then run ./start.sh again."
    export UV_PYTHON_INSTALL_DIR="$HERE/runtime/python"  # Python lives in the project, not in the home folder
    export UV_LINK_MODE=copy  # real copies instead of links into the uv cache (network drives, other users)
    export UV_PYTHON_PREFERENCE=only-managed  # never use the system Python
    if [ -e "$HERE/.venv" ]; then  # move an old environment (e.g. Python 3.10) aside, do not delete it
        old="$HERE/.venv.alt-$(date +%Y%m%d-%H%M%S)"
        mv "$HERE/.venv" "$old" && echo "Old environment moved to: $old (can be deleted)"
    fi
    "$UV" python install "$PY_VERSION" || fail "Python $PY_VERSION could not be installed."
    "$UV" venv --python "$PY_VERSION" "$HERE/.venv" || fail "The environment .venv could not be created."
    "$UV" pip install --python "$VENV_PY" -r "$HERE/requirements.txt" || fail "The packages could not be installed."
    venv_ok || fail "The environment is incomplete – check the output above."
    echo "Set up: $("$VENV_PY" --version), Python lives in runtime/python."
fi

export PYTHONFAULTHANDLER=1  # if something crashes, the exact place shows in the terminal
"$VENV_PY" -m sketch_machine "$@"
status=$?
if [ $status -ne 0 ] && [ -t 0 ]; then
    echo
    read -r -p "Mule ended with error $status – Enter to close … " _
fi
exit $status

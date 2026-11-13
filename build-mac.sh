#!/bin/zsh
set -e

script_dir="${0:A:h}"
cd "$script_dir"

python_bin="${PYTHON_BIN:-/opt/homebrew/bin/python3.12}"
if ! "$python_bin" -c 'import sys, tkinter; assert sys.version_info >= (3, 10)' >/dev/null 2>&1; then
    echo 'Serve Python 3.10+ con Tkinter. Imposta PYTHON_BIN sul suo percorso.' >&2
    exit 1
fi

"$python_bin" -m venv .venv-build
.venv-build/bin/python -m pip install pyinstaller
PYINSTALLER_CONFIG_DIR="$script_dir/.pyinstaller-cache" .venv-build/bin/pyinstaller \
    --noconfirm --clean MoodleVolta.spec

echo 'App pronta: dist/MoodleVolta.app'

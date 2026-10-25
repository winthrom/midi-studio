#!/usr/bin/env bash
# Build MIDI-Studio.app for macOS (Apple Silicon) with PyInstaller.  v22ze-223
# Run packaging/macos/fetch_payload.sh first.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
WORK="$ROOT/build/macos"
DIST="$ROOT/dist/macos"
cd "$ROOT"
PY="${PYTHON:-python3}"
mkdir -p "$WORK"
[ -x "$WORK/venv/bin/python" ] || "$PY" -m venv "$WORK/venv"
VPY="$WORK/venv/bin/python"
"$VPY" -m pip install --upgrade pip
"$VPY" -m pip install mido python-rtmidi pyfluidsynth python-ly pyinstaller certifi
"$VPY" -m py_compile main.py
"$VPY" -c "import tkinter; print('Tcl/Tk', tkinter.TkVersion)"
rm -rf "$DIST/MIDI-Studio" "$DIST/MIDI-Studio.app"
"$VPY" -m PyInstaller --noconfirm --clean --distpath "$DIST" --workpath "$WORK/pyi" \
    packaging/macos/midi-studio.spec
APP="$DIST/MIDI-Studio.app"
[ -d "$APP" ] || { echo "ERROR: $APP was not built"; exit 1; }
# arm64 refuses unsigned code: sign everything inside, then the bundle (ad hoc, no Apple account)
find "$APP" \( -name "*.dylib" -o -name "*.so" \) -exec codesign --force --sign - {} \; 2>/dev/null || true
codesign --force --deep --sign - "$APP"
codesign --verify --deep --strict "$APP" && echo "signature (ad hoc) verifies"
echo "BUILT: $APP  ($(du -sh "$APP" | cut -f1))"

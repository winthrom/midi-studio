#!/usr/bin/env bash
# Stage the app and build the AppImage.  Works on a normal host or inside the
# manylinux container (docker_build.sh).  Needs network (base Python image and
# appimagetool are downloaded from GitHub on first use).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
HERE="$ROOT/packaging/linux"
WORK="$ROOT/build/linux"
DIST="$ROOT/dist/linux"
PYVER="${PYVER:-3.12}"
LINUX_TAG="${LINUX_TAG:-manylinux_2_28_x86_64}"
PYTHON="${PYTHON:-python3}"

"$HERE/stage_app.sh"

mkdir -p "$WORK" "$DIST"
if [ ! -x "$WORK/venv/bin/python-appimage" ]; then
    "$PYTHON" -m venv "$WORK/venv"
    "$WORK/venv/bin/python" -m pip install --upgrade pip python-appimage
fi

# appimagetool / base image are AppImages; run them without needing FUSE.
export APPIMAGE_EXTRACT_AND_RUN=1

cd "$WORK"
rm -f ./*.AppImage
"$WORK/venv/bin/python-appimage" build app \
    -p "$PYVER" -l "$LINUX_TAG" \
    "$HERE/recipe" \
    -x "$WORK/stage/midistudio"

BUILT="$(ls -1 ./*.AppImage | head -n1)"
mv -f "$BUILT" "$DIST/MIDI-Studio-x86_64.AppImage"
chmod +x "$DIST/MIDI-Studio-x86_64.AppImage"
echo "built: $DIST/MIDI-Studio-x86_64.AppImage"

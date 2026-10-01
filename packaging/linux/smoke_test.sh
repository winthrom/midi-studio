#!/usr/bin/env bash
# Usage: smoke_test.sh path/to/MIDI-Studio-x86_64.AppImage
set -euo pipefail
IMG="${1:-dist/linux/MIDI-Studio-x86_64.AppImage}"
[ -f "$IMG" ] || { echo "not found: $IMG" >&2; exit 1; }
chmod +x "$IMG"
export APPIMAGE_EXTRACT_AND_RUN=1
"$IMG" --selftest

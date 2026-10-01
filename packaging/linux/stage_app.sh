#!/usr/bin/env bash
# Copy the app's source + payload into build/linux/stage/midistudio
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
OUT="$ROOT/build/linux/stage/midistudio"
rm -rf "$OUT"
mkdir -p "$OUT"

REQUIRED="main gui midi_io audio_backend app_resources synth theory export sys_platform"
for m in $REQUIRED; do
    [ -f "$ROOT/$m.py" ] || { echo "ERROR: missing $m.py" >&2; exit 1; }
done

for f in "$ROOT"/*.py; do
    b="$(basename "$f")"
    case "$b" in
        test_*|patch_*|harness*|models.py) continue ;;
    esac
    cp "$f" "$OUT/"
done
cp "$ROOT/packaging/linux/selftest.py" "$OUT/"

for sub in lib sound; do
    if [ -d "$ROOT/packaging/linux/payload/$sub" ] && \
       find "$ROOT/packaging/linux/payload/$sub" -type f ! -name .gitkeep | grep -q .; then
        cp -a "$ROOT/packaging/linux/payload/$sub" "$OUT/$sub"
        rm -f "$OUT/$sub/.gitkeep"
        echo "payload: bundled $sub/"
    else
        echo "payload: no $sub/ (will use system one)"
    fi
done
python3 -m py_compile "$OUT"/*.py
rm -rf "$OUT/__pycache__"
echo "staged: $OUT"

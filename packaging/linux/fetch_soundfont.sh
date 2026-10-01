#!/usr/bin/env bash
# Download MuseScore_General.sf3 (MIT licence) + its licence/readme into
# packaging/linux/payload/sound/.  Needs network.  Safe to re-run.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
OUT="$ROOT/packaging/linux/payload/sound"
BASE="https://ftp.osuosl.org/pub/musescore/soundfont/MuseScore_General"
mkdir -p "$OUT"
for f in MuseScore_General.sf3 MuseScore_General_License.md MuseScore_General_Readme.md MuseScore_General_Sample_Sources.csv; do
    echo "downloading $f"
    curl -fsSL --retry 3 -o "$OUT/$f.part" "$BASE/$f"
    mv -f "$OUT/$f.part" "$OUT/$f"
done
# sanity: a SoundFont is a RIFF file of type "sfbk"
head -c 12 "$OUT/MuseScore_General.sf3" | tail -c 4 | grep -q sfbk \
    || { echo "ERROR: MuseScore_General.sf3 is not a SoundFont file" >&2; exit 1; }
SIZE=$(stat -c %s "$OUT/MuseScore_General.sf3")
[ "$SIZE" -gt 20000000 ] || { echo "ERROR: file too small ($SIZE bytes)" >&2; exit 1; }
echo "sha256 $(sha256sum "$OUT/MuseScore_General.sf3" | cut -d' ' -f1)  MuseScore_General.sf3 ($SIZE bytes)"
echo "--- licence (first lines) ---"
head -n 12 "$OUT/MuseScore_General_License.md"
echo "ok: $OUT"

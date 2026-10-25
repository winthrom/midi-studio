#!/usr/bin/env bash
# Fetch the native payload for the macOS (Apple Silicon) build.  v22ze-223
#   libfluidsynth + the libraries it needs  -> packaging/macos/payload/lib   (made self-contained)
#   MuseScore_General.sf3                   -> packaging/macos/payload/sound
# Needs Homebrew (present on GitHub's macOS runners).  Safe to re-run.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LIB="$ROOT/packaging/macos/payload/lib"
SND="$ROOT/packaging/macos/payload/sound"
BASE="https://ftp.osuosl.org/pub/musescore/soundfont/MuseScore_General"
mkdir -p "$LIB" "$SND"

# ---- FluidSynth ---------------------------------------------------------------
brew list fluidsynth >/dev/null 2>&1 || brew install fluidsynth
brew list dylibbundler >/dev/null 2>&1 || brew install dylibbundler
PREFIX="$(brew --prefix fluidsynth)"
SRC="$(ls "$PREFIX"/lib/libfluidsynth.*.dylib 2>/dev/null | head -1)"
[ -n "$SRC" ] || { echo "ERROR: libfluidsynth*.dylib not found under $PREFIX/lib"; ls "$PREFIX/lib" || true; exit 1; }
echo "FluidSynth: $(brew list --versions fluidsynth)  ($SRC)"
rm -f "$LIB"/*.dylib
cp -L "$SRC" "$LIB/$(basename "$SRC")"
# copy every Homebrew library it needs next to it and point them all at @loader_path
dylibbundler -of -b -cd -x "$LIB/$(basename "$SRC")" -d "$LIB" -p @loader_path/
# the program looks for libfluidsynth*.dylib in lib/
ls -l "$LIB"

# each library's own name tag must point into this folder too (dylibbundler leaves the one we gave it alone)
for f in "$LIB"/*.dylib; do
    install_name_tool -id "@loader_path/$(basename "$f")" "$f"
done
# also make the usual short name available (libfluidsynth.3.dylib), which other libraries may ask for
for f in "$LIB"/libfluidsynth.*.*.dylib; do
    [ -e "$f" ] || continue
    short="$(basename "$f" | sed -E 's/^(libfluidsynth\.[0-9]+)\..*/\1.dylib/')"
    [ -e "$LIB/$short" ] || cp "$f" "$LIB/$short" && install_name_tool -id "@loader_path/$short" "$LIB/$short"
done

# every library must now refer only to the system or to its own folder
bad=0
for f in "$LIB"/*.dylib; do
    refs="$(otool -L "$f" | tail -n +2 | awk '{print $1}')"
    for r in $refs; do
        case "$r" in
            /usr/lib/*|/System/*|@loader_path/*|@rpath/*) ;;
            *) echo "NOT SELF-CONTAINED: $(basename "$f") -> $r"; bad=1 ;;
        esac
    done
done
[ "$bad" -eq 0 ] || { echo "ERROR: some libraries still point outside the bundle"; exit 1; }
# new install names invalidate signatures; arm64 will not load unsigned code, so sign them (ad hoc)
for f in "$LIB"/*.dylib; do codesign --force --sign - "$f"; done

# licence note
mkdir -p "$LIB/LICENSES"
cat > "$LIB/LICENSES/README.txt" <<TXT
FluidSynth (LGPL-2.1), from Homebrew: https://formulae.brew.sh/formula/fluidsynth
Source: https://github.com/FluidSynth/fluidsynth
The libraries in this folder are dynamically linked and can be replaced by the user.
Other libraries here are FluidSynth's dependencies from Homebrew, each under its own licence.
TXT

# ---- Soundfont ----------------------------------------------------------------
for f in MuseScore_General.sf3 MuseScore_General_License.md MuseScore_General_Readme.md MuseScore_General_Sample_Sources.csv; do
    echo "downloading $f"
    curl -fsSL --retry 5 --retry-delay 10 -o "$SND/$f.part" "$BASE/$f"
    mv -f "$SND/$f.part" "$SND/$f"
done
head -c 12 "$SND/MuseScore_General.sf3" | tail -c 4 | grep -q sfbk || { echo "ERROR: not a SoundFont file"; exit 1; }
SIZE=$(stat -f %z "$SND/MuseScore_General.sf3")
[ "$SIZE" -gt 20000000 ] || { echo "ERROR: soundfont too small ($SIZE bytes)"; exit 1; }
echo "sha256 $(shasum -a 256 "$SND/MuseScore_General.sf3" | cut -d' ' -f1)  MuseScore_General.sf3 ($SIZE bytes)"
echo "Payload ready."

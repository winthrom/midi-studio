#!/usr/bin/env bash
# Runs INSIDE quay.io/pypa/manylinux_2_28_x86_64 (see docker_build_fluidsynth.sh).
# Builds libsndfile + libfluidsynth, then collects them and their non-system
# dependencies into packaging/linux/payload/lib/ (via collect_libs.sh).
#
# Design: ALSA is the only audio driver compiled in.  PipeWire and PulseAudio
# desktops provide an ALSA device (pipewire-alsa / pulse plugin), and linking
# libasound from the HOST (never bundled) keeps those plugins working.  The
# only hard host requirement is libasound.so.2.
set -euo pipefail

FS_VERSION="${FS_VERSION:-2.6.1}"
SNDFILE_VERSION="${SNDFILE_VERSION:-1.2.2}"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
WORK="$ROOT/build/linux/fs-work"
PREFIX="$WORK/prefix"
OUTLIB="$ROOT/packaging/linux/payload/lib"
JOBS="$(nproc)"

fix_owner() {
    if [ -n "${HOST_UID:-}" ]; then
        chown -R "$HOST_UID:${HOST_GID:-$HOST_UID}" "$ROOT/build" "$ROOT/packaging/linux/payload" 2>/dev/null || true
    fi
}
trap fix_owner EXIT

rm -rf "$WORK"
mkdir -p "$WORK" "$PREFIX"
cd "$WORK"

echo "== system packages =="
dnf install -y alsa-lib-devel libogg-devel libvorbis-devel
for opt in flac-devel opus-devel; do
    dnf install -y "$opt" || echo "WARNING: $opt not available (libsndfile will build without it)"
done

echo "== build tools (cmake, ninja, patchelf) =="
/opt/python/cp312-cp312/bin/python -m venv "$WORK/tools"
"$WORK/tools/bin/pip" install --quiet "cmake<4" ninja patchelf
export PATH="$WORK/tools/bin:$PATH"

fetch() {  # fetch URL FILE
    curl -fsSL --retry 3 -o "$2" "$1"
    echo "sha256 $(sha256sum "$2" | cut -d' ' -f1)  $2"
}

echo "== libsndfile $SNDFILE_VERSION =="
fetch "https://github.com/libsndfile/libsndfile/releases/download/${SNDFILE_VERSION}/libsndfile-${SNDFILE_VERSION}.tar.xz" sndfile.tar.xz
tar xf sndfile.tar.xz
cmake -S "libsndfile-${SNDFILE_VERSION}" -B build-sndfile -G Ninja \
    -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX="$PREFIX" -DCMAKE_INSTALL_LIBDIR=lib \
    -DBUILD_SHARED_LIBS=ON -DBUILD_PROGRAMS=OFF -DBUILD_EXAMPLES=OFF -DBUILD_TESTING=OFF \
    -DENABLE_EXTERNAL_LIBS=ON -DENABLE_MPEG=OFF 2>&1 | tee sndfile-configure.log
cmake --build build-sndfile -j"$JOBS"
cmake --install build-sndfile

echo "== FluidSynth $FS_VERSION =="
fetch "https://github.com/FluidSynth/fluidsynth/archive/refs/tags/v${FS_VERSION}.tar.gz" fluidsynth.tar.gz
tar xf fluidsynth.tar.gz
cmake -S "fluidsynth-${FS_VERSION}" -B build-fs -G Ninja \
    -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX="$PREFIX" -DCMAKE_INSTALL_LIBDIR=lib \
    -DCMAKE_PREFIX_PATH="$PREFIX" -DBUILD_SHARED_LIBS=ON \
    -Denable-alsa=ON -Denable-libsndfile=ON -Denable-threads=ON \
    -Denable-jack=OFF -Denable-pulseaudio=OFF -Denable-pipewire=OFF -Denable-sdl3=OFF \
    -Denable-dbus=OFF -Denable-readline=OFF -Denable-portaudio=OFF -Denable-oss=OFF \
    -Denable-midishare=OFF -Denable-ladspa=OFF -Denable-openmp=OFF -Denable-signalsmith=OFF \
    -Denable-native-dls=OFF -Denable-network=OFF -Denable-systemd=OFF \
    2>&1 | tee fs-configure.log

if grep -q "Could NOT find SndFile" fs-configure.log || grep -q "compiled without OGG/Vorbis" fs-configure.log; then
    echo "ERROR: FluidSynth did not find libsndfile with Vorbis support; SF3 soundfonts would not load." >&2
    exit 1
fi
cmake --build build-fs -j"$JOBS"
cmake --install build-fs

echo "== collect =="
"$ROOT/packaging/linux/collect_libs.sh" "$PREFIX/lib" "$OUTLIB"

mkdir -p "$OUTLIB/LICENSES/fluidsynth" "$OUTLIB/LICENSES/libsndfile"
cp "fluidsynth-${FS_VERSION}/LICENSE" "$OUTLIB/LICENSES/fluidsynth/"
cp "libsndfile-${SNDFILE_VERSION}/COPYING" "$OUTLIB/LICENSES/libsndfile/"
cat > "$OUTLIB/LICENSES/README.txt" <<EOF
Bundled native libraries (dynamically linked; replaceable):
  FluidSynth ${FS_VERSION}   LGPL-2.1   https://github.com/FluidSynth/fluidsynth
  libsndfile ${SNDFILE_VERSION}   LGPL-2.1   https://github.com/libsndfile/libsndfile
  libogg, libvorbis, FLAC, opus (if present): BSD-style, texts in the folders here.
Corresponding source for the versions above is available at the URLs above
(tags v${FS_VERSION} and ${SNDFILE_VERSION}).  Built by packaging/linux/build_fluidsynth.sh.
EOF

echo "== load test (inside the container) =="
python3 - "$OUTLIB" <<'PY'
import ctypes, glob, sys
lib = sorted(glob.glob(sys.argv[1] + "/libfluidsynth.so*"))[0]
l = ctypes.CDLL(lib)
l.fluid_version_str.restype = ctypes.c_char_p
print("loaded", lib, "->", l.fluid_version_str().decode())
PY
echo "DONE: payload/lib is ready.  Now run ./packaging/linux/docker_build.sh (or build_appimage.sh)."

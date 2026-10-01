#!/usr/bin/env bash
# Compile libfluidsynth (+ libsndfile for SF3 soundfonts) inside the old-glibc
# manylinux container and put the results in packaging/linux/payload/lib/.
# Runs as root INSIDE the container (it must install -devel packages); files it
# writes are handed back to you at the end.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
IMAGE="${IMAGE:-quay.io/pypa/manylinux_2_28_x86_64}"
docker run --rm \
    -e HOST_UID="${SUDO_UID:-$(id -u)}" -e HOST_GID="${SUDO_GID:-$(id -g)}" \
    -e FS_VERSION -e SNDFILE_VERSION \
    -v "$ROOT":/src -w /src \
    "$IMAGE" \
    bash packaging/linux/build_fluidsynth.sh

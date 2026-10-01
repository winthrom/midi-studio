#!/usr/bin/env bash
# Build inside the old-glibc manylinux container so anything compiled into
# payload/ stays compatible with glibc 2.28+.  Files are written as YOU.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
IMAGE="${IMAGE:-quay.io/pypa/manylinux_2_28_x86_64}"
docker run --rm \
    --user "$(id -u):$(id -g)" \
    -e HOME=/tmp/home \
    -e PYTHON=/opt/python/cp312-cp312/bin/python \
    -v "$ROOT":/src -w /src \
    "$IMAGE" \
    bash -c 'mkdir -p /tmp/home && packaging/linux/build_appimage.sh'

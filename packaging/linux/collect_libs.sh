#!/usr/bin/env bash
# Usage: collect_libs.sh <dir-with-libfluidsynth.so*> <output-dir>
# Copies libfluidsynth and every dependency EXCEPT core system libraries
# (those must come from the user's machine) into <output-dir>, flat, under
# their SONAME; sets rpath $ORIGIN; strips; and refuses if any file needs a
# glibc newer than 2.28.
set -euo pipefail
SRC="${1:?source lib dir}"
OUT="${2:?output dir}"
MAX_GLIBC="${MAX_GLIBC:-2.28}"

# Provided by the host, never bundled.  libasound MUST stay host-side so the
# host's ALSA plugins (pipewire, pulse) keep working.
EXCLUDE='^(linux-vdso\.so.*|ld-linux.*|libc\.so.*|libm\.so.*|libdl\.so.*|libpthread\.so.*|librt\.so.*|libutil\.so.*|libresolv\.so.*|libnsl\.so.*|libgcc_s\.so.*|libstdc\+\+\.so.*|libasound\.so.*)$'

fs="$(ls "$SRC"/libfluidsynth.so.* 2>/dev/null | head -n1 || true)"
[ -n "$fs" ] || { echo "ERROR: no libfluidsynth.so.* in $SRC" >&2; exit 1; }
fs="$(readlink -f "$fs")"

mkdir -p "$OUT"
find "$OUT" -maxdepth 1 -type f -name '*.so*' -delete

soname() { readelf -d "$1" | sed -n 's/.*Library soname: \[\(.*\)\].*/\1/p' | head -n1; }

declare -A DONE=()
queue=("$fs")
while [ "${#queue[@]}" -gt 0 ]; do
    f="${queue[0]}"; queue=("${queue[@]:1}")
    name="$(soname "$f")"; [ -n "$name" ] || name="$(basename "$f")"
    [ -z "${DONE[$name]:-}" ] || continue
    DONE[$name]=1
    cp -L "$f" "$OUT/$name"
    chmod 755 "$OUT/$name"
    while read -r dep path _; do
        [ -n "$path" ] && [ "$path" != "not" ] || continue
        [ "${path#/}" != "$path" ] || continue
        if [[ "$dep" =~ $EXCLUDE ]]; then continue; fi
        queue+=("$path")
    done < <(LD_LIBRARY_PATH="$SRC:${LD_LIBRARY_PATH:-}" ldd "$f" | sed -n 's/^[[:space:]]*\([^ ]*\) => \(.*\) (0x.*/\1 \2/p')
    if LD_LIBRARY_PATH="$SRC:${LD_LIBRARY_PATH:-}" ldd "$f" | grep -q "not found"; then
        echo "ERROR: unresolved dependency for $f:" >&2
        LD_LIBRARY_PATH="$SRC:${LD_LIBRARY_PATH:-}" ldd "$f" | grep "not found" >&2
        exit 1
    fi
done

# Licences of bundled third-party rpms (when built in an rpm-based container).
if command -v rpm >/dev/null 2>&1; then
    for f in "$OUT"/*.so*; do
        pkg="$(rpm -qf --qf '%{NAME}' "$(LD_LIBRARY_PATH="$SRC" ldd "$fs" | sed -n "s#.*$(basename "$f") => \(/[^ ]*\) .*#\1#p" | head -n1)" 2>/dev/null || true)"
        if [ -n "$pkg" ] && [ -d "/usr/share/licenses/$pkg" ]; then
            mkdir -p "$OUT/LICENSES/$pkg"
            cp -r "/usr/share/licenses/$pkg/." "$OUT/LICENSES/$pkg/"
        fi
    done
fi

for f in "$OUT"/*.so*; do
    if command -v patchelf >/dev/null 2>&1; then
        patchelf --set-rpath '$ORIGIN' "$f"
    else
        echo "WARNING: patchelf missing; relying on LD_LIBRARY_PATH for $f" >&2
    fi
    strip --strip-unneeded "$f" 2>/dev/null || true
done

# glibc ceiling check
worst="0"
for f in "$OUT"/*.so*; do
    v="$(objdump -T "$f" 2>/dev/null | grep -o 'GLIBC_[0-9][0-9.]*' | sed 's/GLIBC_//' | sort -V | tail -n1 || true)"
    [ -n "$v" ] || continue
    if [ "$(printf '%s\n%s\n' "$v" "$worst" | sort -V | tail -n1)" = "$v" ]; then worst="$v"; fi
    if [ "$(printf '%s\n%s\n' "$v" "$MAX_GLIBC" | sort -V | tail -n1)" != "$MAX_GLIBC" ]; then
        echo "ERROR: $(basename "$f") needs GLIBC_$v (> $MAX_GLIBC)" >&2
        exit 1
    fi
done

echo "bundled into $OUT:"
ls -l "$OUT" | sed 's/^/  /'
echo "highest glibc symbol version needed: $worst (limit $MAX_GLIBC)"
if readelf -d "$OUT"/*.so* 2>/dev/null | grep -q 'libstdc++'; then
    echo "NOTE: something needs libstdc++ from the host (fine on any desktop distro)."
fi
echo "host must provide: libasound.so.2 (+ libc)"

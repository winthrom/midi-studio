#! /bin/bash
# python-appimage substitutes {{ python-executable }}.
export MIDI_STUDIO_APP_DIR="${APPDIR}/midistudio"
export LD_LIBRARY_PATH="${APPDIR}/midistudio/lib${LD_LIBRARY_PATH:+:${LD_LIBRARY_PATH}}"
if [ "${1:-}" = "--selftest" ]; then
    exec {{ python-executable }} -s "${APPDIR}/midistudio/selftest.py"
fi
exec {{ python-executable }} -s "${APPDIR}/midistudio/main.py" "$@"

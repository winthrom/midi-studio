# Linux AppImage (Phase 1)

Builds `MIDI-Studio-x86_64.AppImage` with python-appimage.
Baseline: manylinux_2_28 x86_64 (glibc 2.28, roughly 2019+ distros), Python 3.12.

## Layout

    recipe/                python-appimage recipe (desktop file, icon, entrypoint, requirements)
    payload/lib/           (step 2) libfluidsynth + its non-system dependencies
    payload/sound/         (step 3) MuseScore_General.sf3 + licence files
    stage_app.sh           copies the app's .py files + payload into build/linux/stage/midistudio
    build_appimage.sh      stage + build (run directly on a host, or inside the container)
    docker_build.sh        runs build_appimage.sh inside quay.io/pypa/manylinux_2_28_x86_64
    smoke_test.sh          runs the AppImage's headless self-test

## Build

Plain host build (needs python3 with venv, curl/network; Docker NOT needed):

    ./packaging/linux/build_appimage.sh

Build in the old-glibc container (what release builds should use, needed once
payload/lib holds a compiled libfluidsynth):

    ./packaging/linux/docker_build.sh

Result: `dist/linux/MIDI-Studio-x86_64.AppImage`

## Test

    ./packaging/linux/smoke_test.sh dist/linux/MIDI-Studio-x86_64.AppImage

It prints what the bundle contains (Tk, mido/rtmidi, bundled libfluidsynth,
soundfont).  It does not open a window.

## Notes

- The AppImage runs `main.py` from `$APPDIR/midistudio` and sets
  `MIDI_STUDIO_APP_DIR` and `LD_LIBRARY_PATH` so `app_resources.py` finds the
  bundled libfluidsynth and soundfont.
- LilyPond (used for engraving/MusicXML) is an external program and is NOT bundled.

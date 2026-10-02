# Windows build (Phase 2)

Target: Windows 10 / 11, 64-bit.  Python 3.12.  (Windows 7/8.1 = Python 3.8 and
32-bit Windows are NOT covered; see the project roadmap.)

## Build  (on the Windows machine)

1. Install Python 3.12 (64-bit) from python.org; tick "Add python.exe to PATH"
   and keep the "py launcher" option.
2. Double-click `packaging\windows\build_windows.cmd`
   (or run it from a Command Prompt in the repo folder).
3. Result: `dist\windows\MIDI-Studio\MIDI-Studio.exe`  (a folder; zip it to share)

## Check the build

Double-click `packaging\windows\smoke_test.cmd`.  It runs
`MIDI-Studio-selftest.exe`, a console program built from the same bundle that
checks Tk, mido/rtmidi, python-ly, and whether libfluidsynth and a soundfont
are bundled (step 2 adds them).  PASS/FAIL is printed; no window opens.

## Files

    midi-studio.spec    PyInstaller recipe (one folder, two programs: the app and the selftest)
    build_windows.ps1   creates build\windows\venv, installs requirements, runs PyInstaller
    build_windows.cmd   double-clickable wrapper (bypasses the PowerShell script-policy prompt)
    smoke_test.cmd      runs the selftest
    midi-studio.ico     icon (the same artwork as the Linux AppImage)
    payload\lib\       (step 2) libfluidsynth DLLs
    payload\sound\     (step 3) MuseScore_General.sf3 + licence files

The app is NOT signed, so Windows SmartScreen will say "Windows protected your
PC" on first run: click "More info", then "Run anyway".

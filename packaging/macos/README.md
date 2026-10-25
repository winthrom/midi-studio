# MIDI Studio for macOS (Apple Silicon) -- experimental

Built on GitHub's macOS runner (`.github/workflows/macos.yml`):

1. `fetch_payload.sh`  : FluidSynth from Homebrew, made self-contained with dylibbundler, plus the MuseScore General soundfont.
2. `build_macos.sh`    : PyInstaller (`midi-studio.spec`) -> `dist/macos/MIDI-Studio.app`, signed ad hoc (arm64 will not run unsigned code).
3. The workflow runs `MIDI-Studio.app/Contents/MacOS/MIDI-Studio-selftest`, zips the app with a START HERE note, and uploads `MIDI-Studio-macos-arm64.zip`.

Not signed with an Apple Developer ID and not notarized (that costs $99 a year), so the first start needs a one-time approval:
System Settings > Privacy & Security > "Open Anyway", or in Terminal: `xattr -dr com.apple.quarantine /Applications/MIDI-Studio.app`.

Intel Macs: not built yet (needs a tester).

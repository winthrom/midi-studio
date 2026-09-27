# Embedded FluidSynth proof of concept

Goal: prove we can synthesize audio directly, in-process, from a
bundled soundfont — no TiMidity subprocess, no shelling out to any
external program at all. This is step one toward a self-sufficient
app (like MuseScore) that doesn't depend on whatever audio tooling
happens to be installed/working on the user's system.

This is a **standalone POC**. It does not import or touch `gui.py`,
`midi_io.py`, or anything else in `midi-studio`. Nothing about the
existing app's architecture is changed by dropping this in.

## What's here

- `fluidsynth_poc.py` — the actual proof of concept.
- `soundfonts/TimGM6mb.sf2` — a small (~6 MB) bundled General MIDI
  soundfont, so the script has something to play out of the box with
  no setup. See **Licensing** below before this goes into a real
  release build.

## Setup

You need two things, which are different from each other:

1. **The FluidSynth *library* itself** (the actual synthesizer,
   written in C) — this has to be present on the system already for
   this POC, since we're not bundling it yet (see "What this doesn't
   prove yet" below):
   - Arch/EndeavourOS: `sudo pacman -S fluidsynth`
   - Debian/Ubuntu: `sudo apt install libfluidsynth3`
   - macOS: `brew install fluid-synth`
   - Windows: a prebuilt `libfluidsynth-3.dll`, e.g. via MSYS2 or vcpkg

2. **pyfluidsynth** — the Python binding that loads that library via
   ctypes and gives us a Python API:
   ```
   pip install pyfluidsynth numpy
   ```

## Running it

**Live playback** (plays through your actual speakers — the real
test on your machine):
```
python3 fluidsynth_poc.py
```

**Offline WAV render** (no audio device needed at all — this is how
it was verified in a sandboxed environment with no sound card, and
it's a handy regression check anywhere, CI included):
```
python3 fluidsynth_poc.py --wav out.wav
```

Both play one note (middle C, acoustic grand piano, GM program 0) for
1.5 seconds plus a 1-second release tail.

Verified in a headless sandbox: the WAV path produced a correctly
structured stereo/44.1kHz/16-bit file with non-silent audio
(RMS ≈ 390, peak ≈ 2500 out of 32767) — confirming the whole chain
(soundfont load → program select → note-on → sample generation) works
end to end, independent of any audio driver being present.

## What this proves

- We can load a soundfont and synthesize real audio entirely
  in-process, with zero external processes.
- The Python-level integration (pyfluidsynth ↔ libfluidsynth) works.

## What this doesn't prove yet (deliberately out of scope for this step)

- **Bundling the native library.** This POC still depends on
  `libfluidsynth` being installed on the system via the OS package
  manager — exactly the kind of dependency the self-sufficient-app
  goal is trying to eliminate (see the pacman/multilib breakage from
  earlier — that's the failure mode we're trying to make impossible
  for end users). The next step is packaging a specific, known-good
  build of libfluidsynth *inside* the app per platform (Linux/Win11/
  macOS), the way MuseScore does, so nothing needs to be separately
  installed.
- **Live playback on your actual machine.** The WAV render path is
  fully verified; live audio-driver playback (`fluidsynth_poc.py` with
  no `--wav`) needs to be tested on a machine with real audio hardware
  — please confirm you actually hear the note.
- **MIDI file playback.** This plays one hardcoded note. Wiring this
  up to actually play a `Song`/MIDI file is a separate, later step,
  after the core synthesis path and the bundling story are both
  solid.

## Licensing note — read before shipping

`TimGM6mb.sf2` is **GPL-2 licensed** (created by Tim Brechbill; this
copy comes from the Debian/Ubuntu `timgm6mb-soundfont` package,
originally sourced from MuseScore 1.3). It's fine to redistribute for
this proof-of-concept and for development, but GPL-2 is a real
copyleft license — worth deciding deliberately whether this is the
soundfont you want to ship in a real release, or whether you want a
soundfont under different terms (e.g. a public-domain/CC0 GM
soundfont) depending on what license you want for `midi-studio`
overall. Not a decision to make by default via what happened to be
easy to `apt install` during a POC.

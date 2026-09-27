#!/usr/bin/env python3
"""
fluidsynth_poc.py -- minimal embedded-FluidSynth proof of concept.

Goal: prove that we can synthesize audio directly, in-process, from a
bundled soundfont, with NO external subprocess (no TiMidity, no shell-
out of any kind). This is deliberately independent of midi-studio's
existing gui.py / midi_io.py -- nothing here imports or touches them.

Two modes:

  1. Live playback (default): opens the platform's default audio
     driver via FluidSynth itself and plays one note through your
     speakers. This is the real end-to-end test on an actual machine.

         python3 fluidsynth_poc.py

  2. Offline WAV render (--wav): renders the same note to a .wav file
     using FluidSynth's sample-generation API directly, with NO audio
     driver / device involved at all. This is how the concept was
     verified in a headless/sandboxed environment with no sound card,
     and it's a useful regression check on any machine (CI included)
     since it doesn't depend on audio hardware being present.

         python3 fluidsynth_poc.py --wav out.wav

Requires:
  - the pyfluidsynth Python package  (pip install pyfluidsynth)
  - the FluidSynth shared library available on the system:
      Linux:   libfluidsynth.so.3   (e.g. `sudo pacman -S fluidsynth`
               or `sudo apt install libfluidsynth3`)
      macOS:   libfluidsynth.dylib  (e.g. `brew install fluid-synth`)
      Windows: libfluidsynth-3.dll (bundled build, or via vcpkg/MSYS2)

  Note: pyfluidsynth is a *binding*, not the synth itself -- it loads
  the real FluidSynth shared library via ctypes at runtime. The
  self-sufficient-installer goal (no external dependency for the end
  user) means eventually bundling that shared library inside the app
  per platform, the same way MuseScore ships its own copy rather than
  relying on whatever the OS package manager happens to have. This
  script proves the Python-level integration works; bundling the
  native library per platform is a separate, later step.
"""
import argparse
import os
import sys
import wave

import fluidsynth

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_SOUNDFONT = os.path.join(HERE, "soundfonts", "TimGM6mb.sf2")

SAMPLE_RATE = 44100
GM_ACOUSTIC_GRAND_PIANO = 0  # General MIDI program 0
MIDDLE_C = 60
VELOCITY = 100
NOTE_SECONDS = 1.5
RELEASE_TAIL_SECONDS = 1.0


def _load_synth(soundfont_path, gain=0.6):
    if not os.path.isfile(soundfont_path):
        raise FileNotFoundError(f"Soundfont not found: {soundfont_path}")

    synth = fluidsynth.Synth(samplerate=float(SAMPLE_RATE), gain=gain)
    sfid = synth.sfload(soundfont_path)
    if sfid == -1:
        raise RuntimeError(f"FluidSynth failed to load soundfont: {soundfont_path}")
    synth.program_select(0, sfid, 0, GM_ACOUSTIC_GRAND_PIANO)
    return synth


def play_live(soundfont_path, driver=None):
    """Play one note through the system's default (or given) audio driver."""
    synth = _load_synth(soundfont_path)
    synth.start(driver=driver)  # None = FluidSynth's own per-platform default

    print(f"Playing middle C (pitch {MIDDLE_C}) via live audio driver "
          f"({driver or 'platform default'}) ...")
    synth.noteon(0, MIDDLE_C, VELOCITY)
    fluidsynth.time.sleep(NOTE_SECONDS)
    synth.noteoff(0, MIDDLE_C)
    fluidsynth.time.sleep(RELEASE_TAIL_SECONDS)  # let the release tail ring out

    synth.delete()
    print("Done. If you didn't hear anything, check the --driver argument "
          "and your system's default audio output device.")


def render_wav(soundfont_path, out_path):
    """Render one note straight to a WAV file, no audio driver involved."""
    synth = _load_synth(soundfont_path)

    total_seconds = NOTE_SECONDS + RELEASE_TAIL_SECONDS
    total_frames = int(SAMPLE_RATE * total_seconds)
    note_off_frame = int(SAMPLE_RATE * NOTE_SECONDS)

    synth.noteon(0, MIDDLE_C, VELOCITY)

    chunk = 1024  # frames per get_samples() call
    frames_written = 0
    samples = []
    while frames_written < total_frames:
        if frames_written < note_off_frame <= frames_written + chunk:
            # note-off falls inside this chunk -- render up to it, then release
            head = note_off_frame - frames_written
            if head > 0:
                samples.append(synth.get_samples(head))
                frames_written += head
            synth.noteoff(0, MIDDLE_C)
            continue
        n = min(chunk, total_frames - frames_written)
        samples.append(synth.get_samples(n))
        frames_written += n

    synth.delete()

    import numpy as np
    audio = np.concatenate(samples)  # interleaved stereo int16, per pyfluidsynth

    with wave.open(out_path, "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)  # int16
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(audio.tobytes())

    rms = float(np.sqrt(np.mean(audio.astype(np.float64) ** 2)))
    peak = int(np.max(np.abs(audio)))
    print(f"Wrote {out_path}: {total_frames} frames ({total_seconds:.1f}s), "
          f"RMS={rms:.1f}, peak={peak} (max possible {2**15 - 1})")
    if rms < 1.0:
        print("WARNING: rendered audio is silent or near-silent -- "
              "something is wrong (check the soundfont path/program).")
        sys.exit(1)
    print("Non-silent audio confirmed -- synthesis path works end-to-end.")


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--soundfont", default=DEFAULT_SOUNDFONT,
                         help=f"Path to a .sf2 file (default: bundled {DEFAULT_SOUNDFONT})")
    parser.add_argument("--driver", default=None,
                         help="Audio driver name for live playback "
                              "(e.g. alsa, pulseaudio, coreaudio, dsound, wasapi). "
                              "Default: FluidSynth's own per-platform default.")
    parser.add_argument("--wav", metavar="OUT.wav", default=None,
                         help="Render to this WAV file instead of live playback "
                              "(no audio driver / device needed).")
    args = parser.parse_args()

    if args.wav:
        render_wav(args.soundfont, args.wav)
    else:
        play_live(args.soundfont, args.driver)


if __name__ == "__main__":
    main()

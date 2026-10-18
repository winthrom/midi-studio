# Running MIDI Studio from the source code (Linux)

Most people should use the AppImage (see the README). Use this page if you want to
run the program from a copy of the code, for example to try changes.

The package names below are the usual ones; they differ a little between distributions,
so if one is not found, search your package manager for it.

## 1. System packages

Ubuntu / Kubuntu / Debian / Mint:

    sudo apt install git python3 python3-venv python3-tk fluidsynth libfluidsynth3 fluid-soundfont-gm lilypond build-essential libasound2-dev libjack-dev

Arch / EndeavourOS:

    sudo pacman -S git python tk fluidsynth soundfont-fluid lilypond alsa-lib jack2

What they are for: `python3-tk` is the window toolkit, `fluidsynth` and the soundfont
make the sound, `lilypond` prints scores, and the build tools plus the ALSA/JACK
development files let the MIDI-keyboard package (`python-rtmidi`) install.

## 2. Get the code and install the Python packages

    git clone https://github.com/winthrom/midi-studio.git
    cd midi-studio
    python3 -m venv .venv
    .venv/bin/pip install -r requirements.txt

## 3. Start it

    .venv/bin/python main.py

## Notes

- Sound: from source the program uses the system synthesizer and soundfont (for example
  FluidR3). The AppImage carries its own copy instead.
- The AppImage and Windows downloads are built from this same code by GitHub Actions.
- To print scores, `lilypond` must be on your PATH (`lilypond --version` should work).

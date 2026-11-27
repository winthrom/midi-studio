# MIDI Studio: a free MIDI sequencer and notation editor

**MIDI Studio** is a free MIDI sequencer, MIDI editor and notation program for Windows, Linux and macOS (macOS is experimental).
Open a MIDI file and it draws the music as sheet music, shows it as a piano roll, and plays it with a built-in synthesizer.

**[Download](#download)** | **[Releases](https://github.com/winthrom/midi-studio/releases)** | **[User guide](docs/USER_GUIDE.md)**

What you can do with it:

- **Read and play** a MIDI file as a score or as a piano roll (horizontal or vertical, right hand and left hand in different
  colours, keys that light up as the notes sound), with a tempo you can change.
- **Record** from a MIDI keyboard, and mute, solo and choose the sound of each instrument in a mixer.
- **Tidy a score that was played by hand**: separate the hands, fix chords and measures. These repair tools change how the
  score is drawn and keep the original sound (Quantize is the exception, and says so), and everything can be undone.
- **Add suggested fingering and marks** to piano music (suggestions only: check them with a teacher or performer).
- **Print** the score, or export it as MIDI, LilyPond or MusicXML to carry on in other notation software.

MIDI Studio was inspired by MidiSoft Studio for Windows. It is developed for the Sterling Lions Club, Virginia, USA, and is
free software ([GNU General Public License, version 3 or later](LICENSE)).

## Supporting the Sterling Lions Club

MIDI Studio is free, and is developed for the Sterling Lions Club, Virginia, USA.
Donations are gratefully accepted: [make a donation](https://e-clubhouse.org/sites/sterlingva/page-10.php).

Contains MIDI Studio code by Michael Winthrop for the Sterling Lions Club, Virginia, USA. see: https://github.com/winthrom/midi-studio

## Download

Latest test build (no account needed):

- [Windows 10 / 11, 64-bit](https://github.com/winthrom/midi-studio/releases/latest/download/MIDI-Studio-windows-x64.zip)
- [Linux, 64-bit (AppImage)](https://github.com/winthrom/midi-studio/releases/latest/download/MIDI-Studio-x86_64.AppImage)
- All versions: [Releases page](https://github.com/winthrom/midi-studio/releases)

Windows: unzip the whole folder and run MIDI-Studio.exe. Windows will probably show "Windows protected your PC" (the program is not code-signed, so the publisher is unknown): click the small, faint "More info" link, then "Run anyway".
Linux: make the file runnable (chmod +x MIDI-Studio-x86_64.AppImage), then double-click it.

## Licence and trademarks

The program is free software under the [GNU General Public License, version 3 or later](LICENSE):
you may use, change and share it, and anyone who passes on a changed version must pass on its source
under the same licence. (Releases up to v0.3.3 were published under the MIT licence.) The Lions name
and emblem, and other organisations' names and logos, are **not** covered by it and may not be used in forks or modified
copies: see [TRADEMARKS.md](TRADEMARKS.md).

"""v22ze-323: README opening rewritten so the repository can be found and understood (docs only; no program change, so the
build number stays 22ze-322).  The new opening says plainly what MIDI Studio is, in the words people search for (MIDI
sequencer, MIDI editor, MIDI studio, piano roll, sheet music), and links the Download section, the Releases page and the
User Guide at the very top.  Every claim in it matches the User Guide.  The repository's About description, website and topics
are set on GitHub itself (see the commands in the reply that came with this patch).
Run from the repo root:  python3 patch_v22ze323_readme_search.py
"""
import sys

OLD = "# midi-studio\nMIDI notation editor and synthesizer inspired by MidiSoft Studio for Windows\n"

NEW = """# MIDI Studio: a free MIDI sequencer and notation editor

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
"""


def main():
    raw = open("README.md", "rb").read().decode("utf-8")
    crlf = "\r\n" in raw
    t = raw.replace("\r\n", "\n")
    if "a free MIDI sequencer and notation editor" in t:
        print("Already applied. Nothing changed."); return
    if t.count(OLD) != 1:
        print("REFUSED: the first two lines of README.md are not as expected.  Nothing changed."); sys.exit(1)
    t = t.replace(OLD, NEW)
    open("README.md", "wb").write((t.replace("\n", "\r\n") if crlf else t).encode("utf-8"))
    print("Done.")


main()

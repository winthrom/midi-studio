"""Octave pairs get no finger numbers (v22ze-290).  Skipped where gui cannot be imported."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestOctaveNoNumbers(unittest.TestCase):
    def test_octave_pairs_have_no_numbers_but_neighbours_do(self):
        try:
            import gui
        except Exception:
            raise unittest.SkipTest("gui could not be imported here")
        song = gui.Song()
        rh = gui.Track(name="Piano right", channel=0)
        lh = gui.Track(name="Piano left", channel=0)
        song.tracks = [rh, lh]
        q = song.ticks_per_beat // 4
        octave = []
        single = []
        for i, p in enumerate((60, 62, 64, 65, 67)):
            for pp in (p, p + 12):
                n = gui.MidiNote(tick=i * q, pitch=pp, duration=q, velocity=80)
                rh.notes.append(n)
                octave.append(n)
        for i, p in enumerate((72, 71, 69, 67)):
            n = gui.MidiNote(tick=(5 + i) * q, pitch=p, duration=q, velocity=80)
            rh.notes.append(n)
            single.append(n)
        lh.notes.append(gui.MidiNote(tick=0, pitch=40, duration=song.ticks_per_beat, velocity=80))
        out = gui._fingering(song, 0, 1)
        self.assertTrue(all(id(n) not in out for n in octave))
        self.assertTrue(all(id(n) in out for n in single))

    def test_three_note_octave_chord_keeps_numbers(self):
        try:
            import gui
        except Exception:
            raise unittest.SkipTest("gui could not be imported here")
        song = gui.Song()
        rh = gui.Track(name="Piano right", channel=0)
        lh = gui.Track(name="Piano left", channel=0)
        song.tracks = [rh, lh]
        chord = [gui.MidiNote(tick=0, pitch=p, duration=song.ticks_per_beat, velocity=80) for p in (60, 67, 72)]
        rh.notes.extend(chord)
        lh.notes.append(gui.MidiNote(tick=0, pitch=40, duration=song.ticks_per_beat, velocity=80))
        out = gui._fingering(song, 0, 1)
        self.assertTrue(all(id(n) in out for n in chord))


if __name__ == "__main__":
    unittest.main()

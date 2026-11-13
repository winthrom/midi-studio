"""Tests for the instrument list and choice in Separate Hands.  Skipped where gui cannot be imported."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _gui():
    try:
        import gui
        return gui
    except Exception:
        raise unittest.SkipTest("gui could not be imported here")


def _song(g, parts):
    """parts: list of (name, program, channel, number_of_notes, lowest_pitch)."""
    s = g.Song()
    s.ticks_per_beat = 480
    s.tracks = []
    for name, prog, ch, count, low in parts:
        t = g.Track(name=name, channel=ch)
        t.program = prog
        t.notes = [g.MidiNote(tick=i * 240, pitch=low + (i * 5) % 14, duration=200, velocity=80) for i in range(count)]
        s.tracks.append(t)
    return s


class TestKeyboardChoices(unittest.TestCase):
    def test_piano_concerto_offers_only_the_piano(self):
        g = _gui()
        s = _song(g, [("Violin", 40, 0, 300, 67), ("Cello", 42, 1, 200, 40), ("Piano", 0, 2, 120, 50)])
        rows, suggested = s.keyboard_choices()
        self.assertEqual(suggested, 0)
        self.assertEqual([r["program"] for r in rows], [0])
        self.assertEqual(rows[0]["tracks"], [3])

    def test_violin_concerto_has_no_keyboard(self):
        g = _gui()
        s = _song(g, [("Violin", 40, 0, 300, 67), ("Strings", 48, 1, 200, 40)])
        rows, suggested = s.keyboard_choices()
        self.assertEqual(rows, [])
        self.assertIsNone(suggested)

    def test_organ_is_found_when_there_is_no_piano(self):
        g = _gui()
        s = _song(g, [("Strings", 48, 0, 300, 55), ("Organ", 19, 1, 100, 40)])
        rows, suggested = s.keyboard_choices()
        self.assertEqual([r["program"] for r in rows], [19])
        self.assertEqual(suggested, 19)

    def test_piano_is_suggested_before_an_organ(self):
        g = _gui()
        s = _song(g, [("Organ", 19, 0, 300, 40), ("Piano", 0, 1, 100, 48)])
        rows, suggested = s.keyboard_choices()
        self.assertEqual([r["program"] for r in rows], [19, 0])          # busiest first
        self.assertEqual(suggested, 0)                                    # but the piano is the likely one

    def test_drums_and_empty_tracks_are_left_out(self):
        g = _gui()
        s = _song(g, [("Drums", 0, 9, 200, 36), ("Empty", 0, 3, 0, 60), ("Piano", 0, 0, 50, 48)])
        rows, suggested = s.keyboard_choices()
        self.assertEqual([r["program"] for r in rows], [0])
        self.assertEqual(rows[0]["tracks"], [3])

    def test_the_chosen_keyboard_is_the_one_split(self):
        g = _gui()
        s = _song(g, [("Organ", 19, 0, 120, 55), ("Piano", 0, 1, 100, 40)])
        for kp, name, other in ((None, "Piano", "Organ"), (0, "Piano", "Organ"), (19, "Organ", "Piano")):
            params = {"quantize_strength": 0, "detect_tempo": False, "detect_timesig": False, "preserve_hands": False}
            if kp is not None:
                params["keyboard_program"] = kp
            out = s.rationalize_keep_audio(params=params)
            names = [t.name for t in out.tracks]
            self.assertIn(name + " (RH)", names)
            self.assertIn(name + " (LH)", names)
            self.assertIn(other, names)                                   # the other instrument is untouched


if __name__ == "__main__":
    unittest.main()

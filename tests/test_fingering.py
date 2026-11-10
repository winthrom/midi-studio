"""Tests for the fingering suggestions (gui._fingering and its search).  Skipped where gui cannot be imported."""
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


STEP = [2, 2, 1, 2, 2, 2, 1]


def _scale(tonic, n=8):
    p = [tonic]
    for i in range(n - 1):
        p.append(p[-1] + STEP[i % 7])
    return p


def _fing(gui, pitches, hand):
    res = gui._fp_search([[p] for p in pitches], hand)
    return [r[p] for r, p in zip(res, pitches)]


class TestFingeringSearch(unittest.TestCase):
    def test_textbook_scales_one_octave(self):
        gui = _gui()
        ru, rd = [1, 2, 3, 1, 2, 3, 4, 5], [5, 4, 3, 2, 1, 3, 2, 1]
        for name, pc in (("C", 0), ("G", 7), ("D", 2), ("A", 9), ("E", 4), ("F", 5)):
            with self.subTest(scale=name):
                self.assertEqual(_fing(gui, _scale(60 + pc), "R"), ru)
                self.assertEqual(_fing(gui, _scale(60 + pc)[::-1], "R"), rd)
                self.assertEqual(_fing(gui, _scale(48 + pc), "L"), rd)
                self.assertEqual(_fing(gui, _scale(48 + pc)[::-1], "L"), ru)

    def test_right_hand_two_octave_scale(self):
        gui = _gui()
        self.assertEqual(_fing(gui, _scale(60, 15), "R"), [1, 2, 3, 1, 2, 3, 4, 1, 2, 3, 1, 2, 3, 4, 5])

    def test_no_finger_reused_for_a_different_key_in_a_run(self):
        gui = _gui()
        for hand, base in (("R", 60), ("L", 48)):
            f = _fing(gui, _scale(base, 15), hand)
            for a, b in zip(f, f[1:]):
                self.assertNotEqual(a, b)

    def test_chords_use_distinct_rising_fingers(self):
        gui = _gui()
        res = gui._fp_search([[60, 64, 67], [62, 65, 67, 71], [48, 55]], "R")
        for r in res:
            ps = sorted(r)
            fs = [r[p] for p in ps]
            self.assertEqual(fs, sorted(set(fs)))
        # left hand: the thumb is on the highest note
        res = gui._fp_search([[48, 52, 55]], "L")
        self.assertEqual([res[0][p] for p in (48, 52, 55)], [5, 3, 1])

    def test_fast_descending_figure_has_no_thumb_under_four(self):
        """Chopin Op. 10 No. 12 left hand (descending figures): a thumb under finger 4 is hard at speed and not forced here."""
        gui = _gui()
        pitches = [68, 67, 65, 62, 63, 62, 59, 55, 56, 55, 53, 50, 51, 50, 47, 43]
        f = _fing(gui, pitches, "L")
        for a, b in zip(f, f[1:]):
            self.assertNotIn({a, b}, [{1, 4}])

    def test_empty_and_single(self):
        gui = _gui()
        self.assertEqual(gui._fp_search([], "R"), [])
        self.assertEqual(len(gui._fp_search([[60]], "L")), 1)

    def test_fingering_map_covers_notes_and_leaves_them_alone(self):
        gui = _gui()
        song = gui.Song()
        rh = gui.Track(name="Piano right", channel=0)
        lh = gui.Track(name="Piano left", channel=0)
        t = 0
        for p in _scale(60):
            rh.notes.append(gui.MidiNote(tick=t, pitch=p, duration=song.ticks_per_beat // 2, velocity=80))
            t += song.ticks_per_beat // 2
        lh.notes.append(gui.MidiNote(tick=0, pitch=48, duration=song.ticks_per_beat, velocity=80))
        song.tracks = [rh, lh]
        before = [(n.tick, n.pitch, n.duration, n.velocity) for tr in song.tracks for n in tr.notes]
        fm = gui._fingering(song, 0, 1)
        after = [(n.tick, n.pitch, n.duration, n.velocity) for tr in song.tracks for n in tr.notes]
        self.assertEqual(before, after)
        self.assertEqual(len(fm), len(before))
        self.assertTrue(all(1 <= v[0] <= 5 for v in fm.values()))
        first = rh.notes[0]
        self.assertTrue(fm[id(first)][1])   # the first note of a passage always matters


if __name__ == "__main__":
    unittest.main()

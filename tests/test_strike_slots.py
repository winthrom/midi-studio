"""Tests for _strike_slots (where each strike is placed in the Score and the printed score).  Skipped where gui cannot be imported."""
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


class _N:
    def __init__(self, tick, pitch, duration=60):
        self.tick, self.pitch, self.duration = tick, pitch, duration


class _T:
    def __init__(self, notes):
        self.channel = 0
        self.notes = notes


class _S:
    def __init__(self, notes):
        self.tracks = [_T(notes)]

    def get_measure_map(self):
        return [(0, 0, 1920), (1, 1920, 3840), (2, 3840, 5760)]


class TestStrikeSlots(unittest.TestCase):
    def test_two_quick_notes_get_two_slots(self):
        g = _gui()
        a, b, c = _N(960, 70), _N(1020, 72), _N(1080, 70, 120)
        song = _S([a, b, c])
        old = g._strike_slots(song, 120, 480)
        self.assertEqual(old[id(a)], old[id(b)])            # the old behaviour: one slot, drawn as a chord
        new = g._strike_slots(song, 120, 480, split_close=True)
        self.assertEqual([new[id(a)], new[id(b)], new[id(c)]], [960, 1020, 1080])

    def test_a_rolled_chord_stays_together(self):
        g = _gui()
        a, b = _N(960, 70, 480), _N(1020, 72, 420)          # the first note is still sounding
        new = g._strike_slots(_S([a, b]), 120, 480, split_close=True)
        self.assertEqual(new[id(a)], new[id(b)])

    def test_a_chord_stays_one_strike(self):
        g = _gui()
        a, b = _N(960, 60), _N(965, 64)
        new = g._strike_slots(_S([a, b]), 120, 480, split_close=True)
        self.assertEqual(new[id(a)], new[id(b)])

    def test_plain_sixteenths_are_unchanged(self):
        g = _gui()
        notes = [_N(i * 120, 60 + i, 120) for i in range(8)]
        song = _S(notes)
        self.assertEqual(g._strike_slots(song, 120, 480), g._strike_slots(song, 120, 480, split_close=True))


if __name__ == "__main__":
    unittest.main()

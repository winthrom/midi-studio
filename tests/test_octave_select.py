import unittest
from tests.test_octave_lines import _gui, _song


class TestOctaveSelection(unittest.TestCase):
    def test_slow_short_stretch_found_when_picked(self):
        gui = _gui()
        q = gui.Song().ticks_per_beat
        song = _song(gui, 3, q)
        self.assertEqual(gui._octave_runs(song, 0, 1), [])
        plan = gui._octave_runs(song, 0, 1, tick_range=(0, 3 * q))
        self.assertEqual(len(plan), 1)
        self.assertEqual(plan[0]["pairs"], 3)
        self.assertEqual(plan[0]["moves"], 3)

    def test_picked_stretch_ignores_busy_other_hand(self):
        gui = _gui()
        q = gui.Song().ticks_per_beat // 4
        song = _song(gui, 10, q, other=[(0, 80, 10 * q)])
        self.assertEqual(gui._octave_runs(song, 0, 1), [])
        self.assertEqual(len(gui._octave_runs(song, 0, 1, tick_range=(0, 10 * q))), 1)

    def test_range_outside_gives_nothing(self):
        gui = _gui()
        q = gui.Song().ticks_per_beat // 4
        song = _song(gui, 10, q)
        self.assertEqual(gui._octave_runs(song, 0, 1, tick_range=(100 * q, 101 * q)), [])


if __name__ == "__main__":
    unittest.main()

import unittest
from tests.test_octave_lines import _gui, _song


class TestOctaveEnd(unittest.TestCase):
    def test_bass_note_right_after_the_run_does_not_block(self):
        gui = _gui()
        q = gui.Song().ticks_per_beat // 4
        song = _song(gui, 10, q, other=[(10 * q + 5, 40, q)])
        self.assertEqual(len(gui._octave_runs(song, 0, 1)), 1)

    def test_note_sounding_through_the_run_still_blocks(self):
        gui = _gui()
        q = gui.Song().ticks_per_beat // 4
        song = _song(gui, 10, q, other=[(3 * q, 80, 2 * q)])
        self.assertEqual(gui._octave_runs(song, 0, 1), [])


if __name__ == "__main__":
    unittest.main()

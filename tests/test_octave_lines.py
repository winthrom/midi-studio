"""Octave Lines (v22ze-291): finding fast octave runs that two hands would share.  Skipped where gui cannot be imported."""
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


def _song(gui, strikes, step, other=None, split=False):
    song = gui.Song()
    rh = gui.Track(name="Piano right", channel=0)
    lh = gui.Track(name="Piano left", channel=0)
    song.tracks = [rh, lh]
    for i in range(strikes):
        p = 40 + (i % 5)
        lo = gui.MidiNote(tick=i * step, pitch=p, duration=step, velocity=80)
        hi = gui.MidiNote(tick=i * step, pitch=p + 12, duration=step, velocity=80)
        lh.notes.append(lo)
        (rh if split else lh).notes.append(hi)
    for t, p, d in (other or []):
        rh.notes.append(gui.MidiNote(tick=t, pitch=p, duration=d, velocity=80))
    return song


class TestOctaveRuns(unittest.TestCase):
    def test_fast_run_in_one_hand_is_found(self):
        gui = _gui()
        song = _song(gui, 10, song_q := gui.Song().ticks_per_beat // 4)
        plan = gui._octave_runs(song, 0, 1)
        self.assertEqual(len(plan), 1)
        self.assertEqual(plan[0]["pairs"], 10)
        self.assertEqual(plan[0]["moves"], 10)
        self.assertEqual(plan[0]["now"], "L.H.")

    def test_notes_a_few_ticks_apart_upper_first(self):
        gui = _gui()
        q = gui.Song().ticks_per_beat // 4
        song = _song(gui, 10, q)
        for i, n in enumerate(song.tracks[1].notes):
            if i % 2 == 0:   # the lower note of each pair starts a little after the upper one
                n.tick += 3
        plan = gui._octave_runs(song, 0, 1)
        self.assertEqual(len(plan), 1)
        self.assertEqual(plan[0]["pairs"], 10)

    def test_slow_octaves_are_not_a_run(self):
        gui = _gui()
        song = _song(gui, 10, gui.Song().ticks_per_beat)
        self.assertEqual(gui._octave_runs(song, 0, 1), [])

    def test_short_run_is_not_a_run(self):
        gui = _gui()
        song = _song(gui, 3, gui.Song().ticks_per_beat // 4)
        self.assertEqual(gui._octave_runs(song, 0, 1), [])

    def test_other_hand_busy_means_no_offer(self):
        gui = _gui()
        q = gui.Song().ticks_per_beat // 4
        song = _song(gui, 7, q, other=[(3 * q, 84, q)])   # v22ze-299: three free pairs on each side of the busy note: no run of four
        self.assertEqual(gui._octave_runs(song, 0, 1), [])

    def test_already_split_needs_no_move(self):
        gui = _gui()
        song = _song(gui, 10, gui.Song().ticks_per_beat // 4, split=True)
        self.assertEqual(gui._octave_runs(song, 0, 1), [])

    def test_apply_moves_only_the_staff(self):
        gui = _gui()
        q = gui.Song().ticks_per_beat // 4
        song = _song(gui, 10, q)
        before = sorted((n.tick, n.pitch, n.duration) for tr in song.tracks for n in tr.notes)
        plan = gui._octave_runs(song, 0, 1)
        moved = gui._easy_apply(song, plan, lambda e: True)
        after = sorted((n.tick, n.pitch, n.duration) for tr in song.tracks for n in tr.notes)
        self.assertEqual(moved, 10)
        self.assertEqual(before, after)
        self.assertEqual(len(song.tracks[0].notes), 10)
        self.assertTrue(all(n.pitch >= 52 for n in song.tracks[0].notes))
        self.assertTrue(all(n.pitch < 52 for n in song.tracks[1].notes))
        self.assertEqual(gui._octave_runs(song, 0, 1), [])


if __name__ == "__main__":
    unittest.main()

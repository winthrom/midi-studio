import unittest


def _gui():
    try:
        import gui
        return gui
    except Exception:
        raise unittest.SkipTest("gui could not be imported here")


class TestCloseNotes(unittest.TestCase):
    def _song(self, gui, notes):
        song = gui.Song()
        song.ticks_per_beat = 480
        tr = gui.Track(name="P", channel=0)
        song.tracks = [tr]
        for tick, pitch, dur in notes:
            tr.notes.append(gui.MidiNote(tick=tick, pitch=pitch, duration=dur, velocity=80))
        return song, tr

    def test_two_quick_notes_are_not_one_chord(self):
        gui = _gui()
        song, tr = self._song(gui, [(1632, 50, 122), (1710, 51, 80), (1810, 50, 94)])
        sl = gui._strike_slots(song, 120, 480, split_close=True)
        slots = [sl[id(n)] for n in tr.notes]
        self.assertEqual(len(set(slots)), 3, slots)
        self.assertEqual(slots, sorted(slots))

    def test_a_rolled_chord_stays_one_chord(self):
        gui = _gui()
        song, tr = self._song(gui, [(960, 60, 400), (968, 64, 400), (975, 67, 400)])
        sl = gui._strike_slots(song, 120, 480, split_close=True)
        self.assertEqual(len({sl[id(n)] for n in tr.notes}), 1)


if __name__ == "__main__":
    unittest.main()

import unittest


def _gui():
    try:
        import gui
        return gui
    except Exception:
        raise unittest.SkipTest("gui could not be imported here")


class TestOneTrackMessage(unittest.TestCase):
    def test_one_piano_track_gets_the_one_track_message(self):
        gui = _gui()
        song = gui.Song()
        t = gui.Track(name="Piano", channel=0)
        t.notes.append(gui.MidiNote(tick=0, pitch=60, duration=96, velocity=80))
        song.tracks = [t]
        self.assertTrue(gui._is_one_keyboard_track(song))
        self.assertIn("one track", gui._need_hands_text(song))
        self.assertIn("Separate Hands", gui._need_hands_text(song))

    def test_two_hand_tracks_are_not_flagged(self):
        gui = _gui()
        song = gui.Song()
        a = gui.Track(name="Piano (RH)", channel=0)
        b = gui.Track(name="Piano (LH)", channel=0)
        for t in (a, b):
            t.notes.append(gui.MidiNote(tick=0, pitch=60, duration=96, velocity=80))
        song.tracks = [a, b]
        self.assertFalse(gui._is_one_keyboard_track(song))

    def test_violin_keeps_the_old_wording(self):
        gui = _gui()
        song = gui.Song()
        t = gui.Track(name="Violin", channel=0)
        t.program = 40
        t.notes.append(gui.MidiNote(tick=0, pitch=70, duration=96, velocity=80))
        song.tracks = [t]
        self.assertFalse(gui._is_one_keyboard_track(song))
        self.assertIn("right-hand part", gui._need_hands_text(song))


if __name__ == "__main__":
    unittest.main()

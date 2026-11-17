import unittest


def _gui():
    try:
        import gui
        return gui
    except Exception:
        raise unittest.SkipTest("gui could not be imported here")


def _song(gui, step, tpb=480):
    song = gui.Song()
    song.ticks_per_beat = tpb
    tr = gui.Track(name="P", channel=0)
    song.tracks = [tr]
    for i in range(16):
        tr.notes.append(gui.MidiNote(tick=i * step + (7 if i % 2 else -5 if i else 0), pitch=60 + i % 5,
                                     duration=step + 9, velocity=80))
    return song


class TestQuantizeGrid(unittest.TestCase):
    def test_grids_mean_note_values(self):
        gui = _gui()
        for div, ticks in ((4, 480), (8, 240), (16, 120), (32, 60)):
            song = _song(gui, ticks)
            gui.quantize_notes_per_measure(song.tracks[0], song, div=div, strength=1.0)
            for n in song.tracks[0].notes:
                self.assertEqual(n.tick % ticks, 0, (div, n.tick))
                self.assertEqual(n.duration % ticks, 0, (div, n.duration))


if __name__ == "__main__":
    unittest.main()

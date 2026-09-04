"""Integration tests for MIDI I/O module."""

import unittest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Note: These tests mock MIDI I/O since we can't rely on hardware in CI


class TestMidiIOModule(unittest.TestCase):
    """Test MIDI I/O module without hardware."""

    def test_midi_io_imports(self):
        """Test midi_io module can be imported."""
        try:
            import midi_io
            self.assertIsNotNone(midi_io)
        except ImportError as e:
            self.skipTest(f"MIDI module not available: {e}")

    def test_midi_constants(self):
        """Test MIDI constants are defined."""
        try:
            from midi_io import MIDI_OUT_OK, MIDI_IN_OK
            self.assertIsInstance(MIDI_OUT_OK, bool)
            self.assertIsInstance(MIDI_IN_OK, bool)
        except ImportError:
            self.skipTest("MIDI module not available")


class TestSynthIntegration(unittest.TestCase):
    """Integration tests for synth engine."""

    def test_track_creation(self):
        """Test creating a track."""
        from synth import Track
        track = Track(name="Test Track", channel=0)
        self.assertEqual(track.name, "Test Track")
        self.assertEqual(track.channel, 0)

    def test_song_creation(self):
        """Test creating a song."""
        from synth import Song
        song = Song()
        self.assertIsNotNone(song)

    def test_add_track_to_song(self):
        """Test adding tracks to a song."""
        from synth import Song, Track
        song = Song()
        track = Track(name="Piano", channel=0)
        song.tracks.append(track)
        self.assertGreater(len(song.tracks), 0)


if __name__ == "__main__":
    unittest.main()

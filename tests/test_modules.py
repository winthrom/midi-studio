"""Unit tests for platform module."""

import unittest
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from platform import (
    APP_VERSION,
    APP_FULL_NAME,
    load_settings,
    save_settings,
    detect_linux_distro,
    find_soundfont,
)


class TestPlatformModule(unittest.TestCase):
    """Test platform utilities."""

    def test_app_version(self):
        """Test app version is set."""
        self.assertIsNotNone(APP_VERSION)
        self.assertEqual(APP_VERSION, "22ze-73")

    def test_app_full_name(self):
        """Test app full name."""
        self.assertIn("MIDI", APP_FULL_NAME)
        self.assertIn("Studio", APP_FULL_NAME)

    def test_settings_roundtrip(self):
        """Test save and load settings."""
        test_data = {"test_key": "test_value", "number": 42}
        save_settings(test_data)
        loaded = load_settings()
        self.assertEqual(loaded.get("test_key"), "test_value")
        self.assertEqual(loaded.get("number"), 42)

    def test_detect_linux_distro(self):
        """Test distro detection returns valid type."""
        result = detect_linux_distro()
        # Result should be None on non-Linux, or a valid distro name
        if result is not None:
            self.assertIn(result, ["arch", "debian", "fedora", "suse"])

    def test_find_soundfont(self):
        """Test soundfont search returns string or None."""
        result = find_soundfont()
        self.assertTrue(result is None or isinstance(result, str))


class TestTheoryModule(unittest.TestCase):
    """Test theory constants."""

    def test_theory_imports(self):
        """Test theory module imports."""
        from theory import GM_INSTRUMENTS, NOTE_NAMES, key_sig_to_ly
        self.assertEqual(len(GM_INSTRUMENTS), 128)
        self.assertEqual(len(NOTE_NAMES), 12)
        self.assertIsNotNone(key_sig_to_ly)

    def test_key_sig_conversion(self):
        """Test key signature to LilyPond conversion."""
        from theory import key_sig_to_ly
        self.assertEqual(key_sig_to_ly("C"), ("c", "major"))
        self.assertEqual(key_sig_to_ly("Am"), ("a", "minor"))
        self.assertEqual(key_sig_to_ly("F#"), ("fis", "major"))

    def test_key_accidentals(self):
        """Test key accidental counting."""
        from theory import key_sig_accidentals
        sharps, flats = key_sig_accidentals("G")  # G major = 1 sharp
        self.assertEqual((sharps, flats), (1, 0))
        sharps, flats = key_sig_accidentals("F")  # F major = 1 flat
        self.assertEqual((sharps, flats), (0, 1))


class TestSynthModule(unittest.TestCase):
    """Test synthesis engine."""

    def test_synth_imports(self):
        """Test synth module imports."""
        from synth import MidiNote, Track, Song
        self.assertIsNotNone(MidiNote)
        self.assertIsNotNone(Track)
        self.assertIsNotNone(Song)

    def test_midi_note_creation(self):
        """Test MidiNote instantiation."""
        from synth import MidiNote
        note = MidiNote(tick=0, pitch=60, duration=480, velocity=100)
        self.assertEqual(note.pitch, 60)
        self.assertEqual(note.duration, 480)


class TestExportModule(unittest.TestCase):
    """Test export utilities."""

    def test_export_imports(self):
        """Test export module imports."""
        try:
            import export
            self.assertIsNotNone(export)
        except ImportError:
            self.skipTest("Export module not fully initialized")


if __name__ == "__main__":
    unittest.main()

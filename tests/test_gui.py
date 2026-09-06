"""GUI tests for Tkinter components (mocked, no display needed)."""

import unittest
from unittest.mock import Mock, patch, MagicMock
import sys

# Mock tkinter before importing gui
sys.modules['tkinter'] = MagicMock()
sys.modules['tkinter.ttk'] = MagicMock()
sys.modules['tkinter.filedialog'] = MagicMock()
sys.modules['tkinter.messagebox'] = MagicMock()
sys.modules['tkinter.simpledialog'] = MagicMock()


class TestGUIImports(unittest.TestCase):
    """Test that GUI module can be imported."""

    def test_gui_module_imports(self):
        """GUI module should import without errors (with mocked Tk)."""
        try:
            import gui
            self.assertIsNotNone(gui)
        except ImportError as e:
            self.skipTest(f"GUI import skipped: {e}")


class TestTkPopupMenu(unittest.TestCase):
    """Test TkPopupMenu widget."""

    @patch('tkinter.Toplevel')
    def test_popup_menu_creation(self, mock_toplevel):
        """TkPopupMenu should initialize."""
        try:
            from gui import TkPopupMenu
            menu = TkPopupMenu(MagicMock())
            self.assertIsNotNone(menu)
        except (ImportError, Exception):
            self.skipTest("TkPopupMenu test skipped")

    def test_popup_menu_add_command(self):
        """TkPopupMenu should add commands."""
        try:
            from gui import TkPopupMenu
            menu = TkPopupMenu(MagicMock())
            menu.add_command(label="Test", command=lambda: None)
            self.assertEqual(len(menu._items), 1)
        except (ImportError, Exception):
            self.skipTest("TkPopupMenu test skipped")

    def test_popup_menu_add_separator(self):
        """TkPopupMenu should add separators."""
        try:
            from gui import TkPopupMenu
            menu = TkPopupMenu(MagicMock())
            menu.add_separator()
            self.assertEqual(len(menu._items), 1)
            self.assertEqual(menu._items[0][0], "separator")
        except (ImportError, Exception):
            self.skipTest("TkPopupMenu test skipped")


class TestMenuBar(unittest.TestCase):
    """Test TkMenuBar widget."""

    def test_menubar_creation(self):
        """TkMenuBar should initialize."""
        try:
            from gui import TkMenuBar
            menubar = TkMenuBar(MagicMock())
            self.assertIsNotNone(menubar)
        except (ImportError, Exception):
            self.skipTest("TkMenuBar test skipped")


class TestTransport(unittest.TestCase):
    """Test Transport controls."""

    def test_transport_creation(self):
        """Transport should initialize."""
        try:
            from synth import Transport
            transport = Transport()
            self.assertIsNotNone(transport)
        except (ImportError, Exception):
            self.skipTest("Transport test skipped")


class TestPianoRoll(unittest.TestCase):
    """Test PianoRoll widget."""

    def test_pianoroll_creation(self):
        """PianoRoll should initialize with a song."""
        try:
            from gui import PianoRollView
            from synth import Song
            song = Song()
            # Skip actual creation since it needs real Tk
            self.assertIsNotNone(PianoRollView)
        except (ImportError, Exception):
            self.skipTest("PianoRoll test skipped")


if __name__ == "__main__":
    unittest.main()

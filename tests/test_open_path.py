# Open path checks (v22ze-321): what may be opened, and the size limit.  The checks live in sys_platform.py and need no
# window; the last test checks the wiring in gui.py in a separate Python process (tests/test_gui.py replaces tkinter with a
# mock for the whole run) and is skipped when there is no display.
import os, stat, subprocess, sys, tempfile, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import sys_platform as sp

MB = 1024 * 1024


class OpenPath(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def mk(self, name, size=10):
        p = os.path.join(self.d, name)
        with open(p, "wb") as f:
            f.write(b"x" * size)
        return p

    def test_ordinary_file_is_fine(self):
        self.assertIsNone(sp.check_midi_path(self.mk("song.mid"), limit=MB))

    def test_nothing_chosen_missing_folder_empty(self):
        for bad in (None, "", 5, b"x"):
            self.assertIsNotNone(sp.check_midi_path(bad), repr(bad))
        self.assertIn("not be found", sp.check_midi_path(os.path.join(self.d, "nope.mid")))
        self.assertIn("not an ordinary file", sp.check_midi_path(self.d))
        self.assertIn("empty", sp.check_midi_path(self.mk("zero.mid", 0)))

    @unittest.skipIf(sys.platform.startswith("win"), "POSIX only")
    def test_pipe_and_device_are_refused_without_being_opened(self):
        fifo = os.path.join(self.d, "pipe.mid")
        os.mkfifo(fifo)
        self.assertIn("not an ordinary file", sp.check_midi_path(fifo))        # would block forever if it were opened
        self.assertIn("not an ordinary file", sp.check_midi_path("/dev/zero"))

    @unittest.skipIf(sys.platform.startswith("win"), "POSIX file names")
    def test_control_characters_and_long_names(self):
        p = self.mk("two\nlines.mid")
        self.assertIn("not allowed", sp.check_midi_path(p, limit=MB))
        self.assertIn("not allowed", sp.check_midi_path(os.path.join(self.d, "a\x00b.mid")))
        self.assertIn("too long", sp.check_midi_path(os.path.join(self.d, "a" * 256 + ".mid")))
        self.assertIn("too long", sp.check_midi_path("/" + "d/" * 3000 + "x.mid"))
        self.assertIsNone(sp.check_midi_path(self.mk("a" * 200 + ".mid"), limit=MB))   # long but allowed

    def test_names_that_look_like_options_or_have_odd_letters_are_fine_to_open(self):
        for name in ("-rf.mid", "--help.mid", "café étude.mid", "ピアノ.mid", "a b  c.mid"):
            self.assertIsNone(sp.check_midi_path(self.mk(name), limit=MB), name)

    def test_size_just_under_and_just_over_the_limit(self):
        self.assertIsNone(sp.check_midi_path(self.mk("under.mid", 100), limit=100))
        msg = sp.check_midi_path(self.mk("over.mid", 101), limit=100)
        self.assertIn("MB", msg)

    def test_limit_depends_on_free_memory_but_never_above_the_cap(self):
        self.assertEqual(sp.midi_size_limit(avail=10 ** 13), sp.MAX_MIDI_BYTES)          # plenty of memory: the fixed cap
        self.assertEqual(sp.midi_size_limit(avail=60 * 5 * MB), 5 * MB)                 # little memory: free / 60
        self.assertEqual(sp.midi_size_limit(avail=1000), MB)                            # never below 1 MB
        for unknown in (None, 0, -5, "x"):                                              # an unusable reading: the fixed cap
            self.assertEqual(sp.midi_size_limit(avail=unknown), sp.MAX_MIDI_BYTES, repr(unknown))
        got = sp.available_memory_bytes()
        self.assertTrue(got is None or got > 0)
        self.assertLessEqual(sp.midi_size_limit(), sp.MAX_MIDI_BYTES)
        self.assertGreaterEqual(sp.midi_size_limit(), MB)


SCRIPT = """
import sys, os, tempfile
sys.path.insert(0, ROOT)
try:
    import tkinter as tk
    root = tk.Tk()
except Exception:
    sys.exit(77)
import gui
from unittest import mock
root.geometry("200x100+0+0")
d = tempfile.mkdtemp()
big = os.path.join(d, "big.mid")
with open(big, "wb") as f:
    f.truncate(60 * 1024 * 1024)                    # a sparse 60 MB file: over the 50 MB cap on any machine

class Fake: pass
fake = Fake(); fake.root = root; fake._loading = False
fake._confirm_discard = lambda: True
closed = []
fake._close_current = lambda: closed.append(1)
fake._load_file = lambda p: gui.MidisoftStudio._load_file(fake, p)
errors = []
with mock.patch.object(gui.messagebox, "showerror", side_effect=lambda *a, **k: errors.append(a)), \\
     mock.patch.object(gui.filedialog, "askopenfilename", return_value=big), \\
     mock.patch.object(gui.Song, "from_mid", side_effect=AssertionError("the file must not be read")):
    gui.MidisoftStudio._open(fake)                  # the Open command
    gui.MidisoftStudio._load_file(fake, big)        # a file named on the command line
if closed:
    print("the open piece was closed although the new file was refused"); sys.exit(1)
if len(errors) != 2 or "MB" not in str(errors[0]):
    print("expected two refusals mentioning MB, got", errors); sys.exit(1)
sys.exit(0)
"""


class Wiring(unittest.TestCase):
    def test_refused_file_is_not_read_and_does_not_close_the_open_piece(self):
        if sys.platform.startswith("linux") and not os.environ.get("DISPLAY"):
            self.skipTest("no display")
        r = subprocess.run([sys.executable, "-c", "ROOT = %r\n" % ROOT + SCRIPT], capture_output=True, text=True, timeout=180)
        if r.returncode == 77:
            self.skipTest("no tkinter or no display")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr[-800:])


if __name__ == "__main__":
    unittest.main()

"""v22ze-321: Open path hardening, with a size limit that depends on free memory (0.4.2 security work).
  * sys_platform.check_midi_path(path): refuses, with one plain sentence and BEFORE anything is read or closed: nothing
    chosen, a file that cannot be found or read, a folder / device / pipe (not an ordinary file; a pipe would block
    forever), an empty file, a name with line breaks or other control characters, a name over 255 characters or a path over
    4096, and a file over the size limit.
  * The size limit is the smaller of 50 MB and (free memory / 60), never below 1 MB.  Measured: a loaded piece takes about
    20 times its file size in memory (165 bytes a note); 60 leaves room for the untouched copy kept for Compare with
    Original, undo copies, the score and the roll.  Free memory: Linux /proc/meminfo MemAvailable; Windows
    GlobalMemoryStatusEx (ctypes); macOS a quarter of installed RAM; any failure = the fixed 50 MB.  (Windows and macOS
    readings are untested.)
  * The Open command checks first, so a refused file no longer closes the piece that is open; a file named on the command
    line is checked in _load_file.
Run from the repo root:  python3 patch_v22ze321_open_path.py
"""
import sys, os

TEST = r'''# Open path checks (v22ze-321): what may be opened, and the size limit.  The checks live in sys_platform.py and need no
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
'''

FUNCS = r'''MAX_MIDI_BYTES = 50 * 1024 * 1024     # v22ze-321: the largest MIDI file ever opened (real ones are usually under 1 MB)
MIN_MIDI_LIMIT = 1024 * 1024           # a low memory reading never makes the limit smaller than this
MIDI_MEMORY_FACTOR = 60                # memory needed per byte of file (measured about 20 for the piece itself)
MAX_PATH_CHARS = 4096
MAX_NAME_CHARS = 255


def available_memory_bytes():
    """Free memory for a new piece, in bytes, or None when it cannot be read (then the fixed cap is used)."""
    try:
        if sys.platform.startswith("linux"):
            with open("/proc/meminfo") as f:
                for line in f:
                    if line.startswith("MemAvailable:"):
                        return int(line.split()[1]) * 1024
            return None
        if sys.platform.startswith("win"):
            import ctypes

            class _MemStatus(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
            ms = _MemStatus()
            ms.dwLength = ctypes.sizeof(ms)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(ms)):
                return int(ms.ullAvailPhys)
            return None
        if sys.platform == "darwin":
            return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") // 4    # a cautious stand-in for "free"
    except Exception:
        pass
    return None


def midi_size_limit(avail="auto"):
    """The largest MIDI file to open: the smaller of the fixed cap and free memory / 60, never below 1 MB."""
    if avail == "auto":
        avail = available_memory_bytes()
    limit = MAX_MIDI_BYTES
    if isinstance(avail, int) and not isinstance(avail, bool) and avail > 0:
        limit = min(limit, max(MIN_MIDI_LIMIT, avail // MIDI_MEMORY_FACTOR))
    return limit


def check_midi_path(path, limit=None):
    """None when the file may be opened; otherwise one plain sentence saying why not.  Nothing is read."""
    import stat as _stat
    if not isinstance(path, str) or not path:
        return "No file was chosen."
    if len(path) > MAX_PATH_CHARS or len(os.path.basename(path)) > MAX_NAME_CHARS:
        return "The file name or folder path is too long."
    if any(ord(c) < 32 or ord(c) == 127 for c in path):
        return "The file name contains characters that are not allowed (such as a line break)."
    try:
        st = os.stat(path)
    except OSError:
        return "That file could not be found or cannot be read."
    if not _stat.S_ISREG(st.st_mode):
        return "That is not an ordinary file (it may be a folder or a device)."
    if not os.access(path, os.R_OK):
        return "That file could not be found or cannot be read."
    if st.st_size == 0:
        return "That file is empty."
    if limit is None:
        limit = midi_size_limit()
    if st.st_size > limit:
        return ("That file is %.1f MB. The largest this computer can open safely right now is %.1f MB. "
                "A real MIDI file is usually under 1 MB, so this may not be a MIDI file."
                % (st.st_size / 1048576.0, limit / 1048576.0))
    return None


def fetch_latest_release(url=None, timeout=6):
'''


def rd(p):
    raw = open(p, "rb").read().decode("utf-8")
    return "\r\n" in raw, raw.replace("\r\n", "\n")


def wr(p, t, crlf):
    open(p, "wb").write((t.replace("\n", "\r\n") if crlf else t).encode("utf-8"))


def refuse(msg):
    print("REFUSED: " + msg + "  Nothing changed."); sys.exit(1)


def edit(path, pairs):
    crlf, t = rd(path)
    t0 = t
    for old, new, marker in pairs:
        if marker in t:
            continue
        if t.count(old) != 1:
            refuse("anchor not found exactly once in %s: %r" % (path, old[:70]))
        t = t.replace(old, new)
    if t != t0:
        wr(path, t, crlf)
        return True
    return False


def main():
    ch = edit("sys_platform.py", [
        ("def fetch_latest_release(url=None, timeout=6):\n", FUNCS, "def check_midi_path("),
        ('APP_VERSION = "22ze-320"', 'APP_VERSION = "22ze-321"', 'APP_VERSION = "22ze-321"'),
    ])
    ch |= edit("gui.py", [
        ("    fetch_latest_release,\n    safe_release_url,\n", "    check_midi_path,\n    fetch_latest_release,\n    safe_release_url,\n", "    check_midi_path,\n    fetch_latest_release,"),
        ("            self._close_current(); self._load_file(path)\n\n    def _load_file(self,path):",
         "            _why = check_midi_path(path)   # v22ze-321: checked BEFORE the open piece is closed\n"
         "            if _why:\n                messagebox.showerror(\"Open MIDI\", _why, parent=self.root); return\n"
         "            self._close_current(); self._load_file(path)\n\n    def _load_file(self,path):",
         "_why = check_midi_path(path)   # v22ze-321: checked BEFORE"),
        ("    def _load_file(self,path):   # v22ze-253: busy cursor; clicks on the score are ignored while loading\n        self._loading = True\n",
         "    def _load_file(self,path):   # v22ze-253: busy cursor; clicks on the score are ignored while loading\n"
         "        _why = check_midi_path(path)   # v22ze-321: also covers a file named on the command line\n"
         "        if _why:\n            messagebox.showerror(\"Open MIDI\", _why, parent=self.root)\n            return None\n"
         "        self._loading = True\n",
         "also covers a file named on the command line"),
    ])
    p = os.path.join("tests", "test_open_path.py")
    if not os.path.exists(p) or open(p, encoding="utf-8").read() != TEST:
        open(p, "w", encoding="utf-8", newline="\n").write(TEST); ch = True
    import py_compile
    for f in ("gui.py", "sys_platform.py"):
        py_compile.compile(f, doraise=True)
    print("Done." if ch else "Already applied. Nothing changed.")


main()

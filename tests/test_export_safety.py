# Export and external-program safety (v22ze-322): safe saving, temporary files, and LilyPond text injection.
# Starts no window.  Anything that needs gui.py runs in a separate Python process (tests/test_gui.py replaces tkinter with a
# mock for the whole run).  The LilyPond part is skipped when LilyPond is not installed.
import os, stat, subprocess, sys, tempfile, time, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import sys_platform as sp

POSIX = not sys.platform.startswith("win")


def put(path, data):
    with open(path, "wb" if isinstance(data, bytes) else "w") as f:
        f.write(data)


def get(path):
    with open(path, "rb") as f:
        return f.read()


class CheckSavePath(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.d = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def test_good_and_bad_names(self):
        self.assertIsNone(sp.check_save_path(os.path.join(self.d, "new song.mid")))
        self.assertIsNone(sp.check_save_path(os.path.join(self.d, "-rf.mid")))
        for bad in (None, "", 5):
            self.assertIsNotNone(sp.check_save_path(bad), repr(bad))
        self.assertIn("not allowed", sp.check_save_path(os.path.join(self.d, "a\nb.mid")))
        self.assertIn("too long", sp.check_save_path(os.path.join(self.d, "a" * 256)))
        self.assertIn("does not exist", sp.check_save_path(os.path.join(self.d, "nofolder", "x.mid")))

    def test_existing_targets(self):
        self.assertIn("folder or device", sp.check_save_path(self.d))
        if POSIX:
            fifo = os.path.join(self.d, "p.mid"); os.mkfifo(fifo)
            self.assertIn("folder or device", sp.check_save_path(fifo))
            dangling = os.path.join(self.d, "dangling.mid"); os.symlink(os.path.join(self.d, "gone"), dangling)
            self.assertIsNotNone(sp.check_save_path(dangling))

    @unittest.skipUnless(POSIX and hasattr(os, "geteuid") and os.geteuid() != 0, "needs a normal (non-root) user")
    def test_read_only_file_and_folder(self):
        f = os.path.join(self.d, "ro.mid"); put(f, "x"); os.chmod(f, 0o444)
        self.assertIn("read-only", sp.check_save_path(f))
        sub = os.path.join(self.d, "ro"); os.mkdir(sub); os.chmod(sub, 0o555)
        self.assertIn("permission", sp.check_save_path(os.path.join(sub, "x.mid")))
        os.chmod(sub, 0o755)


class AtomicWrite(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.d = self.tmp.name
        self.p = os.path.join(self.d, "song.mid")

    def tearDown(self):
        self.tmp.cleanup()

    def left_over(self):
        return [n for n in os.listdir(self.d) if n.endswith(".part")]

    def test_new_file_and_replace(self):
        sp.atomic_write(self.p, lambda t: put(t, b"one"))
        self.assertEqual(get(self.p), b"one")
        sp.atomic_write(self.p, lambda t: put(t, b"two"))
        self.assertEqual(get(self.p), b"two")
        self.assertEqual(self.left_over(), [])

    def test_failure_keeps_the_old_file_and_removes_the_temporary_one(self):
        put(self.p, b"GOOD")
        def bad(t):
            put(t, b"HALF"); raise RuntimeError("disk full")
        with self.assertRaises(RuntimeError):
            sp.atomic_write(self.p, bad)
        self.assertEqual(get(self.p), b"GOOD")
        self.assertEqual(self.left_over(), [])

    def test_empty_result_is_refused(self):
        put(self.p, b"GOOD")
        with self.assertRaises(OSError):
            sp.atomic_write(self.p, lambda t: None)
        self.assertEqual(get(self.p), b"GOOD")
        self.assertEqual(self.left_over(), [])

    @unittest.skipUnless(POSIX, "POSIX modes and links")
    def test_modes_and_links(self):
        sp.atomic_write(self.p, lambda t: put(t, b"x"))
        self.assertEqual(stat.S_IMODE(os.stat(self.p).st_mode), 0o644)
        os.chmod(self.p, 0o600)
        sp.atomic_write(self.p, lambda t: put(t, b"y"))
        self.assertEqual(stat.S_IMODE(os.stat(self.p).st_mode), 0o600)         # an existing file keeps its permissions
        link = os.path.join(self.d, "link.mid"); os.symlink(self.p, link)
        sp.atomic_write(link, lambda t: put(t, b"z"))
        self.assertTrue(os.path.islink(link))                                  # the link survives
        self.assertEqual(get(self.p), b"z")


class OldTempFiles(unittest.TestCase):
    def test_only_our_old_files_go(self):
        with tempfile.TemporaryDirectory() as d:
            def mk(name, age_days):
                p = os.path.join(d, name); put(p, "x")
                t = time.time() - age_days * 86400; os.utime(p, (t, t)); return p
            old = mk("midistudio_score_old.pdf", 3)
            new = mk("midistudio_score_new.pdf", 0)
            other = mk("somebody_elses_old.pdf", 3)
            wrong_end = mk("midistudio_score_old.txt", 3)
            os.mkdir(os.path.join(d, "midistudio_score_dir.pdf"))
            keep_link = None
            if POSIX:
                keep_link = os.path.join(d, "midistudio_score_link.pdf"); os.symlink(other, keep_link)
            n = sp.remove_old_temp_files("midistudio_score_", ".pdf", directory=d)
            self.assertEqual(n, 1)
            self.assertFalse(os.path.exists(old))
            for p in (new, other, wrong_end):
                self.assertTrue(os.path.exists(p), p)
            self.assertTrue(os.path.isdir(os.path.join(d, "midistudio_score_dir.pdf")))
            if keep_link:
                self.assertTrue(os.path.islink(keep_link))
            self.assertEqual(sp.remove_old_temp_files("x", "y", directory=os.path.join(d, "nofolder")), 0)


SCRIPT = """
import sys, os, shutil, subprocess, tempfile
sys.path.insert(0, ROOT)
import mido, gui
from unittest import mock

import atexit
d = tempfile.mkdtemp()
atexit.register(shutil.rmtree, d, True)       # the folder is removed when this check ends
sentinel = os.path.join(d, "PWNED")
q = 'x" #(system "touch ' + sentinel + '") "y'
m = mido.MidiFile(ticks_per_beat=480)
t0 = mido.MidiTrack(); m.tracks.append(t0)
t0.append(mido.MetaMessage("track_name", name=q, time=0))
t0.append(mido.MetaMessage("text", text="Composer: " + q, time=0))
t0.append(mido.MetaMessage("set_tempo", tempo=500000, time=0))
t1 = mido.MidiTrack(); m.tracks.append(t1)
t1.append(mido.MetaMessage("track_name", name=q + chr(10) + '#(system "touch ' + sentinel + '")', time=0))
for i in range(4):
    t1.append(mido.Message("note_on", note=60 + i, velocity=80, time=0 if i == 0 else 480))
    t1.append(mido.Message("note_off", note=60 + i, velocity=0, time=470))
src = os.path.join(d, "evil.mid"); m.save(src)
song = gui.Song.from_mid(src)
ly = os.path.join(d, "evil.ly"); song.to_ly(ly)
with open(ly, encoding="utf-8") as _f:
    txt = _f.read()
for line in txt.splitlines():
    if "touch" in line:
        # every quote that belongs to the user's text must be escaped or replaced; the text must stay inside one string
        body = line.split("touch", 1)[0]
        raw_quotes = body.replace(chr(92) * 2, "").replace(chr(92) + chr(34), "").count(chr(34))
        if raw_quotes > 1:
            print("a quote in user text is not escaped on this line:", line); sys.exit(1)
if shutil.which("lilypond"):
    r = subprocess.run(["lilypond", "-o", os.path.join(d, "out"), ly], capture_output=True, text=True, timeout=170)
    if os.path.exists(sentinel):
        print("LilyPond RAN the code in a track name or title"); sys.exit(1)

# the real save path: a failing write must leave the existing file alone
good = os.path.join(d, "good.mid")
song.to_mid(good)
def read(p):
    with open(p, "rb") as _f:
        return _f.read()
before = read(good)
class Fake: pass
fake = Fake(); fake._score_only_changes = lambda: 0; fake._update_title = lambda: None; fake.song = song
def boom(self, path, match_score=False):
    with open(path, "wb") as _f:
        _f.write(b"half a file")
    raise RuntimeError("disk full")
with mock.patch.object(gui.Song, "to_mid", boom):
    try:
        gui.MidisoftStudio._write_mid(fake, good)
        print("the failure was swallowed"); sys.exit(1)
    except RuntimeError:
        pass
if read(good) != before:
    print("a failed save damaged the existing file"); sys.exit(1)
if [n for n in os.listdir(d) if n.endswith(".part")]:
    print("a temporary file was left behind"); sys.exit(1)
gui.MidisoftStudio._write_mid(fake, good)             # a working save replaces it with a real MIDI file
mido.MidiFile(good)
sys.exit(0)
"""


class Wiring(unittest.TestCase):
    def test_injection_and_safe_save(self):
        r = subprocess.run([sys.executable, "-c", "ROOT = %r\n" % ROOT + SCRIPT], capture_output=True, text=True, timeout=240)
        if r.returncode == 77:
            self.skipTest("no tkinter")
        self.assertEqual(r.returncode, 0, r.stdout[-1500:] + r.stderr[-800:])


if __name__ == "__main__":
    unittest.main()

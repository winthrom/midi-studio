"""v22ze-322: export and external-program safety (0.4.2 security work).
Findings and changes:
  * Saving never damages a good file.  Every save (Save, Save As, Open in MuseScore, Export LilyPond, Export MusicXML) now
    writes to a temporary file in the same folder and replaces the target in one step, so a full disk or a crash leaves the
    old file untouched; an empty result is refused; existing permissions and links are kept.  (Before, a failure part-way
    could leave half a file where a good one had been.)
  * The chosen save name is checked first (sys_platform.check_save_path): control characters, over-long names, a folder that
    does not exist or cannot be written, and a target that is a folder, device or pipe.
  * Programs started from here (LilyPond, MuseScore, the PDF viewer, the log folder) get the clean environment: an AppImage's
    own library folders are no longer handed to them.  MuseScore is given an absolute path.
  * Print: the temporary folder is removed even when writing the score fails, and our own old score PDFs
    (midistudio_score_*.pdf, over a day old) are deleted; before, every Print left a PDF in the temporary folder for ever.
  * LilyPond text injection was TESTED, not assumed: a crafted MIDI with LilyPond/Scheme code in the title, composer or track
    names does NOT run (checked with LilyPond 2.24.3: the title and composer have quotes replaced, track names are written
    as an escaped string).  LilyPond's own safe mode was removed in 2.23.12, so this escaping is the only defence; a
    regression test now keeps it.  Drag-in of files does not exist in the program, so it has no path to check.
Run from the repo root:  python3 patch_v22ze322_export_safety.py
"""
import sys, os

TEST = r'''# Export and external-program safety (v22ze-322): safe saving, temporary files, and LilyPond text injection.
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
'''

FUNCS = r'''def check_save_path(path):
    """None when `path` may be written to; otherwise one plain sentence.  Nothing is written."""
    import stat as _stat
    if not isinstance(path, str) or not path:
        return "No file name was chosen."
    if len(path) > MAX_PATH_CHARS or len(os.path.basename(path)) > MAX_NAME_CHARS:
        return "The file name or folder path is too long."
    if any(ord(c) < 32 or ord(c) == 127 for c in path):
        return "The file name contains characters that are not allowed (such as a line break)."
    full = os.path.abspath(path)
    folder = os.path.dirname(full)
    if not os.path.isdir(folder):
        return "That folder does not exist."
    if not os.access(folder, os.W_OK | os.X_OK):
        return "You do not have permission to save in that folder."
    if os.path.lexists(full):
        try:
            st = os.stat(full)
        except OSError:
            return "That name is a link to something that does not exist."
        if not _stat.S_ISREG(st.st_mode):
            return "That name belongs to a folder or device, not an ordinary file."
        if not os.access(full, os.W_OK):
            return "That file is read-only."
    return None


def atomic_write(path, writer):
    """Call writer(temporary_path), then put the result at `path` in one step.  A failure, a full disk or a crash leaves any
    existing file exactly as it was, and the temporary file is removed.  Raises whatever the writer raised."""
    import tempfile
    target = os.path.realpath(path)            # a link to a file stays a link; the file it points to is replaced
    fd, tmp = tempfile.mkstemp(prefix=".midistudio-", suffix=".part", dir=os.path.dirname(target))
    os.close(fd)
    try:
        writer(tmp)
        if os.path.getsize(tmp) == 0:
            raise OSError("Nothing was written, so the existing file was left as it is.")
        if not sys.platform.startswith("win"):
            try:
                if os.path.exists(target):
                    shutil.copymode(target, tmp)
                else:
                    os.chmod(tmp, 0o644)
            except OSError:
                pass
        os.replace(tmp, target)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def remove_old_temp_files(prefix, suffix, max_age_seconds=86400, directory=None):
    """Delete this program's own old temporary files: ordinary files (not links) that we own, whose names start with
    `prefix` and end with `suffix` and that are older than max_age_seconds.  Returns how many were removed."""
    import stat as _stat
    import tempfile
    folder = directory or tempfile.gettempdir()
    try:
        names = os.listdir(folder)
    except OSError:
        return 0
    now, removed = time.time(), 0
    for nm in names:
        if not (nm.startswith(prefix) and nm.endswith(suffix)):
            continue
        p = os.path.join(folder, nm)
        try:
            st = os.lstat(p)
            if not _stat.S_ISREG(st.st_mode):
                continue
            if hasattr(os, "getuid") and st.st_uid != os.getuid():
                continue
            if now - st.st_mtime < max_age_seconds:
                continue
            os.remove(p)
            removed += 1
        except OSError:
            continue
    return removed


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
        ("def fetch_latest_release(url=None, timeout=6):\n", FUNCS, "def atomic_write("),
        ('APP_VERSION = "22ze-321"', 'APP_VERSION = "22ze-322"', 'APP_VERSION = "22ze-322"'),
    ])
    ch |= edit("midi_io.py", [
        ("def _trusted_executable(path):\n", "child_env = _child_env   # v22ze-322: the same clean environment, for the other programs we start\n\n\ndef _trusted_executable(path):\n",
         "child_env = _child_env"),
    ])
    ch |= edit("gui.py", [
        ("    check_midi_path,\n    fetch_latest_release,\n", "    atomic_write,\n    check_midi_path,\n    check_save_path,\n    fetch_latest_release,\n    remove_old_temp_files,\n",
         "    atomic_write,\n    check_midi_path,"),
        # Save / Save As
        ("        self.song.to_mid(path, match)\n        self._update_title()\n",
         "        atomic_write(path, lambda _p: self.song.to_mid(_p, match))   # v22ze-322: a failed save keeps the old file\n        self._update_title()\n",
         "atomic_write(path, lambda _p: self.song.to_mid(_p, match))"),
        ("    def _write_mid(self, path):   # v22ze-213\n        match = False\n",
         "    def _write_mid(self, path):   # v22ze-213\n        _why = check_save_path(path)   # v22ze-322\n        if _why:\n            raise OSError(_why)\n        match = False\n",
         "_why = check_save_path(path)   # v22ze-322\n        if _why:\n            raise OSError(_why)\n        match = False"),
        # Open in MuseScore
        ('        try:\n            self.song.to_mid(path)\n        except Exception as e:\n            messagebox.showerror("Export failed", str(e), parent=self.root)\n            return\n',
         '        _why = check_save_path(path)   # v22ze-322\n        if _why:\n            messagebox.showerror("Export failed", _why, parent=self.root)\n            return\n'
         '        path = os.path.abspath(path)\n'
         '        try:\n            atomic_write(path, self.song.to_mid)\n        except Exception as e:\n            messagebox.showerror("Export failed", str(e), parent=self.root)\n            return\n',
         "atomic_write(path, self.song.to_mid)"),
        ("                subprocess.Popen([exe, path])\n", "                subprocess.Popen([exe, path], env=midi_io.child_env())\n", "subprocess.Popen([exe, path], env=midi_io.child_env())"),
        # Export LilyPond
        ("        if path:\n            try:\n                _src = self.song   # already swapped to rationalized version when active\n                _src.to_ly(path,\n                           show_bar_numbers=show_bar_numbers,\n                           staff_size=staff_size,\n                           short_rests=bool(getattr(self, '_short_rests_var', None) and self._short_rests_var.get()))\n",
         "        if path:\n            _why = check_save_path(path)   # v22ze-322\n            if _why:\n                messagebox.showerror(\"Error\", _why, parent=self.root)\n                return\n            try:\n                _src = self.song   # already swapped to rationalized version when active\n"
         "                atomic_write(path, lambda _p: _src.to_ly(_p,\n                           show_bar_numbers=show_bar_numbers,\n                           staff_size=staff_size,\n                           short_rests=bool(getattr(self, '_short_rests_var', None) and self._short_rests_var.get())))\n",
         "atomic_write(path, lambda _p: _src.to_ly(_p,"),
        # Export MusicXML
        ("        if not path:\n            return\n        import tempfile\n        try:\n            with tempfile.TemporaryDirectory() as tmpdir:\n                ly_path = os.path.join(tmpdir, \"score.ly\")\n",
         "        if not path:\n            return\n        _why = check_save_path(path)   # v22ze-322\n        if _why:\n            messagebox.showerror(\"MusicXML Export Failed\", _why, parent=self.root)\n            return\n"
         "        import tempfile\n        try:\n            with tempfile.TemporaryDirectory() as tmpdir:\n                ly_path = os.path.join(tmpdir, \"score.ly\")\n",
         "messagebox.showerror(\"MusicXML Export Failed\", _why"),
        ("            xml_doc.write(path)\n        except Exception as e:\n            messagebox.showerror(\"MusicXML Export Failed\"",
         "            atomic_write(path, xml_doc.write)\n        except Exception as e:\n            messagebox.showerror(\"MusicXML Export Failed\"",
         "atomic_write(path, xml_doc.write)"),
        # Print: temporary folder and old PDFs
        ('        try:\n            tmpdir = tempfile.mkdtemp(prefix="midistudio_print_")\n',
         '        tmpdir = None\n        try:\n            tmpdir = tempfile.mkdtemp(prefix="midistudio_print_")\n',
         "        tmpdir = None\n        try:\n            tmpdir = tempfile.mkdtemp(prefix=\"midistudio_print_\")"),
        ('        except Exception as exc:\n            messagebox.showerror("Print Error", str(exc), parent=self.root)\n            return\n\n        state = {"proc": None,',
         '        except Exception as exc:\n            if tmpdir:\n                shutil.rmtree(tmpdir, ignore_errors=True)   # v22ze-322: no folder left behind\n            messagebox.showerror("Print Error", str(exc), parent=self.root)\n            return\n\n        state = {"proc": None,',
         "no folder left behind"),
        ("                    text=True, **_kw)\n                state[\"proc\"] = proc\n",
         "                    text=True, env=midi_io.child_env(), **_kw)\n                state[\"proc\"] = proc\n",
         "text=True, env=midi_io.child_env(), **_kw)"),
        ("                stable = tempfile.NamedTemporaryFile(\n",
         "                remove_old_temp_files(\"midistudio_score_\", \".pdf\")   # v22ze-322: our own old score PDFs\n                stable = tempfile.NamedTemporaryFile(\n",
         "remove_old_temp_files(\"midistudio_score_\", \".pdf\")"),
        ('                    subprocess.Popen(["open", stable.name])\n                else:\n                    subprocess.Popen(["xdg-open", stable.name])\n',
         '                    subprocess.Popen(["open", stable.name], env=midi_io.child_env())\n                else:\n                    subprocess.Popen(["xdg-open", stable.name], env=midi_io.child_env())\n',
         'subprocess.Popen(["open", stable.name], env=midi_io.child_env())'),
        ('                subprocess.Popen(["open", d])\n', '                subprocess.Popen(["open", d], env=midi_io.child_env())\n', 'subprocess.Popen(["open", d], env=midi_io.child_env())'),
        ('                subprocess.Popen(["xdg-open", d])\n', '                subprocess.Popen(["xdg-open", d], env=midi_io.child_env())\n', 'subprocess.Popen(["xdg-open", d], env=midi_io.child_env())'),
    ])
    ch |= edit("docs/MAINTAINING.md", [
        ("   - Still to review: file-path handling on open, drag-in and export; what the problem-report zip contains.\n",
         "   - Open path done (v22ze-321: size limit = the smaller of 50 MB and free memory / 60; nothing is read or closed when a file is\n"
         "     refused).  Export done (v22ze-322): every save goes through a temporary file and one replace; save names are checked;\n"
         "     external programs get the clean environment; Print cleans up after itself.  LilyPond text injection was tested with\n"
         "     LilyPond 2.24.3 and does not work against our output; LilyPond's own safe mode no longer exists (removed in 2.23.12), so\n"
         "     the escaping in to_ly() is the only defence and is covered by tests/test_export_safety.py.  There is no file drag-in.\n"
         "   - Still to review: what the problem-report zip contains (personal paths in the logs, the temporary copy of the piece).\n",
         "Export done (v22ze-322)"),
    ])
    p = os.path.join("tests", "test_export_safety.py")
    if not os.path.exists(p) or open(p, encoding="utf-8").read() != TEST:
        open(p, "w", encoding="utf-8", newline="\n").write(TEST); ch = True
    import py_compile
    for f in ("gui.py", "midi_io.py", "sys_platform.py"):
        py_compile.compile(f, doraise=True)
    print("Done." if ch else "Already applied. Nothing changed.")


main()

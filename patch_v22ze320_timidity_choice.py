"""v22ze-320: "TiMidity (start it now)" in Setup > MIDI Output Device.  Since v22ze-145 the program does not start TiMidity by
itself when built-in FluidSynth exists (TiMidity crashed on Ubuntu 26.04), and that window lists only ports that are
already running, so a person with TiMidity installed saw no TiMidity choice at all.  Now, when TiMidity is installed and
no TiMidity port is running, the window offers "TiMidity (start it now)"; choosing it starts TiMidity (the 319 safe start),
waits up to 3 s for its port, and switches to it.  If that fails, the window shows the reason and the command to try by
hand, and the current output is kept.  Nothing starts unless that choice is made.
Run from the repo root:  python3 patch_v22ze320_timidity_choice.py
"""
import sys, os

TEST = r'''# "TiMidity (start it now)" in the MIDI Output Device window (v22ze-319b/320).  The window check runs in a separate Python
# process (tests/test_gui.py replaces tkinter with a mock for the whole run) and is skipped when there is no display.
import os, subprocess, sys, unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _mi():
    try:
        import midi_io
        return midi_io
    except Exception:
        raise unittest.SkipTest("midi_io could not be imported here")


class StartTimidity(unittest.TestCase):
    def setUp(self):
        self.mi = _mi()

    def _run(self, names, installed=True, launched=True, wait=1.0):
        mi = self.mi
        launch = mock.Mock(return_value=launched)
        with mock.patch.object(mi.mido, "get_output_names", side_effect=names), \
             mock.patch.object(mi, "timidity_installed", return_value=installed), \
             mock.patch.object(mi, "_launch_timidity", launch), \
             mock.patch.object(mi.time, "sleep"):
            try:
                return mi.start_timidity(wait=wait), launch
            except RuntimeError as exc:
                return exc, launch

    def test_already_running_is_not_started_again(self):
        got, launch = self._run([["Midi Through", "TiMidity port 0"]])
        self.assertEqual(got, "TiMidity port 0"); launch.assert_not_called()

    def test_started_and_found(self):
        got, launch = self._run([[], [], ["TiMidity port 0"]] + [["TiMidity port 0"]] * 20)
        self.assertEqual(got, "TiMidity port 0"); launch.assert_called_once()

    def test_not_installed(self):
        got, launch = self._run([[]] * 5, installed=False)
        self.assertIsInstance(got, RuntimeError); launch.assert_not_called()

    def test_started_but_no_port(self):
        got, launch = self._run([[]] * 50, wait=0.0)
        self.assertIsInstance(got, RuntimeError)
        self.assertIn("-iA", str(got))                  # the message shows the command to try by hand


SCRIPT = """
import sys
sys.path.insert(0, ROOT)
try:
    import tkinter as tk
    root = tk.Tk()
except Exception:
    sys.exit(77)
import gui, midi_io
from unittest import mock
root.geometry("200x100+0+0")

class Fake: pass
fake = Fake(); fake.root = root; fake._update_status = lambda: None
picked = []
def walk(w):
    yield w
    for c in w.winfo_children():
        yield from walk(c)
with mock.patch.object(gui.mido, "get_output_names", return_value=["Midi Through Port-0"]), \\
     mock.patch.object(midi_io, "timidity_installed", return_value=True), \\
     mock.patch.object(midi_io, "start_timidity", return_value="TiMidity port 0"), \\
     mock.patch.object(midi_io, "select_output", side_effect=lambda c, **k: picked.append(c)):
    gui.MidisoftStudio._choose_midi_output(fake)
    for _ in range(5):
        root.update()
    widgets = list(walk(root))
    radios = [w for w in widgets if w.winfo_class() == "Radiobutton"]
    texts = [w.cget("text") for w in radios]
    if midi_io.TIMIDITY_START not in texts:
        print("option missing; found", texts); sys.exit(1)
    next(w for w in radios if w.cget("text") == midi_io.TIMIDITY_START).invoke()
    next(w for w in widgets if w.winfo_class() == "Button" and w.cget("text") == "Use This").invoke()
if picked != ["TiMidity port 0"]:
    print("expected select_output('TiMidity port 0'), got", picked); sys.exit(1)
sys.exit(0)
"""


class OutputWindow(unittest.TestCase):
    def test_choice_is_offered_and_starts_timidity(self):
        if sys.platform.startswith("linux") and not os.environ.get("DISPLAY"):
            self.skipTest("no display")
        r = subprocess.run([sys.executable, "-c", "ROOT = %r\n" % ROOT + SCRIPT], capture_output=True, text=True, timeout=180)
        if r.returncode == 77:
            self.skipTest("no tkinter or no display")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr[-800:])


if __name__ == "__main__":
    unittest.main()
'''

MIDI_FUNCS = r'''def timidity_installed():
    """True when a TiMidity program is installed where it may safely be run (see _trusted_executable)."""
    import shutil
    return _trusted_executable(shutil.which("timidity"))


def _timidity_port():
    try:
        for p in mido.get_output_names():
            if "timidity" in p.lower():
                return p
    except Exception:
        pass
    return None


def start_timidity(wait=3.0):
    """Return the name of a TiMidity output port, starting TiMidity first when none is running.
    Raises RuntimeError (with a plain message) when that is not possible."""
    port = _timidity_port()
    if port:
        return port
    if not timidity_installed():
        raise RuntimeError("TiMidity is not installed, or it is in a folder that is not protected, so it was not started.")
    _launch_timidity()
    end = time.time() + wait
    while True:
        port = _timidity_port()
        if port:
            return port
        if time.time() >= end:
            break
        time.sleep(0.2)
    raise RuntimeError("TiMidity was started but no TiMidity port appeared.\nTo see why, run this in a terminal:\n\n" + TIMIDITY_HINT)


def _prompt_midi_output_choice(trusted_ports):
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
    ch = edit("midi_io.py", [
        ('FLUIDSYNTH_BUILTIN = "FluidSynth (built-in)"\n',
         'FLUIDSYNTH_BUILTIN = "FluidSynth (built-in)"\nTIMIDITY_START = "TiMidity (start it now)"   # v22ze-320: a choice in the output window, not a port name\n',
         "TIMIDITY_START ="),
        ("def _prompt_midi_output_choice(trusted_ports):\n", MIDI_FUNCS, "def start_timidity("),
    ])
    ch |= edit("gui.py", [
        ('        except ImportError:\n            pass\n\n        if not options:\n            messagebox.showinfo("MIDI Output Device",',
         '        except ImportError:\n            pass\n\n'
         '        try:   # v22ze-320: TiMidity installed but not running: offer to start it (nothing starts until it is chosen)\n'
         '            if midi_io.timidity_installed() and not any("timidity" in o.lower() for o in outs):\n'
         '                options.append(midi_io.TIMIDITY_START)\n'
         '        except Exception:\n            pass\n\n'
         '        if not options:\n            messagebox.showinfo("MIDI Output Device",',
         "options.append(midi_io.TIMIDITY_START)"),
        ('                midi_io.select_output(chosen)\n\n                self._update_status()',
         '                if chosen == midi_io.TIMIDITY_START:   # v22ze-320\n                    chosen = midi_io.start_timidity()\n'
         '                midi_io.select_output(chosen)\n\n                self._update_status()',
         "chosen = midi_io.start_timidity()"),
    ])
    ch |= edit("docs/USER_GUIDE.md", [
        ('- **MIDI Output Device…**: choose which "synthesizer" makes the sound, and its volume (section 10).',
         '- **MIDI Output Device…**: choose which "synthesizer" makes the sound, and its volume (section 10). If TiMidity is installed on your computer but not running, the list also offers **TiMidity (start it now)**; choose it and the program starts TiMidity and switches to it.',
         "TiMidity (start it now)"),
    ])
    ch |= edit("sys_platform.py", [
        ('APP_VERSION = "22ze-319"', 'APP_VERSION = "22ze-320"', 'APP_VERSION = "22ze-320"'),
    ])
    p = os.path.join("tests", "test_timidity_choice.py")
    if not os.path.exists(p) or open(p, encoding="utf-8").read() != TEST:
        open(p, "w", encoding="utf-8", newline="\n").write(TEST); ch = True
    import py_compile
    for f in ("gui.py", "midi_io.py", "sys_platform.py"):
        py_compile.compile(f, doraise=True)
    print("Done." if ch else "Already applied. Nothing changed.")


main()

# "TiMidity (start it now)" in the MIDI Output Device window (v22ze-319b/320).  The window check runs in a separate Python
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

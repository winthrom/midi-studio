# The check runs in a separate Python process: tests/test_gui.py replaces tkinter with a mock for the whole test run,
# so a window cannot be built in this process.  Skipped when there is no display.
import os, subprocess, sys, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SCRIPT = """
import os, sys
sys.path.insert(0, ROOT)
try:
    import tkinter as tk
    root = tk.Tk()
except Exception:
    sys.exit(77)
import gui

class S:
    def keyboard_choices(self):
        return ([{"program": 0, "name": "Acoustic Grand Piano", "tracks": [2], "notes": 1500, "lo": 36, "hi": 88},
                 {"program": 1, "name": "Bright Acoustic Piano", "tracks": [3], "notes": 900, "lo": 40, "hi": 90},
                 {"program": 4, "name": "Electric Piano 1", "tracks": [4, 5], "notes": 400, "lo": 48, "hi": 84}], 0)

class F:
    song = S()
    def _dialog_help_button(self, dlg, frm, anchor):
        pass
F.root = root

def find(w, text):
    if isinstance(w, tk.Button) and w.cget("text") == text:
        return w
    for c in w.winfo_children():
        r = find(c, text)
        if r:
            return r

res = {}
def fake_wait(self, w=None):
    w.update()
    b = find(w, "Continue")
    res["found"] = b is not None
    if b is not None:
        x = b.winfo_rootx() + b.winfo_width() // 2
        y = b.winfo_rooty() + b.winfo_height() // 2
        res["top"] = root.winfo_containing(x, y) is b
    w.destroy()
tk.Misc.wait_window = fake_wait
gui.MidisoftStudio._ask_which_instrument(F())
if not res.get("found"):
    print("no Continue button in the dialog"); sys.exit(1)
if not res.get("top"):
    print("Continue is hidden under another widget"); sys.exit(1)
sys.exit(0)
"""


class ContinueButton(unittest.TestCase):
    def test_continue_is_on_top(self):
        if sys.platform.startswith("linux") and not os.environ.get("DISPLAY"):
            self.skipTest("no display")
        r = subprocess.run([sys.executable, "-c", "ROOT = %r\n" % ROOT + SCRIPT], capture_output=True, text=True, timeout=120)
        if r.returncode == 77:
            self.skipTest("no tkinter or no display")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr[-500:])


if __name__ == "__main__":
    unittest.main()

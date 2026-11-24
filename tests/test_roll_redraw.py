# Redraw counts for the two piano rolls (v22ze-318).  Runs in a separate Python process (tests/test_gui.py replaces
# tkinter with a mock for the whole run); skipped when there is no display.
import os, subprocess, sys, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SCRIPT = """
import sys, time, random
sys.path.insert(0, ROOT)
try:
    import tkinter as tk
    root = tk.Tk()
except Exception:
    sys.exit(77)
import gui

random.seed(1)
def mk(name, lo, hi):
    t = gui.Track(name=name, channel=0)
    for i in range(6000):
        t.notes.append(gui.MidiNote(i * 15, random.randint(lo, hi), 80, random.choice([60, 120, 480]), 0))
    return t
song = gui.Song()
song.tracks = [mk("Piano (RH)", 60, 100), mk("Piano (LH)", 30, 60)]

class T:
    position_ticks = 0
    playing = False
    def is_playing(self): return self.playing
class A: pass
app = A(); app.song = song; app.transport = T(); app._open_windows = []; app._score_view = None
root.geometry("200x100+0+0")

def pump(sec):
    end = time.time() + sec
    while time.time() < end:
        root.update(); time.sleep(0.005)

for cls in (gui.VerticalRollView, gui.HorizontalRollView):
    v = cls(root, app)
    v.geometry("1000x700+0+0")
    pump(0.6)
    draws = []
    orig = v._draw
    v._draw = lambda: (draws.append(1), orig())[1]
    for i in range(25):                                   # a burst of size changes, like dragging a window edge
        v.geometry("%dx%d+0+0" % (1000 + i * 6, 700 + i * 2))
        root.update()
    pump(0.6)
    if len(draws) > 2:
        print(cls.__name__, "resize burst caused", len(draws), "full redraws (expected 1 or 2)"); sys.exit(1)
    if not v.canvas.find_withtag("vnote"):
        print(cls.__name__, "nothing drawn after the resize"); sys.exit(1)
    dyn = []
    orig_dyn = v._draw_dynamic
    v._draw_dynamic = lambda force=False: (dyn.append(1), orig_dyn(force))[1]
    app.transport.playing = True
    t0 = time.time(); tick = 0
    while time.time() - t0 < 1.0:                         # the program's loop calls this about every 16 ms
        tick += 90
        v.update_playhead(tick)
        root.update(); time.sleep(0.016)
    if len(dyn) > 45 or len(dyn) < 8:
        print(cls.__name__, "playing for 1 s drew", len(dyn), "times (expected about 30, at most 45)"); sys.exit(1)
    app.transport.playing = False
    v.destroy()
sys.exit(0)
"""


class RollRedraw(unittest.TestCase):
    def test_redraw_counts(self):
        if sys.platform.startswith("linux") and not os.environ.get("DISPLAY"):
            self.skipTest("no display")
        r = subprocess.run([sys.executable, "-c", "ROOT = %r\n" % ROOT + SCRIPT], capture_output=True, text=True, timeout=240)
        if r.returncode == 77:
            self.skipTest("no tkinter or no display")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr[-800:])


if __name__ == "__main__":
    unittest.main()

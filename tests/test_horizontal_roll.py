# The window check runs in a separate Python process: tests/test_gui.py replaces tkinter with a mock for the whole run.
# Skipped when there is no display.
import os, subprocess, sys, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SCRIPT = """
import sys
sys.path.insert(0, ROOT)
try:
    import tkinter as tk
    root = tk.Tk()
except Exception:
    sys.exit(77)
import gui

def mk(name, notes_at, dur):
    t = gui.Track(name=name, channel=0)
    for tk_, p in notes_at:
        t.notes.append(gui.MidiNote(tk_, p, 80, dur, 0))
    return t

song = gui.Song()
song.tracks = [mk("Piano (RH)", [(0, 72), (480, 76)], 480), mk("Piano (LH)", [(0, 48)], 960)]

class T:
    position_ticks = 0
    playing = False
    def is_playing(self): return self.playing

class A: pass
app = A(); app.song = song; app.transport = T(); app._open_windows = []; app._score_view = None
root.geometry("200x100+0+0")
v = gui.HorizontalRollView(root, app)
v.geometry("1100x720+0+0")
import time
_end = time.time() + 0.6        # the first draw is immediate, a resize is drawn 0.15 s after it stops
while time.time() < _end:
    root.update(); time.sleep(0.01)
c = v.canvas
x_now = v.KEYB_W

def fail(msg):
    print(msg); sys.exit(1)

items = c.find_withtag("vnote")
if len(items) != 3:
    fail("expected 3 notes in view, found %d" % len(items))
by_y = sorted(items, key=lambda i: c.coords(i)[1])
if c.itemcget(by_y[0], "fill") != "#56B4E9":
    fail("left-hand note (lowest) is not at the top in blue")
if c.itemcget(by_y[-1], "fill") != "#E69F00":
    fail("right-hand note (highest) is not at the bottom in orange")
if min(c.coords(i)[0] for i in items) < x_now:
    fail("a note reaches into the keyboard strip")
keys = c.find_withtag("key")
if max(c.coords(i)[2] for i in keys) > x_now + 1:
    fail("keyboard is not at the left")
v._scroll_beats(1)
if len(c.find_withtag("vnote")) != 2 or app.transport.position_ticks != 480:
    fail("scrolling one beat did not move the view")
app.transport.playing = True
v.update_playhead(500)
root.update()
if len(c.find_withtag("lit")) < 3:
    fail("keys were not lit while playing")
time.sleep(0.12); v.update_playhead(3000)
root.update()
if c.find_withtag("lit"):
    fail("keys stay lit after the notes ended")
sys.exit(0)
"""


class HorizontalRoll(unittest.TestCase):
    def test_window(self):
        if sys.platform.startswith("linux") and not os.environ.get("DISPLAY"):
            self.skipTest("no display")
        r = subprocess.run([sys.executable, "-c", "ROOT = %r\n" % ROOT + SCRIPT], capture_output=True, text=True, timeout=180)
        if r.returncode == 77:
            self.skipTest("no tkinter or no display")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr[-800:])


if __name__ == "__main__":
    unittest.main()

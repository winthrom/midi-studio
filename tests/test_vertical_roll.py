# The window check runs in a separate Python process: tests/test_gui.py replaces tkinter with a mock for the whole run.
# The window check is skipped when there is no display; the geometry and colour checks need none.
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

def mk(name, pitch, notes_at, dur, ch=0):
    t = gui.Track(name=name, channel=ch)
    for tk_, p in notes_at:
        t.notes.append(gui.MidiNote(tk_, p, 80, dur, ch))
    return t

song = gui.Song()
song.tracks = [mk("Piano (RH)", 72, [(0, 72), (480, 76)], 480), mk("Piano (LH)", 48, [(0, 48)], 960)]

class T:
    position_ticks = 0
    playing = False
    def is_playing(self): return self.playing

class A: pass
app = A(); app.song = song; app.transport = T(); app._open_windows = []; app._score_view = None
root.geometry("200x100+0+0")
vr = gui.VerticalRollView(root, app)
vr.geometry("1100x720+0+0")
import time
_end = time.time() + 0.6        # the first draw is immediate, a resize is drawn 0.15 s after it stops
while time.time() < _end:
    root.update(); time.sleep(0.01)
c = vr.canvas
H = c.winfo_height()
y_now = H - vr.KEYB_H

def fail(msg):
    print(msg); sys.exit(1)

items = c.find_withtag("vnote")
if len(items) != 3:
    fail("expected 3 notes in view, found %d" % len(items))
by_x = sorted(items, key=lambda i: c.coords(i)[0])
if c.itemcget(by_x[0], "fill") != "#56B4E9":
    fail("left-hand note (lowest, leftmost) is not sky blue")
if c.itemcget(by_x[-1], "fill") != "#E69F00":
    fail("right-hand note (highest, rightmost) is not orange")
if max(c.coords(i)[3] for i in items) > y_now:
    fail("a note reaches below the line where the keyboard starts")
keys = c.find_withtag("key")
if min(c.coords(i)[1] for i in keys) < y_now - 1:
    fail("keyboard is not at the bottom")
vr._scroll_beats(1)          # one beat later: the first right-hand note (one beat long) has gone
if len(c.find_withtag("vnote")) != 2 or app.transport.position_ticks != 480:
    fail("scrolling one beat did not move the view (notes %d, position %d)"
         % (len(c.find_withtag("vnote")), app.transport.position_ticks))
app.transport.playing = True
vr.update_playhead(500)      # now the right-hand note at 480 and the left-hand note at 0 are sounding
root.update()
if len(c.find_withtag("lit")) < 3:
    fail("keys were not lit while playing")
time.sleep(0.12); vr.update_playhead(3000)     # past the end
root.update()
if c.find_withtag("lit"):
    fail("keys stay lit after the notes ended")
sys.exit(0)
"""


class VerticalRoll(unittest.TestCase):
    def test_key_geometry(self):
        import gui
        g = gui._vroll_key_geometry(1040)
        self.assertEqual(sorted(g), list(range(21, 109)))
        whites = sorted((v for v in g.values() if not v[2]), key=lambda v: v[0])
        blacks = [p for p, v in g.items() if v[2]]
        self.assertEqual(len(whites), 52)
        self.assertEqual(len(blacks), 36)
        self.assertAlmostEqual(whites[0][0], 0.0)
        self.assertAlmostEqual(whites[-1][1], 1040.0)
        for a, b in zip(whites, whites[1:]):
            self.assertAlmostEqual(a[1], b[0])                      # white keys tile the width
        for p in blacks:                                            # black key sits on the line between its two neighbours
            self.assertAlmostEqual((g[p][0] + g[p][1]) / 2.0, g[p - 1][1])
        for p in range(21, 108):                                    # low notes are to the left
            if not g[p][2] and not g[p + 1][2]:
                self.assertLess(g[p][0], g[p + 1][0])
        self.assertLess(g[21][0], g[108][0])

    def test_colours_and_tracks(self):
        import gui
        def tr(name, ch=0, n=1):
            t = gui.Track(name=name, channel=ch)
            for i in range(n):
                t.notes.append(gui.MidiNote(i * 480, 60 + i, 80, 480, ch))
            return t
        song = gui.Song()
        song.tracks = [tr("Piano (RH)"), tr("Piano (LH)"), tr("Strings"), tr("Drums", ch=9), tr("Flute")]
        shown = gui._vroll_shown_tracks(song)
        self.assertEqual([(i, c, l) for i, t, c, l in shown],
                         [(0, "#E69F00", "Right hand"), (1, "#56B4E9", "Left hand"),
                          (2, "#009E73", "Strings"), (4, "#0072B2", "Flute")])     # drums left out
        song.tracks[2].mute = True
        self.assertEqual([i for i, t, c, l in gui._vroll_shown_tracks(song)], [0, 1, 4])
        self.assertEqual([c for i, t, c, l in gui._vroll_shown_tracks(song)][2], "#0072B2")   # colours stay put
        song.tracks[4].solo = True
        self.assertEqual([i for i, t, c, l in gui._vroll_shown_tracks(song)], [4])
        for col in (gui._VROLL_RH, gui._VROLL_LH) + tuple(gui._VROLL_OTHER):
            self.assertNotIn(col.upper(), ("#FF0000", "#00FF00"))

    def test_window(self):
        if sys.platform.startswith("linux") and not os.environ.get("DISPLAY"):
            self.skipTest("no display")
        r = subprocess.run([sys.executable, "-c", "ROOT = %r\n" % ROOT + SCRIPT], capture_output=True, text=True, timeout=180)
        if r.returncode == 77:
            self.skipTest("no tkinter or no display")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr[-800:])


if __name__ == "__main__":
    unittest.main()

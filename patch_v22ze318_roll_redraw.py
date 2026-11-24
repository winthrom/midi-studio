"""v22ze-318: the piano rolls draw far less often.  On the maintainer's Intel graphics, resizing a roll while a long piece
played (with the score undocked) hung the graphics chip and the whole screen (kernel log: i915 GPU HANG, 2026-11-24).
Three changes, for the vertical and the horizontal roll:
  1. While a roll window is being resized, nothing is redrawn; the roll is drawn once, 0.15 s after the resizing stops
     (the first draw is still immediate).  Before, every size event redrew every item, dozens of times a second.
  2. While playing, the moving notes are redrawn at most about 30 times a second (not about 60), and less often if a
     redraw is slow (the pause is three times the time the last redraw took, up to 0.1 s).
  3. The tests wait for the delayed redraw, and two new tests count the redraws (resize burst and playback).
This is a precaution; it cannot be proved on a machine without the same graphics.  Please try it on the machine that hung.
Run from the repo root:  python3 patch_v22ze318_roll_redraw.py
"""
import sys, os


def rd(p):
    raw = open(p, "rb").read().decode("utf-8")
    return "\r\n" in raw, raw.replace("\r\n", "\n")


def wr(p, t, crlf):
    open(p, "wb").write((t.replace("\n", "\r\n") if crlf else t).encode("utf-8"))


def refuse(msg):
    print("REFUSED: " + msg + "  Nothing changed."); sys.exit(1)


METHODS = '''    # v22ze-318: no redraw while the window is being resized; one draw when the resizing pauses
    def _on_configure(self, e=None):
        if self._geo is None:                 # first appearance: draw at once
            self._draw()
            return
        try:
            if self._cfg_job is not None:
                self.after_cancel(self._cfg_job)
            self._cfg_job = self.after(150, self._configure_done)
        except Exception:
            self._cfg_job = None

    def _configure_done(self):
        self._cfg_job = None
        try:
            if self.winfo_exists():
                self._draw()
        except Exception:
            pass

    def destroy(self):
        try:
            if self._cfg_job is not None:
                self.after_cancel(self._cfg_job)
        except Exception:
            pass
        self._cfg_job = None
        super().destroy()

    def _playing(self):
        try:
            return bool(self.app.transport.is_playing())'''

PLAY_OLD = '        self._tick = float(tick)\n        self._draw_dynamic()\n\n    def update_active_notes'
PLAY_NEW = ('        self._tick = float(tick)\n'
            '        now = time.perf_counter()                       # v22ze-318: at most about 30 redraws a second\n'
            '        if self._playing() and now - self._last_play_draw < self._play_interval:   # (a stopped roll always redraws)\n'
            '            return\n'
            '        self._last_play_draw = now\n'
            '        self._draw_dynamic()\n'
            '        self._play_interval = min(0.1, max(0.033, 3.0 * (time.perf_counter() - now)))\n\n'
            '    def update_active_notes')

TEST_OLD = "for _ in range(10):\n    root.update()\n"
TEST_NEW = ("import time\n_end = time.time() + 0.6        # the first draw is immediate, a resize is drawn 0.15 s after it stops\n"
            "while time.time() < _end:\n    root.update(); time.sleep(0.01)\n")

NEWTEST = r'''# Redraw counts for the two piano rolls (v22ze-318).  Runs in a separate Python process (tests/test_gui.py replaces
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
'''


def main():
    changed = False
    crlf, t = rd("gui.py")
    t0 = t
    if "def _on_configure(self, e=None):" not in t:
        pairs = [
            # (old, new, how many times old must occur)
            ('expand=True)\n        self.canvas.bind("<Configure>", lambda e: self._draw())\n',
             'expand=True)\n        self.canvas.bind("<Configure>", self._on_configure)\n', 1),
            ('self.bind(seq, lambda e, d=d: self._scroll_beats(d))\n        self.canvas.bind("<Configure>", lambda e: self._draw())\n',
             'self.bind(seq, lambda e, d=d: self._scroll_beats(d))\n        self.canvas.bind("<Configure>", self._on_configure)\n', 1),
            ('        self._lit_prev = None\n        nm = app.song.title',
             '        self._lit_prev = None\n        self._cfg_job = None\n        self._drawn_size = None\n'
             '        self._last_play_draw = 0.0\n        self._play_interval = 0.033\n        nm = app.song.title', 1),
            ('    def _playing(self):\n        try:\n            return bool(self.app.transport.is_playing())', METHODS, 1),
            (PLAY_OLD, PLAY_NEW, 1),
            ('        self._last_key = None\n        self._lit_prev = None\n        self._draw_dynamic(force=True)',
             '        self._drawn_size = (W, H)\n        self._last_key = None\n        self._lit_prev = None\n        self._draw_dynamic(force=True)', 2),
            ('        W, H = c.winfo_width(), c.winfo_height()\n        kh = self.KEYB_H\n        y_now = H - kh\n        song = self.app.song\n        self._check_index()',
             '        W, H = c.winfo_width(), c.winfo_height()\n        if self._drawn_size != (W, H):            # being resized: wait for the redraw\n            return\n'
             '        kh = self.KEYB_H\n        y_now = H - kh\n        song = self.app.song\n        self._check_index()', 1),
            ('        W, H = c.winfo_width(), c.winfo_height()\n        kw = self.KEYB_W\n        x_now = kw\n        song = self.app.song\n        self._check_index()',
             '        W, H = c.winfo_width(), c.winfo_height()\n        if self._drawn_size != (W, H):            # being resized: wait for the redraw\n            return\n'
             '        kw = self.KEYB_W\n        x_now = kw\n        song = self.app.song\n        self._check_index()', 1),
        ]
        for old, new, n in pairs:
            if t.count(old) != n:
                refuse("anchor found %d times (expected %d): %r" % (t.count(old), n, old[:70]))
            t = t.replace(old, new)
    if t != t0:
        wr("gui.py", t, crlf); changed = True
    for name in ("test_vertical_roll.py", "test_horizontal_roll.py"):
        p = os.path.join("tests", name)
        crlf, t = rd(p)
        if "_end = time.time() + 0.6" not in t:
            if t.count(TEST_OLD) != 1:
                refuse("test wait anchor not found exactly once in " + p)
            wr(p, t.replace(TEST_OLD, TEST_NEW), crlf); changed = True
    for name, old3, new3 in (("test_vertical_roll.py", "vr.update_playhead(3000)", "time.sleep(0.12); vr.update_playhead(3000)"),
                             ("test_horizontal_roll.py", "v.update_playhead(3000)", "time.sleep(0.12); v.update_playhead(3000)")):
        p = os.path.join("tests", name)
        crlf, t = rd(p)
        if "time.sleep(0.12)" not in t:
            if t.count(old3) != 1:
                refuse("update_playhead(3000) anchor not found exactly once in " + p)
            wr(p, t.replace(old3, new3), crlf); changed = True
    p = os.path.join("tests", "test_roll_redraw.py")
    if not os.path.exists(p) or open(p, encoding="utf-8").read() != NEWTEST:
        open(p, "w", encoding="utf-8", newline="\n").write(NEWTEST); changed = True
    crlf, t = rd("sys_platform.py")
    if 'APP_VERSION = "22ze-318"' not in t:
        if t.count('APP_VERSION = "22ze-317"') != 1:
            refuse("APP_VERSION anchor not found.")
        wr("sys_platform.py", t.replace('APP_VERSION = "22ze-317"', 'APP_VERSION = "22ze-318"'), crlf); changed = True
    import py_compile
    py_compile.compile("gui.py", doraise=True); py_compile.compile("sys_platform.py", doraise=True)
    print("Done." if changed else "Already applied. Nothing changed.")


main()

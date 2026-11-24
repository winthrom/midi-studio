"""v22ze-316: the horizontal piano roll, rebuilt as the vertical roll turned a quarter turn (your note of 2026-11-23: what
we had was wrong).  Keyboard at the LEFT, low notes at the TOP and high notes at the BOTTOM (as a player sitting at that
keyboard sees it); time runs from the right toward the keyboard, so notes slide left onto the keys; keys light up;
right hand orange, left hand blue; every unmuted track; view-only.  Ctrl+2, the Roll button, the track context menu, a
double-click on a track and a click on the overview now open it.  The older roll (one track, notes can be edited) is kept
for now under View > "Piano Roll (edit notes, older)" until it is decided what happens to editing (roll plan step 1).
Run from the repo root:  python3 patch_v22ze316_horizontal_roll.py
"""
import sys, os

CODE = r'''class HorizontalRollView(VerticalRollView):
    """The vertical roll turned a quarter turn: the keyboard is at the LEFT, low notes at the TOP and high notes at the
    BOTTOM (the way a player sitting at that keyboard sees it), time runs from the right toward the keyboard, so the
    notes slide left onto the keys.  Same tracks, colours, lit keys and view-only rule as the vertical roll."""
    KEYB_W = 84

    def __init__(self, parent, app):
        super().__init__(parent, app)
        nm = app.song.title or os.path.basename(app.song.filename or "") or "untitled"
        self.title("Piano Roll — " + nm)

    def _build_ui(self):
        super()._build_ui()
        for seq, d in (("<Right>", 1), ("<Left>", -1)):
            self.bind(seq, lambda e, d=d: self._scroll_beats(d))
        self.canvas.bind("<Configure>", lambda e: self._draw())

    def _draw(self):
        c = self.canvas
        W, H = c.winfo_width(), c.winfo_height()
        kw = self.KEYB_W
        if H < 100 or W < kw + 120:
            return
        self._rebuild_index()
        c.delete("all")
        self._geo = geo = _vroll_key_geometry(H)           # here the "x" of a key is its distance from the top
        x_now = kw
        for p in range(24, 109, 12):                       # a faint line at every C
            y0 = geo[p][0]
            c.create_line(x_now, y0, W, y0, fill="#1c2a38", tags="static")
        for p in sorted(geo):                               # white keys first, black keys over them
            y0, y1, blk = geo[p]
            if not blk:
                c.create_rectangle(0, y0, x_now, y1, fill="#f2f2f2", outline="#555", tags=("static", "key"))
        for p in range(24, 109, 12):
            y0, y1, blk = geo[p]
            c.create_text(4, (y0 + y1) / 2.0, text="C%d" % (p // 12 - 1), anchor="w", fill="#666",
                          font=("TkFixedFont", 7), tags="static")
        for p in sorted(geo):
            y0, y1, blk = geo[p]
            if blk:
                c.create_rectangle(x_now - kw * 0.62, y0, x_now, y1, fill="#222", outline="#000", tags=("static", "key"))
        c.create_line(x_now, 0, x_now, H, fill="#9aa7b4", width=2, tags="static")   # the line the notes slide onto
        self._last_key = None
        self._lit_prev = None
        self._draw_dynamic(force=True)

    def _draw_dynamic(self, force=False):
        c = self.canvas
        geo = self._geo
        if not geo:
            return
        W, H = c.winfo_width(), c.winfo_height()
        kw = self.KEYB_W
        x_now = kw
        song = self.app.song
        self._check_index()
        tpb = float(song.ticks_per_beat or 480)
        k = self._ppb / tpb
        tick = self._tick
        key = (int(round(tick * k)), round(self._ppb, 2), W, H)
        if force or key != self._last_key:
            self._last_key = key
            c.delete("dyn")
            t_end = tick + (W - x_now) / k
            tpm = song.ticks_per_measure()
            if tpm > 0:
                if self._ppb >= 50:                         # beat lines, fainter than bar lines
                    b = int(tick // tpb)
                    while True:
                        tx = b * tpb
                        x = x_now + (tx - tick) * k
                        if x > W:
                            break
                        if tx >= tick and (tx % tpm):
                            c.create_line(x, 0, x, H, fill="#1d2b3b", tags="dyn")
                        b += 1
                b = int(tick // tpm)
                while True:
                    tx = b * tpm
                    x = x_now + (tx - tick) * k
                    if x > W:
                        break
                    if tx >= tick:
                        c.create_line(x, 0, x, H, fill="#4a5f78", tags="dyn")
                        c.create_text(x + 3, 2, text=str(b + 1), anchor="nw", fill="#9db2c8",
                                      font=("TkFixedFont", 8), tags="dyn")
                    b += 1
            for col, starts, notes, maxdur in self._index:
                lo = bisect.bisect_left(starts, tick - maxdur)
                hi = bisect.bisect_right(starts, t_end)
                for j in range(lo, hi):
                    t0, dur, p = notes[j]
                    t1 = t0 + dur
                    if t1 <= tick:
                        continue
                    g = geo.get(p)
                    if g is None:
                        continue
                    x_l = x_now + (max(t0, tick) - tick) * k
                    x_r = min(float(W), x_now + (t1 - tick) * k)
                    if x_r - x_l < 4:
                        x_r = x_l + 4
                    c.create_rectangle(x_l + 1, g[0] + 1, x_r, g[1] - 1, fill=col, outline="#0b1118",
                                       tags=("dyn", "vnote"))
        lit = {}
        if self._playing():
            for col, starts, notes, maxdur in self._index:
                lo = bisect.bisect_left(starts, tick - maxdur)
                hi = bisect.bisect_right(starts, tick)
                for j in range(lo, hi):
                    t0, dur, p = notes[j]
                    if t0 <= tick < t0 + dur:
                        lit[p] = col
        if lit != self._lit_prev:
            c.delete("lit")
            self._lit_prev = dict(lit)
            if lit:
                for p, col in lit.items():
                    g = geo.get(p)
                    if g and not g[2]:
                        c.create_rectangle(1, g[0] + 1, x_now - 1, g[1] - 1, fill=col, outline="#333", tags="lit")
                for p in sorted(geo):                        # black keys again, over the lit white ones
                    g = geo[p]
                    if g[2]:
                        c.create_rectangle(x_now - kw * 0.62, g[0], x_now, g[1], fill=lit.get(p, "#222"),
                                           outline="#000", tags="lit")
'''

OPEN_METHOD = """    def _open_horizontal_roll(self):
        self.root.focus_set()   # dismiss any open menu
        if not self.song or not self.song.tracks:
            messagebox.showinfo("Piano Roll", "Open a file first.", parent=self.root); return
        for w in self._open_windows:
            try:
                if type(w) is HorizontalRollView and w.winfo_exists():
                    w.lift(); w.focus_force(); return
            except Exception: pass
        hr = HorizontalRollView(self.root, self)
        self._open_windows.append(hr)

"""

TEST = r'''# The window check runs in a separate Python process: tests/test_gui.py replaces tkinter with a mock for the whole run.
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
for _ in range(10):
    root.update()
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
v.update_playhead(3000)
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
'''


def rd(p):
    raw = open(p, "rb").read().decode("utf-8")
    return "\r\n" in raw, raw.replace("\r\n", "\n")


def wr(p, t, crlf):
    open(p, "wb").write((t.replace("\n", "\r\n") if crlf else t).encode("utf-8"))


def edit(path, pairs):
    crlf, t0 = rd(path)
    t = t0
    for old, new, marker in pairs:
        if marker in t:
            continue
        if t.count(old) != 1:
            print("REFUSED: anchor not found exactly once in %s: %r" % (path, old[:70])); sys.exit(1)
        t = t.replace(old, new)
    if t != t0:
        wr(path, t, crlf)
        return True
    return False


def main():
    ch = edit("gui.py", [
        ("class PianoRollView(tk.Toplevel):", CODE + "\n\nclass PianoRollView(tk.Toplevel):", "class HorizontalRollView("),
        ('''        vm.add_command(label="Piano Roll\\tCtrl+2",command=self._open_piano_roll,accelerator="Ctrl+2")\n''',
         '''        vm.add_command(label="Piano Roll\\tCtrl+2",command=self._open_horizontal_roll,accelerator="Ctrl+2")\n'''
         '''        vm.add_command(label="Piano Roll (edit notes, older)",command=self._open_piano_roll)\n''', "_open_horizontal_roll,accelerator"),
        ('("<Control-2>",self._open_piano_roll)', '("<Control-2>",self._open_horizontal_roll)', '("<Control-2>",self._open_horizontal_roll)'),
        ('tk.Button(tb,text="♬ Roll",command=self._open_piano_roll,', 'tk.Button(tb,text="♬ Roll",command=self._open_horizontal_roll,', 'text="♬ Roll",command=self._open_horizontal_roll'),
        ('selection_set(idx)\n        self._open_piano_roll()', 'selection_set(idx)\n        self._open_horizontal_roll()', 'selection_set(idx)\n        self._open_horizontal_roll()'),
        ('m.add_command(label="Piano Roll",command=self._open_piano_roll)', 'm.add_command(label="Piano Roll",command=self._open_horizontal_roll)', 'm.add_command(label="Piano Roll",command=self._open_horizontal_roll)'),
        ('app.track_list.bind("<Double-1>", lambda e: app._open_piano_roll())', 'app.track_list.bind("<Double-1>", lambda e: app._open_horizontal_roll())', 'lambda e: app._open_horizontal_roll()'),
        ("    def _open_vertical_roll(self):", OPEN_METHOD + "    def _open_vertical_roll(self):", "def _open_horizontal_roll("),
    ]) 
    ch |= edit("gui.py", [("View only. Mouse wheel or Up/Down keys scroll.", "View only. Mouse wheel or arrow keys scroll.", "View only. Mouse wheel or arrow keys scroll.")])
    ch |= edit("docs/USER_GUIDE.md", [
        ("- **Piano Roll (♬)**: each note is a bar. Higher notes are higher on the screen; longer notes are longer bars. Easy to see exactly when each note starts and stops.",
         "- **Piano Roll (♬)**: each note is a bar; longer notes are longer bars. The keyboard is at the left, as if you sat facing it: low notes at the top, high notes at the bottom. The music comes in from the right and slides left onto the keys, and each key lights up as its note arrives. Right hand is orange and left hand is blue. It shows every instrument that is not muted (or only the soloed ones) and is for looking only. Scroll with the mouse wheel, the Left and Right keys or Page Up and Page Down. The older roll, which edits one instrument\\'s notes, is still under View as \"Piano Roll (edit notes, older)\".",
         "slides left onto the keys"),
    ])
    ch |= edit("sys_platform.py", [
        ('APP_VERSION = "22ze-315"', 'APP_VERSION = "22ze-316"', 'APP_VERSION = "22ze-316"'),
    ])
    tp = os.path.join("tests", "test_horizontal_roll.py")
    if not os.path.exists(tp) or open(tp, encoding="utf-8").read() != TEST:
        open(tp, "w", encoding="utf-8", newline="\n").write(TEST); ch = True
    import py_compile
    py_compile.compile("gui.py", doraise=True); py_compile.compile("sys_platform.py", doraise=True)
    print("Done." if ch else "Already applied. Nothing changed.")


main()

"""v22ze-315: vertical piano roll (roll plan step 3, first version).  New menu entry View > "Piano Roll (vertical)".
A separate window; the existing horizontal roll is unchanged.  Keyboard at the bottom, low notes left, high notes right,
time runs up the screen and notes fall toward the keyboard; keys light up during playback; right hand orange and left hand
blue (Okabe-Ito colour-blind-safe palette); every unmuted track is shown.  View-only: nothing in it changes the music.
Run from the repo root:  python3 patch_v22ze315_vertical_roll.py
"""
import sys

CODE = r'''# ─────────────────────────────────────────────────────────────────────────────
# Piano Roll, vertical (v22ze-315)
# ─────────────────────────────────────────────────────────────────────────────
# The keyboard sits at the bottom, low notes at the left (as the keys sit in front of a player); time runs up the
# screen and the notes fall onto the keyboard while the music plays.  View only: nothing here changes the music.
# Colours: the Okabe-Ito colour-blind-safe palette (Okabe and Ito, "Color Universal Design", 2002): right hand orange,
# left hand sky blue, any other track bluish green, reddish purple, blue, grey in turn.  Never red against green.

_VROLL_RH = "#E69F00"
_VROLL_LH = "#56B4E9"
_VROLL_OTHER = ("#009E73", "#CC79A7", "#0072B2", "#999999")


def _vroll_key_geometry(width):
    """{pitch: (x0, x1, is_black)} for the 88 keys A0 (21) to C8 (108) laid across `width` pixels: 52 white keys of
    equal width, each black key centred on the line between two white keys."""
    black_pcs = (1, 3, 6, 8, 10)
    whites = [p for p in range(21, 109) if p % 12 not in black_pcs]
    wk = width / float(len(whites))
    geo = {}
    index = {}
    for i, p in enumerate(whites):
        geo[p] = (i * wk, (i + 1) * wk, False)
        index[p] = i
    for p in range(21, 109):
        if p % 12 in black_pcs:
            cx = (index[p - 1] + 1) * wk      # the key just below a black key is always a white one
            bw = wk * 0.6
            geo[p] = (cx - bw / 2.0, cx + bw / 2.0, True)
    return geo


def _vroll_shown_tracks(song):
    """[(track_index, track, colour, label)] of the tracks the vertical roll draws: tracks with notes that are not
    muted (and, if any track is soloed, only the soloed ones); drums are left out.  A track keeps its colour when
    another is muted."""
    has_solo = any(t.solo for t in song.tracks)
    rh, lh = _hand_tracks(song)
    other = 0
    out = []
    for i, t in enumerate(song.tracks):
        if i == rh:
            col, label = _VROLL_RH, "Right hand"
        elif i == lh:
            col, label = _VROLL_LH, "Left hand"
        else:
            col = _VROLL_OTHER[other % len(_VROLL_OTHER)]
            other += 1
            label = t.name or "Track %d" % (i + 1)
        if not t.notes or t.mute or (has_solo and not t.solo) or getattr(t, "channel", 0) == 9:
            continue
        out.append((i, t, col, label))
    return out


class VerticalRollView(tk.Toplevel):
    KEYB_H = 84
    BG = "#101820"

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self._ppb = 90.0                 # pixels per beat (zoom)
        try:
            self._tick = float(app.transport.position_ticks or 0)
        except Exception:
            self._tick = 0.0
        self._index = []
        self._sig = None
        self._sig_t = 0.0
        self._geo = None
        self._last_key = None
        self._lit_prev = None
        nm = app.song.title or os.path.basename(app.song.filename or "") or "untitled"
        self.title("Piano Roll (vertical) — " + nm)
        self.geometry("1100x720")
        self._build_ui()

    def _build_ui(self):
        tb = tk.Frame(self, bd=1, relief=tk.RAISED)
        tb.pack(fill=tk.X)
        tk.Button(tb, text="Zoom +", command=self._zoom_in).pack(side=tk.LEFT, padx=2, pady=2)
        tk.Button(tb, text="Zoom −", command=self._zoom_out).pack(side=tk.LEFT, padx=2, pady=2)
        tk.Label(tb, text="   View only. Mouse wheel or Up/Down keys scroll.",
                 fg="#555").pack(side=tk.LEFT)
        self._legend = tk.Frame(tb)
        self._legend.pack(side=tk.RIGHT, padx=6)
        self.canvas = tk.Canvas(self, bg=self.BG, highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)
        self.canvas.bind("<Configure>", lambda e: self._draw())
        self.canvas.bind("<MouseWheel>", self._on_wheel)
        self.canvas.bind("<Button-4>", self._on_wheel)
        self.canvas.bind("<Button-5>", self._on_wheel)
        self.canvas.bind("<Button-1>", lambda e: self.canvas.focus_set())
        for seq, d in (("<Up>", 1), ("<Down>", -1), ("<Prior>", 8), ("<Next>", -8)):
            self.bind(seq, lambda e, d=d: self._scroll_beats(d))
        self.bind("<Home>", lambda e: self._scroll_to(0))
        self.canvas.focus_set()

    # ── movement ──────────────────────────────────────────────────────────
    def _playing(self):
        try:
            return bool(self.app.transport.is_playing())
        except Exception:
            return False

    def _on_wheel(self, e):
        up = getattr(e, "num", 0) == 4 or getattr(e, "delta", 0) > 0
        self._scroll_beats(1 if up else -1)

    def _scroll_beats(self, n):
        if self._playing():
            return
        song = self.app.song
        top = float(song.total_ticks_fast())
        self._scroll_to(max(0.0, min(top, self._tick + n * song.ticks_per_beat)))

    def _scroll_to(self, t):
        if self._playing():
            return
        self._tick = float(t)
        try:
            self.app.transport.position_ticks = int(t)
        except Exception:
            pass
        try:
            sv = getattr(self.app, "_score_view", None)
            if sv is not None and sv.winfo_exists():
                sv.update_cursor(int(t))
        except Exception:
            pass
        self._draw_dynamic()

    def _zoom_in(self):
        self._ppb = min(400.0, self._ppb * 1.4)
        self._draw_dynamic(force=True)

    def _zoom_out(self):
        self._ppb = max(20.0, self._ppb / 1.4)
        self._draw_dynamic(force=True)

    # ── called by the program's tick loop while playing ──────────────────
    def update_playhead(self, tick):
        try:
            if not self.winfo_exists():
                return
        except Exception:
            return
        self._tick = float(tick)
        self._draw_dynamic()

    def update_active_notes(self, active_pitches):
        pass    # the lit keys are worked out here, per track, so each takes its track's colour

    # ── drawing ───────────────────────────────────────────────────────────
    def _signature(self):
        return tuple((len(t.notes), t.mute, t.solo, sum(n.tick + n.pitch + n.duration for n in t.notes))
                     for t in self.app.song.tracks)

    def _rebuild_index(self):
        self._index = []
        shown = _vroll_shown_tracks(self.app.song)
        for i, t, col, label in shown:
            notes = sorted(((n.tick, n.duration, n.pitch) for n in t.notes if n.duration > 0), key=lambda x: x[0])
            if notes:
                self._index.append((col, [x[0] for x in notes], notes, max(x[1] for x in notes)))
        self._sig = self._signature()
        self._sig_t = time.time()
        for w in self._legend.winfo_children():
            w.destroy()
        for i, t, col, label in shown:
            tk.Label(self._legend, text="■ " + label, fg=col, bg="#101820", padx=6).pack(side=tk.LEFT, padx=2)

    def _check_index(self):
        if time.time() - self._sig_t > 0.5:
            self._sig_t = time.time()
            if self._signature() != self._sig:
                self._rebuild_index()
                self._last_key = None

    def _draw(self):
        c = self.canvas
        W, H = c.winfo_width(), c.winfo_height()
        if W < 100 or H < self.KEYB_H + 120:
            return
        self._rebuild_index()
        c.delete("all")
        self._geo = geo = _vroll_key_geometry(W)
        kh = self.KEYB_H
        y_now = H - kh
        for p in range(24, 109, 12):                       # a faint line at every C
            x0 = geo[p][0]
            c.create_line(x0, 0, x0, y_now, fill="#1c2a38", tags="static")
        for p in sorted(geo):                               # white keys first, black keys over them
            x0, x1, blk = geo[p]
            if not blk:
                c.create_rectangle(x0, y_now, x1, H, fill="#f2f2f2", outline="#555", tags=("static", "key"))
        for p in range(24, 109, 12):
            x0, x1, blk = geo[p]
            c.create_text((x0 + x1) / 2.0, H - 4, text="C%d" % (p // 12 - 1), anchor="s", fill="#666",
                          font=("TkFixedFont", 7), tags="static")
        for p in sorted(geo):
            x0, x1, blk = geo[p]
            if blk:
                c.create_rectangle(x0, y_now, x1, y_now + kh * 0.62, fill="#222", outline="#000", tags=("static", "key"))
        c.create_line(0, y_now, W, y_now, fill="#9aa7b4", width=2, tags="static")   # the line the notes fall onto
        self._last_key = None
        self._lit_prev = None
        self._draw_dynamic(force=True)

    def _draw_dynamic(self, force=False):
        c = self.canvas
        geo = self._geo
        if not geo:
            return
        W, H = c.winfo_width(), c.winfo_height()
        kh = self.KEYB_H
        y_now = H - kh
        song = self.app.song
        self._check_index()
        tpb = float(song.ticks_per_beat or 480)
        k = self._ppb / tpb
        tick = self._tick
        key = (int(round(tick * k)), round(self._ppb, 2), W, H)
        if force or key != self._last_key:
            self._last_key = key
            c.delete("dyn")
            t_end = tick + y_now / k
            tpm = song.ticks_per_measure()
            if tpm > 0:
                if self._ppb >= 50:                         # beat lines, fainter than bar lines
                    b = int(tick // tpb)
                    while True:
                        ty = b * tpb
                        y = y_now - (ty - tick) * k
                        if y < 0:
                            break
                        if ty >= tick and (ty % tpm):
                            c.create_line(0, y, W, y, fill="#1d2b3b", tags="dyn")
                        b += 1
                b = int(tick // tpm)
                while True:
                    ty = b * tpm
                    y = y_now - (ty - tick) * k
                    if y < 0:
                        break
                    if ty >= tick:
                        c.create_line(0, y, W, y, fill="#4a5f78", tags="dyn")
                        c.create_text(4, y - 2, text=str(b + 1), anchor="sw", fill="#9db2c8",
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
                    y_bot = y_now - (max(t0, tick) - tick) * k
                    y_top = max(0.0, y_now - (t1 - tick) * k)
                    if y_bot - y_top < 4:
                        y_top = y_bot - 4
                    c.create_rectangle(g[0] + 1, y_top, g[1] - 1, y_bot - 1, fill=col, outline="#0b1118",
                                       tags=("dyn", "vnote"))
        # keys lit while playing, each in its track's colour
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
                        c.create_rectangle(g[0] + 1, y_now + 1, g[1] - 1, H - 1, fill=col, outline="#333", tags="lit")
                for p in sorted(geo):                        # black keys again, over the lit white ones
                    g = geo[p]
                    if g[2]:
                        c.create_rectangle(g[0], y_now, g[1], y_now + kh * 0.62, fill=lit.get(p, "#222"),
                                           outline="#000", tags="lit")


'''

TEST = r'''# The window check runs in a separate Python process: tests/test_gui.py replaces tkinter with a mock for the whole run.
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
for _ in range(10):
    root.update()
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
vr.update_playhead(3000)     # past the end
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
'''

OPEN_METHOD = """    def _open_vertical_roll(self):
        self.root.focus_set()   # dismiss any open menu
        if not self.song or not self.song.tracks:
            messagebox.showinfo("Piano Roll (vertical)", "Open a file first.", parent=self.root); return
        for w in self._open_windows:
            try:
                if isinstance(w, VerticalRollView) and w.winfo_exists():
                    w.lift(); w.focus_force(); return
            except Exception: pass
        vr = VerticalRollView(self.root, self)
        self._open_windows.append(vr)

"""


def rd(p):
    raw = open(p, "rb").read().decode("utf-8")
    return "\r\n" in raw, raw.replace("\r\n", "\n")


def wr(p, t, crlf):
    open(p, "wb").write((t.replace("\n", "\r\n") if crlf else t).encode("utf-8"))


def edit(path, pairs):
    crlf, t = rd(path)
    for old, new, marker in pairs:
        if marker in t:
            continue
        if t.count(old) != 1:
            print("REFUSED: anchor not found exactly once in %s: %r" % (path, old[:70])); sys.exit(1)
        t = t.replace(old, new)
    return crlf, t


def main():
    changed = False
    crlf, t = edit("gui.py", [
        ("class PianoRollView(tk.Toplevel):", CODE + "\n\nclass PianoRollView(tk.Toplevel):", "class VerticalRollView("),
        ('''        vm.add_command(label="Piano Roll\\tCtrl+2",command=self._open_piano_roll,accelerator="Ctrl+2")\n''',
         '''        vm.add_command(label="Piano Roll\\tCtrl+2",command=self._open_piano_roll,accelerator="Ctrl+2")\n'''
         '''        vm.add_command(label="Piano Roll (vertical)",command=self._open_vertical_roll)\n''', "_open_vertical_roll)"),
        ("isinstance(w, PianoRollView) and _winfo_exists(w):", "isinstance(w, (PianoRollView, VerticalRollView)) and _winfo_exists(w):", "(PianoRollView, VerticalRollView)"),
        ("    def _open_list_view(self):", OPEN_METHOD + "    def _open_list_view(self):", "def _open_vertical_roll("),
    ])
    old = open("gui.py", "rb").read().decode("utf-8").replace("\r\n", "\n")
    if t != old:
        wr("gui.py", t, crlf); changed = True
    crlf, t = edit("docs/USER_GUIDE.md", [
        ("**Piano Roll** (Ctrl+2), **MIDI List**", "**Piano Roll** (Ctrl+2), **Piano Roll (vertical)**, **MIDI List**", "Piano Roll (vertical)**"),
        ("- **MIDI List (\U0001f4cb)**:", "- **Piano Roll, vertical** (View menu): the keyboard is at the bottom, low notes at the left and high notes at the right. Time runs up the screen and the notes fall toward the keyboard while the music plays; the key lights up as each note arrives. Right hand is orange and left hand is blue; other instruments have their own colours. It shows every instrument that is not muted (or only the soloed ones). It is for looking only: nothing you do in this window changes the music. Scroll with the mouse wheel, the Up and Down keys or Page Up and Page Down; Zoom + and - change how much time fits on the screen.\n- **MIDI List (\U0001f4cb)**:", "**Piano Roll, vertical**"),
    ])
    old = open("docs/USER_GUIDE.md", "rb").read().decode("utf-8").replace("\r\n", "\n")
    if t != old:
        wr("docs/USER_GUIDE.md", t, crlf); changed = True
    crlf, t = edit("docs/MAINTAINING.md", [
        ("3. **Vertical view, view-only**: time", "3. **Vertical view, view-only** (first version v22ze-315, a separate window, View > Piano Roll (vertical)): time", "first version v22ze-315"),
    ])
    old = open("docs/MAINTAINING.md", "rb").read().decode("utf-8").replace("\r\n", "\n")
    if t != old:
        wr("docs/MAINTAINING.md", t, crlf); changed = True
    crlf, t = edit("sys_platform.py", [
        ('APP_VERSION = "22ze-314"', 'APP_VERSION = "22ze-315"', 'APP_VERSION = "22ze-315"'),
        ('APP_TIMESTAMP = "2026-11-22"', 'APP_TIMESTAMP = "2026-11-23"', 'APP_TIMESTAMP = "2026-11-23"'),
    ])
    old = open("sys_platform.py", "rb").read().decode("utf-8").replace("\r\n", "\n")
    if t != old:
        wr("sys_platform.py", t, crlf); changed = True
    import os
    tp = os.path.join("tests", "test_vertical_roll.py")
    if not os.path.exists(tp) or open(tp, encoding="utf-8").read() != TEST:
        open(tp, "w", encoding="utf-8", newline="\n").write(TEST); changed = True
    import py_compile
    py_compile.compile("gui.py", doraise=True); py_compile.compile("sys_platform.py", doraise=True)
    print("Done." if changed else "Already applied. Nothing changed.")


main()

"""v22ze-317: the older horizontal piano roll (one track, click to add a note, right-click to delete, Select All / Delete /
Quantize / Transpose buttons, no Undo) is removed, as decided 2026-11-24: the new horizontal roll (316) and the vertical roll
(315) are the piano rolls.  Nothing in them changes the music.  Notes can still be changed through the Notes menu (for
example Quantize, which has Undo).  Roll plan step 1 (an "Edit notes" switch) is therefore dropped; step 2 (hand colours) is
done; fingering editing on the roll stays in the later plan (step 7).
Run from the repo root:  python3 patch_v22ze317_remove_old_roll.py
"""
import sys, os, re


def rd(p):
    raw = open(p, "rb").read().decode("utf-8")
    return "\r\n" in raw, raw.replace("\r\n", "\n")


def wr(p, t, crlf):
    open(p, "wb").write((t.replace("\n", "\r\n") if crlf else t).encode("utf-8"))


def refuse(msg):
    print("REFUSED: " + msg + "  Nothing changed."); sys.exit(1)


def cut(t, start, end, must_not_contain, what):
    """Remove t[start:end) where start and end are anchors that each occur once."""
    if t.count(start) != 1 or t.count(end) != 1:
        refuse("anchor for %s not found exactly once." % what)
    a, b = t.index(start), t.index(end)
    if a >= b:
        refuse("anchors for %s are in the wrong order." % what)
    for bad in must_not_contain:
        if bad in t[a + len(start):b]:
            refuse("%s contains %r; not cutting." % (what, bad))
    return t[:a] + t[b:]


def main():
    changed = False
    # ---- gui.py
    crlf, t0 = rd("gui.py")
    t = t0
    if "class PianoRollView(tk.Toplevel):" in t:
        t = cut(t, "class PianoRollView(tk.Toplevel):", "class MidiListView(tk.Toplevel):",
                ["\nclass ", "\ndef ", "\nVERT"], "the old roll class")
    if "def _open_piano_roll(self):" in t:
        t = cut(t, "    def _open_piano_roll(self):", "    def _open_horizontal_roll(self):", ["\n    def "], "the old open method")
    steps = [
        ("            _any_roll = any(isinstance(_w, PianoRollView) for _w in self._open_windows)  # v22ze-167\n"
         "            for tr in (self.song.tracks if _any_roll else ()):\n"
         "                if tr.mute: continue\n"
         "                for n in tr.notes:\n"
         "                    if n.tick <= tick < n.tick + n.duration:\n"
         "                        active.add(n.pitch)\n", ""),
        ("isinstance(w, (PianoRollView, VerticalRollView)) and _winfo_exists(w):",
         "isinstance(w, VerticalRollView) and _winfo_exists(w):"),
        ('        vm.add_command(label="Piano Roll (edit notes, older)",command=self._open_piano_roll)\n', ""),
    ]
    for old, new in steps:
        if old in t:
            if t.count(old) != 1:
                refuse("anchor not found exactly once: %r" % old[:60])
            t = t.replace(old, new)
    for left in ("PianoRollView", "_open_piano_roll"):
        if left in t:
            refuse("%s is still used somewhere in gui.py; not changing it." % left)
    if t != t0:
        wr("gui.py", t, crlf); changed = True
    # ---- tests/test_gui.py: the test that only checked the old class exists
    crlf, t0 = rd(os.path.join("tests", "test_gui.py"))
    t = t0
    m = re.search(r'    def test_pianoroll_creation\(self\):.*?self\.skipTest\("PianoRoll test skipped"\)\n\n?', t, re.S)
    if m:
        t = t[:m.start()] + t[m.end():]
    if "PianoRollView" in t:
        refuse("PianoRollView is still named in tests/test_gui.py.")
    if t != t0:
        wr(os.path.join("tests", "test_gui.py"), t, crlf); changed = True
    # ---- docs
    crlf, t0 = rd("docs/USER_GUIDE.md")
    t = t0
    old = ' The older roll, which edits one instrument\\\'s notes, is still under View as "Piano Roll (edit notes, older)".'
    old2 = ' The older roll, which edits one instrument\'s notes, is still under View as "Piano Roll (edit notes, older)".'
    for o in (old, old2):
        if o in t:
            t = t.replace(o, "")
    if "edit notes, older" in t:
        refuse("the guide sentence about the older roll was not found as expected.")
    if t != t0:
        wr("docs/USER_GUIDE.md", t, crlf); changed = True
    crlf, t0 = rd("docs/MAINTAINING.md")
    t = t0
    note = ("\n**Update 2026-11-24 (v22ze-317):** the older roll (one track, click to add and right-click to delete, no Undo) is\n"
            "removed. Steps 1 and 2 are therefore finished: the rolls are view-only and show both hands in colour (315 vertical,\n"
            "316 horizontal, turned a quarter turn: keyboard at the left, low notes at the top). Fingering editing on the roll stays in\n"
            "step 7.\n")
    if "v22ze-317" not in t:
        anchor = "### Piano roll plan (agreed 2026-11-21; steps 1 to 3 are in 0.4.2, steps 4 to 7 in 0.4.3)\n"
        if t.count(anchor) != 1:
            refuse("plan heading not found exactly once.")
        t = t.replace(anchor, anchor + note)
    if t != t0:
        wr("docs/MAINTAINING.md", t, crlf); changed = True
    # ---- version
    crlf, t0 = rd("sys_platform.py")
    t = t0
    if 'APP_VERSION = "22ze-317"' not in t:
        if t.count('APP_VERSION = "22ze-316"') != 1:
            refuse("APP_VERSION anchor not found.")
        t = t.replace('APP_VERSION = "22ze-316"', 'APP_VERSION = "22ze-317"')
    if t != t0:
        wr("sys_platform.py", t, crlf); changed = True
    import py_compile
    py_compile.compile("gui.py", doraise=True); py_compile.compile("sys_platform.py", doraise=True)
    print("Done." if changed else "Already applied. Nothing changed.")


main()

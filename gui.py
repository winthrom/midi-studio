#!/usr/bin/env python3
"""GUI components: menus, piano roll, MIDI list, transport."""

from __future__ import annotations

import bisect
import math
import os
import sys
import threading
import time
import tkinter as tk
import webbrowser
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from tkinter import filedialog, messagebox, simpledialog, ttk
from xml.dom import minidom

import mido

from theory import (
    _FLAT_ORDER_LETTERS,
    _SHARP_ORDER_LETTERS,
    GM_INSTRUMENTS,
    NOTE_NAMES,
    key_sig_accidentals,
    key_sig_to_ly,
)
import midi_io
from midi_io import (
    _init_fluidsynth,
    _maybe_show_no_synth_dialog,
    _midi_shutdown_evt,
    _save_settings,
    _send,
    _send_raw,
    midi_input_subscribe,
    midi_input_unsubscribe,
)
from sys_platform import (
    APP_FULL_NAME,
    APP_TIMESTAMP,
    APP_TITLE,
    APP_VERSION,
    LIONS_DONATE_URL,
    LIONS_WEBSITE_URL,
)


class TkPopupMenu(tk.Toplevel):
    """A dropdown/context menu built entirely from ordinary Tk widgets in
    a real Toplevel window, instead of Tk's native tk.Menu popup.

    v22ze-56: after the splash screen's virtual-desktop "sticky" bug was
    fixed by giving it a proper window TYPE hint (see SplashScreen), the
    SAME bug was confirmed still present on the main menu bar (File,
    Edit, View, Setup, Song Settings) on the user's real KDE/KWin
    desktop -- the window-type-hint approach doesn't apply there because
    tk.Menu's own popups are Tk's internal implementation detail; the
    actual X11 popup window Tk creates for a posted menu isn't something
    application code can call wm_attributes() on. What DOES reliably
    work, confirmed by the ALREADY-correct behavior of every dialog and
    floated-out window in this app, is an ordinary, fully WM-managed
    Toplevel. This class rebuilds just enough of tk.Menu's behavior
    (add_command, add_separator, add_cascade, add_radiobutton, and the
    tk_popup/grab_release entry points every existing call site already
    uses) out of ordinary Frame/Label widgets inside an ordinary
    Toplevel, trading tk.Menu's fully-borderless native chrome for
    behavior that's actually correct across virtual desktops on every
    window manager -- not just ones that happen to special-case Tk's
    internal popup windows the way we'd want. No overrideredirect and no
    special window-type hint is used here on purpose: those are exactly
    the mechanisms that opt a window OUT of normal window-manager
    desktop tracking, which is the root of this whole class of bug.
    """

    _BG = "#2b2b2b"
    _FG = "#eeeeee"
    _HOVER = "#3d6fa5"
    _SEP = "#555555"
    _ACCEL_FG = "#999999"

    def __init__(self, master, tearoff=0, **kw):
        super().__init__(master)
        self._items = []  # (kind, label, payload, accelerator)
        self._parent_menu = None  # set on submenus via add_cascade
        self._submenu_open = None
        self._posted = False
        self._row_widgets = []  # v22ze-56.1 — see _build_rows below
        self.withdraw()
        self.resizable(False, False)
        self.configure(bg=self._BG, bd=1, relief="solid")
        self.protocol("WM_DELETE_WINDOW", self.unpost)

    # ── tk.Menu-compatible construction API ─────────────────────────────
    def add_command(self, label="", command=None, accelerator="", tooltip="", **kw):
        self._items.append(("command", label, command, accelerator, tooltip))

    def add_separator(self, **kw):
        self._items.append(("separator", None, None, None, ""))

    def add_cascade(self, label="", menu=None, **kw):
        menu._parent_menu = self
        self._items.append(("cascade", label, menu, None, ""))

    def add_radiobutton(self, label="", value=None, variable=None, command=None, **kw):
        self._items.append(("radio", label, (value, variable, command), None, ""))

    # ── building the visible rows (done fresh each popup, so state like
    # a radiobutton's current value is always shown correctly) ─────────
    def _build_rows(self):
        # v22ze-56.1 fix: this used to destroy ALL of winfo_children(),
        # but a submenu's TkPopupMenu is constructed with THIS menu as
        # its master (see add_cascade) — Tk's widget-naming hierarchy
        # tracks that as a "child" for winfo_children() purposes even
        # though it's a separate Toplevel, not something visually nested
        # inside us. Blindly destroying every child therefore destroyed
        # the submenu itself the first time this menu was re-posted,
        # leaving it permanently broken (a "bad window path name" error
        # the next time anything tried to post it). Track only the row
        # widgets THIS method actually creates, and destroy just those.
        for w in self._row_widgets:
            w.destroy()
        self._row_widgets = []
        for kind, label, payload, accel, tooltip in self._items:
            if kind == "separator":
                sep = tk.Frame(self, height=1, bg=self._SEP)
                sep.pack(fill="x", padx=2, pady=3)
                self._row_widgets.append(sep)
                continue
            row = tk.Frame(self, bg=self._BG)
            row.pack(fill="x")
            self._row_widgets.append(row)  # children of row are destroyed with it
            prefix = ""
            if kind == "radio":
                value, variable, _cmd = payload
                prefix = "\u2713 " if variable.get() == value else "\u2002\u2002"
            # tk.Menu convention: "\t" in the label separates the label
            # text from an inline accelerator hint (e.g. "Save\tCtrl+S").
            if "\t" in label:
                text_lbl, accel_txt = label.split("\t", 1)
            else:
                text_lbl, accel_txt = label, accel
            lab = tk.Label(
                row,
                text=prefix + text_lbl,
                bg=self._BG,
                fg=self._FG,
                anchor="w",
                padx=10,
                pady=3,
                font=("TkDefaultFont", 10),
            )
            lab.pack(side="left", fill="x", expand=True)
            widgets = [row, lab]
            if accel_txt:
                acc = tk.Label(
                    row,
                    text=accel_txt,
                    bg=self._BG,
                    fg=self._ACCEL_FG,
                    anchor="e",
                    padx=10,
                    font=("TkDefaultFont", 9),
                )
                acc.pack(side="right")
                widgets.append(acc)
            if kind == "cascade":
                arrow = tk.Label(row, text="\u25b8", bg=self._BG, fg=self._FG, padx=6)
                arrow.pack(side="right")
                widgets.append(arrow)

            def _hover_on(e, ws=widgets):
                for w in ws:
                    w.configure(bg=self._HOVER)

            def _hover_off(e, ws=widgets):
                for w in ws:
                    w.configure(bg=self._BG)

            for w in widgets:
                w.bind("<Enter>", _hover_on)
                w.bind("<Leave>", _hover_off)
            if tooltip:
                _tt(row, tooltip)

            if kind == "command":
                cmd = payload
                for w in widgets:
                    w.bind("<ButtonRelease-1>", lambda e, c=cmd: self._run(c))
            elif kind == "radio":
                value, variable, cmd = payload
                for w in widgets:
                    w.bind(
                        "<ButtonRelease-1>",
                        lambda e, v=value, var=variable, c=cmd: self._run_radio(v, var, c),
                    )
            elif kind == "cascade":
                sub = payload
                for w in widgets:
                    w.bind(
                        "<ButtonRelease-1>",
                        lambda e, s=sub, r=row: self._open_submenu(s, r),
                    )

    def _run(self, command):
        self._close_chain()
        if command:
            command()

    def _run_radio(self, value, variable, command):
        variable.set(value)
        self._close_chain()
        if command:
            command()

    def _close_chain(self):
        """Unpost this menu and every ancestor cascade up to the top —
        a command anywhere in a nested cascade should close the WHOLE
        menu, not just the innermost submenu it was clicked in."""
        m = self
        while m is not None:
            nxt = m._parent_menu
            m.unpost()
            m = nxt

    def _open_submenu(self, submenu, row):
        if self._submenu_open is not None and self._submenu_open is not submenu:
            self._submenu_open.unpost()
        x = self.winfo_rootx() + self.winfo_width()
        y = row.winfo_rooty()
        self._submenu_open = submenu
        submenu.popup(x, y, _is_submenu=True)

    # ── posting / dismissing ────────────────────────────────────────────
    def popup(self, x, y, _is_submenu=False):
        self._build_rows()
        self.update_idletasks()
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        w = self.winfo_reqwidth()
        h = self.winfo_reqheight()
        x = max(0, min(x, sw - w - 4))
        y = max(0, min(y, sh - h - 4))
        self.geometry(f"+{x}+{y}")
        self.deiconify()
        self.lift()
        self._posted = True
        # v22ze-75 fix: the previous fix (v22ze-74) deferred all input-
        # sensitive setup to after_idle(), which fixed the "flashes open
        # and immediately closes" bug MOST of the time — but after_idle()
        # only waits for Tk's own internal idle queue to drain, which is
        # NOT the same thing as the window manager having actually mapped
        # this window yet. That's a race against real wall-clock WM
        # behavior, not against anything Tk itself controls, so its
        # outcome depends on system load / WM speed at the moment — this
        # is exactly why it worked reliably for whichever menu happened
        # to be opened first (the WM had the most idle time beforehand)
        # but was flaky for the others. The actual event that means "the
        # window manager has now really mapped this window" is X11's own
        # <Map> event — waiting for that instead of guessing at idle
        # timing removes the race entirely rather than just usually
        # winning it.
        self._map_seen = False

        def _on_map(event):
            if self._map_seen:
                return
            self._map_seen = True
            self.bind("<Escape>", lambda e: self._close_chain())
            self.bind("<Button-1>", self._on_click)
            self.focus_force()
            if not _is_submenu:
                self.grab_set()

        self.bind("<Map>", _on_map)
        # Fallback safety net: on the small chance a WM never delivers a
        # <Map> event for an already-realized Toplevel (some WMs skip it
        # if the window was merely deiconified rather than newly created),
        # still finish setup after a short delay so the menu never gets
        # permanently stuck half-initialized.
        self.after(150, lambda: _on_map(None))

    def _on_click(self, event):
        under = self.winfo_containing(event.x_root, event.y_root)
        if under is None or not self._owns_widget(under):
            self._close_chain()

    def _owns_widget(self, widget):
        m = self
        while m is not None:
            if str(widget).startswith(str(m)):
                return True
            m = m._submenu_open
        return False

    def unpost(self):
        if self._submenu_open is not None:
            self._submenu_open.unpost()
            self._submenu_open = None
        if self._posted:
            try:
                tk.Toplevel.grab_release(self)
            except Exception:
                pass
            self.withdraw()
            self._posted = False

    # ── tk.Menu API-compatibility shims for existing call sites ────────
    def tk_popup(self, x, y):
        self.popup(x, y)

    def grab_release(self):
        """No-op when called from the outside. Unlike tk.Menu, this class
        manages its own grab lifecycle explicitly via popup()/unpost();
        the standard `try: tk_popup(); finally: grab_release()` idiom
        used everywhere in this codebase for NATIVE tk.Menu (a quirk of
        Tk's own internal menu grab handling) would otherwise immediately
        kill the click-outside-dismiss grab popup() just set up, since
        tk_popup()/popup() both return immediately without waiting for
        the menu to actually be dismissed. The real release happens only
        in unpost(), triggered by an actual dismiss event."""
        pass


class TkMenuBar(tk.Frame):
    """Replacement for the native root.config(menu=...) menu bar, built
    from ordinary Tk widgets so its dropdowns are TkPopupMenu instances
    (real, WM-managed Toplevels) rather than tk.Menu's native popups.

    v22ze-56: see TkPopupMenu's docstring for the full story — this is
    the other half of the same fix, replacing the menu BAR itself (not
    just its dropdowns) so the whole File/Edit/View/Setup/Song Settings
    row no longer depends on root.config(menu=...) or tk.Menu at all.
    Pack this at the top of the main window in place of the old
    mb=tk.Menu(self.root); self.root.config(menu=mb) call — everything
    else (add_cascade with a TkPopupMenu) stays the same shape.
    """

    _BG = "#3c3c3c"
    _FG = "#eeeeee"
    _HOVER = "#3d6fa5"

    def __init__(self, master, **kw):
        super().__init__(master, bg=self._BG, **kw)
        self._open_menu = None

    def add_cascade(self, label="", menu=None, **kw):
        menu._parent_menu = None
        lbl = tk.Label(
            self,
            text=label,
            bg=self._BG,
            fg=self._FG,
            padx=10,
            pady=4,
            font=("TkDefaultFont", 10),
        )
        lbl.pack(side="left")
        lbl.bind("<Enter>", lambda e: lbl.configure(bg=self._HOVER))
        lbl.bind(
            "<Leave>",
            lambda e: lbl.configure(bg=self._HOVER if self._open_menu is menu else self._BG),
        )
        lbl.bind("<ButtonRelease-1>", lambda e: self._toggle(menu, lbl))

    def _toggle(self, menu, lbl):
        if self._open_menu is menu:
            menu.unpost()
            self._open_menu = None
            lbl.configure(bg=self._BG)
            return
        if self._open_menu is not None:
            self._open_menu.unpost()
        x = lbl.winfo_rootx()
        y = lbl.winfo_rooty() + lbl.winfo_height()
        menu.popup(x, y)
        self._open_menu = menu
        lbl.configure(bg=self._HOVER)

        # Reset this label's highlight once the menu actually closes,
        # regardless of how it was dismissed (command run, click-away,
        # Escape, or the v22ze-55 FocusOut safety net).
        def _watch_close():
            if not menu._posted:
                lbl.configure(bg=self._BG)
                if self._open_menu is menu:
                    self._open_menu = None
            else:
                self.after(150, _watch_close)

        self.after(150, _watch_close)


def _make_scrollable(toplevel, bg="#0d1117"):
    """Wrap a Toplevel's content area in a Canvas + vertical Scrollbar,
    and return the inner Frame to build content into (in place of the
    Toplevel itself).

    v22ze-57: user-requested general policy — any window that can be
    resized smaller than its content needs a way to reach whatever gets
    clipped, rather than leaving it invisible with no way back to it.
    Plain Tk frames don't scroll on their own; Canvas + Scrollbar is the
    standard recipe for adding that. The returned inner frame's width is
    kept matched to the canvas's width (so widgets using fill=X still
    expand edge-to-edge), and only vertical space scrolls — these
    dialogs are forms that grow tall, not wide. Mouse-wheel scrolling is
    bound to the dialog's own Toplevel (not globally via bind_all), so
    it works anywhere inside this window without leaking into others.
    """
    outer = tk.Frame(toplevel, bg=bg)
    outer.pack(fill="both", expand=True)
    canvas = tk.Canvas(outer, bg=bg, highlightthickness=0)
    vbar = tk.Scrollbar(outer, orient="vertical", command=canvas.yview)
    canvas.configure(yscrollcommand=vbar.set)
    canvas.pack(side="left", fill="both", expand=True)
    vbar.pack(side="right", fill="y")

    inner = tk.Frame(canvas, bg=bg)
    inner_id = canvas.create_window((0, 0), window=inner, anchor="nw")

    def _on_inner_configure(event=None):
        canvas.configure(scrollregion=canvas.bbox("all"))

    inner.bind("<Configure>", _on_inner_configure)

    def _on_canvas_configure(event):
        canvas.itemconfig(inner_id, width=event.width)

    canvas.bind("<Configure>", _on_canvas_configure)

    def _on_mousewheel(event):
        if event.num == 4:
            canvas.yview_scroll(-1, "units")
        elif event.num == 5:
            canvas.yview_scroll(1, "units")
        elif event.delta:
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    toplevel.bind("<Button-4>", _on_mousewheel, add="+")
    toplevel.bind("<Button-5>", _on_mousewheel, add="+")
    toplevel.bind("<MouseWheel>", _on_mousewheel, add="+")

    return inner


def _backfill_musicxml_staff_tags(xml_doc):
    """Explicitly stamp <staff> on every note in an ly.musicxml document,
    instead of relying on the implicit "inherit from the chord's first
    note" rule the MusicXML DTD allows for chord-continuation notes --
    and correct <staff> element ordering wherever it's misplaced, even
    on notes that already had one.

    v22ze-72: confirmed directly against a real, dense piece that
    python-ly's writer omits <staff> on every chord-continuation note --
    valid per the DTD, but for that file, MORE THAN HALF of all notes
    were chord continuations, and every one of them was missing its
    <staff> tag. A note with no <staff> element defaults to staff 1 per
    the MusicXML spec, so a reader that doesn't correctly walk back to
    the chord's first note for inheritance (as apparently happened here)
    piles the vast majority of a dense, chord-heavy piece onto the top
    staff -- exactly "no hand separation, everything crammed into the
    upper staff." Removing the reliance on inheritance entirely, by
    filling in the correct value explicitly everywhere, sidesteps the
    question of whose fault the inheritance failure is and just makes
    the file unambiguous for any reader.

    Also fixes a SEPARATE, independent python-ly quirk found while
    testing this: on notes carrying an articulation, its writer emits
    <staff> AFTER <notations> -- confirmed present even on notes it
    generated itself, unrelated to the backfill above -- which is
    invalid ordering per the MusicXML DTD (<staff> must precede
    <beam>/<notations>/<lyric>). Every note's <staff> position is
    verified and corrected here, not just ones this function adds.
    """
    import xml.etree.ElementTree as ET

    root = xml_doc.tree.getroot()
    for part in root.findall("part"):
        for measure in part.findall("measure"):
            notes = measure.findall("note")

            # v22ze-73 fix: this used to fill missing <staff> with a
            # single forward pass ("last explicit value seen so far,
            # across ALL voices") -- but confirmed directly against a
            # real file that python-ly sometimes writes a chord's
            # continuation notes (chord=True) BEFORE the anchor note
            # that actually carries the <staff> tag, reversed from the
            # usual order. When that anchor is also the FIRST note of a
            # brand-new voice in the measure (e.g. right after a
            # <backup>), the forward-only fill had nothing from THIS
            # voice yet to fall back on, so it incorrectly inherited
            # whatever staff the PREVIOUS voice's last note happened to
            # use -- putting bass-staff chord notes on the treble staff.
            # Fix: fill per-voice, forward AND backward, so a missing
            # value at the start of a voice's run correctly picks up an
            # explicit value that appears LATER in that same voice.
            by_voice = {}
            for n in notes:
                voice_el = n.find("voice")
                voice = voice_el.text if voice_el is not None else "1"
                by_voice.setdefault(voice, []).append(n)

            resolved = {}
            for voice, vnotes in by_voice.items():
                last = None
                for n in vnotes:
                    st = n.find("staff")
                    if st is not None:
                        last = st.text
                        resolved[id(n)] = last
                    else:
                        resolved[id(n)] = last  # may be None -- backward pass fixes it
                nxt = None
                for n in reversed(vnotes):
                    if resolved[id(n)] is not None:
                        nxt = resolved[id(n)]
                    elif nxt is not None:
                        resolved[id(n)] = nxt
                for n in vnotes:
                    if resolved[id(n)] is None:
                        resolved[id(n)] = "1"  # last-resort: whole voice had no staff at all

            for note in notes:
                val = resolved[id(note)]
                staff_el = note.find("staff")
                if staff_el is None:
                    staff_el = ET.SubElement(note, "staff")
                staff_el.text = val

                # Verify/correct position: <staff> must precede any
                # <beam>/<notations>/<lyric> already present.
                children = list(note)
                cur_idx = children.index(staff_el)
                insert_at = None
                for i, ch in enumerate(children):
                    if i != cur_idx and ch.tag in ("beam", "notations", "lyric"):
                        insert_at = i
                        break
                if insert_at is not None and insert_at < cur_idx:
                    note.remove(staff_el)
                    note.insert(insert_at, staff_el)


def _strip_ly_block(text, keyword):
    """Remove every top-level `\\keyword { ... }` block from LilyPond text,
    correctly handling nested braces (a plain regex can't, since LilyPond
    blocks like \\layout routinely nest \\context { ... } inside
    themselves). Returns the text with all matching blocks removed.

    v22ze-70: used to strip \\layout { } before feeding our .ly text to
    python-ly's MusicXML writer -- confirmed by direct testing that its
    parser doesn't understand LilyPond's \\layout \\context property-
    override syntax (surfaces as "LayoutContext not implemented"
    warnings), and rather than skipping the unrecognized construct
    cleanly, it leaked the literal property name (e.g.
    "barNumberVisibility") into the output as a bogus, non-standard XML
    tag inside <identification> -- which is exactly the kind of thing a
    strict validator (MuseScore's importer, in this case) flags a file
    as "corrupted" over. \\layout is a pure print-formatting concern
    that MusicXML doesn't need anyway -- the receiving notation software
    applies its own layout -- so removing it entirely is not a
    compromise, just scope any MusicXML export never needed in the
    first place.
    """
    out = []
    i = 0
    marker = "\\" + keyword
    while True:
        j = text.find(marker, i)
        if j == -1:
            out.append(text[i:])
            break
        out.append(text[i:j])
        brace = text.find("{", j)
        if brace == -1:
            out.append(text[j:])
            break
        depth = 1
        k = brace + 1
        while k < len(text) and depth > 0:
            if text[k] == "{":
                depth += 1
            elif text[k] == "}":
                depth -= 1
            k += 1
        i = k  # resume scanning right after the matched block's closing brace
    return "".join(out)


def _popup_menu_safe(menu, x, y):
    """Post a context menu, and arm a safety net that force-unposts it if
    the window loses focus while it's still open — e.g. switching virtual
    desktops, which normally fires a FocusOut on X11.

    v22ze-55 fix: Tk's context-menu popups (and, separately, the native
    menu-bar dropdowns built via root.config(menu=...) — see _build_menu)
    are implemented on X11 as override-redirect windows. That's the same
    mechanism the splash screen used to use before this fix (see
    SplashScreen.__init__): override-redirect windows are explicitly NOT
    managed by the window manager, including for virtual-desktop tracking,
    which is exactly why a menu left open while switching desktops could
    get stuck showing on the desktop it was opened on — and, per the
    original bug report, be un-dismissable except by clicking through it
    and accidentally triggering whatever command happened to be under the
    cursor. There's no way to make Tk's native popups WM-managed without
    replacing the whole menu system, so this is a safety net rather than a
    complete fix: a FocusOut on the menu's own toplevel forces it closed
    instead of leaving it stranded. One handler is installed per toplevel
    (guarded so repeated right-clicks don't pile up duplicate bindings);
    it always references whichever menu was posted most recently.
    v22ze-55.1 fix: menu.winfo_toplevel() returns the MENU ITSELF, not
    the real application window it logically belongs to — Tk menus are
    their own top-level-ish objects in the widget naming hierarchy
    (that's part of how they can be posted anywhere on screen). Walking
    up via menu.master.winfo_toplevel() instead correctly reaches the
    real Toplevel/root the menu was constructed under.
    v22ze-56: if menu is a TkPopupMenu (see above), it manages its own
    grab/dismiss lifecycle internally — click-outside detection depends
    on the grab staying active while posted, so this function must NOT
    force an immediate grab_release() the way it does for a native
    tk.Menu below. Kept for any remaining native tk.Menu call sites.
    """
    if isinstance(menu, TkPopupMenu):
        menu.tk_popup(x, y)
        return
    top = menu.master.winfo_toplevel()
    top._pending_popup_menu = menu
    if not getattr(top, "_focusout_menu_guard_installed", False):

        def _unpost_stuck_menu(event=None, _top=top):
            m = getattr(_top, "_pending_popup_menu", None)
            if m is not None:
                try:
                    m.unpost()
                except Exception:
                    pass

        top.bind("<FocusOut>", _unpost_stuck_menu, add="+")
        top._focusout_menu_guard_installed = True
    try:
        menu.tk_popup(x, y)
    finally:
        menu.grab_release()


def key_implied_accidental(letter_idx, key_str):
    """What accidental (+1/-1/0) does this song's key signature already
    imply for a given diatonic letter (0=C..6=B), independent of octave?
    Used so courtesy-accidental suppression doesn't show a sharp/flat
    that the key signature already covers for the whole piece -- e.g. a
    plain B in a piece keyed to 2 flats (Bb, Eb) needs no flat symbol at
    all, since the key signature already implies it everywhere."""
    n_sharps, n_flats = key_sig_accidentals(key_str)
    if n_sharps > 0:
        return 1 if letter_idx in _SHARP_ORDER_LETTERS[:n_sharps] else 0
    if n_flats > 0:
        return -1 if letter_idx in _FLAT_ORDER_LETTERS[:n_flats] else 0
    return 0


# ── Key-signature auto-detection (Krumhansl-Schmuckler) ─────────────────────
# Classic tonal-hierarchy profiles from key-finding research (Krumhansl &
# Kessler 1982): how strongly each of the 12 pitch classes, relative to a
# tonic, is perceived to "belong" to a major vs. minor key. Detecting a key
# is inherently a best-guess/heuristic problem -- chromatic passages,
# modulation within a piece, and non-tonal music can all fool it -- so this
# is offered as a SUGGESTED starting point for the user to confirm or
# override, never as a silent, unreviewable decision.
_KS_MAJOR_PROFILE = [
    6.35,
    2.23,
    3.48,
    2.33,
    4.38,
    4.09,
    2.52,
    5.19,
    2.39,
    3.66,
    2.29,
    2.88,
]
_KS_MINOR_PROFILE = [
    6.33,
    2.68,
    3.52,
    5.38,
    2.60,
    3.53,
    2.54,
    4.75,
    3.98,
    2.69,
    3.34,
    3.17,
]

# MIDI key_signature strings for each of the 12 possible tonics, major/minor
# ChatGPT patch: notation-only quantization settings
NOTATION_DIVISION = 4  # 1=quarter,2=eighth,4=sixteenth,8=thirty-second
                       # Default: sixteenth-note grid so 1/16 notes display on load.
                       # _draw_inner() calls song.detect_notation_division() to
                       # auto-refine this per-song when rendering.
GRACE_NOISE_TICKS = 60  # legacy fixed value, calibrated at 480 ticks/beat.
                       # DO NOT use this constant directly in new code —
                       # use grace_ticks(tpb) instead, which scales
                       # proportionally so the same MUSICAL duration
                       # (1/8 of a beat = a 32nd-note deviation) is used
                       # as the noise floor regardless of file resolution.


def grace_ticks(tpb):
    """Return the grace-note / onset-snap noise floor, scaled to tpb.

    Fixes a resolution-dependence bug: GRACE_NOISE_TICKS=60 was calibrated
    for 480 ticks/beat files (60/480 = 1/8 of a beat = a 32nd-note
    deviation).  A 960 tpb file has twice the ticks per musical duration,
    so the same raw 60-tick threshold represented HALF the musical
    tolerance — grace notes and onset snapping were stricter on
    higher-resolution files for no musical reason.  This function
    preserves the same musical meaning (1/8 beat) at any resolution.
    """
    return max(1, tpb // 8)


def _winfo_exists(widget) -> bool:
    # Safe winfo_exists() — returns False if the widget has been destroyed.
    try:
        return bool(widget and widget.winfo_exists())
    except Exception:
        return False


def _clear_topmost_safe(widget):
    """Clear a widget's -topmost flag, tolerating the widget having already
    been destroyed by the time a scheduled .after() callback fires."""
    try:
        if widget and widget.winfo_exists():
            widget.attributes("-topmost", False)
    except Exception:
        pass


_KEY_STR_MAJOR = ["C", "Db", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"]
_KEY_STR_MINOR = [
    "Cm",
    "C#m",
    "Dm",
    "Ebm",
    "Em",
    "Fm",
    "F#m",
    "Gm",
    "G#m",
    "Am",
    "Bbm",
    "Bm",
]


def detect_key_signature(notes_or_song):
    """Suggest a key signature from note content via the Krumhansl-
    Schmuckler algorithm: build a duration-weighted pitch-class histogram,
    correlate it against all 24 major/minor tonal profiles (each rotated
    to every possible tonic), and return the MIDI key_signature string
    for the best-correlating (tonic, mode).

    Accepts either a Song (uses all tracks' notes) or a flat list of
    MidiNote-like objects with .pitch and .duration.

    Returns (key_str, confidence) where confidence is the winning
    correlation minus the runner-up's -- a small margin means the piece
    is genuinely ambiguous (or not strongly tonal) and the suggestion
    should be treated as weaker. This is a SUGGESTION for the user to
    confirm, not an authoritative answer -- key-finding from note content
    alone cannot be, in general (a piece that modulates, or leans heavily
    chromatic, can legitimately confuse any such algorithm).
    """
    notes = notes_or_song
    if hasattr(notes_or_song, "tracks"):
        notes = [n for tr in notes_or_song.tracks for n in tr.notes]
    if not notes:
        return ("C", 0.0)

    hist = [0.0] * 12
    for n in notes:
        hist[n.pitch % 12] += max(1, getattr(n, "duration", 1))
    total = sum(hist)
    if total <= 0:
        return ("C", 0.0)
    hist = [h / total for h in hist]

    def correlation(a, b):
        ma, mb = sum(a) / len(a), sum(b) / len(b)
        num = sum((x - ma) * (y - mb) for x, y in zip(a, b))
        da = sum((x - ma) ** 2 for x in a) ** 0.5
        db = sum((y - mb) ** 2 for y in b) ** 0.5
        return num / (da * db) if da > 0 and db > 0 else 0.0

    scores = []  # (correlation, key_str)
    for tonic in range(12):
        maj_profile = _KS_MAJOR_PROFILE[-tonic:] + _KS_MAJOR_PROFILE[:-tonic]
        min_profile = _KS_MINOR_PROFILE[-tonic:] + _KS_MINOR_PROFILE[:-tonic]
        scores.append((correlation(hist, maj_profile), _KEY_STR_MAJOR[tonic]))
        scores.append((correlation(hist, min_profile), _KEY_STR_MINOR[tonic]))

    scores.sort(key=lambda x: -x[0])
    best_score, best_key = scores[0]
    runner_up_score = scores[1][0]
    return (best_key, best_score - runner_up_score)


# Chromatic semitone → diatonic step and accidental, SHARP spelling
# (chromatic note grouped with the natural note BELOW it, raised)
_DIA_SHARP = [0, 0, 1, 1, 2, 3, 3, 4, 4, 5, 5, 6]
_ACC_SHARP = [0, 1, 0, 1, 0, 0, 1, 0, 1, 0, 1, 0]
# Chromatic semitone → diatonic step and accidental, FLAT spelling
# (chromatic note grouped with the natural note ABOVE it, lowered)
_DIA_FLAT = [0, 1, 1, 2, 2, 3, 4, 4, 5, 5, 6, 6]
_ACC_FLAT = [0, -1, 0, -1, 0, 0, -1, 0, -1, 0, -1, 0]
# Back-compat aliases (old names, sharp-only) -- kept in case anything
# else in the file references them directly by name.
_DIA = _DIA_SHARP
_ACC = _ACC_SHARP


def note_name(p):
    return f"{NOTE_NAMES[p%12]}{p//12-1}"


def _rotated_ellipse_points(cx, cy, h_rad, v_rad, angle_deg=30, n=16):
    """Return a flat [x0,y0,x1,y1,...] point list approximating an
    ellipse centered at (cx,cy), rotated by angle_deg from horizontal,
    for use with canvas create_polygon(..., smooth=True).

    tkinter's create_oval only draws axis-aligned ellipses; real
    engraved noteheads are calligraphic ovals whose long axis tilts up
    from left to right (~20-30 degrees), not perfectly horizontal.
    Canvas Y increases downward, so angle_deg is negated internally --
    a positive angle_deg here produces a shape that slopes UP going
    left to right on screen, matching that convention, not down.
    """
    theta = math.radians(-angle_deg)
    cos_t, sin_t = math.cos(theta), math.sin(theta)
    pts = []
    for i in range(n):
        a = 2 * math.pi * i / n
        ex, ey = h_rad * math.cos(a), v_rad * math.sin(a)
        pts.append(cx + ex * cos_t - ey * sin_t)
        pts.append(cy + ex * sin_t + ey * cos_t)
    return pts


def _draw_notehead(c, cx, cy, h_rad, v_rad, outline, fill, width=1, angle_deg=30):
    """Draw a single calligraphic (rotated-ellipse) notehead.
    fill="" draws an open/hollow notehead -- since this is a polygon
    with no fill, anything already drawn underneath (a staff line, most
    notably) shows through the interior, exactly like a real engraved
    half/whole note sitting on a staff line."""
    pts = _rotated_ellipse_points(cx, cy, h_rad, v_rad, angle_deg)
    return c.create_polygon(*pts, outline=outline, fill=fill, width=width, smooth=True)


def pitch_to_staff(pitch, use_flats=False):
    """Return (diatonic_pos_rel_C4, accidental).
    C4(MIDI 60) = 0; each unit = one staff step (line or space).
    accidental: +1 = sharp, -1 = flat, 0 = natural.

    v22ze fix: this used to always spell chromatically-altered notes as
    sharps (accidental was only ever 0 or 1), regardless of the piece's
    actual key -- so a piece in a flat key (e.g. G minor, 2 flats) had
    every Bb/Eb drawn on-screen as A#/D#. Confirmed as a real, separate
    bug from to_ly()'s equivalent (pitch_ly, already fixed) -- both were
    independently hardcoded to sharps-only, so the exported LilyPond and
    the on-screen score could show different letter names for the exact
    same MIDI pitch. use_flats defaults to False so any caller that
    doesn't pass it explicitly keeps the old (sharp) behavior -- this is
    the risk-reducing default the earlier session note referred to.
    """
    oct_, semi = divmod(int(round(pitch)), 12)  # ensure int — float pitch crashes table lookups
    dia, acc = (_DIA_FLAT, _ACC_FLAT) if use_flats else (_DIA_SHARP, _ACC_SHARP)
    return oct_ * 7 + dia[semi] - 35, acc[semi]  # C4=octave5*7+0=35


_SPELL_ACC_DELTA = {
    "double_flat": -2,
    "flat": -1,
    "natural": 0,
    "sharp": 1,
    "double_sharp": 2,
}


def note_staff_pos(note, use_flats=False):
    """Like pitch_to_staff(note.pitch, use_flats), but honors an explicit
    per-note spelling override (note.spelling) if the Accidental tool has
    set one (v22ze-51). Falls back to the ordinary key-based spelling
    exactly like before for any note that's never had an accidental
    explicitly applied (the default, empty spelling), so this is a pure
    additive change -- nothing that never touches the Accidental tool
    renders any differently than it did previously.

    The override works by finding this exact accidental's "natural
    pitch" (the pitch of the same letter with no accidental) and asking
    pitch_to_staff for THAT pitch's position -- natural pitches are
    unambiguous (both the sharp and flat spelling tables agree on every
    white-key letter), so this always lands on a real, valid line/space.
    """
    spelling = getattr(note, "spelling", "") or ""
    acc = _SPELL_ACC_DELTA.get(spelling)
    if acc is not None:
        natural_pitch = note.pitch - acc
        nat_pos, nat_acc = pitch_to_staff(natural_pitch, use_flats)
        if nat_acc == 0:  # sanity check -- should always hold
            return nat_pos, acc
    return pitch_to_staff(note.pitch, use_flats)


def _song_uses_flats(song):
    """True if `song`'s key signature should be spelled with flats.
    Convenience wrapper around key_sig_accidentals() for ScoreView call
    sites -- returns False (sharps, the historical default) for pieces
    with no key signature set."""
    if song is None:
        return False
    _n_sharps, n_flats = key_sig_accidentals(getattr(song, "key_sig", "C") or "C")
    return n_flats > 0


# ─────────────────────────────────────────────────────────────────────────────
# Data model
# ─────────────────────────────────────────────────────────────────────────────


def _find_split_pitch_for_track(notes, prefer_lh_octaves=True):
    """Find the best treble/bass split point for a piano track: one
    global split for the WHOLE set of notes given (not per-chord).
    Looks for the largest gap between adjacent pitches; falls back to
    MIDI 60 (C4) if there are < 2 distinct pitches.

    v22ze-27 (housekeeping item 8): this used to exist twice -- once
    nested inside Song.to_ly() (whole-piece split) and once as
    ScoreView._find_gap_split() (a DIFFERENT algorithm, recomputed
    fresh per individual chord). Two independent implementations of
    "find the hand split" inevitably drift, and per-chord vs whole-
    piece splitting is a structurally different result even before any
    drift -- that's why the on-screen raw view and the Lilypond export
    could visibly disagree for un-rationalized data. Hoisted here so
    both call sites use the exact same function on the exact same
    data, and agree by construction.
    """
    if not notes:
        return 60
    pitches = sorted(set(n.pitch for n in notes))
    if len(pitches) < 2:
        return 60
    # Find the largest gap between consecutive pitches
    best_gap = 0
    split = 60
    for i in range(len(pitches) - 1):
        gap = pitches[i + 1] - pitches[i]
        if gap > best_gap:
            best_gap = gap
            # Split point = just above the lower pitch of the gap
            split = pitches[i] + 1
    # Clamp to a musically reasonable range (E3-E5)
    split = max(52, min(76, split))

    # v22ze-20: left-hand-octave preference (housekeeping item 4).
    # Concert pianists generally prefer offloading extra work to
    # whichever hand is less busy rather than splitting an octave
    # doubling across both hands -- a lower-register octave is
    # idiomatically played entirely in the LH, not torn so the upper
    # note lands in the RH just because it's above the split point.
    # This is a preference, not a hard rule, so it's a Song-level
    # option (default on, matching how most composers actually notate
    # this) rather than forced. Detect simultaneous note pairs exactly
    # an octave (12 semitones) apart where the lower note falls in the
    # LH and the upper note would currently land in the RH, and nudge
    # the split boundary up just far enough to pull the whole pair
    # into the LH -- within the same clamp range used above, so this
    # shifts the heuristic's result rather than overriding it.
    if prefer_lh_octaves:
        by_tick = {}
        for n in notes:
            by_tick.setdefault(n.tick, set()).add(n.pitch)
        highest_needed = split
        for tick, pset in by_tick.items():
            for p in pset:
                if p + 12 in pset:  # simultaneous octave pair
                    lower, upper = p, p + 12
                    if lower < split <= upper:
                        highest_needed = max(highest_needed, upper + 1)
        split = max(52, min(76, highest_needed))

    return split


class MidiNote:
    __slots__ = (
        "tick",
        "pitch",
        "velocity",
        "duration",
        "channel",
        "articulation",
        "spelling",
    )

    def __init__(self, tick, pitch, velocity, duration, channel=0, articulation="", spelling=""):
        self.tick = tick
        self.pitch = pitch
        self.velocity = velocity
        self.duration = duration
        self.channel = channel
        self.articulation = articulation
        # v22ze-51 fix: explicit accidental spelling override, set only
        # when the user picks an accidental via the Accidental tool (see
        # ScoreView._click_accidental). Empty string (the default) means
        # "no explicit choice yet -- derive the spelling from the song's
        # key signature", exactly the old behaviour, so every note that's
        # never been touched by the tool renders identically to before.
        # This is what note_staff_pos() (near pitch_to_staff, below)
        # checks first. Without this, the ONLY place a note's spelling
        # could live was the key signature + raw pitch -- so clicking
        # "sharp" on a note already shown as a flat had to recompute the
        # diatonic letter from scratch using the global key convention,
        # which frequently picked a DIFFERENT letter than the one on
        # screen (the notehead visibly "jumped" to a different line/
        # space, changing the pitch by more than a semitone even though
        # the user only asked for a different accidental symbol).
        self.spelling = spelling


class MidiEvent:
    __slots__ = ("tick", "msg")

    def __init__(self, tick, msg):
        self.tick = tick
        self.msg = msg


class Track:
    """One MIDI track: notes, raw events, and display properties.

    staff_mode controls how ScoreView renders this track:
      "auto"   -- use program number to decide (piano/organ -> grand staff,
                  everything else -> single staff).  Default; preserves
                  existing behaviour for tracks loaded from MIDI files.
      "grand"  -- always render as grand staff (treble + bass), regardless
                  of GM program.  Set when the user explicitly chooses
                  "Keyboard / Grand staff" when arming a recording track.
      "single" -- always render as single staff (treble clef by default).
                  Set when the user chooses "Single-line instrument" when
                  arming a recording track (guitar, violin, flute, etc.).
    """

    def __init__(self, name="Track", channel=0, program=0, volume=100):
        self.name = name
        self.channel = channel
        self.program = program
        self.volume = volume
        self.mute = False
        self.solo = False
        self.staff_mode = "auto"  # "auto" | "grand" | "single"
        self.notes: list[MidiNote] = []
        self.events: list[MidiEvent] = []
        # v22ze-35: notation-only annotations (currently: dynamics
        # markings) that are NOT real MIDI messages -- kept separate from
        # self.events, which has an established invariant elsewhere in
        # the app that every entry's .msg is a real mido-shaped message
        # (control_change, program_change, etc.). Reusing that list for
        # tuple-based markers broke every consumer that assumes .msg.type
        # exists; a dedicated list avoids touching all of them.
        self.markings: list[MidiEvent] = []
        # v22v: when True, this track is always shown in the track list and
        # mixer regardless of note count.  Set by Song.add_track() so a
        # freshly created blank track (waiting to be recorded into) is
        # never hidden by the empty-track filter — that filter is meant
        # only for a loaded file's leftover meta/tempo-only tracks, which
        # default to always_show=False.
        self.always_show = False

    def note_count(self):
        return len(self.notes)


def _build_measure_map_core(tpb, sigs, total):
    """Core fixed-grid measure builder, shared by Song.build_measure_map()
    and Song.rationalize()'s content-derived map construction.

    sigs  : sorted list of (tick, num, den) with an entry at tick 0 guaranteed.
    total : tick extent to cover (padded by caller as needed).

    Returns list of (idx, start_tick, end_tick, num, den, tpm).
    """
    first_tpm = max(1, int(tpb * 4 * sigs[0][1] / sigs[0][2]))
    total = max(total, first_tpm * 4)  # pad to at least 4 measures

    measures = []
    m_idx = 0
    tick = 0
    while tick < total:
        num, den = sigs[0][1], sigs[0][2]
        for sig_tick, sig_num, sig_den in sigs:
            if sig_tick <= tick:
                num, den = sig_num, sig_den
            else:
                break
        tpm = max(1, int(tpb * 4 * num / den))
        end_tick = tick + tpm
        measures.append((m_idx, tick, end_tick, num, den, tpm))
        tick = end_tick
        m_idx += 1
    return measures


class Song:
    def __init__(self):
        self.ticks_per_beat = 480
        self.tempo = 500000
        self.time_sig_num = 4
        self.time_sig_den = 4
        self.sig_changes: list[tuple] = []  # [(abs_tick, numerator, denominator), ...]
        self.key_sig: str = "C"  # e.g. "C", "Bb", "F#", "Gm" — from MIDI key_signature meta
        self.tracks: list[Track] = []
        self.filename = None
        self.modified = False
        # Set by Song.rationalize() to a measure map (idx,start,end,num,den,tpm)
        # constructed from actual beat content rather than a fixed external
        # grid.  When present, consumers (bake_to_score, to_ly, ScoreView,
        # Score Setup) should prefer this over build_measure_map().
        self.rationalized_measure_map = None

    @property
    def bpm(self):
        return round(60_000_000 / self.tempo)

    @bpm.setter
    def bpm(self, v):
        self.tempo = int(60_000_000 / max(1, v))

    def ticks_per_measure(self):
        # Correct for all time signatures: tpb is always ticks-per-quarter-note.
        # e.g. 4/4 → tpb*4; 3/4 → tpb*3; 6/8 → tpb*3; 12/8 → tpb*6
        return int(self.ticks_per_beat * 4 * self.time_sig_num / self.time_sig_den)

    def set_time_signature(self, num, den):
        """Set the song's time signature, keeping time_sig_num/den AND
        sig_changes[tick=0] in sync.

        build_measure_map() reads from self.sig_changes (NOT the standalone
        time_sig_num/den fields) whenever an entry already exists at tick 0 —
        which is true for almost every real MIDI file, since they carry an
        explicit time signature meta-event at tick 0.  Before this method
        existed, code that only set self.time_sig_num/den silently had no
        effect on the measure grid, because sig_changes[0] always won.

        This is the SINGLE point of entry for changing the song's time
        signature.  All call sites (Score Setup's Apply button, undo/redo
        restore, MIDI import defaults) must go through this method rather
        than assigning the fields directly.
        """
        self.time_sig_num = num
        self.time_sig_den = den
        self.sig_changes = [(t, n, d) for (t, n, d) in (self.sig_changes or []) if t != 0]
        self.sig_changes.insert(0, (0, num, den))
        self.modified = True

    def build_measure_map(self):
        """Return a list of measure descriptors for the entire song.

        Each entry is a tuple: (idx, start_tick, end_tick, num, den, tpm)
          idx        — zero-based measure index
          start_tick — absolute tick of the measure's downbeat
          end_tick   — absolute tick of the following downbeat (= next measure start)
          num, den   — time signature in effect for this measure
          tpm        — ticks per measure  (= tpb * 4 * num / den)

        Time-signature changes are read from self.sig_changes, which is populated
        during MIDI import.  The list is deduplicated and sorted by tick; a default
        entry at tick 0 is always present so the map never returns empty.

        NOTE: this builds a FIXED grid from the song's declared time signature(s).
        It does not know anything about actual note content.  After
        rationalize() has run, prefer get_measure_map() instead, which returns
        the content-derived map when one is available.
        """
        tpb = self.ticks_per_beat
        raw = list(self.sig_changes) if self.sig_changes else []
        seen: dict[int, tuple] = {}
        for tick, num, den in raw:
            seen[tick] = (num, den)
        if 0 not in seen:
            seen[0] = (self.time_sig_num, self.time_sig_den)
        sigs = sorted((t, n, d) for t, (n, d) in seen.items())
        total = max(self.total_ticks(), 1)
        return _build_measure_map_core(tpb, sigs, total)

    def get_measure_map(self):
        """Return the best available measure map for this song.

        Prefers self.rationalized_measure_map (the content-derived map built
        by rationalize() — see Issue 4 in session_brief_v22h_design.txt)
        when present, since it guarantees every measure contains the correct
        number of beats.  Falls back to build_measure_map() (the fixed
        declared-time-signature grid) otherwise — e.g. for a raw,
        not-yet-rationalized song, or a song loaded fresh from disk.
        """
        if self.rationalized_measure_map:
            return self.rationalized_measure_map
        return self.build_measure_map()

    def tpm_at_tick(self, tick):
        """Return ticks-per-measure for the time signature active at `tick`."""
        for _, start, end, num, den, tpm in self.get_measure_map():
            if start <= tick < end:
                return tpm
        return self.ticks_per_measure()

    def validate_measure_fill(self):
        """Check every measure against its time signature and report discrepancies.

        Returns a list of dicts, one per problematic measure:
          { 'measure': 1-based index,
            'start': start_tick,
            'expected_tpm': tpm,
            'used_ticks': ticks_occupied_by_notes,
            'overflow': bool,   # notes extend past barline
            'underfill': bool,  # notes leave gap before next barline
          }

        A measure with no notes is considered fully underfilled but is only
        flagged if it would otherwise be drawn (i.e., it is not a trailing
        empty measure padding).

        This is a read-only diagnostic — it does not mutate the Song.
        Call rationalize() to actually fix problems.
        """
        import bisect as _bv

        mmap = self.get_measure_map()
        total = self.total_ticks()
        problems = []

        for m_idx, ms, me, num, den, tpm in mmap:
            if ms >= total:
                break  # trailing padding measures — not a problem

            # Find all notes whose onset falls in this measure
            used_end = ms  # furthest tick reached by any note
            has_overflow = False
            for tr in self.tracks:
                for n in tr.notes:
                    if ms <= n.tick < me:
                        note_end = n.tick + n.duration
                        if note_end > me:
                            has_overflow = True
                        used_end = max(used_end, min(note_end, me))

            used = used_end - ms
            underfill = used < tpm
            if has_overflow or underfill:
                problems.append(
                    {
                        "measure": m_idx + 1,
                        "start": ms,
                        "expected_tpm": tpm,
                        "used_ticks": used,
                        "overflow": has_overflow,
                        "underfill": underfill,
                    }
                )

        return problems

    def total_ticks(self):
        mx = self.ticks_per_beat * 4
        for t in self.tracks:
            for n in t.notes:
                mx = max(mx, n.tick + n.duration)
        return mx

    def add_track(self, name=None):
        n = len(self.tracks) + 1
        ch = min(15, len(self.tracks))
        if ch >= 9:
            ch += 1
        ch = ch % 16
        t = Track(name or f"Track {n}", channel=ch)
        t.always_show = True  # v22v: keep visible even before it has notes
        self.tracks.append(t)
        self.modified = True
        return t

    def delete_track(self, idx):
        if 0 <= idx < len(self.tracks):
            self.tracks.pop(idx)
            self.modified = True

    # ── MIDI import ──────────────────────────────────────────────────────────
    @classmethod
    def from_mid(cls, path):
        mid = mido.MidiFile(path)
        song = cls()
        song.filename = path
        song.ticks_per_beat = mid.ticks_per_beat
        song.midi_type = mid.type

        def _close_note(open_n, key, abs_t, notes_list, channel):
            """Close an open note safely; returns True if a note was appended."""
            if key in open_n:
                s, v = open_n.pop(key)
                dur = abs_t - s
                if dur > 0:
                    notes_list.append(MidiNote(s, key[1], v, dur, channel))
                    return True
            return False

        if mid.type == 0 and len(mid.tracks) == 1:
            # Type 0: single track — auto-split by channel
            ch_prog = {}
            abs_t = 0
            for msg in mid.tracks[0]:
                abs_t += msg.time
                if msg.type == "set_tempo":
                    song.tempo = msg.tempo
                elif msg.type == "time_signature":
                    # v22ze-45 fix: this used to overwrite time_sig_num/
                    # den on EVERY time_signature event, so a piece with
                    # real mid-piece meter changes (common in classical
                    # repertoire) ended up with this single "current"
                    # field holding whatever the LAST change in the file
                    # was, not the piece's actual opening meter -- shown
                    # as a seemingly wrong/arbitrary signature in the
                    # rationalize dialog and elsewhere. sig_changes below
                    # still correctly records the full history either
                    # way; only the single "primary" field needs to stay
                    # at the first (opening) value.
                    if not song.sig_changes:
                        song.time_sig_num = msg.numerator
                        song.time_sig_den = msg.denominator
                    song.sig_changes.append((abs_t, msg.numerator, msg.denominator))
                elif msg.type == "key_signature":
                    song.key_sig = msg.key  # e.g. "Bb", "F#", "C"
                elif msg.type == "program_change":
                    ch_prog[msg.channel] = msg.program
            ch_tracks = {}
            open_n = {}
            abs_t = 0
            for msg in mid.tracks[0]:
                abs_t += msg.time
                ch = getattr(msg, "channel", None)
                if ch is None:
                    continue
                if ch not in ch_tracks:
                    prog = ch_prog.get(ch, 0)
                    ch_tracks[ch] = Track(
                        name=f"Ch {ch+1} - {GM_INSTRUMENTS[prog]}",
                        channel=ch,
                        program=prog,
                    )
                if msg.type == "note_on" and msg.velocity > 0:
                    k = (ch, msg.note)
                    # Close any still-open note on this pitch before re-striking
                    _close_note(open_n, k, abs_t, ch_tracks[ch].notes, ch)
                    open_n[k] = (abs_t, msg.velocity)
                elif msg.type in ("note_off",) or (msg.type == "note_on" and msg.velocity == 0):
                    k = (ch, msg.note)
                    _close_note(open_n, k, abs_t, ch_tracks[ch].notes, ch)
                elif msg.type == "control_change":
                    if msg.control == 7:
                        ch_tracks[ch].volume = msg.value
                    ch_tracks[ch].events.append(MidiEvent(abs_t, msg))
            # Flush any unclosed notes (file truncated or missing note-off)
            for (ch, pitch), (s, v) in open_n.items():
                dur = max(1, mid.ticks_per_beat // 2)
                ch_tracks[ch].notes.append(MidiNote(s, pitch, v, dur, ch))
            for ch in sorted(ch_tracks):
                if ch_tracks[ch].notes:
                    song.tracks.append(ch_tracks[ch])
        else:
            for i, mt in enumerate(mid.tracks):
                tr = Track(name=mt.name or f"Track {i+1}")
                abs_t = 0
                open_n = {}
                for msg in mt:
                    abs_t += msg.time
                    if msg.type == "set_tempo":
                        song.tempo = msg.tempo
                        tr.events.append(MidiEvent(abs_t, msg))
                    elif msg.type == "time_signature":
                        # v22ze-45 fix: same issue as the Type-0 loop
                        # above -- only the FIRST time_signature event
                        # should set the "primary" field; sig_changes
                        # still records every change.
                        if not song.sig_changes:
                            song.time_sig_num = msg.numerator
                            song.time_sig_den = msg.denominator
                        song.sig_changes.append((abs_t, msg.numerator, msg.denominator))
                    elif msg.type == "key_signature":
                        song.key_sig = msg.key  # store on song; last one wins
                    elif msg.type == "program_change":
                        tr.program = msg.program
                        tr.channel = msg.channel
                        tr.events.append(MidiEvent(abs_t, msg))
                    elif msg.type == "note_on" and msg.velocity > 0:
                        k = (msg.channel, msg.note)
                        # Re-strike: close previous note first
                        _close_note(open_n, k, abs_t, tr.notes, msg.channel)
                        open_n[k] = (abs_t, msg.velocity)
                        tr.channel = msg.channel
                    elif msg.type in ("note_off",) or (msg.type == "note_on" and msg.velocity == 0):
                        k = (msg.channel, msg.note)
                        _close_note(open_n, k, abs_t, tr.notes, msg.channel)
                    elif msg.type == "control_change":
                        if msg.control == 7:
                            tr.volume = msg.value
                        tr.events.append(MidiEvent(abs_t, msg))
                    else:
                        try:
                            tr.events.append(MidiEvent(abs_t, msg))
                        except:
                            pass
                # Flush unclosed notes
                for (ch, pitch), (s, v) in open_n.items():
                    dur = max(1, mid.ticks_per_beat // 2)
                    tr.notes.append(MidiNote(s, pitch, v, dur, ch))
                if tr.notes or (tr.events and i > 0):
                    song.tracks.append(tr)
        return song

    # ── MIDI export ──────────────────────────────────────────────────────────
    def to_mid(self, path):
        """Write song to a Standard MIDI File.

        Tie-continuation notes (articulation='tie_continuation') are merged
        with their predecessor before writing so the saved file contains one
        sustained note rather than a re-attacked pair.  This makes the MIDI
        match what the score displays.
        """
        import copy as _tmcopy

        mid = mido.MidiFile(ticks_per_beat=self.ticks_per_beat)
        tt = mido.MidiTrack()
        tt.append(mido.MetaMessage("set_tempo", tempo=self.tempo, time=0))
        tt.append(
            mido.MetaMessage(
                "time_signature",
                numerator=self.time_sig_num,
                denominator=self.time_sig_den,
                time=0,
            )
        )
        # v22ze fix: key_sig was never written here at all -- set_tempo and
        # time_signature were, but key_signature wasn't, so self.key_sig
        # (correctly read on load, correctly used by the screen renderer,
        # and now correctly used by to_ly()'s \key fix) got silently
        # dropped every time a file was saved. Reloading a saved file
        # always came back with key_sig='C' (the Song default) regardless
        # of what it actually was beforehand. mido expects the same
        # string format this class already reads back in from_mid()
        # (e.g. "C", "Gm", "F#"), so no conversion is needed here.
        try:
            tt.append(
                mido.MetaMessage("key_signature", key=getattr(self, "key_sig", "C") or "C", time=0)
            )
        except Exception:
            pass  # a key_sig value mido doesn't recognize shouldn't block saving
        # v22ze-45 fix: this used to write exactly ONE time_signature
        # event (the single self.time_sig_num/den field), silently
        # collapsing a piece with genuine mid-piece meter changes
        # (common in classical repertoire) down to one uniform signature
        # throughout, every time it was saved -- self.sig_changes already
        # correctly recorded the full history on load, it just never got
        # written back out. Appended here (after the existing tick-0
        # meta events above) so their time=0 delta positioning isn't
        # disturbed; mido tracks use delta-time, so each additional
        # event's `time` is ticks since the previous message in this
        # track, tracked via _last_sig_tick starting from the tick-0
        # baseline already established above.
        _last_sig_tick = 0
        for _chg_tick, _chg_num, _chg_den in sorted(getattr(self, "sig_changes", [])):
            if _chg_tick <= 0:
                continue  # already covered by the initial tick-0 event above
            tt.append(
                mido.MetaMessage(
                    "time_signature",
                    numerator=_chg_num,
                    denominator=_chg_den,
                    time=_chg_tick - _last_sig_tick,
                )
            )
            _last_sig_tick = _chg_tick
        mid.tracks.append(tt)
        for tr in self.tracks:
            # ── Merge tie-continuation notes ──────────────────────────────────
            # Sort by tick, then for every note whose articulation is
            # 'tie_continuation', extend the most-recent note with the same
            # pitch so the two notes become one seamless sustain.
            sorted_notes = sorted(tr.notes, key=lambda n: n.tick)
            merged: list = []
            # last_of_pitch[pitch] → index into merged[] of the open note
            last_of_pitch: dict = {}
            for n in sorted_notes:
                if getattr(n, "articulation", "") == "tie_continuation":
                    idx = last_of_pitch.get(n.pitch)
                    if idx is not None:
                        # Extend the predecessor to cover this continuation
                        pred = merged[idx]
                        pred.duration = (n.tick + n.duration) - pred.tick
                        # Keep last_of_pitch pointing at the same slot —
                        # further continuations chain onto the now-longer note
                        continue
                    # No predecessor found (shouldn't happen in well-formed data
                    # but be safe): treat as a normal note
                nc = _tmcopy.copy(n)
                last_of_pitch[nc.pitch] = len(merged)
                merged.append(nc)

            mt = mido.MidiTrack()
            mt.name = tr.name
            evs = [
                (
                    0,
                    mido.Message("program_change", channel=tr.channel, program=tr.program, time=0),
                ),
                (
                    0,
                    mido.Message(
                        "control_change",
                        channel=tr.channel,
                        control=7,
                        value=tr.volume,
                        time=0,
                    ),
                ),
            ]
            for n in merged:
                evs.append(
                    (
                        n.tick,
                        mido.Message(
                            "note_on",
                            channel=tr.channel,
                            note=n.pitch,
                            velocity=n.velocity,
                            time=0,
                        ),
                    )
                )
                evs.append(
                    (
                        n.tick + n.duration,
                        mido.Message(
                            "note_off",
                            channel=tr.channel,
                            note=n.pitch,
                            velocity=0,
                            time=0,
                        ),
                    )
                )
            for e in tr.events:
                if e.msg.type not in ("set_tempo", "time_signature", "program_change"):
                    evs.append((e.tick, e.msg))
            evs.sort(key=lambda x: x[0])
            prev = 0
            for tick, msg in evs:
                try:
                    mt.append(msg.copy(time=tick - prev))
                    prev = tick
                except:
                    pass
            mt.append(mido.MetaMessage("end_of_track", time=0))
            mid.tracks.append(mt)
        mid.save(path)
        self.filename = path
        self.modified = False

    # ── MuseScore .mscx export ───────────────────────────────────────────────
    def to_mscx(self, path):
        """Export as MuseScore 4.x compatible .mscx XML.

        Key structural rules learned from real MuseScore files:
        - version="4.60" (match current MuseScore 4)
        - Score > metaTag*, Part+, Staff+ (Staff at Score level, NOT inside Part)
        - Part contains Staff stubs (no measures) + trackName + Instrument
        - Score-level Staff elements carry all the Measure/voice/Chord data
        - Notes at the same tick grouped into one Chord element (polyphony)
        - Duration = durationType string + optional <dots>1</dots>
        - First measure voice starts with KeySig, TimeSig, then Tempo
        - Two Staff per Part for piano (treble + bass); one for other instruments
        - Whole-measure rest uses <durationType>measure</durationType> + <duration>N/D</duration>
        """
        tpb = self.ticks_per_beat
        tpm = self.ticks_per_measure()
        n_meas = max(1, math.ceil(self.total_ticks() / tpm))

        root = ET.Element("museScore", version="4.60")

        # ── programVersion (required by MuseScore 4) ──────────────────────
        ET.SubElement(root, "programVersion").text = "4.4.0"
        ET.SubElement(root, "programRevision").text = "000000"

        score = ET.SubElement(root, "Score")
        ET.SubElement(score, "Division").text = str(tpb)
        ET.SubElement(score, "showInvisible").text = "1"
        ET.SubElement(score, "showUnprintable").text = "1"
        ET.SubElement(score, "showFrames").text = "1"
        ET.SubElement(score, "showMargins").text = "0"

        # metaTags
        for name, val in [
            ("arranger", ""),
            ("composer", ""),
            ("copyright", ""),
            ("lyricist", ""),
            ("originalFormat", "mid"),
            ("platform", "Linux"),
            ("source", ""),
            ("workTitle", ""),
        ]:
            mt = ET.SubElement(score, "metaTag", name=name)
            mt.text = val

        # ── Part definitions (stubs — no measures here) ───────────────────
        staff_id = 1
        track_staff_ids = []  # list of (first_staff_id, n_staves) per track

        for tr in self.tracks:
            is_piano = tr.program < 8 or tr.program in range(16, 24)
            n_staves = 2 if is_piano else 1
            track_staff_ids.append((staff_id, n_staves))

            part = ET.SubElement(score, "Part", id=str(len(track_staff_ids)))

            # Staff stub(s) inside Part
            for si in range(n_staves):
                stub = ET.SubElement(part, "Staff")
                stype = ET.SubElement(stub, "StaffType", group="pitched")
                ET.SubElement(stype, "name").text = "stdNormal"
                if n_staves == 2 and si == 0:
                    ET.SubElement(stub, "bracket", type="1", span="2", col="0", visible="1")
                    ET.SubElement(stub, "barLineSpan").text = "1"
                if n_staves == 2 and si == 1:
                    ET.SubElement(stub, "defaultClef").text = "F"

            ET.SubElement(part, "trackName").text = tr.name

            instr_id = _program_to_instrument_id(tr.program)
            instr = ET.SubElement(part, "Instrument", id=instr_id)
            ET.SubElement(instr, "longName").text = GM_INSTRUMENTS[tr.program]
            ET.SubElement(instr, "shortName").text = GM_INSTRUMENTS[tr.program][:4] + "."
            ET.SubElement(instr, "trackName").text = GM_INSTRUMENTS[tr.program]
            ET.SubElement(instr, "minPitchP").text = "0"
            ET.SubElement(instr, "maxPitchP").text = "127"
            ET.SubElement(instr, "minPitchA").text = "0"
            ET.SubElement(instr, "maxPitchA").text = "127"
            ET.SubElement(instr, "instrumentId").text = instr_id
            if n_staves == 2:
                ET.SubElement(instr, "clef", staff="2").text = "F"
            chan = ET.SubElement(instr, "Channel")
            prog_el = ET.SubElement(chan, "program")
            prog_el.set("value", str(tr.program))
            ET.SubElement(chan, "synti").text = "Fluid"

            staff_id += n_staves

        # ── Score-level Staff elements (carry all measures) ───────────────
        for ti, tr in enumerate(self.tracks):
            first_sid, n_staves = track_staff_ids[ti]
            notes_sorted = sorted(tr.notes, key=lambda n: n.tick)

            print("[RESTSRC]", [(n.tick, n.duration) for n in notes_sorted[:10]])

            for si in range(n_staves):
                sid = first_sid + si
                staff_el = ET.SubElement(score, "Staff", id=str(sid))

                # Split notes: treble (pitch >= 60) → staff 1, bass (pitch < 60) → staff 2
                # For non-piano, all notes go to staff 1
                if n_staves == 2:
                    staff_notes = [
                        n
                        for n in notes_sorted
                        if (si == 0 and n.pitch >= 60) or (si == 1 and n.pitch < 60)
                    ]
                else:
                    staff_notes = notes_sorted

                for m in range(n_meas):
                    ms = m * tpm
                    me = ms + tpm
                    meas_notes = [n for n in staff_notes if ms <= n.tick < me]
                    meas_el = ET.SubElement(staff_el, "Measure")

                    # Build voice 1: group simultaneous notes into Chords
                    voice_el = ET.SubElement(meas_el, "voice")

                    # First measure: add KeySig, TimeSig, Tempo
                    if m == 0 and sid == first_sid:
                        keysig = ET.SubElement(voice_el, "KeySig")
                        ET.SubElement(keysig, "concertKey").text = str(getattr(self, "key_sig", 0))
                        tsig = ET.SubElement(voice_el, "TimeSig")
                        ET.SubElement(tsig, "sigN").text = str(self.time_sig_num)
                        ET.SubElement(tsig, "sigD").text = str(self.time_sig_den)
                        tempo_el = ET.SubElement(voice_el, "Tempo")
                        ET.SubElement(tempo_el, "tempo").text = str(round(self.bpm / 60.0, 6))
                        txt = ET.SubElement(tempo_el, "text")
                        ET.SubElement(txt, "sym").text = "metNoteQuarterUp"
                    elif m == 0:
                        # Other staves still need KeySig and TimeSig in measure 1
                        keysig = ET.SubElement(voice_el, "KeySig")
                        ET.SubElement(keysig, "concertKey").text = "0"
                        tsig = ET.SubElement(voice_el, "TimeSig")
                        ET.SubElement(tsig, "sigN").text = str(self.time_sig_num)
                        ET.SubElement(tsig, "sigD").text = str(self.time_sig_den)

                    if not meas_notes:
                        rest = ET.SubElement(voice_el, "Rest")
                        ET.SubElement(rest, "durationType").text = "measure"
                        ET.SubElement(rest, "duration").text = (
                            f"{self.time_sig_num}/{self.time_sig_den}"
                        )
                        continue

                    # Group notes by tick into chords
                    from itertools import groupby

                    cursor = ms
                    tick_groups = []
                    for tick, grp in groupby(meas_notes, key=lambda n: n.tick):
                        tick_groups.append((tick, list(grp)))

                    for tick, chord_notes in tick_groups:
                        # Rest before this chord
                        gap = tick - cursor
                        if gap > 0:
                            _write_rest_sequence(voice_el, gap, tpb)

                        # All notes at this tick → one Chord element
                        # Duration = the longest note in the chord
                        chord_dur = max(n.duration for n in chord_notes)
                        dtype, dots = _ticks_to_dtype_dots(chord_dur, tpb)
                        chord_el = ET.SubElement(voice_el, "Chord")
                        ET.SubElement(chord_el, "durationType").text = dtype
                        if dots:
                            ET.SubElement(chord_el, "dots").text = str(dots)

                        for note in chord_notes:
                            note_el = ET.SubElement(chord_el, "Note")
                            ET.SubElement(note_el, "pitch").text = str(note.pitch)
                            ET.SubElement(note_el, "tpc").text = str(_midi_to_tpc(note.pitch))
                            ET.SubElement(note_el, "velocity").text = str(note.velocity)

                        cursor = tick + chord_dur

                    # Rest after last chord to end of measure
                    tail = me - cursor
                    if tail > 0:
                        _write_rest_sequence(voice_el, tail, tpb)

        # ── Serialise ─────────────────────────────────────────────────────
        raw = ET.tostring(root, encoding="unicode", xml_declaration=False)
        nice = minidom.parseString('<?xml version="1.0" encoding="UTF-8"?>' + raw).toprettyxml(
            indent="  "
        )
        # minidom adds its own declaration; strip the duplicate
        lines = nice.split("\n")
        if lines[0].startswith("<?xml") and lines[1].startswith("<?xml"):
            lines = lines[1:]
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

    # ── Score Rationalization ────────────────────────────────────────────────
    def rationalize(self, params=None, measure_range=None):
        """Return a NEW Song with rationalized notation.

        The original Song is never modified.  The returned Song has:
          • Corrected tempo (detected from performed note density)
          • Arpeggios collapsed into true simultaneous chords
          • Note onsets quantized to the appropriate grid
          • Short rests eliminated
          • Measures summing correctly to the time signature
          • Notes split between Right Hand / Left Hand tracks via DP

        Parameters
        ----------
        params : dict, optional
            Keys (all optional, defaults shown):
              arpeggio_window   int   60      ticks; notes closer than this → chord
              quantize_div      int   8       grid: 4=quarter 8=eighth 16=16th
              quantize_strength float 0.85    0=none 1=hard snap
              rest_threshold    int   0       remove rests shorter than N ticks
              max_span          int   14      semitones; max comfortable hand span
              max_notes_per_hand int  5       max simultaneous notes one hand can
                                              take (thumb + 4 fingers); a chord
                                              needing more MUST split across hands
                                              regardless of span or clef
              detect_tempo      bool  True    auto-detect performed BPM
              tempo_override    int   None    force a specific BPM (overrides detect)
        measure_range : tuple (first, last), optional
            1-based inclusive measure range to rationalize.
            None = whole song.

        Returns
        -------
        Song  — a new Song object (copy with corrections applied)
        """
        import copy
        import math
        import statistics

        p = {
            "arpeggio_window": None,  # None = auto (≈20 ms in ticks at song tempo)
            "quantize_div": 8,
            "quantize_strength": 0.85,
            "rest_threshold": 0,
            "max_span": 14,
            "max_notes_per_hand": 5,  # v22ze NEW — see _split_cost below
            "detect_tempo": True,
            "tempo_override": None,
            "detect_timesig": True,  # NEW v22i — auto-detect time signature
            "timesig_override": None,  # NEW v22i — (num, den) tuple, overrides detection
            "preserve_hands": False,  # NEW v22t — skip DP hand separation, trust
            # the file's own existing RH/LH tracks
            "pedal_voice_limit": 4,  # NEW v22ze-53 — max simultaneous onset
            # EVENTS (chords count as one event, not
            # one per note) a pedal is allowed to
            # keep ringing at once. Models a half/
            # third pedal: once a NEW onset arrives
            # and this many are already sustaining,
            # the OLDEST is damped off right at that
            # new onset, same as a real (or partial)
            # pedal doesn't let an unlimited number
            # of struck notes ring forever. Prevents
            # fast pedaled arpeggios from tying every
            # single note into one barline cluster
            # (see the v22ze-52 fix note above the
            # actual tie-split, which restored ties
            # for genuinely-held pedal notes but
            # reopened exactly this risk for runs).
        }
        if params:
            p.update(params)

        tpb = self.ticks_per_beat

        # ── Resolve arpeggio window ──────────────────────────────────────────
        # Default: ~20 ms in ticks at song tempo.  At 120 BPM/tpb=480 that is
        # ≈19 ticks — far tighter than the old fixed 60, so fast melodic runs
        # (16th notes at 108 BPM ≈ 111 ticks apart) are no longer collapsed.
        if p["arpeggio_window"] is None:
            _tempo_us = self.tempo if self.tempo > 0 else 500_000
            _ms_per_tick = _tempo_us / (tpb * 1000.0)
            p["arpeggio_window"] = max(1, int(20.0 / _ms_per_tick))
        # ── 0. Collect all notes, tagged with source track ───────────────────
        # We keep a PARALLEL list src_track_ids (same length and order as
        # all_notes) instead of setting attributes on MidiNote.  MidiNote uses
        # __slots__ which forbids dynamic attributes, and touching __slots__
        # causes stale-bytecode surprises.  A parallel list is simpler and safe.
        all_notes = []
        src_track_ids = []
        for tr_idx, tr in enumerate(self.tracks):
            for n in tr.notes:
                all_notes.append(copy.copy(n))
                src_track_ids.append(tr_idx)
        # Sort both lists together by tick
        paired = sorted(zip(all_notes, src_track_ids), key=lambda x: x[0].tick)
        if not paired:
            return copy.deepcopy(self)
        all_notes, src_track_ids = zip(*paired)
        all_notes = list(all_notes)
        src_track_ids = list(src_track_ids)

        # ── 0.1. Preserve-hands tagging ────────────────────────────────────
        # If the user has asked to preserve the file's existing hand
        # separation (v22t), tag every note's channel slot with 0 (RH) or
        # 1 (LH) based on which ORIGINAL track it came from.  This tag
        # survives every copy.copy() downstream (channel is a real __slots__
        # field) and lets step 8 skip the DP beam search entirely, trusting
        # the file's own separation instead of re-deriving it from a merged
        # pool.  This avoids the "rationalized sounds nothing like the raw"
        # problem on files that were already carefully hand-separated —
        # re-running DP on already-correct data can reassign individual
        # notes in fast interleaved passages where the DP's heuristics
        # disagree with the file's ground truth.
        _preserve_hands = bool(p.get("preserve_hands", False))
        if _preserve_hands:
            _hand_info = self.detect_separated_hands()
            if _hand_info["separated"]:
                _rh_idx = _hand_info["rh_track_idx"]
                _lh_idx = _hand_info["lh_track_idx"]
                for _n, _src in zip(all_notes, src_track_ids):
                    _n.channel = 0 if _src == _rh_idx else 1
                print(
                    f"[rationalize] Preserve-hands: RH=track{_rh_idx} "
                    f"({_hand_info['rh_notes']} notes), "
                    f"LH=track{_lh_idx} ({_hand_info['lh_notes']} notes)",
                    file=sys.stderr,
                )
            else:
                _preserve_hands = False  # fall back — couldn't detect 2 hands
                print(
                    "[rationalize] Preserve-hands requested but file does "
                    "not have exactly 2 note-bearing tracks — falling back "
                    "to automatic hand separation.",
                    file=sys.stderr,
                )
        if not all_notes:
            return copy.deepcopy(self)

        # ── 0.5. Pedal-aware duration correction ─────────────────────────────
        # Rule (per Michael F. Winthrop):
        #   A note's written duration = time from its onset to the next onset
        #   of the SAME pitch — whether re-struck or simply the harmonic
        #   boundary where it would become a faded harmony.  The sustain
        #   pedal release is the outer bound (harmonic clearance).
        #
        # This transforms piano early-release artefacts (16th/32nd MIDI
        # durations) into musically correct quarter/dotted-quarter/half
        # note values before any grid quantization runs.
        #
        # CC64 events are already stored in track.events by the MIDI loader.
        import bisect as _bisect
        from collections import defaultdict as _dd

        def _build_pedal_segs(tracks, threshold=64):
            cc64 = []
            for tr in tracks:
                for ev in tr.events:
                    if (
                        hasattr(ev, "msg")
                        and ev.msg.type == "control_change"
                        and ev.msg.control == 64
                    ):
                        cc64.append((ev.tick, ev.msg.value))
            cc64.sort()
            segs, ped_on = [], None
            for tick, val in cc64:
                if val >= threshold and ped_on is None:
                    ped_on = tick
                elif val < threshold and ped_on is not None:
                    segs.append((ped_on, tick))
                    ped_on = None
            if ped_on is not None and cc64:
                segs.append((ped_on, cc64[-1][0]))
            return segs

        def _pedal_duration_correct(notes, pedal_segs, voice_limit=4):
            """Extend note durations to next same-pitch onset or pedal release.

            v22r fix: marks extended notes via n.articulation = 'pedal_extended'
            — a real __slots__ field — rather than tracking by Python id() as
            v22q did.  id() of a copy.copy()'d note always differs from id()
            of the original, so the v22q id()-based set silently stopped
            matching the moment quantization (step 5) copied every note.
            Pass A's "if id(n) in pedal_extended_ids" check therefore always
            evaluated False, ties were created anyway, and the barline
            chord-cluster bug reappeared even though the code looked correct.
            articulation survives copy.copy() because copy.copy() duplicates
            attribute VALUES, and 'pedal_extended' is a value, not an identity.

            v22ze-53: after v22ze-52 restored ties for genuinely pedal-held
            notes (standard engraving shows both a tie AND a pedal mark for
            a note that's actually held down), a fast pedaled ARPEGGIO
            crossing a barline started tying every single note in the run
            into one solid chord-cluster — every note got extended to
            nearly the same pedal-release tick, so every one of them
            "crossed the barline" together. A held pedal doesn't really let
            every struck note ring at full strength forever; with a half or
            third pedal (or just piano physics), earlier notes decay and
            blur out as new ones are added. Model that with a second pass
            below: within one pedal segment, only the most recent
            `voice_limit` onset EVENTS (a simultaneous chord counts as ONE
            event, not one slot per note — a real chord isn't "stolen" from
            itself) may be actively ringing at once. When a new onset
            arrives and that many are already ringing, the OLDEST event is
            damped off right at the new onset — same as physically
            releasing/re-pedaling. This only trims notes that were pedal-
            extended in the first place; a note whose own written duration
            already reached that far needs no help from the pedal and is
            untouched.
            """
            pitch_idx = _dd(list)
            for n in notes:
                pitch_idx[n.pitch].append(n.tick)
            ped_ons = [s[0] for s in pedal_segs]
            ped_offs = [s[1] for s in pedal_segs]
            for n in notes:
                if getattr(n, "articulation", "") == "staccato":
                    continue
                tick = n.tick
                onsets = pitch_idx[n.pitch]
                idx = _bisect.bisect_right(onsets, tick)
                nsp = onsets[idx] if idx < len(onsets) else None
                npd = None
                seg_idx = _bisect.bisect_right(ped_ons, tick) - 1
                if 0 <= seg_idx < len(pedal_segs):
                    on, off = pedal_segs[seg_idx]
                    if on <= tick < off:
                        npd = off
                if npd is None and seg_idx + 1 < len(pedal_segs):
                    npd = pedal_segs[seg_idx + 1][0]
                _decay_ticks = int(tpb * (2.0 + (n.velocity / 127.0) * 4.0))
                bounds = [b for b in (nsp, npd) if b is not None]
                if bounds:
                    new_dur = max(n.duration, min(bounds) - tick)
                else:
                    new_dur = max(n.duration, _decay_ticks)
                if new_dur > n.duration and n.articulation == "":
                    # Mark via the articulation SLOT (not id() or a tuple key).
                    # articulation is a real __slots__ field, so it survives
                    # every copy.copy() made downstream (quantize, Pass A/B) —
                    # unlike id() which changes on every copy, and unlike a
                    # (tick, pitch, channel) tuple key which breaks once
                    # quantization changes tick.  This is the v22r fix for the
                    # barline chord-cluster regression: the v22q id()-based
                    # check silently always failed because Pass A saw a
                    # freshly-copied note with a new id().
                    n.articulation = "pedal_extended"
                    n_extended_count[0] += 1
                n.duration = new_dur

            # ── v22ze-53: second pass — voice-limited decay ────────────────
            # Only touches notes actually marked pedal_extended above; every
            # other note (including a note whose OWN written duration was
            # already long enough) is left exactly as the first pass set it.
            _win = p["arpeggio_window"]
            for seg_on, seg_off in pedal_segs:
                seg_notes = sorted(
                    (
                        n
                        for n in notes
                        if getattr(n, "articulation", "") == "pedal_extended"
                        and seg_on <= n.tick < seg_off
                    ),
                    key=lambda n: n.tick,
                )
                if not seg_notes:
                    continue
                # Cluster into onset events: notes within one arpeggio_window
                # of the event's start tick are "simultaneous" (a chord) and
                # share one ringing slot.
                events = []  # list of (event_tick, [notes])
                for n in seg_notes:
                    if events and n.tick - events[-1][0] <= _win:
                        events[-1][1].append(n)
                    else:
                        events.append((n.tick, [n]))
                ringing = []  # list of (event_tick, [notes]) still sounding
                for ev_tick, ev_notes in events:
                    # Drop anything that already ended naturally by now —
                    # no stealing needed, it wasn't competing for a slot.
                    ringing = [
                        r for r in ringing if max(rn.tick + rn.duration for rn in r[1]) > ev_tick
                    ]
                    if len(ringing) >= voice_limit:
                        oldest_tick, oldest_notes = ringing.pop(0)
                        for on_note in oldest_notes:
                            capped = ev_tick - on_note.tick
                            if capped < on_note.duration:
                                on_note.duration = max(1, capped)
                    ringing.append((ev_tick, ev_notes))

        _pedal_extended_count = 0
        n_extended_count = [0]
        pedal_segs = _build_pedal_segs(self.tracks)
        if pedal_segs:
            _pedal_duration_correct(all_notes, pedal_segs, voice_limit=p["pedal_voice_limit"])
            _pedal_extended_count = n_extended_count[0]
            print(
                f"[rationalize] Pedal correction applied "
                f"({len(pedal_segs)} segments, {_pedal_extended_count} notes extended)",
                file=sys.stderr,
            )
        else:
            print(
                "[rationalize] No CC64 pedal events — " "skipping pedal duration correction",
                file=sys.stderr,
            )

        # ── 0.55. Grace note detection ───────────────────────────────────────
        # A grace note is a note shorter than 2× the arpeggio window that
        # immediately precedes a longer "main" note within one beat.
        # Grace notes should be marked articulation='grace' rather than
        # suppressed (GRACE_NOISE_TICKS removal) or forced into a dotted value.
        # They will be rendered as small noteheads before the beat and exported
        # as \grace { } in LilyPond — not as standard-duration notes.
        #
        # This distinguishes:
        #   staccato = note IS on the beat, played short by performer choice
        #   grace    = note is BEFORE the beat, played short by definition
        _grace_thresh = p["arpeggio_window"] * 2  # notes shorter than this
        _beat_window = tpb // 2  # must be within half-beat of next
        all_notes_sorted = sorted(all_notes, key=lambda n: n.tick)
        for i, n in enumerate(all_notes_sorted):
            if n.duration >= _grace_thresh:
                continue  # too long to be a grace note
            if getattr(n, "articulation", ""):
                continue  # already marked
            # Look for a longer note within one beat following this note
            for j in range(i + 1, len(all_notes_sorted)):
                m = all_notes_sorted[j]
                gap = m.tick - (n.tick + n.duration)
                if gap > _beat_window:
                    break  # too far ahead — not a grace
                if m.duration >= _grace_thresh and m.pitch != n.pitch:
                    # This short note precedes a longer different-pitch note
                    n.articulation = "grace"
                    break

        # ── 0.6. Staccato detection (AFTER pedal correction) ─────────────────
        # Staccato ratio only makes sense once pedal correction has extended
        # durations to their musically intended length.  On raw MIDI, almost
        # every note looks staccato because pianists release keys early.
        # Threshold 0.38: note held < 38% of IOI = deliberate staccato.
        #
        # v22ze-68 fix: this used to test n.duration/ioi PER NOTE, completely
        # independent of whether other notes were sounding at the same
        # instant as part of the same chord. Ordinary human performance
        # imprecision -- one finger releasing a fraction of a second before
        # the others in the same chord -- was enough to mark JUST that one
        # note staccato while its chord-mates were left alone, rendering as
        # a dot under one particular notehead in a chord rather than the
        # whole chord. bake_to_score()'s own staccato pass downstream
        # already avoids this by using the chord's LONGEST note as the
        # representative duration; group notes the same way here, before
        # any per-note articulation gets set, so the whole pipeline agrees
        # a chord is staccato -- or isn't -- as one decision, not one
        # decision per notehead.
        import bisect as _bisect_stac

        _arp_win = p["arpeggio_window"]
        _all_tick = sorted(n.tick for n in all_notes)
        _stac_groups = []  # [(tick, [notes])], notes within _arp_win of tick
        for _n in sorted(all_notes, key=lambda n: n.tick):
            if _stac_groups and _n.tick - _stac_groups[-1][0] <= _arp_win:
                _stac_groups[-1][1].append(_n)
            else:
                _stac_groups.append((_n.tick, [_n]))
        for _tick, _chord in _stac_groups:
            _chord_live = [n for n in _chord if getattr(n, "articulation", "") != "pedal_extended"]
            if not _chord_live:
                continue  # every note here is pedal-extended -- see below
            _idx = _bisect_stac.bisect_right(_all_tick, _tick)
            _next_mean = next((t for t in _all_tick[_idx:] if t - _tick > _arp_win), None)
            if _next_mean is None:
                continue
            _ioi = _next_mean - _tick
            if _ioi <= 0:
                continue
            # Representative duration = the chord's LONGEST note, matching
            # bake_to_score()'s own chord-level staccato test downstream.
            _rep_dur = max(n.duration for n in _chord_live)
            if _rep_dur / _ioi < 0.38:
                for _n in _chord_live:
                    # a pedal-extended note isn't staccato by definition
                    # (it's ringing ON, the opposite of short) -- the
                    # _chord_live filter above already excludes those from
                    # BOTH the representative-duration calculation and this
                    # assignment, so the guard here is just a second,
                    # cheap safety net, not the primary mechanism.
                    if getattr(_n, "articulation", "") != "pedal_extended":
                        _n.articulation = "staccato"

        # ── 1. Tempo detection ───────────────────────────────────────────────
        # Strategy: group notes into chord events (arpeggio collapse),
        # then find the IOI that best explains the chord onset distribution.
        # We look for the median IOI of bass notes (pitch < 55) since bass
        # lines tend to mark beats reliably in piano music.
        def _collapse(notes, src_ids, window):
            """Group simultaneous notes into chords.
            Notes from different source tracks (per src_ids) are never
            collapsed together.  Returns (groups, group_src_ids) where
            group_src_ids[i] is the source track index of groups[i]."""
            if not notes:
                return [], []
            groups, g_src = [], []
            cur, cur_src = [notes[0]], src_ids[0]
            for n, s in zip(notes[1:], src_ids[1:]):
                if s == cur_src and n.tick - cur[0].tick <= window:
                    cur.append(n)
                else:
                    groups.append(cur)
                    g_src.append(cur_src)
                    cur, cur_src = [n], s
            groups.append(cur)
            g_src.append(cur_src)
            return groups, g_src

        chord_groups, chord_src_ids = _collapse(all_notes, src_track_ids, p["arpeggio_window"])
        chord_onsets = [g[0].tick for g in chord_groups]

        performed_tpb = tpb  # may be updated below
        if p["tempo_override"]:
            new_bpm = p["tempo_override"]
            performed_tpb = int(round(tpb * self.bpm / new_bpm))
        elif p["detect_tempo"]:
            bass_onsets = sorted(set(round(n.tick / 10) * 10 for n in all_notes if n.pitch < 55))
            # Merge bass onsets within 30 ticks
            merged = [bass_onsets[0]] if bass_onsets else chord_onsets[:1]
            for o in bass_onsets[1:]:
                if o - merged[-1] > 30:
                    merged.append(o)
            iois = [
                merged[i + 1] - merged[i]
                for i in range(len(merged) - 1)
                if 100 < merged[i + 1] - merged[i] < tpb * 4
            ]
            if len(iois) >= 4:
                # The median IOI approximates the 8th-note (or beat) period.
                # We then find which standard note value it best matches.
                med_ioi = statistics.median(iois)
                # Test note value multiples: 8th, quarter, dotted-quarter, half
                candidates = {
                    "eighth": tpb / 2,
                    "quarter": tpb,
                    "dotted-quarter": tpb * 1.5,
                    "half": tpb * 2,
                }
                best_name, best_ratio = None, None  # None = no match yet
                for name, std_val in candidates.items():
                    ratio = med_ioi / std_val
                    if 0.7 < ratio < 1.4:
                        if best_ratio is None or abs(ratio - 1.0) < abs(best_ratio - 1.0):
                            best_ratio = ratio
                            best_name = name
                # Only apply tempo scaling when we have a confident match.
                # If no candidate matched the IOI, leave performed_tpb = tpb
                # so we don't blindly halve all tick values (old bug: defaulted
                # to best_ratio=2.0 and compressed 100 measures → 50).
                #
                # v22ze fix: a ratio merely being the *closest* candidate to
                # 1.0 doesn't mean it's a confident, real tempo mismatch —
                # syncopated bass rhythm (8th-note figures mixed with
                # quarters, an ordinary and common pattern) skews the
                # median IOI by a percent or two even when the performer
                # (or, as found here, a mechanically-generated, perfectly
                # quantized LilyPond MIDI with NO free timing at all) is
                # exactly on tempo. Confirmed via a real reference file:
                # median IOI=380 vs a true quarter of 384 (ratio=0.990)
                # got accepted as a genuine correction, then applied via
                # `n.tick = round(n.tick * scale)` a few lines down —
                # since that scale wasn't exactly 1.0, rounding error
                # compounded with tick magnitude across the piece,
                # producing a small forward drift (a few ticks by the
                # end) and spurious tiny "leftover" notes at some measure
                # boundaries where the drift crossed a rounding boundary.
                # A genuine free-tempo performance worth correcting for
                # is typically 5-20% off, not ~1% — so treat anything
                # within a few percent of 1.0 as "already correct" and
                # skip rescaling entirely, rather than applying a
                # sub-percent "correction" that only ever introduces
                # noise of its own.
                TEMPO_DEAD_ZONE = 0.03
                if best_ratio is not None and abs(best_ratio - 1.0) < TEMPO_DEAD_ZONE:
                    print(
                        f"[rationalize] IOI median={med_ioi:.0f}t → "
                        f"best match={best_name} (ratio={best_ratio:.3f}) → "
                        f"within {TEMPO_DEAD_ZONE*100:.0f}% of nominal tempo; "
                        f"treating as already correct, skipping rescale.",
                        file=sys.stderr,
                    )
                elif best_ratio is not None and 0.75 < best_ratio < 1.35:
                    performed_tpb = int(round(tpb * best_ratio))
                    detected_bpm = round(60_000_000 / (performed_tpb * (self.tempo / tpb)))
                    print(
                        f"[rationalize] IOI median={med_ioi:.0f}t → "
                        f"best match={best_name} (ratio={best_ratio:.3f}) → "
                        f"detected BPM≈{detected_bpm}",
                        file=sys.stderr,
                    )
                else:
                    print(
                        f"[rationalize] IOI median={med_ioi:.0f}t → "
                        f"no candidate matched; skipping tempo rescale.",
                        file=sys.stderr,
                    )
            else:
                print(
                    "[rationalize] Not enough bass onsets for tempo detection; " "using song BPM.",
                    file=sys.stderr,
                )

        # ── 1.5. Time signature detection ──────────────────────────────────
        # Run BEFORE building new_song's shell so the detected/overridden
        # meter is what new_song actually uses, rather than blindly copying
        # self.time_sig_num/den (which may be wrong — this was the root
        # cause of bass-clef notes overflowing/underflowing measures after
        # a manual time-signature change in Score Setup; see
        # session_brief_v22h_design.txt Issue 4).
        if p["timesig_override"]:
            detected_num, detected_den = p["timesig_override"]
            ts_confidence, ts_note = 1.0, "User override"
        elif p["detect_timesig"]:
            detected_num, detected_den, ts_confidence, ts_note = self.detect_time_signature()
            # v22ze-40 fix: ts_confidence was computed but never actually
            # used as a gate -- the detected signature got applied
            # UNCONDITIONALLY, however weak the signal. This is what
            # caused a time signature to drift (reported: 4/4 -> 3/4 ->
            # 2/4) across successive rationalizations of the same piece:
            # the accent-pattern detector relies on natural expressive
            # velocity/timing variation to find the meter, but running
            # it AGAIN on already-rationalized output (which has had that
            # variation flattened/altered by the first pass) produces a
            # weaker, noisier signal -- and a low-confidence guess was
            # still silently overwriting the correct, already-established
            # signature. Require a real threshold before trusting it;
            # otherwise keep what the song already has.
            MIN_TIMESIG_CONFIDENCE = 0.3
            if ts_confidence < MIN_TIMESIG_CONFIDENCE:
                print(
                    f"[rationalize] Time signature detection LOW CONFIDENCE "
                    f"({ts_confidence:.0%}) -- keeping existing "
                    f"{self.time_sig_num}/{self.time_sig_den} instead of "
                    f"the {detected_num}/{detected_den} guess. {ts_note}",
                    file=sys.stderr,
                )
                detected_num, detected_den = self.time_sig_num, self.time_sig_den
            else:
                print(
                    f"[rationalize] Time signature detection: {ts_note}",
                    file=sys.stderr,
                )
        else:
            detected_num, detected_den = self.time_sig_num, self.time_sig_den
            ts_confidence, ts_note = 1.0, "Detection disabled — using song default"

        # ── 2. Build the rationalized Song shell ─────────────────────────────
        new_song = Song()
        new_song.ticks_per_beat = tpb
        # Correct the tempo: if performed_tpb != tpb the performer played
        # at a different BPM than the MIDI's default tempo.  We preserve
        # tpb (so tick arithmetic stays clean) and adjust tempo instead.
        if performed_tpb != tpb and performed_tpb > 0:
            ratio = performed_tpb / tpb
            new_bpm = max(20, round(self.bpm / ratio))
            new_song.tempo = int(60_000_000 / new_bpm)
        else:
            new_song.tempo = self.tempo
        new_song.time_sig_num = detected_num
        new_song.time_sig_den = detected_den
        new_song.sig_changes = [(0, detected_num, detected_den)]
        new_song.key_sig = getattr(self, "key_sig", "C")

        # ── 3. Measure range filter ──────────────────────────────────────────
        mmap = self.build_measure_map()
        if measure_range:
            m0 = max(0, measure_range[0] - 1)
            m1 = min(len(mmap) - 1, measure_range[1] - 1)
            range_start = mmap[m0][1]
            range_end = mmap[m1][2]
            in_range = lambda t: range_start <= t < range_end
        else:
            in_range = lambda t: True

        # ── 4. Re-scale ticks if tempo correction applied ────────────────────
        if performed_tpb != tpb and performed_tpb > 0:
            scale = tpb / performed_tpb  # < 1 if performer was slower
            for n in all_notes:
                n.tick = int(round(n.tick * scale))
                n.duration = max(1, int(round(n.duration * scale)))
            chord_groups, chord_src_ids = _collapse(all_notes, src_track_ids, p["arpeggio_window"])
            chord_onsets = [g[0].tick for g in chord_groups]

        # ── 5. Adaptive quantize chord onsets ────────────────────────────────
        # MuseScore insight: each chord uses its own grid =
        #   min(max_grid, IOI_to_next_chord)
        # so 16th-note chords use a 16th grid while quarter-note chords
        # use the max grid.  Short notes are never coarsened to 8ths.
        max_grid = max(1, tpb // p["quantize_div"])
        min_grid = max(1, tpb // 32)  # never finer than 32nd note
        strength = p["quantize_strength"]

        # Standard grids from whole down to 32nd
        _std_grids = sorted(
            set(tpb * m for m in [4, 2, 1])
            | set(tpb // d for d in [2, 4, 8, 16, 32] if tpb // d >= min_grid)
        )

        def _adaptive_grid(ioi):
            """Grid = min(max_grid, largest standard value ≤ ioi)."""
            candidates = [g for g in _std_grids if g <= ioi]
            return min(max_grid, max(candidates)) if candidates else max_grid

        q_groups = []
        for gi, group in enumerate(chord_groups):
            rep_tick = group[0].tick
            if not in_range(rep_tick):
                q_groups.append(group)
                continue
            # IOI: find next group from the SAME source track so cross-track
            # simultaneity (both hands on beat 1) doesn't give IOI=0 and
            # collapse the adaptive grid to a 32nd note.
            ref_src = chord_src_ids[gi]
            ioi = None
            for gj in range(gi + 1, len(chord_groups)):
                if chord_src_ids[gj] == ref_src:
                    candidate = chord_groups[gj][0].tick - rep_tick
                    if candidate > 0:
                        ioi = candidate
                        break
            if ioi and ioi > 0:
                grid = max(min_grid, _adaptive_grid(max(ioi, min_grid)))
            else:
                grid = max_grid
            q_tick = round(rep_tick / grid) * grid
            offset = int(strength * (q_tick - rep_tick))
            new_group = []
            for n in group:
                nc = copy.copy(n)
                nc.tick = max(0, n.tick + offset)
                # Snap duration to nearest grid multiple without forcing a
                # minimum of `grid` — preserves staccato and short notes.
                q_dur = round(n.duration / grid) * grid
                if q_dur > 0:
                    nc.duration = int(n.duration + strength * (q_dur - n.duration))
                else:
                    nc.duration = n.duration  # shorter than half grid — keep as-is
                nc.duration = max(1, nc.duration)
                new_group.append(nc)
            q_groups.append(new_group)

        # ── 6. Eliminate rests shorter than rest_threshold ───────────────────
        # v22ze-68 fix: this used to cap the threshold at max_grid-1, where
        # max_grid comes from the QUANTIZE grid setting (quantize_div) --
        # an unrelated control (how fine onsets snap), not the rest-removal
        # threshold's own semantic ceiling. For the common default grid
        # (quantize_div=8) at tpb=960, that cap was only 119 ticks --
        # smaller than even a genuine 16th-note rest (240 ticks) -- so a
        # user selecting "remove rests shorter than a 16th" (or 8th) could
        # have their choice silently overridden down to something closer
        # to a 32nd, and rests exactly the size they asked to clear would
        # survive. Cap at just under one full beat instead: a rest that
        # long is essentially always intentional regardless of any other
        # setting, and this ceiling no longer depends on an unrelated
        # control the user didn't touch.
        thresh = min(p["rest_threshold"], max(0, tpb - 1))
        if thresh > 0:
            cleaned = []
            for i, group in enumerate(q_groups):
                if i == 0:
                    cleaned.append(group)
                    continue
                prev_end = max(n.tick + n.duration for n in cleaned[-1])
                cur_start = group[0].tick
                gap = cur_start - prev_end
                if 0 < gap < thresh:
                    # Extend previous group's notes to fill the gap
                    for n in cleaned[-1]:
                        n.duration += gap
                cleaned.append(group)
            q_groups = cleaned

        # ── 6.5. Metrical duration analysis — REMOVED (v22g) ────────────────
        #
        # This step formerly split every note at within-measure metric
        # boundaries using metrically_subdivide_duration(), producing up to
        # 6 layers of tie-continuation fragments per note.  On a 3,990-note
        # piano MIDI at 170 BPM it multiplied the note count to 77,243 —
        # an average of 19.4 fragments per original note — because notes at
        # weak metric positions (64th-note offsets) were split at every
        # intermediate boundary before reaching their actual duration.
        #
        # The 77,243 fragments then passed through the DP hand-separator
        # (O(n * K * splits) per group), causing multi-minute runtimes and
        # producing nonsensical hand assignments.
        #
        # WHY IT IS SAFE TO REMOVE:
        #   • Pass A (below) already handles the only case rationalize() needs:
        #     notes that cross a BARLINE are split there and marked
        #     tie_continuation.  Within-measure metric sub-division is purely
        #     a notation-export concern.
        #   • bake_to_score() applies the duration vocabulary (whole/half/
        #     quarter/eighth…) and snaps each note to the nearest standard
        #     value when the user accepts the rationalization.
        #   • to_ly() handles engraver-quality tie rendering for LilyPond
        #     export independently of the rationalize pipeline.
        #
        # metrically_subdivide_duration() is kept as a module-level helper
        # (it may be useful in future notation-specific contexts) but is no
        # longer called from rationalize().

        # ── 7. Measure integrity — clip, tie, and fill ───────────────────────
        #
        # Goal (inspired by MuseScore's internal measure validation):
        #   Every measure must account for exactly tpm ticks of content —
        #   no more (overflow) and no less (underfill).  We enforce this in
        #   three passes:
        #
        #   Pass A — Tie-split overflow notes
        #     A note that crosses a barline is split into two pieces:
        #       piece 1: from note.tick to barline (stays in current measure)
        #       piece 2: remainder, starting at barline (kept in q_groups
        #                with a 'tie_from' flag for the renderer to draw a tie)
        #     This is the same strategy MuseScore uses for its tie-across-
        #     barline feature, but implemented purely on our MidiNote objects.
        #
        #   Pass B — Clamp notes that start at or after a barline
        #     Such notes (rare after quantization) are nudged back to the
        #     last legal tick in their measure.  This prevents a note starting
        #     past the end of a measure boundary from corrupting the layout.
        #
        #   Pass C — Rest infill
        #     After all notes are placed, we scan each measure's occupied
        #     ticks.  Any gap (silence) within the measure is recorded as an
        #     explicit rest interval.  The rest intervals are stored on each
        #     q_group note as n._rests_before = [(rest_start, rest_dur), ...]
        #     so the score renderer (ScoreView, LilyPond exporter) can draw
        #     them without re-inferring gaps.
        #
        # The q_groups list is mutated in place; tie-continuation notes are
        # appended as new single-element groups (so they sort naturally by
        # tick later).

        # NOTE (v22i): new_song has no tracks yet (they're added in step 9),
        # so new_song.total_ticks() returns 0.  We cannot call
        # new_song.build_measure_map() directly.  Previously this used
        # self.build_measure_map() — the ORIGINAL song's grid — but that
        # grid reflects the song's DECLARED time signature, not the
        # detected/overridden one from step 1.5.  If the user manually set
        # a time signature in Score Setup, or auto-detection disagreed with
        # the file's embedded meta-event, Pass A/B/C would clamp notes
        # against the WRONG grid — producing exactly the overflow/underflow
        # pattern seen in testing (bass-clef notes running through new
        # barlines because the grid that Pass A/B used never changed).
        #
        # Fix: build the measure grid here directly from new_song's
        # (corrected) tpb/time-signature using the module-level
        # _build_measure_map_core() helper, sized to the actual extent of
        # the quantized notes rather than the original song's tick range.
        _extent = max((n.tick + n.duration for group in q_groups for n in group), default=tpb * 4)
        new_mmap = _build_measure_map_core(tpb, [(0, detected_num, detected_den)], _extent)

        # Fast O(1) lookup: tick → (m_start, m_end, tpm)
        _mmap_starts = [ms for (_, ms, me, *_) in new_mmap]

        def _measure_bounds(tick):
            """Return (m_start, m_end, tpm) for the measure containing tick."""
            import bisect as _b

            i = _b.bisect_right(_mmap_starts, tick) - 1
            if 0 <= i < len(new_mmap):
                _, ms, me, _, _, tpm_m = new_mmap[i]
                return ms, me, tpm_m
            return None, None, None

        # ── Pass A+B: overflow split and barline clamp ────────────────────────
        extra_groups = []  # tie-continuation notes added here
        for group in q_groups:
            for n in group:
                ms, me, tpm_m = _measure_bounds(n.tick)
                if ms is None:
                    continue
                max_dur = me - n.tick
                if max_dur <= 0:
                    # Pass B: note starts exactly at or past barline — clamp onset
                    # back to last grid position inside the measure.
                    ms_prev, me_prev, tpm_prev = (
                        _measure_bounds(ms - 1) if ms > 0 else (None, None, None)
                    )
                    if ms_prev is not None:
                        n.tick = me_prev - max(1, tpm_prev // p["quantize_div"])
                        ms, me, tpm_m = _measure_bounds(n.tick)
                        if ms is None:
                            continue
                        max_dur = me - n.tick
                if n.duration > max_dur:
                    # Pass A: note crosses barline — split into a tied pair.
                    # v22ze-52 fix: pedal-extended notes used to be clipped
                    # here with NO tie at all, on the theory that the tail
                    # was "just sustain" and the pedal mark alone should
                    # communicate it. Standard engraving practice actually
                    # shows BOTH: an explicit tie on the specific note being
                    # melodically sustained, plus a separate pedal bracket
                    # for the harmonic sustain -- they represent different
                    # things, and a genuinely held note (not just a short
                    # attack ringing on via pedal) should still be tied.
                    # Pedal-extended notes now go through the exact same
                    # split as any other note; only the marker itself is
                    # cleared here (its job -- flagging this note for
                    # _pedal_duration_correct above -- is done) so it
                    # doesn't linger and get mistaken for something still
                    # pedal-active downstream.
                    if n.articulation == "pedal_extended":
                        n.articulation = ""
                    remainder = n.duration - max_dur
                    n.duration = max_dur  # clip to barline
                    # Build tie-continuation note
                    tie_note = copy.copy(n)
                    tie_note.tick = me  # starts at next barline
                    tie_note.duration = remainder
                    tie_note.articulation = "tie_continuation"
                    extra_groups.append([tie_note])

        # Merge tie-continuations in so that they get Pass A+B treatment too
        # (iterate until stable — handles notes spanning 3+ measures).
        _safety = 0
        while extra_groups and _safety < 64:
            _safety += 1
            newly_added = []
            for group in extra_groups:
                for n in group:
                    ms, me, tpm_m = _measure_bounds(n.tick)
                    if ms is None:
                        continue
                    max_dur = me - n.tick
                    if max_dur <= 0:
                        n.tick = ms  # snap to measure start if somehow past end
                        max_dur = tpm_m
                    if n.duration > max_dur:
                        remainder = n.duration - max_dur
                        n.duration = max_dur
                        cont = copy.copy(n)
                        cont.tick = me
                        cont.duration = remainder
                        cont.articulation = "tie_continuation"
                        newly_added.append([cont])
            q_groups.extend(extra_groups)
            extra_groups = newly_added
        q_groups.extend(extra_groups)  # flush any last remainder

        # ── Pass C: rest infill ──────────────────────────────────────────────
        # Build a per-measure occupied-tick map, then record gap intervals on
        # each note that follows a gap.
        #
        # MuseScore insight: every voice must be "full" — rests are first-class
        # elements, not inferred absence.  We store them as metadata here so
        # the renderer can draw them explicitly (whole-bar rest, half rest, etc.)
        # rather than discovering gaps at draw time and potentially getting
        # beam/rest consolidation wrong.

        # Collect all notes in tick order for gap analysis
        all_q_notes = sorted(
            (n for group in q_groups for n in group), key=lambda n: (n.tick, n.pitch)
        )

        # Build measure → list of (onset, end) intervals (one per note)
        from collections import defaultdict as _dd2

        measure_note_intervals = _dd2(list)  # ms → [(onset, end), ...]
        for n in all_q_notes:
            ms, me, tpm_m = _measure_bounds(n.tick)
            if ms is not None:
                measure_note_intervals[ms].append((n.tick, n.tick + n.duration))

        def _merge_intervals(ivs):
            """Union of (start,end) intervals, sorted."""
            if not ivs:
                return []
            ivs = sorted(ivs)
            out = [ivs[0]]
            for s, e in ivs[1:]:
                if s <= out[-1][1]:
                    out[-1] = (out[-1][0], max(out[-1][1], e))
                else:
                    out.append((s, e))
            return out

        # For each measure, compute gap list (rest intervals)
        measure_rests = {}  # ms → [(rest_start, rest_dur), ...]
        for _, ms, me, _, _, tpm_m in new_mmap:
            ivs = _merge_intervals(measure_note_intervals.get(ms, []))
            gaps = []
            cursor = ms
            for s, e in ivs:
                if s > cursor:
                    gaps.append((cursor, s - cursor))  # rest before this note
                cursor = max(cursor, e)
            if cursor < me:
                gaps.append((cursor, me - cursor))  # trailing rest
            if gaps:
                measure_rests[ms] = gaps

        # Rest metadata is stored in new_song._rests_before_map (see below)
        # keyed by (tick, pitch, channel) — no MidiNote attribute needed.

        # Expose measure_rests on new_song so exporters can use it directly.
        new_song._measure_rests = measure_rests
        # Also store per-note rest metadata as an external dict keyed by
        # (tick, pitch, channel) — avoids setting attributes on __slots__ MidiNote.
        rests_before_map = {}  # (tick,pitch,channel) → [(rest_start, rest_dur),...]
        for n in all_q_notes:
            ms2, me2, tpm_m2 = _measure_bounds(n.tick)
            if ms2 is None:
                continue
            rests_in_measure = measure_rests.get(ms2, [])
            my_rests = [(rs, rd) for (rs, rd) in rests_in_measure if rs < n.tick]
            if my_rests:
                key = (n.tick, n.pitch, n.channel)
                rests_before_map[key] = rests_before_map.get(key, []) + my_rests
        new_song._rests_before_map = rests_before_map

        # ── 7.5. Arpeggio group detection ─────────────────────────────────────
        # Before the DP runs, identify groups of 3+ consecutive notes that
        # form a genuine arpeggio pattern: sequential (not simultaneous),
        # uniformly spaced in time, spanning at least a fifth (7 semitones),
        # and moving predominantly in one direction (ascending or descending).
        # Tag all notes in a group with a shared _arpeggio_group integer so
        # the DP can treat them as a unit.
        #
        # Key constraint: ALL notes in an arpeggio group go to the hand whose
        # register contains the group's LOWEST note, regardless of how high
        # the arpeggio climbs.  This prevents left-hand jazz arpeggios from
        # being split at C4 just because their top note enters RH territory.
        #
        # A note's _arpeggio_group is stored in a parallel dict (not on the
        # MidiNote object itself, since __slots__ forbids dynamic attributes).

        _arp_groups = {}  # id(note) → group_idx (int)
        _arp_group_hand = {}  # group_idx → 'LH' | 'RH' | None (undecided)
        _next_group = [0]

        def _detect_arpeggios(groups_list):
            """Scan chord groups for arpeggio runs. Modifies _arp_groups."""
            # Flatten to (tick, pitch, note_obj) for single-note groups only
            single_events = []
            for grp in groups_list:
                if len(grp) == 1:
                    single_events.append(grp[0])
            if len(single_events) < 3:
                return

            tol = p["arpeggio_window"] * 3  # IOI tolerance
            min_span = 7  # at least a fifth

            i = 0
            while i < len(single_events) - 2:
                n0 = single_events[i]
                # Compute IOI from n0 to n1
                ioi_ref = single_events[i + 1].tick - n0.tick
                if ioi_ref <= 0:
                    i += 1
                    continue

                # Collect run of notes with similar IOI
                run = [n0]
                for j in range(i + 1, len(single_events)):
                    nj = single_events[j]
                    ioi = nj.tick - single_events[j - 1].tick
                    if abs(ioi - ioi_ref) <= tol:
                        run.append(nj)
                    else:
                        break

                if len(run) >= 3:
                    pitches = [n.pitch for n in run]
                    span = max(pitches) - min(pitches)
                    # Check directional consistency (ascending or descending)
                    diffs = [pitches[k + 1] - pitches[k] for k in range(len(pitches) - 1)]
                    ascending = sum(1 for d in diffs if d > 0)
                    descending = sum(1 for d in diffs if d < 0)
                    directional = ascending >= len(diffs) // 2 or descending >= len(diffs) // 2

                    if span >= min_span and directional:
                        grp_idx = _next_group[0]
                        _next_group[0] += 1
                        for n in run:
                            _arp_groups[id(n)] = grp_idx
                        # Hand for this group = based on lowest note's register
                        low_pitch = min(pitches)
                        _arp_group_hand[grp_idx] = "LH" if low_pitch < 60 else "RH"
                        i += len(run)
                        continue
                i += 1

        _detect_arpeggios(q_groups)
        if _arp_groups:
            n_groups = _next_group[0]
            print(f"[rationalize] Arpeggio groups detected: {n_groups}", file=sys.stderr)

        # ── 8. DP hand separation ─────────────────────────────────────────────
        # State: (lh_center, rh_center) = pitch center of last LH and RH chords
        # We process chord groups in time order, assigning each group's notes
        # to LH, RH, or split between them.
        #
        # Cost function:
        #   - span violation: notes in one hand > max_span semitones apart → +50/note
        #   - hand travel: |new_center - old_center| semitones → +1/semitone
        #   - voice crossing: LH plays above RH → +100
        #
        # We use a beam search (keep top K states) for efficiency.

        BEAM_K = 6
        MAX_SPAN = p["max_span"]
        MAX_NOTES_PER_HAND = p["max_notes_per_hand"]
        INF = float("inf")

        def _split_cost(pitches_lh, pitches_rh, prev_lh, prev_rh):
            if not pitches_lh and not pitches_rh:
                return INF
            cost = 0.0
            # v22ze: physical note-count constraint. Span alone doesn't
            # capture this — a tight cluster chord can have a small span
            # (all adjacent semitones) yet still need more simultaneous
            # notes than one hand has fingers for. A human hand has a
            # thumb + 4 fingers; 5 is already a full stretch for most
            # voicings, 6+ is not playable by one hand regardless of how
            # narrow the span is. This was previously not checked at
            # all — only span was. Penalized heavily (not hard-rejected)
            # so the DP always has a fallback rather than potentially
            # finding no valid candidate at all for a genuinely huge
            # cluster chord that can't be brought under the limit even
            # when split as evenly as possible.
            if len(pitches_lh) > MAX_NOTES_PER_HAND:
                cost += (len(pitches_lh) - MAX_NOTES_PER_HAND) * 40
            if len(pitches_rh) > MAX_NOTES_PER_HAND:
                cost += (len(pitches_rh) - MAX_NOTES_PER_HAND) * 40
            # v22ze-26 ("share the work more evenly"): the physical demand
            # of a chord grows with note count well before it hits the
            # hard MAX_NOTES_PER_HAND ceiling above -- a 3+ note chord
            # clustered near middle C is exactly the kind of thing a
            # performer often lets LH help with, IF LH can reach there
            # cheaply. This is a much smaller, graduated nudge (not a
            # hard constraint): it only creates the INCENTIVE to offload
            # a note near C4 off of a loaded RH chord. Whether the DP
            # actually takes that offer still comes down to the hand-
            # travel cost below -- if LH is busy elsewhere or would have
            # to leap to reach it, that cost outweighs this nudge and RH
            # keeps the full chord, same as today. Restricted to chords
            # where most of the notes are actually near C4, so a big
            # chord entirely up in the treble isn't penalized just
            # because LH isn't sharing notes nowhere near its reach.
            NEAR_C4_RANGE = 12  # within an octave of C4 (48-72)
            if len(pitches_rh) >= 3:
                near_c4_count = sum(1 for p in pitches_rh if abs(p - 60) <= NEAR_C4_RANGE)
                if near_c4_count >= 3:
                    cost += (len(pitches_rh) - 2) * 6
            # Span violations
            if len(pitches_lh) > 1:
                span = max(pitches_lh) - min(pitches_lh)
                if span > MAX_SPAN:
                    cost += (span - MAX_SPAN) * 15
            if len(pitches_rh) > 1:
                span = max(pitches_rh) - min(pitches_rh)
                if span > MAX_SPAN:
                    cost += (span - MAX_SPAN) * 15
            # Centers
            lh_c = statistics.mean(pitches_lh) if pitches_lh else prev_lh
            rh_c = statistics.mean(pitches_rh) if pitches_rh else prev_rh
            # Hand travel
            cost += abs(lh_c - prev_lh) * 0.5
            cost += abs(rh_c - prev_rh) * 0.5
            # Voice crossing
            if pitches_lh and pitches_rh:
                if max(pitches_lh) > min(pitches_rh):
                    cost += 30
            # Prefer low notes in LH, high in RH — strengthened in v22m
            # to better match common piano writing conventions.
            # Notes below C4 (midi 60) strongly prefer LH; above G4 (67) prefer RH.
            if pitches_lh and pitches_rh:
                lh_mean = statistics.mean(pitches_lh)
                rh_mean = statistics.mean(pitches_rh)
                if lh_mean > rh_mean:
                    cost += 40
                # Extra penalty: LH notes above C4 when RH has lower notes
                if pitches_lh and min(pitches_lh) > 60 and pitches_rh and min(pitches_rh) < 60:
                    cost += 50
                # Extra penalty: RH notes below E3 (52) — almost always LH territory
                if pitches_rh and min(pitches_rh) < 52:
                    cost += 60 * sum(1 for p in pitches_rh if p < 52)
            return cost, lh_c, rh_c

        def _enumerate_splits(pitches):
            """Yield (lh_pitches, rh_pitches) splits for a chord."""
            n = len(pitches)
            if n == 0:
                yield [], []
                return
            if n == 1:
                yield pitches, []
                yield [], pitches
                return
            sp = sorted(pitches)
            # All-LH, all-RH
            yield sp, []
            yield [], sp
            # Split at each position (lower k notes to LH, rest to RH)
            for k in range(1, n):
                yield sp[:k], sp[k:]

        # Beam state: list of (cost, lh_center, rh_center, assignments)
        # assignments: list of (lh_note_indices, rh_note_indices) per group so far
        lh_start = 45.0  # E2 — typical LH starting position
        rh_start = 65.0  # F4 — typical RH starting position
        beam = [(0.0, lh_start, rh_start, [])]

        for group in q_groups:
            pitches = sorted(set(n.pitch for n in group))
            if not pitches:
                for i, state in enumerate(beam):
                    beam[i] = (state[0], state[1], state[2], state[3] + [([], [])])
                continue

            new_beam = []
            for cost, lh_c, rh_c, assigns in beam:
                for lh_p, rh_p in _enumerate_splits(pitches):
                    result = _split_cost(lh_p, rh_p, lh_c, rh_c)
                    if result == INF:
                        continue
                    step_cost, new_lh_c, new_rh_c = result
                    new_beam.append(
                        (
                            cost + step_cost,
                            new_lh_c,
                            new_rh_c,
                            assigns + [(set(lh_p), set(rh_p))],
                        )
                    )

            # Keep top BEAM_K states
            new_beam.sort(key=lambda s: s[0])
            beam = new_beam[:BEAM_K]
            if not beam:
                # Fallback: median split
                mid = statistics.median(pitches)
                lh_p = [p for p in pitches if p <= mid]
                rh_p = [p for p in pitches if p > mid]
                beam = [(INF, lh_c, rh_c, assigns + [(set(lh_p), set(rh_p))])]

        # Best assignment
        best = beam[0]
        assignments = best[3]  # one (lh_set, rh_set) per chord group
        # NOTE: when _preserve_hands is True, this DP result is computed but
        # discarded — see the final assignment loop below (step 9), which
        # checks n.channel directly rather than n.pitch-in-rh_set.  Using
        # pitch-set membership would misassign notes in the rare case where
        # both hands play the identical pitch within one chord group.

        # ── 9. Build output tracks ────────────────────────────────────────────
        # Use the track names / programs from the first matching source track
        src_track = self.tracks[0] if self.tracks else None
        prog = src_track.program if src_track else 0
        name = src_track.name if src_track else "Piano"
        # v22ze-43 fix: re-rationalizing an already-rationalized song (its
        # tracks already named "X (RH)"/"X (LH)" from a prior pass) used
        # to blindly append ANOTHER "(RH)"/"(LH)" suffix on top, producing
        # "X (RH) (RH)" -- and would compound further with each additional
        # pass. Strip any existing suffix first so the name stays clean
        # regardless of how many times this has already run.
        for _suffix in (" (RH)", " (LH)"):
            if name.endswith(_suffix):
                name = name[: -len(_suffix)]
                break

        rh_track = Track(name=f"{name} (RH)", channel=0, program=prog)
        lh_track = Track(name=f"{name} (LH)", channel=1, program=prog)

        # Copy all CC64 pedal events from every original track into both
        # output tracks so pedal marks render correctly and to_mid() plays
        # back with correct sustain.  Other non-note events (e.g. pitch bend,
        # expression CC11) go to the RH track by convention.
        pedal_events = []
        other_events = []
        for tr in self.tracks:
            for ev in tr.events:
                if hasattr(ev, "msg") and ev.msg.type == "control_change" and ev.msg.control == 64:
                    pedal_events.append(ev)
                else:
                    other_events.append(ev)
        # De-duplicate pedal events (same tick+value from multiple tracks)
        seen_pedal = set()
        for ev in sorted(pedal_events, key=lambda e: e.tick):
            key = (ev.tick, ev.msg.value)
            if key not in seen_pedal:
                seen_pedal.add(key)
                rh_track.events.append(ev)
                lh_track.events.append(ev)
        rh_track.events.extend(other_events)
        rh_track.events.sort(key=lambda e: e.tick)
        lh_track.events.sort(key=lambda e: e.tick)

        for group, (lh_set, rh_set) in zip(q_groups, assignments):
            for n in group:
                # Preserve-hands mode (v22t): trust the note's own channel
                # tag (set at step 0.1 from the file's original track)
                # directly, bypassing both the DP result AND the arpeggio
                # group override below.  This is the most faithful path —
                # no algorithm re-derives what the file already told us.
                if _preserve_hands:
                    if n.channel == 0:
                        nc = copy.copy(n)
                        nc.channel = 0
                        rh_track.notes.append(nc)
                    else:
                        nc = copy.copy(n)
                        nc.channel = 1
                        lh_track.notes.append(nc)
                    continue

                # Arpeggio group override (v22p): if this note belongs to a
                # detected arpeggio group, assign the ENTIRE group to the hand
                # determined by the group's lowest note — regardless of what
                # the DP decided.  This prevents left-hand jazz arpeggios from
                # being split at C4 because the top of the arpeggio climbs
                # into right-hand register.
                grp_idx = _arp_groups.get(id(n))
                if grp_idx is not None:
                    forced_hand = _arp_group_hand.get(grp_idx)
                    if forced_hand == "RH":
                        nc = copy.copy(n)
                        nc.channel = 0
                        rh_track.notes.append(nc)
                        continue
                    elif forced_hand == "LH":
                        nc = copy.copy(n)
                        nc.channel = 1
                        lh_track.notes.append(nc)
                        continue
                # Normal DP assignment
                if n.pitch in rh_set:
                    nc = copy.copy(n)
                    nc.channel = 0
                    rh_track.notes.append(nc)
                else:
                    nc = copy.copy(n)
                    nc.channel = 1
                    lh_track.notes.append(nc)

        rh_track.notes.sort(key=lambda n: n.tick)
        lh_track.notes.sort(key=lambda n: n.tick)
        new_song.tracks = [rh_track, lh_track]

        # Store the content-derived measure map (Issue 4).  Rebuild sized to
        # the final populated tracks so it covers the full output, then
        # attach so downstream consumers (bake_to_score, to_ly, ScoreView,
        # Score Setup) prefer it over a fixed declared-time-signature grid.
        final_extent = max(new_song.total_ticks(), tpb * 4)
        new_song.rationalized_measure_map = _build_measure_map_core(
            tpb, [(0, detected_num, detected_den)], final_extent
        )

        print(
            f"[rationalize] Done: {len(rh_track.notes)} RH notes, "
            f"{len(lh_track.notes)} LH notes, "
            f"tempo={new_song.bpm} BPM, "
            f"time_sig={detected_num}/{detected_den} "
            f"(confidence {ts_confidence:.0%}), "
            f"measures={len(new_song.rationalized_measure_map)}",
            file=sys.stderr,
        )
        return new_song

    # ── LilyPond .ly export ──────────────────────────────────────────────────
    def detect_calibration(self):
        """Analyse the tick stream and return a calibration suggestion.

        Returns a dict:
            {
                'bpm'        : float   — suggested global BPM (None if uncertain),
                'confidence' : float   — 0.0–1.0 fit quality of the IOI match,
                'note'       : str     — human-readable explanation,
            }

        This is a lightweight read-only operation; it never modifies the Song.
        The full rationalize() pipeline uses the same detection but also
        applies the result.  detect_calibration() is for the Score Setup panel's
        "Auto-detect" button.
        """
        import statistics as _st

        tpb = self.ticks_per_beat
        all_notes = [n for tr in self.tracks for n in tr.notes]
        if len(all_notes) < 8:
            return {
                "bpm": None,
                "confidence": 0.0,
                "note": "Too few notes for reliable detection.",
            }

        all_notes.sort(key=lambda n: n.tick)

        # Use bass notes (pitch < 55) for IOI — they carry the pulse reliably.
        # Fall back to all notes if there are fewer than 4 bass notes.
        bass = [n for n in all_notes if n.pitch < 55]
        if len(bass) < 4:
            bass = all_notes

        ticks = sorted(set(n.tick for n in bass))
        iois = [ticks[i + 1] - ticks[i] for i in range(len(ticks) - 1) if ticks[i + 1] > ticks[i]]
        if not iois:
            return {"bpm": None, "confidence": 0.0, "note": "Cannot compute IOI."}

        med_ioi = _st.median(iois)

        # Standard note values to match against (in ticks)
        _std = {
            "whole": tpb * 4,
            "half": tpb * 2,
            "q-dot": int(tpb * 1.5),
            "quarter": tpb,
            "e-dot": int(tpb * 0.75),
            "eighth": tpb // 2,
            "sixteenth": tpb // 4,
        }

        best_name = None
        best_ratio = None
        best_conf = 0.0

        for name, val in _std.items():
            if val <= 0:
                continue
            ratio = med_ioi / val
            # Confidence: how close ratio is to a small integer (1, 2, 3)
            for mult in (1, 2, 3):
                deviation = abs(ratio - mult) / mult
                conf = max(0.0, 1.0 - deviation * 4)
                if conf > best_conf:
                    best_conf = conf
                    best_ratio = ratio / mult  # actual tpb correction factor
                    best_name = f"{mult}×{name}"

        if best_conf < 0.3 or best_ratio is None:
            return {
                "bpm": None,
                "confidence": best_conf,
                "note": f"Weak IOI match (conf={best_conf:.2f}). " "Try setting BPM manually.",
            }

        performed_tpb = tpb / best_ratio
        current_bpm = 60_000_000 / self.tempo if self.tempo > 0 else 120.0
        suggested_bpm = round(current_bpm * (performed_tpb / tpb), 1)
        suggested_bpm = max(20.0, min(300.0, suggested_bpm))

        note = (
            f"IOI median={med_ioi:.0f}t matched {best_name} "
            f"(conf={best_conf:.2f}) → {suggested_bpm:.1f} BPM"
        )
        return {"bpm": suggested_bpm, "confidence": best_conf, "note": note}

    def detect_separated_hands(self):
        """Detect whether the file already has hands separated into two tracks.

        Returns a dict:
            {
                'separated'   : bool,
                'rh_track_idx': int or None,
                'lh_track_idx': int or None,
                'rh_notes'    : int,
                'lh_notes'    : int,
            }

        A file is considered "already separated" when exactly two tracks
        contain notes (tracks with zero notes — metadata, pedal-only,
        copyright text tracks, etc. — are ignored).  Which of the two is
        RH vs LH is determined first by name (containing "right"/"rh" or
        "left"/"lh", case-insensitive), falling back to average pitch
        (the higher-average-pitch track is assumed RH).
        """
        non_empty = [(i, tr) for i, tr in enumerate(self.tracks) if tr.notes]
        if len(non_empty) != 2:
            return {
                "separated": False,
                "rh_track_idx": None,
                "lh_track_idx": None,
                "rh_notes": 0,
                "lh_notes": 0,
            }

        (i0, t0), (i1, t1) = non_empty

        def _name_hint(name):
            n = name.lower()
            if "right" in n or "rh" in n:
                return "RH"
            if "left" in n or "lh" in n:
                return "LH"
            return None

        hint0, hint1 = _name_hint(t0.name), _name_hint(t1.name)
        if hint0 == "RH" and hint1 != "RH":
            rh_idx, lh_idx = i0, i1
        elif hint1 == "RH" and hint0 != "RH":
            rh_idx, lh_idx = i1, i0
        elif hint0 == "LH" and hint1 != "LH":
            rh_idx, lh_idx = i1, i0
        elif hint1 == "LH" and hint0 != "LH":
            rh_idx, lh_idx = i0, i1
        else:
            # No usable name hint — fall back to average pitch
            avg0 = sum(n.pitch for n in t0.notes) / len(t0.notes)
            avg1 = sum(n.pitch for n in t1.notes) / len(t1.notes)
            rh_idx, lh_idx = (i0, i1) if avg0 >= avg1 else (i1, i0)

        return {
            "separated": True,
            "rh_track_idx": rh_idx,
            "lh_track_idx": lh_idx,
            "rh_notes": len(self.tracks[rh_idx].notes),
            "lh_notes": len(self.tracks[lh_idx].notes),
        }

    def detect_time_signature(self, beat_ticks=None):
        """Suggest a time-signature numerator from accent periodicity.

        Returns (num, den, confidence, note).

        Strategy: build a per-beat accent-strength histogram from note
        velocities (weighted 1.6× toward bass-register notes, pitch < 55),
        indexed by beat number.  Test candidates (2, 3, 4, 6) and score each
        by the mean accent difference between strong beats (beat_idx % num == 0)
        and weak beats.

        Key fix (v22k): candidates that are MULTIPLES of a smaller candidate
        whose score is already good are penalised.  Without this, 4/4 music
        also scores well for 2 and 4 — but so does 6 because the sixteenth-
        note subdivision groups of the accompaniment look like 6 equal beats.
        The fix: if candidate C = k * B for some smaller B already in scores,
        and score(C) < score(B) * 1.15 (not substantially better), discount C
        by dividing its score by k.  Smaller, simpler meters win ties.

        den is always returned as 4 in this version.
        beat_ticks: optional override for the empirical beat period.
        """
        import statistics as _st
        from collections import defaultdict as _dd_ts

        all_notes = [n for tr in self.tracks for n in tr.notes]
        if len(all_notes) < 16:
            return (
                self.time_sig_num,
                self.time_sig_den,
                0.0,
                "Too few notes for reliable meter detection.",
            )

        if beat_ticks is None:
            bass = [n for n in all_notes if n.pitch < 55] or all_notes
            onsets = sorted(set(round(n.tick / 10) * 10 for n in bass))
            if len(onsets) < 8:
                return (
                    self.time_sig_num,
                    self.time_sig_den,
                    0.0,
                    "Not enough onsets for meter detection.",
                )
            merged = [onsets[0]]
            for o in onsets[1:]:
                if o - merged[-1] > 30:
                    merged.append(o)
            iois = [
                merged[i + 1] - merged[i]
                for i in range(len(merged) - 1)
                if 50 < merged[i + 1] - merged[i] < self.ticks_per_beat * 4
            ]
            if len(iois) < 8:
                return (
                    self.time_sig_num,
                    self.time_sig_den,
                    0.0,
                    "Not enough IOI data for meter detection.",
                )
            beat_ticks = _st.median(iois)

        if beat_ticks <= 0:
            return (self.time_sig_num, self.time_sig_den, 0.0, "Invalid beat period.")

        # Per-beat accent strength: velocity weighted toward bass register
        accent = _dd_ts(float)
        for n in all_notes:
            beat_idx = round(n.tick / beat_ticks)
            weight = n.velocity * (1.6 if n.pitch < 55 else 1.0)
            accent[beat_idx] += weight

        candidates = (2, 3, 4, 6)
        raw_scores = {}
        for num in candidates:
            on_beat = [v for k, v in accent.items() if k % num == 0]
            off_beat = [v for k, v in accent.items() if k % num != 0]
            if not on_beat or not off_beat:
                continue
            raw_scores[num] = _st.mean(on_beat) - _st.mean(off_beat)

        if not raw_scores:
            return (
                self.time_sig_num,
                self.time_sig_den,
                0.0,
                "Could not score any meter candidate.",
            )

        # ── Simplicity bias (v22k) ────────────────────────────────────────
        # Penalise a larger candidate when a smaller divisor already accounts
        # for the accent pattern almost as well.  This stops 6 from beating
        # 4 merely because sixteenth-note groups create 6 apparent "beats".
        adjusted = dict(raw_scores)
        for num in sorted(candidates):
            if num not in adjusted:
                continue
            for larger in candidates:
                if larger <= num or larger not in adjusted:
                    continue
                if larger % num == 0:
                    ratio = larger // num
                    # Only discount if the larger candidate is NOT
                    # substantially better (< 15% improvement)
                    if adjusted[larger] < adjusted[num] * 1.15:
                        adjusted[larger] = adjusted[larger] / ratio

        best_num = max(adjusted, key=adjusted.get)
        best_score = adjusted[best_num]
        ordered = sorted(adjusted.values(), reverse=True)
        runner_up = ordered[1] if len(ordered) > 1 else 0.0
        spread = best_score - runner_up
        confidence = max(0.0, min(1.0, spread / (abs(best_score) + 1e-6)))

        note = (
            f"Beat period={beat_ticks:.0f}t; "
            f'raw={{{", ".join(f"{k}:{round(v,1)}" for k,v in raw_scores.items())}}}; '
            f'adj={{{", ".join(f"{k}:{round(v,1)}" for k,v in adjusted.items())}}} '
            f"→ {best_num}/4 (confidence {confidence:.0%})"
        )
        return (best_num, 4, confidence, note)

    def detect_notation_division(self):
        """Return the finest NOTATION_DIVISION needed to display all notes.

        Scans all note durations and finds the shortest value present,
        then returns the division (2=eighth, 4=sixteenth, 8=32nd) that
        can represent it.  Capped at 4 (sixteenth) by default — 32nd notes
        are rare and create very dense scores; the caller can override.

        Returns an int: 1, 2, 4, or 8.
        """
        tpb = self.ticks_per_beat
        if tpb <= 0:
            return 4
        all_notes = [n for tr in self.tracks for n in tr.notes]
        if not all_notes:
            return 2

        # Find shortest duration in ticks, ignoring sub-grace-threshold noise
        min_dur = min(
            (n.duration for n in all_notes if n.duration >= grace_ticks(tpb)),
            default=tpb,
        )

        # Map shortest duration to required division
        # tpb      = quarter  → division 1
        # tpb//2   = eighth   → division 2
        # tpb//4   = 16th     → division 4
        # tpb//8   = 32nd     → division 8
        if min_dur >= tpb:
            return 1
        elif min_dur >= tpb // 2:
            return 2
        elif min_dur >= tpb // 4:
            return 4
        else:
            return 4  # cap at sixteenth — 32nds make scores unreadably dense

    def bake_to_score(self):
        """Return a NEW Song whose note data matches exactly what the score displays.

        The score renderer (build_measure_str inside to_ly) applies a cleaning
        pipeline — grid snap, grace removal, duration rounding, tie merging —
        purely for display and never writes changes back.  This method runs the
        same pipeline and commits the results to MidiNote objects so that:

          • Playback sounds identical to the score
          • to_mid() produces a MIDI that sounds like the score
          • The score view renders identically (snapping already-snapped notes
            is idempotent)
          • Empty tracks are dropped

        Returns a new Song; the caller's song is never modified.
        """
        import copy as _bk

        tpb = self.ticks_per_beat
        mmap = self.get_measure_map()

        # ── Duration vocabulary ────────────────────────────────────────────────
        # RULE (v22j, relaxed in v22ze): dotted eighth and dotted sixteenth
        # are common, completely ordinary notation and are now allowed for
        # notes, not just rests. The original v22j restriction was a
        # deliberate narrowing heuristic adopted specifically to help
        # isolate the causes of a bar-overshoot bug under investigation at
        # the time -- not a claim that dotted eighths are unplayable or
        # shouldn't appear in real notation. That bug has since been
        # found and fixed elsewhere (the dur_str nearest-match rounding
        # issue in to_ly()'s build_measure_str); the narrowing heuristic
        # is no longer needed and was overly restrictive to keep as a
        # permanent rule. Dotted 32nd and smaller remain excluded -- those
        # really are impractical to notate/execute with precision, and
        # rest_seq (to_ly()'s rest-decomposition table) never allowed
        # them either, so this also brings the note and rest vocabularies
        # into agreement down to the sixteenth-note level.
        _STD_VALS = [
            tpb * 4,  # whole
            tpb * 3,  # dotted half
            tpb * 2,  # half
            tpb * 3 // 2,  # dotted quarter
            tpb,  # quarter
            tpb * 3 // 4,  # dotted eighth
            tpb // 2,  # eighth
            tpb * 3 // 8,  # dotted sixteenth
            tpb // 4,  # sixteenth
            tpb // 8,  # 32nd             ← NO dotted-32nd
            tpb // 16,  # 64th
        ]
        _STD_VALS = [v for v in _STD_VALS if v > 0]

        # Quarter note threshold: notes at quarter or larger may use upward
        # snap with 60% bias.  Notes BELOW quarter (eighth and shorter) snap
        # DOWN only — use the largest plain value that fits the actual
        # duration.  This prevents staccato eighths from being inflated to
        # dotted quarters or other larger values they were never meant to be.
        _QUARTER = tpb

        def _snap_note(ticks, available):
            """Snap note duration to vocabulary.

            Snaps from RAW DURATION ONLY — available space is only a hard
            cap, never used to select among candidates.  This is the key
            v22r fix: a 200-tick note snaps to a sixteenth (240) regardless
            of whether available is 480 (which would previously inflate it
            to an eighth).  The gap between chosen and available becomes an
            explicit rest, not silent absorption into the note.

            Quarter and larger: snap UP if ticks >= 60% of the next value.
            Sub-quarter (eighth and shorter): snap DOWN from raw duration.
            Returns (chosen_ticks, is_staccato).
            """
            plain_vals = _STD_VALS
            if ticks >= _QUARTER:
                # Quarter or larger: upward snap with 60% bias
                for v in sorted(plain_vals, reverse=True):
                    if ticks >= v:
                        return min(v, available), False
                    if ticks >= v * 0.60:
                        return min(v, available), False
                return min(plain_vals[-1], available), False
            else:
                # Sub-quarter: snap DOWN from raw duration, cap at available
                candidates = [v for v in plain_vals if v <= ticks * 1.5]
                if not candidates:
                    candidates = list(plain_vals)
                chosen = min(max(candidates), available)
                is_staccato = ticks < chosen * 0.75
                return chosen, is_staccato

        def _best_dur_le(ticks):
            # v22zd: return 0 (not _STD_VALS[-1]) when ticks is smaller than
            # even the shortest notatable value (a 64th note).  The old
            # fallback returned the SMALLEST available duration anyway,
            # which is LARGER than what was asked for -- e.g. a genuine
            # 1-tick residual gap got "filled" with a 30-tick 64th-note
            # rest, silently adding up to 29 ticks of unaccounted-for
            # duration.  Found via an isolated test rig reproducing the
            # exact rest-filling logic (see testrig/measure_writer.py) —
            # confirmed real, separate from the double-fill bug fixed in
            # v22zb.  Callers must treat 0 as "nothing to notate here".
            candidates = [v for v in _STD_VALS if v <= ticks]
            return max(candidates) if candidates else 0

        grid = max(1, tpb // NOTATION_DIVISION)

        # ── Build the new Song shell ──────────────────────────────────────────
        out = Song()
        out.ticks_per_beat = tpb
        out.tempo = self.tempo
        out.time_sig_num = self.time_sig_num
        out.time_sig_den = self.time_sig_den
        out.sig_changes = _bk.deepcopy(self.sig_changes)
        out.filename = self.filename
        out.title = getattr(self, "title", "")
        out.modified = True  # baked copy always needs a Save

        for tr in self.tracks:
            if not tr.notes:
                continue  # drop empty tracks — they carry no musical content

            out_tr = Track(name=tr.name, channel=tr.channel, program=tr.program, volume=tr.volume)
            out_tr.mute = tr.mute
            out_tr.solo = tr.solo
            # Copy non-note events (pedal CC, etc.) unchanged
            out_tr.events = _bk.deepcopy(tr.events)

            baked_notes: list = []

            for _mi, ms, me, _num, _den, tpm in mmap:
                # Notes whose onset falls in this measure
                meas_notes = [n for n in tr.notes if ms <= n.tick < me]
                if not meas_notes:
                    continue

                # ── Step 1: snap onsets to grid ───────────────────────────────
                snapped = []
                budget = int(tpm)
                _gt = grace_ticks(tpb)  # v22s: scaled to this song's resolution
                for n in meas_notes:
                    rel = int(n.tick) - ms
                    qrel = round(rel / grid) * grid
                    # grace_ticks(tpb) tolerance: same musical meaning as the
                    # renderer, scaled correctly for this file's resolution.
                    if abs(rel - qrel) <= _gt:
                        q = qrel
                    else:
                        q = qrel
                    q = max(0, min(budget - grid, q))
                    snapped.append((q, n))
                snapped.sort(key=lambda x: x[0])

                # ── Step 2: remove sub-threshold notes ────────────────────────
                # Use grace_ticks(tpb) as the removal threshold — scaled to
                # this file's resolution (v22s) so a 960-tpb file isn't held
                # to a stricter noise floor than an identical 480-tpb file.
                # EXCEPTION: notes marked articulation='grace' are preserved
                # regardless of duration — they will be rendered as small
                # prefatory noteheads before the beat.
                min_dur = _gt
                snapped = [
                    (q, n)
                    for q, n in snapped
                    if n.duration >= min_dur or getattr(n, "articulation", "") == "grace"
                ]
                if not snapped:
                    continue

                # ── Step 3: group same-tick notes into chords ─────────────────
                groups: list = []  # [(grid_tick, [notes])]
                for q, n in snapped:
                    if groups and groups[-1][0] == q:
                        groups[-1][1].append(n)
                    else:
                        groups.append((q, [n]))

                # ── Step 4: snap durations, insert rests for gaps ─────────────
                for i, (tick, chord) in enumerate(groups):
                    next_tick = groups[i + 1][0] if i + 1 < len(groups) else budget
                    available = next_tick - tick
                    if available <= 0:
                        continue

                    raw_dur = max(n.duration for n in chord)
                    chosen, is_staccato = _snap_note(raw_dur, available)
                    if chosen <= 0:
                        chosen = grid

                    abs_tick = ms + tick
                    for n in chord:
                        nc = _bk.copy(n)
                        nc.tick = abs_tick
                        nc.duration = chosen
                        # v22ze-48 fix: this used to clear the
                        # tie_continuation marker RIGHT HERE, before
                        # Step 5 below ever got a chance to see it --
                        # meaning Step 5's entire merge-back-into-
                        # predecessor logic was dead code, since by the
                        # time it ran, every tie_continuation flag had
                        # already been wiped. That's what caused
                        # cross-barline ties to become two independently
                        # struck notes ("double strikes") instead of one
                        # merged, continuous note. Leave the marker
                        # intact here; Step 5 is responsible for
                        # clearing it (only on the orphan fallback path,
                        # where no predecessor was found to merge into).
                        if is_staccato and nc.articulation == "":
                            nc.articulation = "staccato"
                        baked_notes.append(nc)

                    # If chosen < available, the gap is a rest.
                    # We don't create MidiNote objects for rests — they are
                    # implicit in the score as absence of notes.  The renderer
                    # and to_ly() fill these gaps with rest symbols when they
                    # see no note at the cursor position.  Nothing to do here.

            # ── Step 5: merge any remaining tie-continuation notes ────────────
            # Rationalize() may have placed continuations whose onset still
            # falls outside the predecessor's snapped window.  Merge them now.
            baked_notes.sort(key=lambda n: n.tick)
            merged: list = []
            last_of_pitch: dict = {}  # pitch → index into merged[]
            for n in baked_notes:
                if getattr(n, "articulation", "") == "tie_continuation":
                    idx = last_of_pitch.get(n.pitch)
                    if idx is not None:
                        pred = merged[idx]
                        pred.duration = (n.tick + n.duration) - pred.tick
                        continue
                    # Orphan: no predecessor found to merge into (e.g. the
                    # predecessor note was itself dropped/clipped to zero
                    # length somewhere upstream). Falls through to being
                    # appended as its own note below -- clear the marker
                    # so it doesn't carry a meaningless 'tie_continuation'
                    # tag into the final, exported note data.
                    n = _bk.copy(n)
                    n.articulation = ""
                nc = _bk.copy(n)
                last_of_pitch[nc.pitch] = len(merged)
                merged.append(nc)

            out_tr.notes = merged
            out.tracks.append(out_tr)

        return out

    def to_ly(self, path, show_bar_numbers=True, staff_size=16):
        r"""Export to LilyPond 2.26+ format.
        Design decisions:
            * Uses \\absolute pitch mode — no relative-interval arithmetic errors.
            * Piano/keyboard tracks get a PianoStaff grand staff; split point
              found dynamically (largest pitch gap in the piece).
            * Drum tracks (channel 9) get a percussion staff.
            * Other tracks: clef chosen by median pitch of notes.
            * Note durations snapped with upward bias (performers release early).
            * Chord window 50 ticks (~50 ms at 120 BPM) for live recordings.
            * \\paper targets US Letter with tight spacing for good packing.
            * Dense chords thinned to 6 notes to avoid LilyPond layout crashes.
        Parameters:
            show_bar_numbers : bool — print bar numbers at each system start.
            staff_size       : int  — global staff size in points (default 16;
                                      LilyPond default 20 — smaller = more systems
                                      per page).
        """

        tpb = self.ticks_per_beat
        mmap = self.get_measure_map()
        tpm = mmap[0][5] if mmap else self.ticks_per_measure()  # first measure tpm (for compat)
        n_meas = len(mmap)
        title = os.path.splitext(os.path.basename(path))[0]

        # v22x: compute the filtered (non-empty) track list and a dynamic
        # `indent` value BEFORE the \paper block is written, fixing a real
        # bug: indent was hardcoded to 0in regardless of instrumentName
        # length.  A long track name (e.g. a raw MIDI file's original
        # channel/instrument label, "Ch 1 - Acoustic Grand Piano") combined
        # with indent=0in left NO horizontal space reserved for that label,
        # confirmed via an exported .ly file to collide with — and visually
        # suppress — the \clef sign at the very start of the first system.
        # Short names ("Piano", from an RH/LH merge — see v22u) never hit
        # this, which is exactly why only some files showed the bug.
        # Fix: reserve indent proportional to the longest instrument name
        # that will actually be used in THIS score, clamped to a sane range.
        _ly_track_list_preview = [tr for tr in self.tracks if tr.notes]
        _longest_name_len = max((len(tr.name) for tr in _ly_track_list_preview), default=5)
        # ~0.09in per character is a reasonable estimate for the default
        # instrument-name font at staff-size 16; clamp so a very long name
        # can't blow out the page and a very short one still gets a
        # sensible minimum (LilyPond's own default is roughly 1.5-2in).
        _dynamic_indent_in = max(1.2, min(3.0, 0.6 + _longest_name_len * 0.09))

        print("[LY] Export started")

        def W(f, s=""):
            f.write(s + "\n")

        # ===============================================================================================================

        # ── helpers ──────────────────────────────────────────────────────────

        def snap_note(ticks, available=None):
            """Snap note duration to vocabulary from raw duration only (v22r).

            available is a hard cap — never used to select among candidates.
            A 200-tick note snaps to sixteenth (240) whether available is 240
            or 480.  The gap between chosen and available is rendered as an
            explicit rest in the LilyPond output, not silently absorbed.

            Quarter and larger: snap UP if ticks >= 60% of the next value.
            Sub-quarter (eighth and shorter): snap DOWN from raw duration.
            """
            if available is None:
                available = ticks * 4
            if ticks >= tpb:
                # Quarter or larger: upward snap with 60% bias
                for v in sorted(_STD_VALS, reverse=True):
                    if ticks >= v:
                        return min(v, available)
                    if ticks >= v * 0.60:
                        return min(v, available)
                return min(_STD_VALS[-1], available)
            else:
                # Sub-quarter: snap DOWN from raw duration, cap at available
                candidates = [v for v in _STD_VALS if v <= ticks * 1.5]
                if not candidates:
                    candidates = list(_STD_VALS)
                return min(max(candidates), available)

        def snap_rest(ticks):
            """Snap rest duration DOWN to the largest standard value that fits."""
            return best_dur_le(max(1, int(ticks)))

        # ── Standard duration table (ticks → LilyPond string) ────────────────
        # RULE (v22j, relaxed in v22ze): dotted eighth/sixteenth restored --
        # see the matching note in bake_to_score's _STD_VALS above for the
        # full reasoning. This also brings notes and rest_seq's rest
        # vocabulary (below) into full agreement.
        _STD_DURS = [
            (tpb * 4, "1"),
            (tpb * 3, "2."),  # dotted half
            (tpb * 2, "2"),
            (tpb * 3 // 2, "4."),  # dotted quarter
            (tpb, "4"),
            (tpb * 3 // 4, "8."),  # dotted eighth
            (tpb // 2, "8"),
            (tpb * 3 // 8, "16."),  # dotted sixteenth
            (tpb // 4, "16"),
            (tpb // 8, "32"),  # 32nd — NO dotted-32nd
            (tpb // 16, "64"),
        ]
        _STD_DURS = [(v, s) for v, s in _STD_DURS if v > 0]
        _STD_VALS = [v for v, _ in _STD_DURS]

        def dur_str(ticks):
            """Return the LilyPond duration string for the closest standard value."""
            return min(_STD_DURS, key=lambda x: abs(x[0] - ticks))[1]

        def best_dur_le(ticks):
            """Return the largest standard tick value that is <= ticks.

            v22zd: returns 0 (not _STD_VALS[-1]) when ticks is smaller than
            the shortest notatable value (a 64th note) -- see the matching
            fix in bake_to_score's _best_dur_le for the full explanation.
            Callers (rest_seq) must skip emitting anything when this
            returns 0 rather than treating it as a valid duration.
            """
            candidates = [v for v in _STD_VALS if v <= ticks]
            return max(candidates) if candidates else 0

        def rest_seq(ticks):
            # Greedy decomposition of a tick gap into LilyPond rest strings.
            #
            # v22ze update: this table includes r8. (dotted eighth) and
            # r16. (dotted sixteenth), which used to be a deliberate
            # asymmetry with the NOTE duration vocabulary (_STD_VALS
            # below excluded them, per the old v22j rule). That rule has
            # since been relaxed -- dotted eighths/sixteenths are
            # ordinary notation and are now allowed for notes too (see
            # _STD_DURS above) -- so notes and rests agree again down to
            # the sixteenth-note level. Kept this note for history: this
            # asymmetry was never the cause of the bar-overshoot bug
            # (rest_seq's own decomposition was always correctly bounded
            # by `rem` and could never overshoot its gap) -- the real
            # cause was dur_str's nearest-match rounding, fixed via
            # chosen = best_dur_le(chosen) above.
            table = [
                (tpb * 4, "r1"),
                (tpb * 3, "r2."),
                (tpb * 2, "r2"),
                (tpb * 3 // 2, "r4."),
                (tpb, "r4"),
                (tpb * 3 // 4, "r8."),
                (tpb // 2, "r8"),
                (tpb * 3 // 8, "r16."),
                (tpb // 4, "r16"),
                (tpb // 8, "r32"),
                (tpb // 16, "r64"),
            ]
            table = [(v, s) for v, s in table if v > 0]
            result = []
            rem = int(ticks)
            for val, sym in table:
                while rem >= val:
                    result.append(sym)
                    rem -= val
            # v22ze: also return the number of ticks actually consumed
            # (== ticks minus whatever undecomposable residual was
            # dropped, per the v22zd fallback-removal note below).
            # The tail-fill call site was previously discarding this and
            # never advancing `cursor` to match, which didn't affect the
            # actual written notation (rest_seq's tokens were appended to
            # mstr correctly either way) but did make the [measure]
            # actual=/delta= diagnostic under-report -- e.g. showing
            # delta=-960 for a measure whose real notated content, on
            # inspection of the written .ly, was already a correct 1920.
            consumed = int(ticks) - rem
            # v22zd: return whatever was actually decomposed, INCLUDING
            # empty.  The old fallback `if result else ["r4"]` fabricated
            # a full QUARTER-NOTE rest (480 ticks at tpb=480) whenever the
            # gap was smaller than the shortest notatable value (a 64th
            # note, tpb//16) -- e.g. a genuine 1-tick rounding residual
            # could get "filled" with a 480-tick rest, a massive overshoot.
            # A gap too small to notate should simply be dropped (absorbed
            # into the neighboring note/rest), not replaced with an
            # arbitrary, unrelated duration.  Found via an isolated test
            # rig reproducing this exact logic (testrig/measure_writer.py),
            # while investigating a confirmed "bar check failed" overshoot
            # reported by LilyPond itself.
            return result, consumed

        # v22ze fix: pitch_ly used to hardcode sharp-only spelling
        # (cis/dis/fis/gis/ais) regardless of key -- so a piece in a flat
        # key (e.g. G minor, 2 flats) got every Bb/Eb spelled as ais/dis
        # instead of bes/ees. That's wrong on its own (doesn't match how
        # the piece is actually notated in any real edition), and it also
        # defeats the \key directive just added to globalSettings above:
        # LilyPond only suppresses a redundant printed accidental when
        # the note's spelling matches what the key signature implies --
        # "ais" in a piece keyed to 2 flats doesn't match "bes", so it
        # still gets an explicit accidental every time regardless of the
        # key signature being correct. Pick flat vs sharp spelling once,
        # for the whole piece, from the same key_sig used for \key.
        _FLAT_KEYS = {
            "F",
            "Bb",
            "Eb",
            "Ab",
            "Db",
            "Gb",
            "Cb",
            "Dm",
            "Gm",
            "Cm",
            "Fm",
            "Bbm",
            "Ebm",
            "Abm",
        }
        _use_flats = getattr(self, "key_sig", "C") in _FLAT_KEYS
        _SHARP_NAMES = [
            "c",
            "cis",
            "d",
            "dis",
            "e",
            "f",
            "fis",
            "g",
            "gis",
            "a",
            "ais",
            "b",
        ]
        _FLAT_NAMES = [
            "c",
            "des",
            "d",
            "ees",
            "e",
            "f",
            "ges",
            "g",
            "aes",
            "a",
            "bes",
            "b",
        ]

        _LY_LETTER = {0: "c", 2: "d", 4: "e", 5: "f", 7: "g", 9: "a", 11: "b"}
        _LY_SUFFIX = {-2: "eses", -1: "es", 0: "", 1: "is", 2: "isis"}

        def _ly_octave_suffix(note, midi_pitch):
            oct_idx = midi_pitch // 12
            diff = oct_idx - 5  # 0 → C4 = c'
            if diff >= 0:
                return note + "'" * (diff + 1)
            else:
                ticks_below = -diff - 1
                return note + "," * ticks_below if ticks_below > 0 else note

        def pitch_ly(note_or_pitch):
            # MIDI pitch (or MidiNote) → LilyPond absolute note name.
            #
            # v22ze-54 fix: this used to spell every note purely from the
            # piece's global key signature (see _use_flats above), with
            # no way to honor a note's explicit forced accidental — the
            # exact same architecture gap note_staff_pos() fixed for the
            # on-screen renderer (see its docstring for the full story).
            # A note pinned to a specific sharp/flat via the Accidental
            # tool could round-trip through LilyPond export spelled
            # differently than what's shown on screen. Accepts either a
            # MidiNote (checked for .spelling first) or a bare int pitch
            # (always falls back to the key-based spelling below, so
            # every pre-existing call site that only ever had an int
            # keeps behaving exactly as before).
            spelling = getattr(note_or_pitch, "spelling", "") or ""
            midi_pitch = note_or_pitch.pitch if hasattr(note_or_pitch, "pitch") else note_or_pitch
            acc = _SPELL_ACC_DELTA.get(spelling)
            if acc is not None:
                natural_pitch = midi_pitch - acc
                letter = _LY_LETTER.get(natural_pitch % 12)
                if letter is not None:  # sanity check — should always hold
                    return _ly_octave_suffix(letter + _LY_SUFFIX[acc], midi_pitch)
            names = _FLAT_NAMES if _use_flats else _SHARP_NAMES
            return _ly_octave_suffix(names[midi_pitch % 12], midi_pitch)

        def thin_chord(notes, max_notes=6):
            # Keep outer voices if chord has too many notes.
            if len(notes) <= max_notes:
                return notes
            notes_s = sorted(notes, key=lambda n: n.pitch)
            keep = max_notes // 2
            return notes_s[:keep] + notes_s[-keep:]

        # ── dynamic piano split ───────────────────────────────────────────────
        # v22ze-27 fix (housekeeping item 8): find_split_pitch used to be
        # defined here, nested inside to_ly(), while ScoreView had its
        # own separate _find_gap_split() -- a DIFFERENT algorithm (one
        # global split for the whole piece here, vs a fresh split
        # recomputed per individual chord there). That's why the on-
        # screen raw view and the Lilypond export could visibly diverge
        # for un-rationalized data: two independent implementations of
        # "find the hand split" will drift, and per-chord vs whole-piece
        # splitting is a structurally different result, not just a
        # tuning difference. Hoisted to _find_split_pitch_for_track() at
        # module level (below) so both to_ly() and ScoreView call the
        # exact same function on the exact same data -- they agree by
        # construction now, not by coincidence.
        def find_split_pitch(notes):
            return _find_split_pitch_for_track(
                notes, prefer_lh_octaves=getattr(self, "prefer_lh_octaves", True)
            )

        def build_measure_str(notes_in_meas, cursor_start, measure_tpm):
            """Grid-based measure builder — guarantees clean standard note values.

            Algorithm:
              1. Snap every note's START TICK to the nearest 16th-note grid point
                 within this measure.
              2. Group same-grid-tick notes into chords.
              3. For each chord, choose the largest standard duration that fits
                 in the space up to the NEXT chord (or end of measure).
              4. Fill gaps with rests using standard values only.
            Because every tick is on the grid, rest_seq always produces clean output.
            """

            grid = max(1, tpb // NOTATION_DIVISION)  # user-selectable notation grid
            budget = int(measure_tpm)

            # ── Step 1: snap note positions to grid ───────────────────────────
            snapped_notes = []
            for n in notes_in_meas:
                rel = int(n.tick) - cursor_start  # offset within measure
                qraw = round(rel / grid) * grid  # nearest grid point

                # v22ze: this used to be an if/else on
                # `abs(rel - qraw) <= grace_ticks(tpb)` ("grace timing
                # noise suppression" -- snap to grid only if close enough,
                # else... also snap to grid).  Both branches set q = qraw,
                # so the conditional never did anything; removed along
                # with the now-unused grace_ticks(tpb) call above. If
                # grace-note timing tolerance is meant to do something
                # different here (e.g. leave far-off notes unsnapped),
                # that behavior needs to be designed and added back
                # deliberately, not left as dead code.
                q = qraw

                q = max(0, min(budget - grid, q))  # clamp inside measure
                snapped_notes.append((q, n))

            snapped_notes.sort(key=lambda x: x[0])

            # ── Step 2: group same-tick notes into chords ─────────────────────
            groups = []  # [(grid_tick, [notes...])]
            for q, n in snapped_notes:
                if groups and groups[-1][0] == q:
                    groups[-1][1].append(n)
                else:
                    groups.append((q, [n]))

            # ── Step 3 & 4: build token list ──────────────────────────────────
            mstr = []
            # v22ze: parallel list, same length as mstr, classifying each
            # token as 'staccato' / 'note' / 'rest' -- used below to find
            # runs of 2+ consecutive staccato notes with no intervening
            # rest, for the portato slur heuristic (staccato dot AND a
            # phrase slur together, as seen in the published score).
            mstr_kind = []
            cursor = 0  # ticks consumed in this measure

            for i, (tick, chord) in enumerate(groups):
                next_tick = groups[i + 1][0] if i + 1 < len(groups) else budget

                # Rest gap before this chord (always on-grid)
                if tick > cursor:
                    gap = tick - cursor
                    for rs in rest_seq(gap)[0]:
                        mstr.append(rs)
                        mstr_kind.append("rest")
                    cursor = tick
                elif tick < cursor:
                    # Overlap: this chord's snapped tick falls inside the previous
                    # note — skip it to avoid double-filling.
                    continue

                # Note duration: snap from raw duration (v22r) — available
                # is a hard cap only, not a selection criterion.  Any gap
                # between chosen and next onset becomes an explicit rest.
                available = next_tick - tick
                if available <= 0:
                    continue
                raw_dur = max(n.duration for n in chord)
                chosen = snap_note(raw_dur, available)
                if chosen <= 0:
                    # v22zd: fall back to `available` itself, not a fixed
                    # `grid` unit.  best_dur_le(available) can now return 0
                    # when available is smaller than the shortest notatable
                    # value (a 64th note) -- see best_dur_le's docstring.
                    # The old "or grid" fallback could then set chosen to a
                    # FULL grid unit (e.g. 120 ticks) even when available
                    # was only a few ticks, reintroducing the exact
                    # overshoot this fix is meant to eliminate.  Falling
                    # back to `available` guarantees chosen never exceeds
                    # the space actually left in the measure.
                    chosen = best_dur_le(available) or available

                # v22ze fix: `chosen` may not itself be a standard notatable
                # duration -- e.g. when capped by `available` to an odd
                # multiple of the grid such as 360 or 600 ticks (values
                # excluded from the note vocabulary by the "no sub-quarter
                # dotted values" rule below).  dur_str() picks the NEAREST
                # standard duration by absolute distance, which can round
                # UP past `chosen` -- e.g. dur_str(360) returns "4" (a
                # 480-tick quarter note) because 480 and 240 are equidistant
                # and 480 sorts first in the table.  The written note then
                # represents MORE ticks than were ever budgeted, even though
                # `cursor` below is bumped using the correctly-capped
                # `chosen` -- a silent mismatch between what's accounted
                # for internally and what's actually printed to the file.
                # This is invisible to the [measure] diagnostic a few
                # screens down, because that diagnostic sums `chosen`, not
                # the written token -- which is exactly why every diagnostic
                # log ever captured for this bug showed delta <= 0 (only
                # ever undershoot) while LilyPond's own bar-checker, reading
                # the actual written notation, reported real overshoot.
                # Confirmed via direct instrumentation: every occurrence of
                # chosen in {360, 600, 840, ...} (available capped to an
                # odd multiple of the 16th-note grid) produced a written
                # duration exactly 120 ticks (1/16 of a 4/4 measure) larger
                # than `chosen`, matching the "+2/32 per measure" overshoot
                # pattern originally observed in C1Prelude5-v22zd.ly.
                # Flooring `chosen` down to the nearest standard value
                # at-or-below itself, BEFORE deriving both the LilyPond
                # token and the cursor advance from the same number, means
                # the two can never again disagree.
                chosen = best_dur_le(chosen) or chosen

                chord_notes = thin_chord(sorted(chord, key=lambda n: n.pitch))
                ds = dur_str(chosen)
                # Staccato: note is marked staccato by bake_to_score(), OR
                # the raw performed duration is < 75% of the snapped value
                # (catches notes not yet baked but clearly short).
                stac_count = sum(
                    1
                    for n in chord_notes
                    if (
                        getattr(n, "articulation", "") == "staccato"
                        or (n.duration < chosen * 0.75 and chosen <= tpb // 2)
                    )
                )
                stac_sfx = "-." if stac_count > len(chord_notes) / 2 else ""
                if len(chord_notes) == 1:
                    mstr.append(pitch_ly(chord_notes[0]) + ds + stac_sfx)
                else:
                    pitches = " ".join(pitch_ly(n) for n in chord_notes)
                    mstr.append("<" + pitches + ">" + ds + stac_sfx)
                mstr_kind.append("staccato" if stac_sfx else "note")

                cursor = tick + chosen

                # v22zb: REMOVED a redundant "fill gap to next chord" block
                # that used to sit here.  It emitted a rest for
                # (next_tick - cursor) WITHOUT advancing cursor to match —
                # so the very same gap got filled a SECOND time, either by
                # the top-of-loop "if tick > cursor" check on the next
                # iteration, or by the tail-fill step below for the last
                # chord in a measure.  Confirmed by hand: a measure that
                # should sum to exactly 32/32 (4/4) was instead summing to
                # 47/32 — a 15/32 excess LilyPond's own bar-checker caught
                # directly.  The top-of-loop mechanism alone already fills
                # every such gap correctly; no separate block was needed.

            # ── Fill tail with rests ─────────────────────────────────────────
            if cursor < budget:
                _tail_rests, _tail_consumed = rest_seq(budget - cursor)
                for rs in _tail_rests:
                    mstr.append(rs)
                    mstr_kind.append("rest")
                # v22ze fix: advance cursor by what rest_seq actually wrote,
                # not just leave it where the last note ended. Previously
                # `cursor` was never updated here, so the diagnostic below
                # (and anything else inspecting cursor after this point)
                # under-reported a measure as short by however much tail
                # rest content was appended, even when that content was
                # written to the file correctly and the measure was, in
                # fact, complete. Confirmed via a real repro: measure #2
                # of a live session reported "actual=960 delta=-960" here
                # while the written .ly line for that measure summed to a
                # correct, full 1920 ticks (...ending in a clean r2).
                cursor += _tail_consumed

            # Diagnostic: first 12 measures only
            try:
                if not hasattr(self, "_measure_diag_count"):
                    self._measure_diag_count = 0
                    self._measure_diag_errors = 0

                if self._measure_diag_count < 12:
                    actual_ticks = cursor
                    delta = actual_ticks - budget

                    print(
                        f"[measure] #{self._measure_diag_count+1} actual={actual_ticks} expected={budget} delta={delta}"
                    )

                    if delta != 0:
                        self._measure_diag_errors += 1

                    self._measure_diag_count += 1

                    if self._measure_diag_count == 12:
                        print(
                            f"[measure-check] checked first 12 measures, {self._measure_diag_errors} mismatches"
                        )
            except Exception as e:
                print(f"[measure-check] diagnostic error: {e}")

            # v22ze: portato heuristic -- best-effort, not a general slur/
            # phrase-detection engine (see the discussion this came from:
            # a slur is fundamentally a phrasing decision, not something
            # with a clean acoustic signature the way staccato is).
            # Narrow, defensible scope: wrap runs of 2+ CONSECUTIVE
            # already-detected staccato notes/chords, with no rest
            # breaking the run, in a LilyPond phrasing slur \( \) --
            # exactly the "staccato dot + slur together" articulation
            # (portato / mezzo staccato) reported in the published score.
            # Scoped to within one measure only; a phrase slur that
            # genuinely continues across a barline would need state
            # threaded between calls to this function, which is a bigger
            # change than this heuristic's intended scope.
            run_start = None
            for i, kind in enumerate(mstr_kind + ["__end__"]):
                if kind == "staccato":
                    if run_start is None:
                        run_start = i
                else:
                    if run_start is not None and i - run_start >= 2:
                        mstr[run_start] += r"\("
                        mstr[i - 1] += r"\)"
                    run_start = None

            return " ".join(mstr) if mstr else "r1"

        def clef_for_median(notes):
            # Choose treble or bass clef based on median pitch.
            if not notes:
                return "treble"
            pitches = sorted(n.pitch for n in notes)
            median = pitches[len(pitches) // 2]
            return "bass" if median < 57 else "treble"

        def is_piano(tr):
            return 0 <= tr.program <= 7

        def analyze_velocity(notes):
            """Analyze velocity distribution in notes.
            Returns (min_vel, max_vel, mean_vel, velocities_by_measure)."""
            if not notes:
                return 64, 64, 64, {}

            velocities = [n.velocity for n in notes if n.velocity > 0]
            if not velocities:
                return 64, 64, 64, {}

            min_vel = min(velocities)
            max_vel = max(velocities)
            mean_vel = sum(velocities) / len(velocities)

            # Group velocities by measure index (using mmap for correct boundaries)
            vel_by_meas = {}
            for n in notes:
                m_idx = 0
                for idx, ms, me, _n, _d, _t in mmap:
                    if ms <= n.tick < me:
                        m_idx = idx
                        break
                if m_idx not in vel_by_meas:
                    vel_by_meas[m_idx] = []
                if n.velocity > 0:
                    vel_by_meas[m_idx].append(n.velocity)

            # Average velocity per measure
            for m in vel_by_meas:
                vel_by_meas[m] = sum(vel_by_meas[m]) / len(vel_by_meas[m])

            return min_vel, max_vel, mean_vel, vel_by_meas

        def velocity_to_dynamic(velocity, min_vel, max_vel):
            """Map MIDI velocity (0–127) to LilyPond dynamic marking.
            ppp=17, pp=33, p=49, mp=65, mf=81, f=97, ff=113, fff=127."""
            dynamics = [
                (17, r"\ppp"),
                (33, r"\pp"),
                (49, r"\p"),
                (65, r"\mp"),
                (81, r"\mf"),
                (97, r"\f"),
                (113, r"\ff"),
                (127, r"\fff"),
            ]

            # Clamp velocity to min/max range in this piece
            vel = max(min_vel, min(max_vel, velocity))

            # Find closest dynamic
            best_dyn = r"\mf"
            best_dist = 999
            for threshold, dyn in dynamics:
                dist = abs(vel - threshold)
                if dist < best_dist:
                    best_dist = dist
                    best_dyn = dyn

            return best_dyn

        # v22za: MAX_MEASURES_PER_SYSTEM (\break every N measures) was
        # REMOVED here.  It caused measures to overflow the page: \break
        # is an unconditional instruction, so a genuinely dense passage
        # landing inside a forced 6-measure group had no way to get the
        # extra room it needed — LilyPond couldn't break earlier to
        # relieve it, since we'd already told it exactly where to break.
        # LilyPond's own automatic line-breaking already respects
        # line-width by construction, choosing MORE measures per line on
        # sparse passages and FEWER on dense ones, guided by the
        # per-measure spacing-increment below.  That was working
        # correctly before the hard cap overrode it.

        def compute_measure_density(notes, mmap):
            """Return {m_idx: attacks_per_beat} across the given notes.

            v22z: used to drive a PER-MEASURE spacing-increment override
            instead of one fixed value for the whole piece.  A single global
            increment is always a compromise — too loose on sparse measures,
            too tight on dense ones (confirmed: even spacing-increment=2.2
            was not enough to keep a Rachmaninoff-density passage from
            overflowing the page width, while that same value would be
            needlessly loose on a simple, sparse measure elsewhere).

            v22ze fix: this used to count every individual NOTE instance
            (`sum(1 for n in notes if ...)`), not distinct attacks. A thick
            chord -- entirely normal, unremarkable Rachmaninoff piano
            writing -- has several notes stacked on the SAME onset, but
            takes essentially the same horizontal space to engrave as a
            single note of that duration; it's the number of separate
            onsets in sequence that drives horizontal spacing, not how
            many pitches are stacked at each one. Counting raw notes
            conflated chord thickness with rhythmic density, so a
            passage of e.g. 4 chord-attacks/beat with 4-note chords in
            each hand (16 raw notes/beat combined -- ordinary, not
            unusually dense, writing) landed in the SAME top spacing
            tier as a genuinely fast passage of 16 separate attacks/beat,
            inflating spacing-increment for nearly every measure of a
            real, consistently chordal piece and forcing one measure per
            system throughout, rather than only for passages that are
            actually rhythmically dense. Counting distinct onset ticks
            (snapped to a 16th-note grid, matching the granularity
            build_measure_str itself notates at) instead of raw notes
            fixes this.
            """
            density = {}
            grid = max(
                1, tpb // 4
            )  # 16th-note grid -- same attack granularity build_measure_str notates at
            for m_idx, ms, me, num, den, tpm in mmap:
                attack_ticks = set()
                for n in notes:
                    if ms <= n.tick < me:
                        attack_ticks.add(round((n.tick - ms) / grid))
                beats = max(1, num)
                density[m_idx] = len(attack_ticks) / beats
            return density

        def spacing_increment_for_density(d):
            """Map notes-per-beat to a LilyPond spacing-increment value.

            LilyPond's own default is 1.2.  These thresholds were chosen
            empirically as a starting point — dense virtuosic passages
            (Rachmaninoff-style fast chords/arpeggios) commonly run well
            past 8 notes/beat combined across both hands.

            v22za: added a higher extreme-density tier (>14) as extra
            safety margin, now that the hard \\break-every-N-measures cap
            has been removed — that cap was, in effect, also acting as a
            crude overflow guard; without it, the very densest measures
            need spacing-increment alone to keep them from overflowing.
            """
            if d <= 2:
                return 1.2
            if d <= 4:
                return 2.0
            if d <= 8:
                return 3.2
            if d <= 14:
                return 4.5
            return 6.0

        def detect_clef_runs(notes, mmap, home_clef):
            """Find contiguous runs of measures whose content sits clearly
            in the OPPOSITE clef's comfortable range.

            v22ze: this mirrors logic that already existed for the
            interactive score view (bass_treble_measures, in the Tk
            canvas renderer) but was never ported to the LilyPond export
            -- to_ly() picked a single clef per voice for the whole piece
            via clef_for_median() and left it there, so a passage that
            temporarily crosses into the other clef's range just
            accumulates ledger lines in print instead of getting a
            temporary clef change the way the screen view (partially)
            already showed one. This generalizes the on-screen check
            (which only handled LH climbing into treble range) to both
            directions: a LH passage sitting entirely above middle C, or
            a RH passage sitting entirely below it, for a contiguous run
            of measures, gets a temporary opposite clef with a clef
            change back afterward -- standard published-score engraving
            practice (see e.g. Henle/Schirmer editions) for exactly this
            situation, and consistent with what the interactive view
            already does for the LH-too-high case.

            v22ze update: this originally used raw pitch thresholds
            (pitch>59 / pitch<60) with no position pre-filter, while the
            screen's equivalent used a position-based pre-filter plus
            slightly different thresholds (pitch<64 for the treble-low
            case). Two independently-tuned versions of the same check,
            reported as a real, visible mismatch -- the screen and the
            exported LilyPond disagreeing about which measures needed a
            temporary clef change for the exact same file. Now uses the
            identical pitch_to_staff-based logic the screen uses, so
            both paths derive the same answer from the same rule instead
            of two hand-tuned approximations of it.

            v22ze-71 fix: this "v22ze update" (above) unified the pitch
            thresholds with the screen's check, but that happened BEFORE
            v22ze-67 further tightened the screen's version -- requiring
            at least 2 corroborating notes (not just one) and a stricter
            treble-side threshold (<60, not <64) -- specifically because
            a single borderline note in a not-yet-hand-split measure was
            enough to flip an entire staff's clef incorrectly. This copy
            never got that second fix, so it could still trigger falsely
            on exactly the same single-note case v22ze-67 fixed on
            screen -- confirmed directly: the same real file rendered
            correctly (treble at the opening) in this app's own score
            view, but exported with bass clef misapplied. Now uses the
            identical, fully-updated thresholds.

            Returns (enter_at, revert_at): sets of measure indices.
            enter_at measures get a \\clef <opposite> just before their
            content; revert_at measures get a \\clef <home> just before
            theirs.
            """
            _use_flats = _song_uses_flats(self)
            opposite_measures = set()
            for m_idx, ms, me, num, den, tpm in mmap:
                mn = [n for n in notes if ms <= n.tick < me]
                if not mn:
                    continue
                if home_clef == "bass":
                    cluster = [n for n in mn if note_staff_pos(n, _use_flats)[0] < 2]
                    if len(cluster) >= 2 and all(n.pitch > 64 for n in cluster):
                        opposite_measures.add(m_idx)
                elif home_clef == "treble":
                    cluster = [n for n in mn if note_staff_pos(n, _use_flats)[0] >= -2]
                    if len(cluster) >= 2 and all(n.pitch < 60 for n in cluster):
                        opposite_measures.add(m_idx)

            enter_at, revert_at = set(), set()
            if opposite_measures:
                sorted_ms = sorted(opposite_measures)
                runs = []
                run_start = run_end = sorted_ms[0]
                for m in sorted_ms[1:]:
                    if m == run_end + 1:
                        run_end = m
                    else:
                        runs.append((run_start, run_end))
                        run_start = run_end = m
                runs.append((run_start, run_end))
                for rs, re in runs:
                    enter_at.add(rs)
                    revert_at.add(re + 1)
            return enter_at, revert_at

        def write_voice(f, vn, notes, clef_name, mmap, density_map=None, emit_spacing=False):
            """Write a single \\absolute voice variable with per-measure time sigs.

            density_map / emit_spacing (v22z): when emit_spacing is True and
            a density_map is supplied, a \\once \\override
            Score.SpacingSpanner.spacing-increment is written at the start
            of each measure, sized to that measure's actual note density.
            Only ONE voice per staff pair should pass emit_spacing=True --
            it's a Score-wide property, so emitting it from both treble and
            bass would just be redundant, not wrong, but the treble voice
            is written first and is the natural single source.
            """
            W(f, vn + r" = \absolute {")
            W(f, r"  \globalSettings")

            opposite_clef = "bass" if clef_name == "treble" else "treble"
            clef_enter_at, clef_revert_at = detect_clef_runs(notes, mmap, clef_name)

            # v22ze-71 fix: this used to unconditionally write \clef
            # <clef_name> here, THEN separately, in the per-measure loop
            # below, write \clef <opposite_clef> again immediately if the
            # very first measure was flagged as needing the opposite clef
            # (the same "opens low"/"opens high" heuristic fixed on the
            # screen side, v22ze-67) -- producing two contradictory clef
            # declarations back to back with no notes between them (e.g.
            # "\clef treble \clef bass"). LilyPond's own renderer silently
            # uses whichever comes last, so this was invisible in our own
            # PDF output -- confirmed directly against a real file where
            # LilyPond's PDF rendering matched this app's own score view
            # correctly despite the redundant pair being present. But
            # python-ly's musicxml converter, fed the exact same text,
            # picked up the FIRST (wrong) clef instead and produced a
            # grand staff with bass clef on both staves and all content
            # crammed into one -- confirmed directly against a real
            # exported file and reported independently by both MuseScore
            # (flagged the file invalid) and Rosegarden (crashed on it).
            # Only write the home clef here if the first measure ISN'T
            # about to override it anyway.
            if mmap and mmap[0][0] not in clef_enter_at:
                W(f, r"  \clef " + clef_name)

            min_vel, max_vel, mean_vel, vel_by_meas = analyze_velocity(notes)
            use_dynamics = (max_vel - min_vel) > 20
            prev_dyn = None
            prev_num, prev_den = None, None  # force \time on first measure

            for m_idx, ms, me, num, den, tpm in mmap:
                if m_idx in clef_enter_at:
                    W(f, r"  \clef " + opposite_clef)
                elif m_idx in clef_revert_at:
                    W(f, r"  \clef " + clef_name)

                if emit_spacing and density_map is not None:
                    _incr = spacing_increment_for_density(density_map.get(m_idx, 0))
                    W(
                        f,
                        f"  \\once \\override Score.SpacingSpanner.spacing-increment = #{_incr}",
                    )

                # Emit \time directive when time signature changes
                if num != prev_num or den != prev_den:
                    W(f, f"  \\time {num}/{den}")
                    prev_num, prev_den = num, den
                mn = [n for n in notes if ms <= n.tick < me]
                mstr = build_measure_str(mn, ms, tpm)

                if use_dynamics and mn and m_idx in vel_by_meas:
                    cur_vel = vel_by_meas[m_idx]
                    dyn = velocity_to_dynamic(cur_vel, min_vel, max_vel)
                    # Detect crescendo / diminuendo trends across measures
                    next_vel = vel_by_meas.get(m_idx + 1)
                    prev_vel = vel_by_meas.get(m_idx - 1)
                    trend_sfx = ""
                    if next_vel is not None and prev_vel is not None:
                        if next_vel - cur_vel > 8 and cur_vel - prev_vel > 8:
                            trend_sfx = r"\<"  # clear crescendo
                        elif cur_vel - next_vel > 8 and prev_vel - cur_vel > 8:
                            trend_sfx = r"\>"  # clear diminuendo
                    if dyn != prev_dyn or trend_sfx:
                        tokens = mstr.split()
                        first_note_idx = next(
                            (
                                i
                                for i, t in enumerate(tokens)
                                if t and not t.startswith("r") and not t.startswith("<")
                            ),
                            None,
                        )
                        if first_note_idx is None:
                            first_note_idx = next(
                                (i for i, t in enumerate(tokens) if t and t.startswith("<")),
                                None,
                            )
                        if first_note_idx is not None:
                            mark = ""
                            if dyn != prev_dyn:
                                mark += dyn
                                prev_dyn = dyn
                            if trend_sfx:
                                mark += trend_sfx
                            tokens[first_note_idx] = tokens[first_note_idx] + mark
                            mstr = " ".join(tokens)

                W(f, "  " + mstr + " |")
            W(f, "}\n")
            W(f)

            # ── Write file ────────────────────────────────────────────────────────

        with open(path, "w") as f:
            print(f"[LY] Writing: {path}")
            W(f, r'\version "2.26.0"')
            W(f)
            # ── Global staff size — smaller than default (20) packs more
            # systems per page.  16 pt is readable on US Letter at full size;
            # go to 14 for very dense scores.
            W(f, f"#(set-global-staff-size {staff_size})")
            W(f)
            W(f, r"\header {")
            W(f, r'  title = "' + title + r'"')
            W(f, r'  composer = ""')
            W(f, r"  tagline = ##f")  # suppress "Music engraving by LilyPond" footer
            W(f, r"}")
            W(f)
            # ── Paper block ────────────────────────────────────────────────
            # US Letter 8.5 × 11 in.
            # ragged-right = ##f  → systems STRETCH to fill page width
            #                       (eliminates the "2 measures on one line"
            #                        problem caused by ragged-right = ##t)
            # v22w: on very dense passages, ##f's forced stretching could
            # over-compress instead of over-stretch — fixed via
            # SpacingSpanner.spacing-increment in the \layout block below,
            # NOT by touching ragged-right (see that block's comment).
            # ragged-last  = ##t  → last system may be short (natural)
            # page-breaking = ly:optimal-breaking  → LilyPond decides how many
            #                       systems fit per page rather than us forcing it
            # system-system-spacing controls whitespace between systems on a page
            W(f, r"\paper {")
            W(f, r'  #(set-paper-size "letter")')
            W(f, f"  indent           = {_dynamic_indent_in:.2f}\\in")
            W(f, r"  short-indent     = 0\in")
            W(f, r"  left-margin      = 0.75\in")
            W(f, r"  right-margin     = 0.75\in")
            W(f, r"  top-margin       = 0.5\in")
            W(f, r"  bottom-margin    = 0.5\in")
            W(f, r"  line-width       = 7.0\in")
            # v22w: ragged-right stays ##f — a PRIOR fix (see comment above
            # this \paper block) deliberately chose ##f to avoid a "2
            # measures crammed onto one line with huge gaps" problem caused
            # by ##t.  Flipping it back to fix over-compression on dense
            # passages would likely reintroduce that older problem instead.
            # Safer fix: increase SpacingSpanner.spacing-increment (below,
            # in the \layout block) so LilyPond's own line-breaking chooses
            # FEWER measures per line on dense material — meaning less
            # stretching is needed to fill the line, without touching
            # ragged-right at all.
            W(f, r"  ragged-right     = ##f")
            W(f, r"  ragged-last      = ##t")
            W(f, r"  page-breaking    = #ly:optimal-breaking")
            # Tighten the gaps between systems so more fit per page.
            # Dot-notation sets individual spacing properties without
            # the multi-line alist syntax that LilyPond rejects.
            W(f, r"  system-system-spacing.basic-distance   = #12")
            W(f, r"  system-system-spacing.minimum-distance = #8")
            W(f, r"  system-system-spacing.padding          = #1")
            W(f, r"  score-system-spacing.basic-distance    = #12")
            W(f, r"  score-system-spacing.minimum-distance  = #8")
            W(f, r"  score-system-spacing.padding           = #1")
            W(f, r"}")

            W(f)
            W(f, r"globalSettings = {")
            # v22ze fix: this never emitted \key at all, so LilyPond
            # silently defaulted to C major/no-accidentals regardless of
            # the piece's actual key -- e.g. a G minor piece (2 flats)
            # got printed with zero key signature, forcing every single
            # Bb/Eb to carry an explicit accidental instead of being
            # implied once. LilyPond suppresses redundant printed
            # accidentals automatically once \key is correct, so this
            # doesn't require changing how individual notes are spelled
            # elsewhere -- it was purely a missing declaration.
            _key_tonic, _key_mode = key_sig_to_ly(getattr(self, "key_sig", "C"))
            W(f, r"  \key " + _key_tonic + " \\" + _key_mode)
            W(f, r"  \tempo 4 = " + str(self.bpm))
            W(f, r"}")
            W(f)

            # ── Generate voice variables ───────────────────────────────────
            import re

            # Helper: detect a pre-split RH/LH pair — either produced by
            # rationalize() ('X (RH)'/'X (LH)' suffix) or already present in
            # the source file under common hand-naming conventions ('Piano
            # right'/'Piano left', 'Right Hand'/'Left Hand', 'RH'/'LH' as
            # whole words).  Such pairs are combined into ONE PianoStaff
            # with NO pitch re-splitting — the hand assignment is already
            # correct, whether it came from our own DP or from the file
            # itself, and re-splitting by pitch would silently discard that.
            def _is_rh_lh_pair(ta, tb):
                if (
                    ta.name.endswith(" (RH)")
                    and tb.name.endswith(" (LH)")
                    and ta.name[:-5] == tb.name[:-5]
                ):
                    return True
                if _ly_hand_hint(ta.name) == "R" and _ly_hand_hint(tb.name) == "L":
                    return True
                # v22ze-29 fix (housekeeping item 8 regression, part 2):
                # ScoreView's pair-detector (_sv_rh_lh) has always had a
                # broader fallback here -- two consecutive same-
                # instrument-family piano tracks count as a pre-split
                # pair even without a name match (validated correct
                # against an actual printed page in an earlier fix).
                # This detector didn't have that fallback, so a pair the
                # screen correctly recognized (and rendered by trusting
                # each hand directly, no pitch re-splitting) could fall
                # through here into the OTHER merge-and-resplit branch
                # below -- which has the same "one outlier note skews
                # the whole-track split" vulnerability that was just
                # fixed on the screen side, but was never fixed here.
                # Mirroring the fallback makes the two detectors agree
                # by construction instead of by naming luck.
                return is_piano(ta) and is_piano(tb)

            def _ly_hand_hint(name):
                n = name.lower()
                if re.search(r"\bright\b|\brh\b", n):
                    return "R"
                if re.search(r"\bleft\b|\blh\b", n):
                    return "L"
                return None

            def _ly_pair_base_name(name):
                if name.endswith(" (RH)"):
                    return name[:-5]
                stripped = re.sub(r"\s*\b(right|rh)\b\s*", " ", name, flags=re.IGNORECASE).strip()
                return stripped if stripped else name

            score_entries = []
            # v22x: filter out tracks with no notes before generating any
            # staves.  Without this, every empty metadata track in a MIDI
            # file (a "Pedal" track with only CC64 events and no notes, a
            # composer-name track, a copyright-text track, an edition-info
            # track, etc.) got its own PianoStaff/Staff block full of empty
            # measures — repeated on EVERY page of the printed score.
            # Confirmed by screenshot: a Rachmaninoff file with one real
            # "Piano" track plus five empty metadata tracks printed as SIX
            # stacked staff-groups per system, bloating an otherwise normal
            # piece to 8 pages and starving each system of the vertical
            # space it needed, contributing to the reported page-overflow
            # and mid-piece staff-collapse symptoms.
            # The on-screen ScoreView has filtered empty tracks since v22a;
            # this brings the LilyPond exporter to the same standard.
            track_list = _ly_track_list_preview  # already computed above,
            # before the \paper block,
            # so indent and the actual
            # rendered tracks always agree
            ti = 0
            while ti < len(track_list):
                tr = track_list[ti]
                vbase = "trk" + chr(ord("a") + min(ti, 25))

                if ti + 1 < len(track_list) and _is_rh_lh_pair(tr, track_list[ti + 1]):
                    # ── Pre-split RH/LH pair from rationalize() ──────────────
                    # RH track → treble staff, LH track → bass staff.
                    # No pitch re-splitting: DP hand separation already ran.
                    tr_rh = tr
                    tr_lh = track_list[ti + 1]
                    notes_rh = sorted(tr_rh.notes, key=lambda n: n.tick)
                    notes_lh = sorted(tr_lh.notes, key=lambda n: n.tick)
                    v_treble = vbase + "R"
                    v_bass = vbase + "L"
                    base_name = _ly_pair_base_name(tr_rh.name)
                    print(f"[LY] RH/LH pair → single PianoStaff: {base_name!r}")
                    _density_map = compute_measure_density(notes_rh + notes_lh, mmap)
                    write_voice(
                        f,
                        v_treble,
                        notes_rh,
                        "treble",
                        mmap,
                        _density_map,
                        emit_spacing=True,
                    )
                    write_voice(f, v_bass, notes_lh, "bass", mmap)
                    entry = (
                        "    \\new PianoStaff <<\n"
                        '      \\set PianoStaff.instrumentName = #"' + base_name + '"\n'
                        "      \\new Staff { \\" + v_treble + " }\n"
                        "      \\new Staff { \\" + v_bass + " }\n"
                        "    >>"
                    )
                    score_entries.append(entry)
                    ti += 2  # consume both RH and LH tracks

                elif is_piano(tr):
                    # ── Piano track(s): always ONE grand staff ────────────────
                    # Merge consecutive piano channel-tracks (e.g. Format 0 MIDI
                    # split by channel) so we never produce 4 staves.
                    if (
                        ti + 1 < len(track_list)
                        and is_piano(track_list[ti + 1])
                        and not _is_rh_lh_pair(tr, track_list[ti + 1])
                    ):
                        merge_notes = sorted(
                            tr.notes + track_list[ti + 1].notes, key=lambda n: n.tick
                        )
                        base_name = tr.name.split(" - ")[-1] if " - " in tr.name else tr.name
                        ti_step = 2
                    else:
                        merge_notes = sorted(tr.notes, key=lambda n: n.tick)
                        base_name = tr.name
                        ti_step = 1
                    split = find_split_pitch(merge_notes)
                    v_treble = vbase + "R"
                    v_bass = vbase + "L"
                    t_notes = [n for n in merge_notes if n.pitch >= split]
                    b_notes = [n for n in merge_notes if n.pitch < split]
                    _density_map = compute_measure_density(merge_notes, mmap)
                    write_voice(
                        f,
                        v_treble,
                        t_notes,
                        "treble",
                        mmap,
                        _density_map,
                        emit_spacing=True,
                    )
                    write_voice(f, v_bass, b_notes, "bass", mmap)
                    entry = (
                        "    \\new PianoStaff <<\n"
                        '      \\set PianoStaff.instrumentName = #"' + base_name + '"\n'
                        "      \\new Staff { \\" + v_treble + " }\n"
                        "      \\new Staff { \\" + v_bass + " }\n"
                        "    >>"
                    )
                    score_entries.append(entry)
                    ti += ti_step

                else:
                    # ── Non-piano: single staff, clef by median pitch ─────────
                    notes = sorted(tr.notes, key=lambda n: n.tick)
                    clef = clef_for_median(notes)
                    print("[LY] Writing single staff")
                    _density_map = compute_measure_density(notes, mmap)
                    write_voice(f, vbase, notes, clef, mmap, _density_map, emit_spacing=True)
                    entry = (
                        "    \\new Staff \\with {\n"
                        '      instrumentName = #"' + tr.name + '"\n'
                        '      shortInstrumentName = #"' + tr.name[:4] + '."\n'
                        "    } { \\" + vbase + " }"
                    )
                    score_entries.append(entry)
                    ti += 1

            # ── Score block ───────────────────────────────────────────────
            W(f, r"\score {")
            W(f, r"  \new StaffGroup <<")
            for entry in score_entries:
                W(f, entry)
            W(f, r"  >>")
            W(f, r"  \layout {")
            W(f, r"    \context {")
            W(f, r"      \Score")
            # v22z: this is now only a FALLBACK baseline — actual spacing is
            # driven per-measure by \once overrides in write_voice(), sized
            # to that measure's real note density (see
            # compute_measure_density / spacing_increment_for_density).
            # A fixed global value here was always a compromise: 2.2 was
            # too tight for genuinely dense passages and needlessly loose
            # for sparse ones.  Kept modest since per-measure values should
            # cover virtually every measure in practice.
            W(f, r"      \override SpacingSpanner.spacing-increment = #1.4")
            # v22z(2): show EVERY bar number, not just system starts.
            # Previously only the first measure of each system was numbered
            # — correct, standard engraving practice, but combined with
            # density-based spacing (sparse passages legitimately pack many
            # measures per system) this made large jumps in the visible
            # number ("3" then "23") look like missing measures, when every
            # measure was actually present and correctly rendered.  Numbering
            # every measure removes that ambiguity entirely.
            if show_bar_numbers:
                W(f, r"      \override BarNumber.break-visibility = #all-visible")
                W(f, r"      barNumberVisibility = #all-bar-numbers-visible")
            else:
                W(f, r'      \remove "Bar_number_engraver"')
            W(f, r"    }")
            W(f, r"    \context {")
            W(f, r"      \StaffGroup")
            # Tighten spacing between staves within a system
            W(
                f,
                r"      \override StaffGrouper.staff-staff-spacing.basic-distance = #8",
            )
            W(
                f,
                r"      \override StaffGrouper.staffgroup-staff-spacing.basic-distance = #10",
            )
            W(f, r"    }")
            W(f, r"  }")
            # ── MIDI block (fixed: properly closed braces) ─────────────────
            W(f, r"  \midi {")
            W(f, r"    \context {")
            W(f, r"      \Score")
            W(f, r"      % Map dynamics to MIDI velocity (0-127)")
            W(
                f,
                r"      dynamicAbsoluteVolumeFunction = #default-dynamic-absolute-volume",
            )
            W(f, r"    }")
            W(f, r"  }")
            W(f, r"}")


def _ticks_to_dtype_dots(ticks, tpb):
    """Return (durationType_string, dots) for a tick duration.
    Supports dotted values (dots=1). Snaps to nearest standard value.
    Module-level so it can be called from Song.to_mscx() without self."""
    durations = [
        ("whole", tpb * 4),
        ("half", tpb * 2),
        ("quarter", tpb),
        ("eighth", tpb // 2),
        ("16th", tpb // 4),
        ("32nd", tpb // 8),
        ("64th", tpb // 16),
    ]
    best_name, best_dots, best_diff = "quarter", 0, tpb * 999
    for name, base in durations:
        if base <= 0:
            continue
        dotted = base + base // 2
        for val, dots in [(base, 0), (dotted, 1)]:
            diff = abs(ticks - val)
            if diff < best_diff:
                best_name, best_dots, best_diff = name, dots, diff
    return best_name, best_dots


def _write_rest_sequence(voice_el, ticks, tpb):
    # Write one or more Rest elements to fill the given tick gap.
    durations = [
        ("whole", tpb * 4),
        ("half", tpb * 2),
        ("quarter", tpb),
        ("eighth", tpb // 2),
        ("16th", tpb // 4),
        ("32nd", tpb // 8),
        ("64th", tpb // 16),
    ]
    remaining = ticks
    safety = 0
    while remaining > 0 and safety < 32:
        safety += 1
        placed = False
        for name, base in durations:
            if base <= 0:
                continue
            dotted = base + base // 2
            for val, dots in [(dotted, 1), (base, 0)]:
                if remaining >= val:
                    rest = ET.SubElement(voice_el, "Rest")
                    ET.SubElement(rest, "durationType").text = name
                    if dots:
                        ET.SubElement(rest, "dots").text = str(dots)
                    remaining -= val
                    placed = True
                    break
            if placed:
                break
        if not placed:
            break


def _program_to_instrument_id(program):
    # Map GM program number to a MuseScore instrument id string.
    # Covers the most common families; defaults to strings for unknown
    if program < 8:
        return "keyboard.piano"
    if program < 16:
        return "keyboard.piano"
    if program < 24:
        return "keyboard.organ"
    if program < 32:
        return "guitar.classical"
    if program < 40:
        return "plucked.bass-guitar"
    if program < 48:
        return "strings.violin"
    if program < 56:
        return "strings.cello"
    if program < 64:
        return "brass.trumpet"
    if program < 72:
        return "brass.saxophone.alto"
    if program < 80:
        return "wind.flutes.flute"
    return "strings.violin"


def _ticks_to_dtype(ticks, tpb):
    b = ticks / tpb
    if b >= 4:
        return "whole"
    if b >= 2:
        return "half"
    if b >= 1:
        return "quarter"
    if b >= 0.5:
        return "eighth"
    if b >= 0.25:
        return "16th"
    return "32nd"


def _midi_to_tpc(pitch):
    return [14, 21, 16, 23, 18, 13, 20, 15, 22, 17, 24, 19][pitch % 12]


def _ticks_to_ly_snap(ticks, tpb):
    # Snap raw tick duration to nearest standard value.
    table = [
        tpb * 4,
        tpb * 3,
        tpb * 2,
        tpb * 3 // 2,
        tpb,
        tpb * 3 // 4,
        tpb // 2,
        tpb // 4,
        tpb // 8,
        tpb // 16,
    ]
    return min(table, key=lambda v: abs(v - ticks)) if table else tpb


def _ticks_to_ly_rest_seq(ticks, tpb):
    # Return list of LilyPond rest strings that sum exactly to ticks.
    table = [
        (tpb * 4, "r1"),
        (tpb * 3, "r2."),
        (tpb * 2, "r2"),
        (tpb * 3 // 2, "r4."),
        (tpb, "r4"),
        (tpb * 3 // 4, "r8."),
        (tpb // 2, "r8"),
        (tpb // 4, "r16"),
        (tpb // 8, "r32"),
        (tpb // 16, "r64"),
    ]
    result = []
    rem = int(ticks)
    for val, sym in table:
        if val <= 0:
            continue
        while rem >= val:
            result.append(sym)
            rem -= val
    return result if result else ["r4"]


def _ticks_to_ly_dur(ticks, tpb):
    b = ticks / tpb
    if b >= 4:
        return "1"
    if b >= 2:
        return "2"
    if b >= 1.5:
        return "2."
    if b >= 1:
        return "4"
    if b >= 0.75:
        return "4."
    if b >= 0.5:
        return "8"
    if b >= 0.25:
        return "16"
    return "32"


def _pitch_to_ly(pitch):
    """Convert MIDI pitch to LilyPond note name with correct octave marks.
    LilyPond middle C (C4, MIDI 60) = c' in \\relative c' context.
    We output absolute pitches using octave tick/comma notation from C4."""
    names = ["c", "cis", "d", "dis", "e", "f", "fis", "g", "gis", "a", "ais", "b"]
    oct_ = pitch // 12  # MIDI octave: C4=oct 5, C3=oct 4, C5=oct 6
    note = names[pitch % 12]
    # In LilyPond absolute: c = C3 (MIDI oct 4), c' = C4 (oct 5), c,=C2 (oct 3)
    # ticks above C3: each octave above adds one '
    # commas below C3: each octave below adds one ,
    diff = oct_ - 4  # 0 → c (C3), +1 → c' (C4), -1 → c, (C2)
    if diff > 0:
        return note + "'" * diff
    elif diff < 0:
        return note + "," * (-diff)
    else:
        return note


# ─────────────────────────────────────────────────────────────────────────────
# Transport (play / stop / record / seek)
# ─────────────────────────────────────────────────────────────────────────────

# ─────────────────────────────────────────────────────────────────────────────
# Metrical duration analysis  (MuseScore importmidi_meter.cpp approach)
# ─────────────────────────────────────────────────────────────────────────────


def _metric_beat_strengths(m_start, tpm, tpb, num, den):
    """Return a sorted list of (tick, strength) for every grid position in
    one measure, where higher strength = metrically more significant.

    Strategy mirrors MuseScore importmidi_meter.cpp:

    Simple duple/quadruple (2/4, 4/4, 2/2, cut-time):
        Dyadic hierarchy — the offset from the measure start is divided
        repeatedly by 2.  The number of times it divides evenly (i.e. the
        number of trailing binary zeros of  offset / min_unit) gives the
        strength, plus a base level for the beat.

    Simple triple (3/4, 3/8, 3/2):
        Three equal beats; within each beat the hierarchy is dyadic.
        Beat 1 is strongest (strength 2), beats 2–3 are strength 1,
        sub-beat positions carry strength 0.

    Compound (6/8, 9/8, 12/8):
        Groups of 3 eighth-notes form a beat.  Two (or three/four) such
        groups per measure.  Beat groups follow the triple scheme;
        within each group sub-divisions are dyadic.

    The downbeat (offset 0) always gets the maximum strength so a note
    at the very start of a measure can legally fill the whole measure.
    """
    min_unit = max(1, tpb // 16)  # 64th note is our finest grid
    positions = {}  # offset → strength

    is_compound = num in (6, 9, 12) and den in (8, 16)
    is_triple = num == 3 and not is_compound

    if is_compound:
        # Group size = 3 eighth-notes
        eighth = tpb // 2
        group = 3 * eighth  # one beat = dotted quarter
        n_groups = num // 3
        for g in range(n_groups):
            g_start = g * group
            # Downbeat of the group
            positions[g_start] = (n_groups - g) + 1  # beat 1 stronger
            # Within the group: 3 eighths, sub-divide each dyadically
            for e in range(3):
                e_off = g_start + e * eighth
                if e_off not in positions:
                    positions[e_off] = 1 if e else positions[g_start]
                # 16ths within each eighth
                for s in range(1, tpb // min_unit // 2):
                    sub = e_off + s * min_unit
                    if 0 < sub < tpm and sub not in positions:
                        positions[sub] = 0

    elif is_triple:
        # 3 equal quarter-note beats
        beat = tpb * 4 // den  # ticks per beat
        for b in range(num):
            b_start = b * beat
            positions[b_start] = 2 if b == 0 else 1
            # Dyadic sub-divisions within each beat
            unit = beat
            s = 1
            while unit > min_unit:
                unit //= 2
                for k in range(0, beat // unit):
                    off = b_start + k * unit
                    if 0 < off < tpm and off % (unit * 2) != 0:
                        if off not in positions:
                            positions[off] = max(0, s - 1)
                s += 1

    else:
        # Simple duple / quadruple: fully dyadic
        # Compute the number of dyadic levels: log2(tpm / min_unit)
        import math as _math

        n_levels = int(_math.log2(max(1, tpm // min_unit)))
        unit = tpm
        for level in range(n_levels + 1):
            strength = n_levels - level
            step = unit
            k = 0
            while k * step < tpm:
                off = k * step
                if off not in positions:
                    positions[off] = strength
                k += 1
            unit = max(min_unit, unit // 2)

    # Downbeat is always the strongest
    positions[0] = max(positions.get(0, 0), 255)

    return sorted((m_start + off, s) for off, s in positions.items() if 0 <= off < tpm)


def metrically_subdivide_duration(onset_tick, duration, tpb, mmap):
    """Split a duration into tied note values that respect metric structure.

    Based on MuseScore's importmidi_meter.cpp logic:

      A note whose sounding duration would cross the next metrically
      equal-or-stronger boundary is split there.  Each resulting piece
      is then expressed as the largest standard note value that fits.

    Returns a list of (tick, duration) pairs (all in ticks) representing
    tied note values.  The list always sums to `duration`.

    Parameters
    ----------
    onset_tick : int   — absolute tick where the note begins
    duration   : int   — total sounding duration in ticks
    tpb        : int   — ticks per beat
    mmap       : list  — Song.build_measure_map() result
    """
    if duration <= 0:
        return []

    # Standard note values (ticks), largest first, including dotted
    def _std_values(tpb_):
        vals = []
        for mult_n, mult_d in [
            (4, 1),
            (3, 1),
            (2, 1),
            (3, 2),
            (1, 1),
            (3, 4),
            (1, 2),
            (3, 8),
            (1, 4),
            (3, 16),
            (1, 8),
        ]:
            v = tpb_ * mult_n // mult_d
            if v > 0:
                vals.append(v)
        return sorted(set(v for v in vals if v >= max(1, tpb_ // 16)), reverse=True)

    std_vals = _std_values(tpb)
    min_unit = max(1, tpb // 16)

    # Fast measure lookup
    def _find_measure(tick):
        for _, ms, me, num, den, tpm in mmap:
            if ms <= tick < me:
                return ms, me, num, den, tpm
        return None, None, None, None, None

    result = []
    cur_tick = onset_tick
    cur_dur = duration
    guard = 0

    while cur_dur > 0 and guard < 64:
        guard += 1
        ms, me, num, den, tpm = _find_measure(cur_tick)
        if ms is None:
            # Beyond all measures — just append remainder as-is
            result.append((cur_tick, cur_dur))
            break

        avail_in_measure = me - cur_tick

        # Get beat strengths for this measure
        strengths = _metric_beat_strengths(ms, tpm, tpb, num, den)
        # strength at cur_tick
        cur_strength = next((s for t, s in strengths if t == cur_tick), 0)

        # Find next tick with strength >= cur_strength (exclusive of cur_tick)
        next_boundary = me  # default: barline
        for t, s in strengths:
            if t > cur_tick and s >= cur_strength:
                next_boundary = t
                break

        # Maximum span = minimum of: remainder, available in measure, next boundary
        max_span = min(cur_dur, avail_in_measure, next_boundary - cur_tick)
        if max_span <= 0:
            max_span = min_unit

        # Choose largest standard value that fits within max_span
        chosen = min_unit
        for v in std_vals:
            if v <= max_span:
                chosen = v
                break

        result.append((cur_tick, chosen))
        cur_tick += chosen
        cur_dur -= chosen

    return result


# ─────────────────────────────────────────────────────────────────────────────
# Quantization: snap recorded note durations to standard musical values
# ─────────────────────────────────────────────────────────────────────────────
def quantize_notes_per_measure(
    track,
    song,
    div=8,
    strength=1.0,
    measure_start=None,
    measure_end=None,
    grace_ticks=0,
):
    """
    Per-measure quantization (v19g).

    Parameters
    ----------
    track         : Track object whose notes are modified in place.
    song          : Song — used for build_measure_map() and ticks_per_beat.
    div           : Grid division: 4=quarter, 8=eighth, 16=sixteenth, 32=thirty-second.
    strength      : 1.0 = full snap, 0.5 = halfway (humanise), etc.
    measure_start : First measure to quantize (1-based, inclusive). None = first.
    measure_end   : Last  measure to quantize (1-based, inclusive). None = last.
    grace_ticks   : Notes whose duration is strictly less than this many ticks are
                    removed before quantization (grace-note cleanup).

    Returns
    -------
    (notes_quantized, grace_removed) — counts for display in UI.
    """
    if not track or not track.notes:
        return 0, 0

    tpb = song.ticks_per_beat
    mmap = song.get_measure_map()

    # ── 1. Grace-note cleanup ────────────────────────────────────────────────
    grace_removed = 0
    if grace_ticks > 0:
        before = len(track.notes)
        track.notes = [n for n in track.notes if n.duration >= grace_ticks]
        grace_removed = before - len(track.notes)

    # ── 2. Measure range (convert 1-based UI values to 0-based mmap indices) ─
    m_start_idx = (measure_start - 1) if measure_start is not None else 0
    m_end_idx = (measure_end - 1) if measure_end is not None else len(mmap) - 1
    m_start_idx = max(0, m_start_idx)
    m_end_idx = min(len(mmap) - 1, m_end_idx)

    # Build a set of (ms, me) pairs for fast lookup
    active_measures = {
        (ms, me) for m_idx, ms, me, _n, _d, _t in mmap if m_start_idx <= m_idx <= m_end_idx
    }

    # ── 3. Per-measure snap ──────────────────────────────────────────────────
    notes_quantized = 0
    for ms, me in active_measures:
        grid = max(1, tpb // div)  # consistent grid across measures

        for n in track.notes:
            if not (ms <= n.tick < me):
                continue

            # Snap onset to grid (within-measure relative)
            rel = n.tick - ms
            q_rel = round(rel / grid) * grid
            n.tick = ms + int(rel + strength * (q_rel - rel))

            # Snap duration to nearest grid multiple.
            # Do NOT force a minimum of `grid` — that would make every
            # staccato/short note become as long as the grid value (e.g. all
            # notes become quarter notes with 1/4 quantize).
            # If the rounded duration is 0 (note shorter than half a grid
            # cell), preserve the original duration so the note stays short
            # rather than disappearing or jumping to the grid minimum.
            q_dur = round(n.duration / grid) * grid
            if q_dur > 0:
                n.duration = int(n.duration + strength * (q_dur - n.duration))
                n.duration = max(1, min(n.duration, me - n.tick))
            # else: note is shorter than half a grid step — leave it unchanged

            notes_quantized += 1

    print(
        f"[quantize] '{track.name}': "
        f"{notes_quantized} notes quantized, {grace_removed} grace notes removed "
        f"(div={div}, strength={strength}, "
        f"measures {m_start_idx+1}–{m_end_idx+1})",
        file=sys.stderr,
    )

    return notes_quantized, grace_removed


def quantize_notes(track, tpb, div=4, strength=1.0, threshold=0):
    """Legacy whole-song quantize — used internally after auto-record.
    For the user-facing dialog use quantize_notes_per_measure()."""
    if not track or not track.notes:
        return
    grid = max(1, tpb // div)
    for n in track.notes:
        q_start = round(n.tick / grid) * grid
        if abs(q_start - n.tick) >= threshold:
            n.tick = int(n.tick + strength * (q_start - n.tick))
        q_dur = round(n.duration / grid) * grid
        if q_dur > 0 and abs(q_dur - n.duration) >= threshold:
            n.duration = int(n.duration + strength * (q_dur - n.duration))
        n.duration = max(1, n.duration)
    print(
        f"[quantize-legacy] '{track.name}': {len(track.notes)} notes " f"grid-snapped (div={div})",
        file=sys.stderr,
    )


class Transport:
    def __init__(self, song: Song):
        self.song = song
        self.position_ticks = 0
        self.position_sec = 0.0
        self._playing = False
        self._recording = False
        self._stop_evt = threading.Event()
        self._thread = None
        self._rec_track_idx = None
        self._rec_open = {}
        self._rec_lock = threading.Lock()  # guards _rec_open and song.modified in _rec_cb
        self._metronome = False
        self._on_tick_cb = None
        self._play_until_tick = None  # if set, stop playback at this tick

    def _all_sounds_off(self):
        """Send all-sounds-off (CC 120) + all-notes-off (CC 123) + sustain release
        on every channel.  Call before starting playback and after stopping to
        prevent notes accumulating in TiMidity across play/stop cycles."""
        for ch in range(16):
            _send_raw(0xB0 | ch, 120, 0)  # all sounds off  — immediate silence
            _send_raw(0xB0 | ch, 123, 0)  # all notes off   — respects release
            _send_raw(0xB0 | ch, 64, 0)  # sustain pedal off

    def play(self, on_tick=None):
        if self._playing:
            return
        # Wait for any previous thread to exit before clearing the stop event.
        # Without this, a rapid Stop→Play causes the old thread to see a cleared
        # event and keep firing note_ons alongside the new thread → buzz + pops.
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=0.5)
        self._all_sounds_off()  # clear any residue from previous pass
        self._on_tick_cb = on_tick
        self._stop_evt.clear()
        self._playing = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def record(self, track_idx, on_tick=None):
        if self._playing or self._recording:
            return
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=0.5)
        self._all_sounds_off()
        self._rec_track_idx = track_idx
        self._rec_open = {}
        self._on_tick_cb = on_tick
        self._stop_evt.clear()
        self._playing = True
        self._recording = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        # Stop at current position — does NOT reset position.
        self._stop_evt.set()
        self._playing = False
        self._recording = False
        # Block until the playback thread exits (v22q: was 0.3s timeout).
        # A short timeout meant the thread could still be sending note events
        # when the caller replaced self.song, causing old-song audio to play
        # against the new score display.  We now wait up to 2 seconds and
        # send all-sounds-off whether or not the thread finished.
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
            if self._thread.is_alive():
                import sys

                print(
                    "[transport] WARNING: playback thread did not exit within 2s",
                    file=sys.stderr,
                )
        self._all_sounds_off()

    def rewind(self):
        self.stop()
        time.sleep(0.06)
        self.position_ticks = 0
        self.position_sec = 0.0

    def seek_measures(self, delta):
        was = self._playing
        self.stop()
        time.sleep(0.06)
        mmap = self.song.get_measure_map()
        # Find which measure the current position is in
        cur_idx = 0
        for m_idx, ms, me, _n, _d, _t in mmap:
            if ms <= self.position_ticks < me:
                cur_idx = m_idx
                break
        # Jump to target measure
        target = max(0, min(len(mmap) - 1, cur_idx + delta))
        self.position_ticks = mmap[target][1]  # start_tick of target measure
        self.position_sec = self._t2s(self.position_ticks)
        if was:
            self.play(self._on_tick_cb)

    def is_playing(self):
        return self._playing

    def is_recording(self):
        return self._recording

    def set_metronome(self, on):
        self._metronome = on

    def _t2s(self, ticks):
        return (ticks / self.song.ticks_per_beat) * (self.song.tempo / 1_000_000)

    def _s2t(self, sec):
        return sec * self.song.ticks_per_beat / (self.song.tempo / 1_000_000)

    # ── Tempo map helpers ────────────────────────────────────────────────────
    def _build_tempo_map(self):
        """Build a list of (abs_tick, tempo_us) change points from track events.
        Always starts with the song's base tempo at tick 0."""
        map_ = [(0, self.song.tempo)]
        for tr in self.song.tracks:
            for ev in tr.events:
                if ev.msg.type == "set_tempo":
                    map_.append((ev.tick, ev.msg.tempo))
        map_.sort(key=lambda x: x[0])
        # Deduplicate: keep last tempo at each tick
        deduped = []
        for tick, tempo in map_:
            if deduped and deduped[-1][0] == tick:
                deduped[-1] = (tick, tempo)
            else:
                deduped.append((tick, tempo))
        return deduped

    def _tmap_tick_to_sec(self, tick, tempo_map, start_tick=0):
        """Convert absolute tick to wall-clock seconds using tempo map.
        Returns seconds relative to start_tick."""
        sec = 0.0
        prev_tick = start_tick
        prev_tempo = self.song.tempo
        # Find the tempo in effect at start_tick
        for t, tmp in tempo_map:
            if t <= start_tick:
                prev_tempo = tmp
        for t, tmp in tempo_map:
            if t <= start_tick:
                continue
            if t >= tick:
                break
            dt = t - prev_tick
            sec += (dt / self.song.ticks_per_beat) * (prev_tempo / 1_000_000)
            prev_tick = t
            prev_tempo = tmp
        dt = tick - prev_tick
        sec += (dt / self.song.ticks_per_beat) * (prev_tempo / 1_000_000)
        return sec

    def _tmap_sec_to_tick(self, sec, tempo_map, start_tick=0):
        # Convert wall-clock seconds (from start_tick) back to absolute tick.
        remaining = sec
        prev_tick = start_tick
        prev_tempo = self.song.tempo
        for t, tmp in tempo_map:
            if t <= start_tick:
                prev_tempo = tmp
        for t, tmp in tempo_map:
            if t <= start_tick:
                continue
            seg_ticks = t - prev_tick
            seg_sec = (seg_ticks / self.song.ticks_per_beat) * (prev_tempo / 1_000_000)
            if remaining <= seg_sec:
                break
            remaining -= seg_sec
            prev_tick = t
            prev_tempo = tmp
        ticks_in_seg = remaining * self.song.ticks_per_beat / (prev_tempo / 1_000_000)
        return start_tick + int(prev_tick - start_tick + ticks_in_seg)

    def _run(self):
        try:
            self._run_body()
        except Exception as _run_exc:
            import traceback

            print(f"[Transport._run] CRASHED: {_run_exc}")
            traceback.print_exc()
        finally:
            self._playing = False
            self._recording = False

    def _run_body(self):
        song = self.song
        tpb = song.ticks_per_beat
        start_t = self.position_ticks
        wall0 = time.perf_counter()
        tempo_map = self._build_tempo_map()

        def t2s(tick):
            return self._tmap_tick_to_sec(tick, tempo_map, start_t)

        timeline = []
        has_solo = any(t.solo for t in song.tracks)
        for tr in song.tracks:
            if tr.mute:
                continue
            if has_solo and not tr.solo:
                continue
            ch = tr.channel
            timeline.append((0.0, lambda c=ch, pg=tr.program: _send_raw(0xC0 | c, pg)))
            timeline.append((0.0, lambda c=ch, v=tr.volume: _send_raw(0xB0 | c, 7, v)))
            for note in tr.notes:
                if note.tick < start_t:
                    continue
                is_tie = getattr(note, "articulation", "") == "tie_continuation"
                ton = t2s(note.tick)
                toff = t2s(note.tick + note.duration)
                # Tie continuations: suppress the re-attack so the note sounds
                # as one unbroken sustain across the barline.  The note_off at
                # toff is still needed to release the pitch at the tied duration end.
                if not is_tie:
                    timeline.append(
                        (
                            ton,
                            lambda c=ch, n=note.pitch, v=note.velocity: _send_raw(0x90 | c, n, v),
                        )
                    )
                timeline.append((toff, lambda c=ch, n=note.pitch: _send_raw(0x80 | c, n, 0)))
            for ev in tr.events:
                if ev.tick < start_t:
                    continue
                if ev.msg.type == "control_change" and ev.msg.control == 64:
                    te = t2s(ev.tick)
                    val = ev.msg.value
                    timeline.append((te, lambda c=ch, v=val: _send_raw(0xB0 | c, 64, v)))
        # Metronome — use base tempo; sufficient for live use
        if self._metronome:
            base_tempo = song.tempo
            beat_sec = base_tempo / 1_000_000
            bi = 0
            t = 0.0
            if self._recording:
                # During recording: extend metronome far enough that it never
                # runs out before the user presses Stop (~2 hours @ any tempo)
                total_sec = 7200.0
            else:
                min_sec = beat_sec * song.time_sig_num * 4
                total_sec = max(min_sec, t2s(song.total_ticks()))
            while t <= total_sec + beat_sec:
                p = 76 if bi == 0 else 77
                tc = t
                timeline.append((tc, lambda pp=p: _send_raw(0x99, pp, 90)))
                timeline.append((tc + 0.05, lambda pp=p: _send_raw(0x89, pp, 0)))
                t += beat_sec
                bi = (bi + 1) % song.time_sig_num

        # During recording with no existing notes the song is empty, so total_ticks
        # is tiny — add a sentinel event far in the future so the loop doesn't
        # exit after a few beats of silence.
        if self._recording:
            timeline.append((7200.0, lambda: None))  # 2-hour sentinel
        timeline.sort(key=lambda x: x[0])
        # ── Subscribe to MIDI input for recording ──────────────────────────
        rec_token = None
        if self._recording and midi_io.MIDI_IN_OK and self._rec_track_idx is not None:
            tr_rec = song.tracks[self._rec_track_idx]
            _send_raw(0xC0 | tr_rec.channel, tr_rec.program)
            rec_open = self._rec_open

            _rec_lock = self._rec_lock  # local alias for closure

            def _rec_cb(msg, _tr=tr_rec, _tpb=tpb, _start=start_t, _w0=wall0):
                # Echo immediately — this runs in the dispatcher thread, so
                # latency is just the 1 ms dispatcher poll + OS audio path.
                # NOTE: echo happens BEFORE the lock so we don't block audio output.
                try:
                    echoed = msg.copy(channel=_tr.channel) if hasattr(msg, "channel") else msg
                    _send(echoed)
                except Exception:
                    _send(msg)
                # Compute tick with current tempo at this moment
                elapsed = time.perf_counter() - _w0
                ctick = _start + max(0, int(elapsed * _tpb / (song.tempo / 1_000_000)))
                # ── All dict/list mutations are under the lock ─────────────────
                # rec_open is read and written by both this callback (dispatcher
                # thread) and stop() / post-recording cleanup (main thread).
                # song.modified and _tr.notes likewise need protection.
                with _rec_lock:
                    if msg.type == "note_on" and msg.velocity > 0:
                        rec_open[(msg.channel, msg.note)] = (ctick, msg.velocity)
                    elif msg.type in ("note_off",) or (msg.type == "note_on" and msg.velocity == 0):
                        k = (msg.channel, msg.note)
                        if k in rec_open:
                            s, v = rec_open.pop(k)
                            dur = max(1, ctick - s)
                            _tr.notes.append(MidiNote(s, msg.note, v, dur, _tr.channel))
                            _tr.notes.sort(key=lambda n: n.tick)
                            song.modified = True
                    elif msg.type == "control_change" and msg.control == 64:
                        # Guard the track index access too — recording may stop concurrently
                        ri = self._rec_track_idx
                        if ri is not None and ri < len(song.tracks):
                            song.tracks[ri].events.append(MidiEvent(ctick, msg))

            rec_token = midi_input_subscribe(_rec_cb)

        # ── Main playback loop ─────────────────────────────────────────────
        end_tick = self._play_until_tick
        for t_sec, action in timeline:
            if self._stop_evt.is_set():
                break
            if end_tick is not None and self.position_ticks >= end_tick:
                break
            wait = t_sec - (time.perf_counter() - wall0)
            if wait > 0:
                self._stop_evt.wait(timeout=wait)
                if self._stop_evt.is_set():
                    break  # check BEFORE firing action
            # Update position from wall clock — avoids float drift
            el = time.perf_counter() - wall0
            self.position_sec = el
            self.position_ticks = self._tmap_sec_to_tick(el, tempo_map, start_t)
            if self._on_tick_cb:
                try:
                    self._on_tick_cb(self.position_ticks)
                except:
                    pass
            action()

        if rec_token is not None:
            midi_input_unsubscribe(rec_token)

        # Quantize recorded notes to fix timing imprecision
        if self._recording and self._rec_track_idx is not None:
            quantize_notes(song.tracks[self._rec_track_idx], tpb)

        # Always silence TiMidity at end — whether the loop finished naturally
        # or was broken by stop_evt.  Prevents notes accumulating across plays.
        self._all_sounds_off()

        if not self._stop_evt.is_set():
            self.position_ticks = song.total_ticks()
        self._playing = False
        self._recording = False

    def close(self):
        self.stop()
        if midi_io._midi_out:
            try:
                midi_io._midi_out.close()
            except:
                pass
        if midi_io._midi_in:
            try:
                midi_io._midi_in.close()
            except:
                pass


# ─────────────────────────────────────────────────────────────────────────────
# Piano Roll
# ─────────────────────────────────────────────────────────────────────────────


class PianoRollView(tk.Toplevel):
    CELL_W = 2
    CELL_H = 10
    KEY_W = 64
    HEADER_H = 24

    def __init__(self, parent, app, track_idx):
        super().__init__(parent)
        self.app = app
        self.track_idx = track_idx
        self._zoom = 1.0
        self._sel = set()
        tr = app.song.tracks[track_idx]
        self.title(f"Piano Roll — {tr.name}")
        self.geometry("900x500")
        self._build_ui()
        self._draw()

    def _build_ui(self):
        tb = tk.Frame(self, bd=1, relief=tk.RAISED)
        tb.pack(fill=tk.X)
        for lbl, cmd in [
            ("Zoom +", self._zoom_in),
            ("Zoom −", self._zoom_out),
            ("Select All", self._select_all),
            ("Delete", self._delete_sel),
            ("Quantize…", self._quantize_dlg),
            ("Transpose…", self._transpose_dlg),
        ]:
            tk.Button(tb, text=lbl, command=cmd).pack(side=tk.LEFT, padx=2, pady=2)

        fr = tk.Frame(self)
        fr.pack(fill=tk.BOTH, expand=True)

        # Shared scrollbars
        hb = ttk.Scrollbar(fr, orient=tk.HORIZONTAL)
        vb = ttk.Scrollbar(fr, orient=tk.VERTICAL)
        hb.pack(side=tk.BOTTOM, fill=tk.X)
        vb.pack(side=tk.RIGHT, fill=tk.Y)

        # Fixed keyboard canvas (left strip — does NOT scroll horizontally)
        self.key_canvas = tk.Canvas(fr, bg="#222", width=self.KEY_W, yscrollcommand=vb.set)
        self.key_canvas.pack(side=tk.LEFT, fill=tk.Y)

        # Scrolling roll canvas (right — scrolls both axes)
        self.canvas = tk.Canvas(
            fr,
            bg="#1a1a2e",
            cursor="crosshair",
            xscrollcommand=hb.set,
            yscrollcommand=vb.set,
        )
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Wire scrollbars to BOTH canvases for y, roll only for x
        def _yscroll(*args):
            self.canvas.yview(*args)
            self.key_canvas.yview(*args)

        vb.configure(command=_yscroll)
        hb.configure(command=self.canvas.xview)

        # Sync key_canvas y when roll scrolls (mousewheel)
        def _on_roll_scroll(event):
            delta = -1 if event.delta > 0 else 1
            self.canvas.yview_scroll(delta, "units")
            self.key_canvas.yview_scroll(delta, "units")

        self.canvas.bind("<MouseWheel>", _on_roll_scroll)
        self.key_canvas.bind("<MouseWheel>", _on_roll_scroll)

        self.canvas.bind("<Button-1>", self._on_click)
        self.canvas.bind("<Button-3>", self._on_right)

    def _zoom_in(self):
        self._zoom = min(8.0, self._zoom * 1.5)
        self._draw()
        self._restore_playhead()

    def _zoom_out(self):
        self._zoom = max(0.25, self._zoom / 1.5)
        self._draw()
        self._restore_playhead()

    def _restore_playhead(self):
        """Re-draw the playhead after a _draw() call, which does a blanket
        canvas.delete("all") and so wipes it along with everything else.

        v22ze-64 fix: same underlying mistake just fixed for ScoreView's
        zoom/fit buttons and resize handler (see _current_cursor_tick) --
        here it's update_playhead() unconditionally recreating the line
        each time it's called, but nothing was calling it again after a
        zoom-triggered _draw() cleared the canvas, so the cursor stayed
        gone until the next natural playback tick (or Play was pressed
        again, if playback was stopped).
        """
        try:
            tick = self.app.transport.position_ticks
        except Exception:
            return
        self.update_playhead(tick)

    def _select_all(self):
        self._sel = set(range(len(self.app.song.tracks[self.track_idx].notes)))
        self._draw()

    def _delete_sel(self):
        tr = self.app.song.tracks[self.track_idx]
        tr.notes = [n for i, n in enumerate(tr.notes) if i not in self._sel]
        self._sel.clear()
        self.app.song.modified = True
        self.app._update_title()
        self._draw()

    def _quantize_dlg(self):
        v = simpledialog.askinteger(
            "Quantize",
            "Ticks (120=16th@480tpb):",
            parent=self,
            initialvalue=120,
            minvalue=1,
        )
        if not v:
            return
        tr = self.app.song.tracks[self.track_idx]
        for i in (self._sel if self._sel else range(len(tr.notes))):
            n = tr.notes[i]
            n.tick = round(n.tick / v) * v
            n.duration = max(v, round(n.duration / v) * v)
        self.app.song.modified = True
        self._draw()

    def _transpose_dlg(self):
        v = simpledialog.askinteger(
            "Transpose",
            "Semitones:",
            parent=self,
            initialvalue=0,
            minvalue=-48,
            maxvalue=48,
        )
        if v is None:
            return
        tr = self.app.song.tracks[self.track_idx]
        for i in (self._sel if self._sel else range(len(tr.notes))):
            tr.notes[i].pitch = max(0, min(127, tr.notes[i].pitch + v))
            # v22ze-51 fix: a bulk pitch shift invalidates any explicit
            # accidental spelling set earlier via the Accidental tool --
            # left in place, a forced "sharp" from before the transpose
            # would misspell the note at its new pitch. Reset to the
            # default (key-signature-derived) spelling; the user can
            # re-apply an explicit accidental afterward if still needed.
            tr.notes[i].spelling = ""
        self.app.song.modified = True
        self._draw()

    def _tx(self, t):
        return self.HEADER_H + int(t * self._zoom * self.CELL_W / 10)

    def _py(self, p):
        return self.HEADER_H + (127 - p) * self.CELL_H

    def _xt(self, x):
        return max(0, int((x - self.HEADER_H) * 10 / (self._zoom * self.CELL_W)))

    def _yp(self, y):
        return max(0, min(127, 127 - (y - self.HEADER_H) // self.CELL_H))

    def _draw(self):
        c = self.canvas
        kc = self.key_canvas
        c.delete("all")
        kc.delete("all")
        tr = self.app.song.tracks[self.track_idx]
        tpb = self.app.song.ticks_per_beat
        tot = max(self.app.song.total_ticks(), tpb * 4)
        RW = self._tx(tot) + 100
        H = self.HEADER_H + 128 * self.CELL_H
        c.configure(scrollregion=(0, 0, RW, H))
        kc.configure(scrollregion=(0, 0, self.KEY_W, H))

        # Auto-scroll to note range on first draw
        if tr.notes:
            pitches = [n.pitch for n in tr.notes]
            mid_p = (max(pitches) + min(pitches)) // 2
        else:
            mid_p = 60
        if not hasattr(self, "_scrolled_once"):
            self._scrolled_once = True
            mid_y = self._py(mid_p)
            c.after(
                10,
                lambda: [
                    c.yview_moveto(max(0, (mid_y - 200) / H)),
                    kc.yview_moveto(max(0, (mid_y - 200) / H)),
                ],
            )

        # ── Roll background rows ──────────────────────────────────────────
        for p in range(128):
            y = self._py(p)
            bg = "#16213e" if "#" in NOTE_NAMES[p % 12] else "#0f3460"
            c.create_rectangle(0, y, RW, y + self.CELL_H, fill=bg, outline="")

        # ── Beat/bar grid lines ───────────────────────────────────────────
        for beat in range(int(tot / tpb) + 2):
            x = self._tx(beat * tpb)
            isbar = beat % self.app.song.time_sig_num == 0
            c.create_line(x, 0, x, H, fill="#445566" if isbar else "#2a3a4a")
            if isbar:
                c.create_text(
                    x + 2,
                    4,
                    text=str(beat // self.app.song.time_sig_num + 1),
                    fill="#88aacc",
                    font=("TkFixedFont", 8),
                    anchor="nw",
                )

        # ── Middle C dotted line ──────────────────────────────────────────
        mc_y = self._py(60)
        c.create_line(0, mc_y, RW, mc_y, fill="#ff6633", width=1, dash=(4, 4))
        c.create_text(2, mc_y - 1, text="C4", fill="#ff6633", font=("TkFixedFont", 7), anchor="sw")

        # ── Notes with taper (last 30% narrows to point) ─────────────────
        for i, note in enumerate(tr.notes):
            if note.duration <= 0:
                continue
            x1 = self._tx(note.tick)
            x2 = self._tx(note.tick + note.duration)
            y1 = self._py(note.pitch)
            y2 = y1 + self.CELL_H - 1
            sel = i in self._sel
            nw = max(3, x2 - x1 - 1)
            body_w = int(nw * 0.70)  # full-width body (70%)
            taper_w = nw - body_w  # taper zone (30%)
            fill_c = "#ffdd44" if sel else "#5bc8f5"
            out_c = "#ffe" if sel else "#1a7aad"
            fade_c = "#ffe8a0" if sel else "#a0ddf5"
            # Body rectangle
            c.create_rectangle(
                x1, y1, x1 + body_w, y2, fill=fill_c, outline=out_c, tags=f"note_{i}"
            )
            # Taper: trapezoid narrowing to 1px at right end
            ymid = (y1 + y2) / 2
            if taper_w > 1:
                c.create_polygon(
                    x1 + body_w,
                    y1,
                    x1 + body_w,
                    y2,
                    x1 + nw,
                    ymid,
                    fill=fade_c,
                    outline="",
                    tags=f"note_{i}",
                )
            # Velocity bar inside body
            if body_w > 8:
                vw = max(2, int(body_w * note.velocity / 127))
                vc = "#ffee88" if sel else "#88ddff"
                c.create_rectangle(
                    x1 + 1,
                    y1 + 1,
                    x1 + vw,
                    y2 - 1,
                    fill=vc,
                    outline="",
                    tags=f"note_{i}",
                )

        # ── Piano keyboard (drawn on key_canvas — never scrolls x) ────────
        for p in range(128):
            y = self._py(p)
            is_b = "#" in NOTE_NAMES[p % 12]
            kc.create_rectangle(
                0,
                y,
                self.KEY_W,
                y + self.CELL_H,
                fill="#111" if is_b else "#eee",
                outline="#333",
            )
            nm = NOTE_NAMES[p % 12]
            if nm == "C":  # C octave label
                oct_n = p // 12 - 1
                kc.create_text(
                    self.KEY_W - 3,
                    y + self.CELL_H // 2,
                    text=f"C{oct_n}",
                    anchor="e",
                    fill="#f64" if p == 60 else "#844",
                    font=("TkFixedFont", 7),
                )

    def update_playhead(self, tick):
        if not self.winfo_exists():
            return
        c = self.canvas
        c.delete("playhead")
        x = self._tx(tick)
        W = c.winfo_width()
        sr = c.cget("scrollregion")
        if sr:
            try:
                total_w = float(sr.split()[2])
                if total_w > 0:
                    frac = max(0.0, (x - W * 0.4) / total_w)
                    c.xview_moveto(frac)
            except:
                pass
        H = self.HEADER_H + 128 * self.CELL_H
        c.create_line(x, 0, x, H, fill="#ff3333", width=2, dash=(4, 3), tags="playhead")

    def update_active_notes(self, active_pitches):
        if not self.winfo_exists():
            return
        c = self.key_canvas  # draw on fixed keyboard canvas
        c.delete("active_key")
        for p in active_pitches:
            y = self._py(p)
            is_b = "#" in NOTE_NAMES[p % 12]
            c.create_rectangle(
                0,
                y,
                self.KEY_W,
                y + self.CELL_H - 1,
                fill="#f5a623" if is_b else "#ffcc44",
                outline="#333",
                tags="active_key",
            )
            c.create_text(
                self.KEY_W - 3,
                y + self.CELL_H // 2,
                text=NOTE_NAMES[p % 12],
                fill="#000",
                font=("TkFixedFont", 7),
                anchor="e",
                tags="active_key",
            )

    def _cxy(self, e):
        return self.canvas.canvasx(e.x), self.canvas.canvasy(e.y)

    def _on_click(self, event):
        cx, cy = self._cxy(event)
        for it in self.canvas.find_overlapping(cx - 2, cy - 2, cx + 2, cy + 2):
            for tag in self.canvas.gettags(it):
                if tag.startswith("note_"):
                    self._sel = {int(tag.split("_")[1])}
                    self._draw()
                    return
        tr = self.app.song.tracks[self.track_idx]
        tr.notes.append(
            MidiNote(
                self._xt(cx),
                self._yp(cy),
                80,
                self.app.song.ticks_per_beat // 4,
                tr.channel,
            )
        )
        tr.notes.sort(key=lambda n: n.tick)
        self.app.song.modified = True
        self.app._update_title()
        self._draw()

    def _on_right(self, event):
        cx, cy = self._cxy(event)
        tr = self.app.song.tracks[self.track_idx]
        for it in self.canvas.find_overlapping(cx - 2, cy - 2, cx + 2, cy + 2):
            for tag in self.canvas.gettags(it):
                if tag.startswith("note_"):
                    tr.notes.pop(int(tag.split("_")[1]))
                    self.app.song.modified = True
                    self.app._update_title()
                    self._draw()
                    return


# ─────────────────────────────────────────────────────────────────────────────
# MIDI List View
# ─────────────────────────────────────────────────────────────────────────────


class MidiListView(tk.Toplevel):
    """Two-tab MIDI data viewer with a track selector.

    Track selector (Combobox at top)
        Shows all tracks in the song by name.  Changing the selection
        instantly reloads both tabs for the chosen track.  The initial
        track is clamped to a valid index so an out-of-range value from
        the caller never causes an IndexError on multi-track files.

    Tab 1 — Notes
        Every MidiNote: Tick, Pitch, Note name, Velocity, Duration, Channel.
        Sortable by column.  Delete selected notes.  Double-click to edit
        velocity.

    Tab 2 — Raw Events
        Every MidiEvent in track.events: tempo changes, program changes,
        CC messages, pitch bend, key/time signature meta-events, etc.
        Sortable by column.  Read-only.
    """

    COLS = ("Tick", "Pitch", "Note", "Velocity", "Duration", "Channel")
    EV_COLS = ("Tick", "Type", "Channel", "Detail")

    def __init__(self, parent, app, track_idx):
        super().__init__(parent)
        self.app = app
        # ── Clamp track_idx to a valid range (off-by-one guard) ───────────
        n_tracks = len(app.song.tracks)
        self.track_idx = max(0, min(track_idx, n_tracks - 1)) if n_tracks else 0
        self.geometry("720x440")
        self._build_ui()
        self._reload()

    # ── UI construction ────────────────────────────────────────────────────
    def _build_ui(self):
        # ── Top bar: track selector + action buttons ───────────────────────
        tb = tk.Frame(self)
        tb.pack(fill=tk.X, padx=4, pady=2)

        tk.Label(tb, text="Track:").pack(side=tk.LEFT)

        self._track_var = tk.StringVar()
        self._track_cb = ttk.Combobox(tb, textvariable=self._track_var, state="readonly", width=32)
        self._track_cb.pack(side=tk.LEFT, padx=(2, 8))
        self._track_cb.bind("<<ComboboxSelected>>", self._on_track_select)

        tk.Button(tb, text="Delete Selected", command=self._delete_sel).pack(side=tk.LEFT, padx=2)
        tk.Button(tb, text="Refresh", command=self._reload).pack(side=tk.LEFT, padx=2)

        # Populate the combobox values
        self._refresh_track_list()

        # ── Notebook ───────────────────────────────────────────────────────
        nb = ttk.Notebook(self)
        nb.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)
        self._nb = nb

        # Tab 1 — Notes
        notes_frame = tk.Frame(nb)
        nb.add(notes_frame, text="Notes")

        self.tree = ttk.Treeview(
            notes_frame, columns=self.COLS, show="headings", selectmode="extended"
        )
        col_widths = [70, 50, 60, 70, 70, 60]
        for col, w in zip(self.COLS, col_widths):
            self.tree.heading(col, text=col, command=lambda c=col: self._sort(c))
            self.tree.column(col, width=w, anchor="center")
        vsb = ttk.Scrollbar(notes_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.pack(fill=tk.BOTH, expand=True)
        self.tree.bind("<Double-1>", self._on_double)

        # Tab 2 — Raw Events
        ev_frame = tk.Frame(nb)
        nb.add(ev_frame, text="Raw Events")

        self.ev_tree = ttk.Treeview(
            ev_frame, columns=self.EV_COLS, show="headings", selectmode="browse"
        )
        ev_widths = [70, 140, 60, 360]
        for col, w in zip(self.EV_COLS, ev_widths):
            self.ev_tree.heading(col, text=col, command=lambda c=col: self._sort_events(c))
            self.ev_tree.column(col, width=w, anchor="center" if col != "Detail" else "w")
        ev_vsb = ttk.Scrollbar(ev_frame, orient=tk.VERTICAL, command=self.ev_tree.yview)
        ev_hsb = ttk.Scrollbar(ev_frame, orient=tk.HORIZONTAL, command=self.ev_tree.xview)
        self.ev_tree.configure(yscrollcommand=ev_vsb.set, xscrollcommand=ev_hsb.set)
        ev_vsb.pack(side=tk.RIGHT, fill=tk.Y)
        ev_hsb.pack(side=tk.BOTTOM, fill=tk.X)
        self.ev_tree.pack(fill=tk.BOTH, expand=True)

    # ── Track selector ─────────────────────────────────────────────────────
    def _refresh_track_list(self):
        """Rebuild the combobox values from the current song's track list."""
        tracks = self.app.song.tracks
        names = [f"Track {i+1}:  {tr.name}  (ch {tr.channel+1})" for i, tr in enumerate(tracks)]
        self._track_cb["values"] = names
        # Select the current track
        idx = max(0, min(self.track_idx, len(tracks) - 1))
        if names:
            self._track_cb.current(idx)
        self.title(f"MIDI List — {tracks[idx].name}" if tracks else "MIDI List")

    def _on_track_select(self, _event=None):
        """Called when the user picks a different track in the combobox."""
        sel = self._track_cb.current()
        if sel < 0:
            return
        self.track_idx = sel
        tracks = self.app.song.tracks
        self.title(f"MIDI List — {tracks[sel].name}")
        self._populate()
        self._populate_events()

    # ── Reload both tabs ───────────────────────────────────────────────────
    def _reload(self):
        """Refresh track list, notes, and raw events."""
        self._refresh_track_list()
        self._populate()
        self._populate_events()

    # ── Notes tab ─────────────────────────────────────────────────────────
    def _populate(self):
        self.tree.delete(*self.tree.get_children())
        tr = self.app.song.tracks[self.track_idx]
        for i, n in enumerate(sorted(tr.notes, key=lambda n: n.tick)):
            self.tree.insert(
                "",
                tk.END,
                iid=str(i),
                values=(
                    n.tick,
                    n.pitch,
                    note_name(n.pitch),
                    n.velocity,
                    n.duration,
                    n.channel,
                ),
            )

    def _sort(self, col):
        tr = self.app.song.tracks[self.track_idx]
        m = {
            "Tick": "tick",
            "Pitch": "pitch",
            "Velocity": "velocity",
            "Duration": "duration",
            "Channel": "channel",
        }
        tr.notes.sort(key=lambda n: getattr(n, m.get(col, "tick")))
        self._populate()

    def _delete_sel(self):
        """Delete selected rows (Notes tab only — Raw Events is read-only)."""
        if self._nb.index(self._nb.select()) != 0:
            return
        tr = self.app.song.tracks[self.track_idx]
        for idx in sorted([int(s) for s in self.tree.selection()], reverse=True):
            if 0 <= idx < len(tr.notes):
                tr.notes.pop(idx)
        self.app.song.modified = True
        self.app._update_title()
        self._populate()

    def _on_double(self, event):
        item = self.tree.focus()
        if not item:
            return
        note = self.app.song.tracks[self.track_idx].notes[int(item)]
        v = simpledialog.askinteger(
            "Edit Velocity",
            f"Velocity for {note_name(note.pitch)}:",
            parent=self,
            initialvalue=note.velocity,
            minvalue=1,
            maxvalue=127,
        )
        if v:
            note.velocity = v
            self.app.song.modified = True
            self._populate()

    # ── Raw Events tab ─────────────────────────────────────────────────────
    def _populate_events(self):
        """Reload Raw Events tab from track.events, decoded to readable form."""
        self.ev_tree.delete(*self.ev_tree.get_children())
        tr = self.app.song.tracks[self.track_idx]
        if not tr.events:
            self.ev_tree.insert("", tk.END, values=("", "(no raw events)", "", ""))
            return
        for i, ev in enumerate(sorted(tr.events, key=lambda e: e.tick)):
            msg = ev.msg
            mtype = getattr(msg, "type", type(msg).__name__)
            ch = str(getattr(msg, "channel", "—"))
            # Human-readable detail per message type
            if mtype == "set_tempo":
                bpm = round(60_000_000 / msg.tempo)
                detail = f"tempo={msg.tempo} us/beat  ({bpm} BPM)"
            elif mtype == "time_signature":
                detail = (
                    f"{msg.numerator}/{msg.denominator}  "
                    f"clocks_per_click={msg.clocks_per_click}"
                )
            elif mtype == "key_signature":
                detail = f"key={msg.key}"
            elif mtype == "program_change":
                detail = f"program={msg.program}"
            elif mtype in ("control_change", "cc"):
                CC = {
                    1: "Mod Wheel",
                    7: "Volume",
                    10: "Pan",
                    11: "Expression",
                    64: "Sustain Pedal",
                    91: "Reverb",
                    93: "Chorus",
                }
                detail = f"{CC.get(msg.control,f'CC#{msg.control}')}  value={msg.value}"
            elif mtype == "pitchwheel":
                detail = f"pitch={msg.pitch}"
            elif mtype in ("note_on", "note_off"):
                detail = f"note={msg.note} ({note_name(msg.note)})  " f"vel={msg.velocity}"
            elif mtype == "text":
                detail = f'"{msg.text}"'
            elif mtype == "track_name":
                detail = f'name="{msg.name}"'
            elif mtype == "end_of_track":
                detail = "(end of track)"
            else:
                raw = str(msg)
                detail = raw[raw.find(" ") + 1 :] if " " in raw else raw
            self.ev_tree.insert("", tk.END, iid=f"ev{i}", values=(ev.tick, mtype, ch, detail))

    def _sort_events(self, col):
        tr = self.app.song.tracks[self.track_idx]
        key = {
            "Tick": lambda e: e.tick,
            "Type": lambda e: getattr(e.msg, "type", ""),
            "Channel": lambda e: getattr(e.msg, "channel", -1),
            "Detail": lambda e: e.tick,
        }.get(col, lambda e: e.tick)
        tr.events.sort(key=key)
        self._populate_events()


# ─────────────────────────────────────────────────────────────────────────────
# Mixer
# ─────────────────────────────────────────────────────────────────────────────

# ─────────────────────────────────────────────────────────────────────────────
# DockablePane — generic dock/float wrapper  (v19h foundation)
# ─────────────────────────────────────────────────────────────────────────────
# Wraps any content-building callable so it can live either:
#   DOCKED  — as a Frame in a pre-planned slot inside the main window
#   FLOATED — as its own Toplevel, movable anywhere on a multi-monitor desktop
#
# Design choice: toggling dock/float DESTROYS and REBUILDS the content rather
# than attempting to re-parent live Tk widgets (Tk has no reliable, portable
# way to reparent a widget tree across windows). This is safe here because
# every content class in this app (Mixer, and Score/PianoRoll later) already
# redraws itself entirely from self.app.song — there is no transient state
# that lives only in the widget tree and would be lost on rebuild.
# ─────────────────────────────────────────────────────────────────────────────


class DockablePane:
    def __init__(
        self,
        app,
        dock_parent,
        content_factory,
        title="Pane",
        floated=False,
        min_w=300,
        min_h=200,
        dock_fill=None,
    ):
        # dock_fill kept as ignored kwarg for call-site compatibility.
        # The vertical PanedWindow now controls all pane sizing.
        self.app = app
        self.dock_parent = dock_parent
        self.content_factory = content_factory
        self.title = title
        self.floated = floated
        self.min_w = min_w
        self.min_h = min_h
        self.shell = None
        self.content = None
        self._build()

    # ── construction ─────────────────────────────────────────────────────────
    def _build(self):
        if self.floated:
            self._build_floated()
        else:
            self._build_docked()

    def _title_bar(self, master, dock_label, content=None):
        bar = tk.Frame(master, bg="#161b22")
        tk.Label(
            bar,
            text=self.title,
            bg="#161b22",
            fg="#58a6ff",
            font=("TkDefaultFont", 8, "bold"),
        ).pack(side=tk.LEFT, padx=5, pady=1)
        tk.Button(
            bar,
            text=dock_label,
            command=self.toggle,
            bg="#21262d",
            fg="#aaa",
            relief=tk.FLAT,
            padx=5,
            pady=0,
            font=("TkDefaultFont", 7),
            activebackground="#30363d",
        ).pack(side=tk.RIGHT, padx=3, pady=1)
        if content is not None and hasattr(content, "zoom_in") and hasattr(content, "zoom_out"):
            zbtn_kw = dict(
                bg="#21262d",
                fg="#aaa",
                relief=tk.FLAT,
                padx=5,
                pady=0,
                font=("TkDefaultFont", 8, "bold"),
                activebackground="#30363d",
            )
            tk.Button(bar, text="+", command=content.zoom_in, **zbtn_kw).pack(
                side=tk.RIGHT, padx=(3, 1), pady=1
            )
            tk.Button(bar, text="−", command=content.zoom_out, **zbtn_kw).pack(
                side=tk.RIGHT, padx=(0, 1), pady=1
            )
        return bar

    def _build_docked(self):
        self.shell = tk.Frame(self.dock_parent, bg="#0d1117")
        body = tk.Frame(self.shell, bg="#0d1117")
        self.content = self.content_factory(body)
        self._title_bar(self.shell, "⧉ Float Out", self.content).pack(fill=tk.X)
        body.pack(fill=tk.BOTH, expand=True)
        self.content.pack(fill=tk.BOTH, expand=True)
        # Always fill the PanedWindow pane slot — no side=BOTTOM stacking
        self.shell.pack(fill=tk.BOTH, expand=True)

    def _build_floated(self):
        win = tk.Toplevel(self.app.root)
        win.title(self.title)
        win.geometry(f"{self.min_w}x{self.min_h}")
        win.configure(bg="#0d1117")
        win.minsize(self.min_w // 2, self.min_h // 2)
        body = tk.Frame(win, bg="#0d1117")
        self.content = self.content_factory(body)
        self._title_bar(win, "⧉ Dock In", self.content).pack(fill=tk.X)
        body.pack(fill=tk.BOTH, expand=True)
        self.content.pack(fill=tk.BOTH, expand=True)
        win.protocol("WM_DELETE_WINDOW", self.toggle)
        self.shell = win

    def toggle(self):
        try:
            self.shell.destroy()
        except:
            pass
        self.floated = not self.floated
        self._build()

    def refresh(self):
        if self.content is not None:
            try:
                self.content.destroy()
            except:
                pass
        body = getattr(self.content, "master", None)
        if body is None or not _winfo_exists(body):
            self.toggle()
            self.toggle()
            return
        self.content = self.content_factory(body)
        self.content.pack(fill=tk.BOTH, expand=True)


class TracksView(tk.Frame):
    """Track List + Overview, wrapped as a dockable pane (v20f)."""

    def __init__(self, parent, app):
        super().__init__(parent, bg="#0d1117")
        self.app = app
        self._zoom = 1.0
        self._build()

    def zoom_in(self):
        self._zoom = min(2.0, self._zoom * 1.2)
        self._build()

    def zoom_out(self):
        self._zoom = max(0.6, self._zoom / 1.2)
        self._build()

    def _build(self):
        for w in self.winfo_children():
            w.destroy()
        z = self._zoom
        hdr_fnt = max(7, int(9 * z))
        list_fnt = max(7, int(10 * z))
        app = self.app

        pane = tk.PanedWindow(
            self, orient=tk.HORIZONTAL, bg="#0d1117", sashrelief=tk.FLAT, sashwidth=4
        )
        pane.pack(fill=tk.BOTH, expand=True)
        left = tk.Frame(pane, bg="#161b22", width=220)
        pane.add(left, minsize=180)
        tk.Label(
            left,
            text="TRACKS",
            bg="#161b22",
            fg="#58a6ff",
            font=("TkDefaultFont", hdr_fnt, "bold"),
        ).pack(anchor="w", padx=6, pady=(6, 2))
        lf = tk.Frame(left, bg="#161b22")
        lf.pack(fill=tk.BOTH, expand=True)
        app.track_list = tk.Listbox(
            lf,
            bg="#0d1117",
            fg="white",
            selectbackground="#1f6feb",
            activestyle="none",
            font=("TkFixedFont", list_fnt),
            relief=tk.FLAT,
            borderwidth=0,
        )
        vsb = ttk.Scrollbar(lf, orient=tk.VERTICAL, command=app.track_list.yview)
        app.track_list.configure(yscrollcommand=vsb.set)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        app.track_list.pack(fill=tk.BOTH, expand=True)
        app.track_list.bind("<Double-1>", lambda e: app._open_piano_roll())
        app.track_list.bind("<Button-3>", app._track_ctx)
        right = tk.Frame(pane, bg="#0d1117")
        pane.add(right, minsize=300)
        ov_hdr = tk.Frame(right, bg="#0d1117")
        ov_hdr.pack(fill=tk.X, padx=4, pady=(6, 0))
        tk.Label(
            ov_hdr,
            text="OVERVIEW",
            bg="#0d1117",
            fg="#58a6ff",
            font=("TkDefaultFont", hdr_fnt, "bold"),
        ).pack(side=tk.LEFT)
        app._ov_mode_btn = tk.Button(
            ov_hdr,
            text="⊞ Minimap",
            bg="#21262d",
            fg="#aaa",
            relief=tk.FLAT,
            padx=4,
            pady=1,
            font=("TkDefaultFont", max(7, hdr_fnt - 1)),
            command=app._toggle_overview_mode,
        )
        app._ov_mode_btn.pack(side=tk.RIGHT, padx=4)
        ov_frame = tk.Frame(right, bg="#0d1117")
        ov_frame.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        ov_vsb = ttk.Scrollbar(ov_frame, orient=tk.VERTICAL)
        ov_vsb.pack(side=tk.RIGHT, fill=tk.Y)
        app.overview = tk.Canvas(
            ov_frame,
            bg="#0d1117",
            relief=tk.FLAT,
            bd=0,
            height=120,
            yscrollcommand=ov_vsb.set,
        )
        app.overview.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        ov_vsb.configure(command=app.overview.yview)
        app.overview.bind("<Configure>", app._on_overview_configure)
        app.overview.bind("<Double-1>", app._overview_dbl_click)
        app.overview.bind("<ButtonPress-1>", app._overview_btn_press)
        app.overview.bind("<B1-Motion>", app._overview_drag_motion)
        app.overview.bind("<ButtonRelease-1>", app._overview_btn_release)
        app.overview.bind(
            "<MouseWheel>",
            lambda e: app.overview.yview_scroll(-1 if e.delta > 0 else 1, "units"),
        )


class MixerView(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg="#1a1a2e")
        self.app = app
        self._strips = []
        self._zoom = 1.0
        self._build()

    def zoom_in(self):
        self._zoom = min(2.0, self._zoom * 1.2)
        self._build()

    def zoom_out(self):
        self._zoom = max(0.6, self._zoom / 1.2)
        self._build()

    def _build(self):
        for w in self.winfo_children():
            w.destroy()
            self._strips.clear()
        z = self._zoom
        fnt = max(7, int(9 * z))
        fnt_b = max(7, int(9 * z))
        scale_len = int(75 * z)
        fr = tk.Frame(self, bg="#1a1a2e")
        fr.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        # v22v: use visible_tracks() so empty file-meta tracks don't clutter
        # the mixer — same filtering/renumbering as the track list panel.
        # mk_nm/mk_v/mk_m/mk_s callbacks below all close over the ORIGINAL
        # index i (not sequence position), so editing/mute/solo/volume still
        # affect the correct underlying track regardless of display filtering.
        _visible = self.app.visible_tracks()
        if not _visible:
            tk.Label(
                fr,
                text="No tracks",
                bg="#1a1a2e",
                fg="#888",
                font=("TkDefaultFont", fnt),
            ).pack(side=tk.LEFT, padx=20, pady=20)
        for i, tr, display_name in _visible:
            col = tk.Frame(fr, bg="#16213e", relief=tk.RAISED, bd=1, padx=4, pady=4)
            col.pack(side=tk.LEFT, fill=tk.Y, padx=2)
            nv = tk.StringVar(value=display_name)

            def mk_nm(idx, v):
                def cb(*_):
                    self.app.song.tracks[idx].name = v.get()
                    self.app.song.modified = True
                    self.app._refresh_track_list()

                return cb

            tk.Entry(
                col,
                textvariable=nv,
                width=10,
                bg="#0f3460",
                fg="white",
                insertbackground="white",
                font=("TkDefaultFont", fnt),
            ).pack()
            nv.trace_add("write", mk_nm(i, nv))

            # ── Volume slider beside Mute/Solo/notes (was stacked below —
            #    this cuts ~60-70px off each strip's total height) ────────────
            row = tk.Frame(col, bg="#16213e")
            row.pack()
            vcol = tk.Frame(row, bg="#16213e")
            vcol.pack(side=tk.LEFT)
            tk.Label(vcol, text="Vol", bg="#16213e", fg="white", font=("TkDefaultFont", fnt)).pack()
            vv = tk.IntVar(value=tr.volume)

            def mk_v(idx, v):
                def cb(*_):
                    self.app.song.tracks[idx].volume = v.get()
                    self.app.song.modified = True

                return cb

            tk.Scale(
                vcol,
                from_=127,
                to=0,
                variable=vv,
                orient=tk.VERTICAL,
                bg="#16213e",
                fg="white",
                troughcolor="#0f3460",
                highlightthickness=0,
                length=scale_len,
                command=mk_v(i, vv),
            ).pack()

            msn = tk.Frame(row, bg="#16213e")
            msn.pack(side=tk.LEFT, padx=(4, 0), fill=tk.Y)
            mv = tk.BooleanVar(value=tr.mute)
            sv = tk.BooleanVar(value=tr.solo)

            def mk_m(idx, v):
                def cb():
                    self.app.song.tracks[idx].mute = v.get()

                return cb

            def mk_s(idx, v):
                def cb():
                    self.app.song.tracks[idx].solo = v.get()

                return cb

            tk.Checkbutton(
                msn,
                text="Mute",
                variable=mv,
                bg="#16213e",
                fg="white",
                selectcolor="#333",
                activebackground="#16213e",
                font=("TkDefaultFont", fnt),
                command=mk_m(i, mv),
            ).pack(anchor="w")
            tk.Checkbutton(
                msn,
                text="Solo",
                variable=sv,
                bg="#16213e",
                fg="#fc0",
                selectcolor="#333",
                activebackground="#16213e",
                font=("TkDefaultFont", fnt),
                command=mk_s(i, sv),
            ).pack(anchor="w")
            tk.Label(
                msn,
                text=f"{tr.note_count()}\nnotes",
                bg="#16213e",
                fg="#88aacc",
                font=("TkFixedFont", max(6, fnt - 1)),
                justify=tk.LEFT,
            ).pack(anchor="w", pady=(4, 0))

            tk.Label(
                col, text="Instr", bg="#16213e", fg="white", font=("TkDefaultFont", fnt)
            ).pack()
            pv = tk.StringVar(value=GM_INSTRUMENTS[tr.program])

            def mk_p(idx, v):
                def cb(val):
                    self.app.song.tracks[idx].program = GM_INSTRUMENTS.index(val)
                    self.app.song.modified = True

                return cb

            cw = ttk.Combobox(
                col, textvariable=pv, values=GM_INSTRUMENTS, width=12, state="readonly"
            )
            try:
                cw.configure(font=("TkDefaultFont", fnt))
            except Exception:
                pass
            cw.pack()
            cw.bind("<<ComboboxSelected>>", lambda e, idx=i, v=pv: mk_p(idx, v)(v.get()))
            tk.Label(col, text="Ch", bg="#16213e", fg="white", font=("TkDefaultFont", fnt)).pack()
            cv = tk.IntVar(value=tr.channel + 1)

            def mk_c(idx, v):
                def cb(*_):
                    self.app.song.tracks[idx].channel = v.get() - 1
                    self.app.song.modified = True

                return cb

            tk.Spinbox(
                col,
                from_=1,
                to=16,
                textvariable=cv,
                width=4,
                bg="#0f3460",
                fg="white",
                buttonbackground="#0f3460",
                font=("TkDefaultFont", fnt),
            ).pack()
            cv.trace_add("write", mk_c(i, cv))
            self._strips.append((nv, vv, pv, cv, mv, sv))

        # ── Midi Thru strip — rightmost, fixed (matches original Studio4 layout) ─
        thru = tk.Frame(fr, bg="#0f1f3d", relief=tk.RAISED, bd=1, padx=6, pady=4)
        thru.pack(side=tk.LEFT, fill=tk.Y, padx=(12, 2))
        tk.Label(
            thru,
            text="Midi Thru",
            bg="#0f1f3d",
            fg="#58a6ff",
            font=("TkDefaultFont", fnt_b, "bold"),
        ).pack(pady=(0, 4))
        tk.Checkbutton(
            thru,
            text="Enabled",
            variable=self.app.midi_thru_enabled,
            bg="#0f1f3d",
            fg="white",
            selectcolor="#333",
            activebackground="#0f1f3d",
            font=("TkDefaultFont", fnt),
        ).pack(pady=2)
        tk.Label(thru, text="Volume", bg="#0f1f3d", fg="white", font=("TkDefaultFont", fnt)).pack()
        tk.Scale(
            thru,
            from_=127,
            to=0,
            variable=self.app.midi_thru_volume,
            orient=tk.VERTICAL,
            bg="#0f1f3d",
            fg="white",
            troughcolor="#0a1730",
            highlightthickness=0,
            length=scale_len,
        ).pack()


# ─────────────────────────────────────────────────────────────────────────────
# Song Settings dialog
# ─────────────────────────────────────────────────────────────────────────────


class SongSettingsDlg(tk.Toplevel):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.title("Song Settings")
        # v22ze-46: resizable + always-on-top per presentation request --
        # also reported as too tall for the screen on some displays.
        # v22ze-57: wrapped content in _make_scrollable so shrinking this
        # window below its content shows a scrollbar instead of clipping
        # rows with no way back to them (this dialog is small today, but
        # the same policy applies here as everywhere else).
        self.resizable(True, True)
        self.attributes("-topmost", True)
        self.grab_set()
        content = _make_scrollable(self, bg=self.cget("bg"))
        s = app.song
        tk.Label(content, text="Tempo (BPM):").grid(row=0, column=0, padx=8, pady=4, sticky="w")
        self.bpm_var = tk.IntVar(value=s.bpm)
        tk.Spinbox(content, from_=20, to=300, textvariable=self.bpm_var, width=6).grid(
            row=0, column=1, pady=4
        )
        tk.Label(content, text="Time Signature:").grid(row=1, column=0, padx=8, pady=4, sticky="w")
        tf = tk.Frame(content)
        tf.grid(row=1, column=1, pady=4)
        self.ts_num = tk.IntVar(value=s.time_sig_num)
        self.ts_den = tk.IntVar(value=s.time_sig_den)
        tk.Spinbox(tf, from_=1, to=16, textvariable=self.ts_num, width=3).pack(side=tk.LEFT)
        tk.Label(tf, text=" / ").pack(side=tk.LEFT)
        ttk.Combobox(
            tf,
            textvariable=self.ts_den,
            values=[1, 2, 4, 8, 16, 32],
            width=4,
            state="readonly",
        ).pack(side=tk.LEFT)
        tk.Label(content, text="Ticks per Beat:").grid(row=2, column=0, padx=8, pady=4, sticky="w")
        self.tpb_var = tk.IntVar(value=s.ticks_per_beat)
        tk.Spinbox(
            content, from_=48, to=960, textvariable=self.tpb_var, increment=48, width=6
        ).grid(row=2, column=1)
        bf = tk.Frame(content)
        bf.grid(row=3, column=0, columnspan=2, pady=8)
        tk.Button(bf, text="OK", width=8, command=self._ok).pack(side=tk.LEFT, padx=4)
        tk.Button(bf, text="Cancel", width=8, command=self.destroy).pack(side=tk.LEFT, padx=4)

    def _ok(self):
        s = self.app.song
        s.bpm = self.bpm_var.get()
        s.set_time_signature(self.ts_num.get(), self.ts_den.get())
        s.ticks_per_beat = self.tpb_var.get()
        s.modified = True
        self.app._update_title()
        self.app._update_status()
        self.destroy()


# ─────────────────────────────────────────────────────────────────────────────
# Startup Splash Screen
# ─────────────────────────────────────────────────────────────────────────────


class SplashScreen(tk.Toplevel):
    """Startup splash — stays open until the user explicitly closes it.

    Centers on whichever monitor contains the main program window (correct on
    dual-screen setups).  Dismissed only by clicking the "Continue" button —
    clicking a credit/donation link opens that link in the browser without
    closing the splash.  No auto-close timer.
    """

    def __init__(self, root, app):
        super().__init__(root)
        self.app = app

        # ── Window chrome ──────────────────────────────────────────────────────
        # v22ze-55 fix: overrideredirect(True) tells the window manager
        # "don't manage this window at all" -- that's how we got a
        # borderless splash, but it also meant NO virtual-desktop
        # tracking, since that's WM-managed behavior this window had
        # explicitly opted out of. That's exactly why the splash could
        # get stuck showing on whichever virtual desktop was active when
        # it appeared, regardless of switching desktops afterward --
        # proper Toplevel dialogs and floated-out panels don't have this
        # problem because they ARE WM-managed. On X11/EWMH-compliant
        # window managers, requesting the "splash" window TYPE hint gets
        # the same borderless look while keeping the window WM-managed
        # (so it follows virtual-desktop switches like any other
        # window). '-type' is X11-specific and not available on every
        # platform/WM, so fall back to the old overrideredirect behavior
        # anywhere it's rejected -- this bug is X11-virtual-desktop-
        # specific to begin with, so the fallback is harmless elsewhere.
        try:
            self.wm_attributes("-type", "splash")
        except tk.TclError:
            self.overrideredirect(True)  # no title bar / borders (fallback)
        self.configure(bg="#0d1117")
        self.attributes("-topmost", True)

        # ── Build content ──────────────────────────────────────────────────────
        self._build()

        # ── Position after WM settles ─────────────────────────────────────────
        # On dual-monitor setups, winfo_x/y return virtual-desktop coordinates.
        # If we read them too early the WM hasn't placed the window yet and we
        # get (0,0) — which is the secondary screen on many configurations.
        # Defer 80 ms so the WM has finished placing the main window, then
        # centre the splash on whatever monitor contains the main window.
        self.update_idletasks()
        self.after(80, lambda: self._position_on_parent_screen(root))

        # ── Dismiss bindings ───────────────────────────────────────────────────
        # Only the "Continue" button (below, in _build) dismisses this window.
        # Previously any click anywhere, or any key press, also dismissed it —
        # which meant clicking a credit/donation link both opened the browser
        # AND closed the splash before the user could read anything else on it.

    def _position_on_parent_screen(self, root):
        """Centre on the monitor that currently contains the main window."""
        try:
            root.update()  # ensure root geometry is up-to-date
            self.update_idletasks()

            # Root window position and size in virtual-desktop coordinates
            px = root.winfo_rootx()
            py = root.winfo_rooty()
            pw = root.winfo_width()
            ph = root.winfo_height()

            # Splash size
            w = self.winfo_width()
            h = self.winfo_height()
            if w < 2:
                w = self.winfo_reqwidth()
            if h < 2:
                h = self.winfo_reqheight()

            # Centre of the root window → position splash
            x = px + (pw - w) // 2
            y = py + (ph - h) // 2

            # Clamp so the splash never goes above / left of the root window's
            # screen origin — prevents drifting onto the neighbouring monitor.
            x = max(px, x)
            y = max(py, y)

            self.geometry(f"{w}x{h}+{x}+{y}")
            self.lift()
        except Exception:
            pass  # if anything fails, splash just appears wherever Tk put it

    def _build(self):
        import webbrowser

        BG = "#0d1117"
        BLUE = "#58a6ff"
        GREEN = "#3fb950"
        GOLD = "#d29922"
        MUTED = "#8b949e"
        BDCOL = "#21262d"

        outer = tk.Frame(self, bg=BDCOL, padx=2, pady=2)
        outer.pack()
        inner = tk.Frame(outer, bg=BG, padx=40, pady=30)
        inner.pack()

        tk.Label(inner, text="🎹", bg=BG, fg=BLUE, font=("TkDefaultFont", 38)).pack()

        tk.Label(
            inner,
            text="Midi-Studio",
            bg=BG,
            fg=BLUE,
            font=("TkDefaultFont", 24, "bold"),
        ).pack(pady=(6, 2))

        tk.Label(
            inner,
            text="Work-Alike — no code from the original",
            bg=BG,
            fg=MUTED,
            font=("TkDefaultFont", 9, "italic"),
        ).pack()

        tk.Label(
            inner,
            text="MidiSoft Studio4 created by Raymond Bily",
            bg=BG,
            fg=MUTED,
            font=("TkDefaultFont", 8),
        ).pack(pady=(1, 0))

        _credit_lf = tk.Frame(inner, bg=BG)
        _credit_lf.pack(pady=(2, 0))
        for txt, url in [
            ("MidiSoft.com", "https://midisoft.com/"),
            (
                "MIDISOFT Studio 4.0 @ vetusware.com",
                "https://vetusware.com/download/MIDISOFT%20Studio%204.0%204.0/?id=5666",
            ),
        ]:
            _clk = tk.Label(
                _credit_lf,
                text=txt,
                bg=BG,
                fg=MUTED,
                font=("TkDefaultFont", 7, "underline"),
                cursor="hand2",
            )
            _clk.pack()
            def _open_link(e, u=url):
                webbrowser.open(u)
                return "break"  # don't let this click also reach the
                                # Toplevel's own <Button-1> dismiss binding
            _clk.bind("<Button-1>", _open_link)
            _clk.bind("<Enter>", lambda e, w=_clk: w.configure(fg=BLUE))
            _clk.bind("<Leave>", lambda e, w=_clk: w.configure(fg=MUTED))

        tk.Label(
            inner,
            text=f"Version {APP_VERSION}  ·  Python / tkinter / mido",
            bg=BG,
            fg=GREEN,
            font=("TkDefaultFont", 9),
        ).pack(pady=(4, 8))

        tk.Label(inner, text="A collaboration:", bg=BG, fg=MUTED, font=("TkDefaultFont", 8)).pack()
        tk.Label(
            inner,
            text="Michael F. Winthrop  &  Claude Sonnet 4.6",
            bg=BG,
            fg=GOLD,
            font=("TkDefaultFont", 10, "bold"),
        ).pack(pady=(0, 20))

        tk.Frame(inner, bg=BDCOL, height=1).pack(fill=tk.X)

        tk.Label(
            inner,
            text="Supporting the Sterling Lions Club",
            bg=BG,
            fg=GOLD,
            font=("TkDefaultFont", 11, "italic"),
        ).pack(pady=(16, 6))

        lf = tk.Frame(inner, bg=BG)
        lf.pack()
        for txt, url in [
            ("🦁  Make a Donation", LIONS_DONATE_URL),
            ("🌐  https://e-clubhouse.org/sites/sterlingva", LIONS_WEBSITE_URL),
        ]:
            lk = tk.Label(
                lf,
                text=txt,
                bg=BG,
                fg=BLUE,
                font=("TkDefaultFont", 10, "underline"),
                cursor="hand2",
            )
            lk.pack(pady=1)

            def _open_lions_link(e, u=url):
                webbrowser.open(u)
                return "break"

            lk.bind("<Button-1>", _open_lions_link)
            lk.bind("<Enter>", lambda e, w=lk: w.configure(fg="#79c0ff"))
            lk.bind("<Leave>", lambda e, w=lk: w.configure(fg=BLUE))

        tk.Frame(inner, bg=BDCOL, height=1).pack(fill=tk.X, pady=(16, 8))

        midi_ok = midi_io.MIDI_OUT_OK
        midi_txt = "MIDI ready" if midi_ok else "⚠  No MIDI output — start TiMidity"
        midi_col = GREEN if midi_ok else "#f78166"
        tk.Label(inner, text=midi_txt, bg=BG, fg=midi_col, font=("TkDefaultFont", 9)).pack()

        tk.Label(
            inner,
            text="Click Continue below to proceed",
            bg=BG,
            fg=MUTED,
            font=("TkDefaultFont", 8),
        ).pack(pady=(6, 4))

        tk.Button(
            inner,
            text="Continue  ▶",
            bg="#21262d",
            fg=BLUE,
            activebackground="#30363d",
            activeforeground="#79c0ff",
            relief=tk.FLAT,
            bd=0,
            padx=16,
            pady=6,
            font=("TkDefaultFont", 10, "bold"),
            cursor="hand2",
            command=self._dismiss,
        ).pack(pady=(4, 0))

    def _dismiss(self):
        try:
            self.destroy()
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────────────────────
class QuantizeDlg(tk.Toplevel):
    """Full quantization dialog (v19g).

    Features
    --------
    • Target: armed track or all tracks.
    • Measure range: all measures, or a user-specified N–M window.
    • Grid division: quarter / eighth / sixteenth / 32nd.
    • Snap strength: 100 % / 75 % / 50 %.
    • Grace-note cleanup: remove notes shorter than a threshold before snapping.
    """

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.title("Quantize")
        # v22ze-46: resizable + always-on-top per presentation request
        self.resizable(True, True)
        self.attributes("-topmost", True)
        self.configure(bg="#0d1117")
        self.grab_set()
        self._build()
        self.wait_window(self)

    # ── UI construction ───────────────────────────────────────────────────────
    def _build(self):
        song = self.app.song
        BG = "#0d1117"
        FG = "white"
        LBG = "#161b22"  # label-frame bg
        pad = dict(padx=12, pady=6)
        lf_kw = dict(
            bg=LBG,
            fg="#58a6ff",
            font=("TkDefaultFont", 9, "bold"),
            relief=tk.GROOVE,
            bd=1,
        )
        rb_kw = dict(
            bg=LBG,
            fg=FG,
            selectcolor="#21262d",
            activebackground=LBG,
            activeforeground=FG,
        )
        # v22ze-57: content lives in a scrollable inner frame (not `self`
        # directly) so shrinking this window below its content shows a
        # scrollbar on the right edge instead of clipping controls.
        content = _make_scrollable(self, bg=BG)

        # ── Target ────────────────────────────────────────────────────────────
        tf = tk.LabelFrame(content, text=" Target ", **lf_kw)
        tf.pack(fill=tk.X, **pad)
        self._target = tk.StringVar(value="armed")
        armed_name = (
            song.tracks[self.app._rec_armed].name
            if self.app._rec_armed is not None and self.app._rec_armed < len(song.tracks)
            else "—"
        )
        tk.Radiobutton(
            tf,
            text=f"Armed track  ({armed_name})",
            variable=self._target,
            value="armed",
            **rb_kw,
        ).pack(anchor="w", padx=6, pady=2)
        tk.Radiobutton(tf, text="All tracks", variable=self._target, value="all", **rb_kw).pack(
            anchor="w", padx=6
        )

        # ── Measure Range ─────────────────────────────────────────────────────
        mf = tk.LabelFrame(content, text=" Measure Range ", **lf_kw)
        mf.pack(fill=tk.X, **pad)
        self._range = tk.StringVar(value="all")
        tk.Radiobutton(
            mf,
            text="All measures",
            variable=self._range,
            value="all",
            command=self._sync_range,
            **rb_kw,
        ).pack(anchor="w", padx=6, pady=2)

        rf = tk.Frame(mf, bg=LBG)
        rf.pack(anchor="w", padx=6, pady=(0, 6))
        tk.Radiobutton(
            rf,
            text="From measure",
            variable=self._range,
            value="range",
            command=self._sync_range,
            **rb_kw,
        ).pack(side=tk.LEFT)

        total_meas = max(1, int(song.total_ticks() // song.ticks_per_measure()))
        self._m_from = tk.IntVar(value=1)
        self._m_to = tk.IntVar(value=total_meas)
        spin_kw = dict(
            bg="#21262d",
            fg=FG,
            buttonbackground="#21262d",
            insertbackground=FG,
            width=5,
        )
        self._sp_from = tk.Spinbox(rf, from_=1, to=9999, textvariable=self._m_from, **spin_kw)
        self._sp_from.pack(side=tk.LEFT, padx=(4, 2))
        tk.Label(rf, text="to", bg=LBG, fg=FG).pack(side=tk.LEFT)
        self._sp_to = tk.Spinbox(rf, from_=1, to=9999, textvariable=self._m_to, **spin_kw)
        self._sp_to.pack(side=tk.LEFT, padx=(2, 0))

        # ── Division ──────────────────────────────────────────────────────────
        df = tk.LabelFrame(content, text=" Grid Division ", **lf_kw)
        df.pack(fill=tk.X, **pad)
        default_div = getattr(self.app, "quantize_division", 8) or 8
        self._div = tk.IntVar(value=default_div)
        for lbl, val in [
            ("Quarter notes  (1/4)", 4),
            ("Eighth notes   (1/8)", 8),
            ("Sixteenth      (1/16)", 16),
            ("Thirty-second  (1/32)", 32),
        ]:
            tk.Radiobutton(df, text=lbl, variable=self._div, value=val, **rb_kw).pack(
                anchor="w", padx=6, pady=1
            )

        # ── Strength ──────────────────────────────────────────────────────────
        sf = tk.LabelFrame(content, text=" Snap Strength ", **lf_kw)
        sf.pack(fill=tk.X, **pad)
        self._strength = tk.DoubleVar(value=1.0)
        for lbl, val in [
            ("100%  — full snap", 1.0),
            ("75%   — slight humanise", 0.75),
            ("50%   — half-way (humanise)", 0.50),
        ]:
            tk.Radiobutton(sf, text=lbl, variable=self._strength, value=val, **rb_kw).pack(
                anchor="w", padx=6, pady=1
            )

        # ── Grace-note Cleanup ────────────────────────────────────────────────
        gf = tk.LabelFrame(content, text=" Grace Note Cleanup ", **lf_kw)
        gf.pack(fill=tk.X, **pad)
        tk.Label(
            gf,
            text="Remove notes shorter than:",
            bg=LBG,
            fg="#8b949e",
            font=("TkDefaultFont", 8),
        ).pack(anchor="w", padx=6)
        gr = tk.Frame(gf, bg=LBG)
        gr.pack(anchor="w", padx=6, pady=(2, 6))
        default_grace = getattr(self.app, "grace_cleanup_ms", 40)
        self._grace = tk.IntVar(value=default_grace)
        for lbl, val in [
            ("Off", 0),
            ("20 ms", 20),
            ("40 ms", 40),
            ("60 ms", 60),
            ("80 ms", 80),
        ]:
            tk.Radiobutton(gr, text=lbl, variable=self._grace, value=val, **rb_kw).pack(
                side=tk.LEFT, padx=4
            )

        # ── Buttons ───────────────────────────────────────────────────────────
        bf = tk.Frame(content, bg=BG)
        bf.pack(pady=10)
        btn_kw = dict(relief=tk.FLAT, padx=16, pady=5, font=("TkDefaultFont", 10))
        tk.Button(
            bf,
            text="Quantize",
            command=self._ok,
            bg="#1f6feb",
            fg=FG,
            activebackground="#388bfd",
            activeforeground=FG,
            **btn_kw,
        ).pack(side=tk.LEFT, padx=8)
        tk.Button(
            bf,
            text="Cancel",
            command=self.destroy,
            bg="#21262d",
            fg=FG,
            activebackground="#30363d",
            activeforeground=FG,
            **btn_kw,
        ).pack(side=tk.LEFT, padx=8)

        self._sync_range()

    def _sync_range(self):
        """Enable / disable the from/to spinboxes based on range radio."""
        state = tk.NORMAL if self._range.get() == "range" else tk.DISABLED
        for w in (self._sp_from, self._sp_to):
            w.configure(state=state)

    # ── Apply ─────────────────────────────────────────────────────────────────
    def _ok(self):
        import copy as _copy

        song = self.app.song
        tpb = song.ticks_per_beat

        # Measure range
        if self._range.get() == "range":
            m_from = max(1, self._m_from.get())
            m_to = max(m_from, self._m_to.get())
        else:
            m_from = m_to = None

        # Grace threshold: ms → ticks (using current tempo)
        grace_ms = self._grace.get()
        grace_ticks = int(grace_ms * tpb / (song.tempo / 1_000_000) / 1000) if grace_ms > 0 else 0

        # Which tracks
        if self._target.get() == "armed":
            idx = self.app._rec_armed
            if idx is None or idx >= len(song.tracks):
                messagebox.showwarning("No track", "Arm a track first.", parent=self)
                return
            tracks = [song.tracks[idx]]
        else:
            tracks = list(song.tracks)

        # Snapshot BEFORE quantizing so Ctrl+Z can restore it
        before_tracks = _copy.deepcopy(song.tracks)
        before_map = _copy.deepcopy(song.rationalized_measure_map)

        if not tracks:
            messagebox.showwarning("No tracks", "No tracks to quantize.", parent=self)
            return

        total_q = 0
        total_g = 0
        for tr in tracks:
            nq, ng = quantize_notes_per_measure(
                tr,
                song,
                div=self._div.get(),
                strength=self._strength.get(),
                measure_start=m_from,
                measure_end=m_to,
                grace_ticks=grace_ticks,
            )
            total_q += nq
            total_g += ng

        song.modified = True
        self.app._update_title()
        self.app._refresh_track_list()

        # Push undo so Ctrl+Z restores the pre-quantize state
        self.app._push_undo(
            RationalizationAction(
                description="Quantize",
                before_tracks=before_tracks,
                after_tracks=_copy.deepcopy(song.tracks),
                before_map=before_map,
                after_map=_copy.deepcopy(song.rationalized_measure_map),
            )
        )

        # Force an immediate, unconditional redraw — don't rely on the
        # play-state-gated refresh inside _refresh_track_list(), since the
        # user just explicitly asked to see this change right now.
        try:
            sv = self.app._score_view
            if sv is not None and sv.winfo_exists():
                sv._score_dirty = True
                sv._draw()
        except Exception:
            pass

        parts = [f"Quantized {total_q} note(s)."]
        if total_g:
            parts.append(f"Removed {total_g} grace note(s) shorter than {grace_ms} ms.")
        messagebox.showinfo("Quantize Complete", "\n".join(parts), parent=self.app.root)
        self.destroy()


# ─────────────────────────────────────────────────────────────────────────────
# Score View  — all tracks, playback cursor, editable
# ─────────────────────────────────────────────────────────────────────────────


class ScoreView(tk.Frame):
    """
    Full multi-track score view.
    • Each track gets a grand-staff system (treble + bass).
    • Red cursor scrolls with playback.
    • Click to add a note, right-click to remove.
    • Stems, flags (tails) for 8th/16th notes.
    • Whole-measure rests shown.
    """

    # Named tuple for passing stem geometry from _draw_chord to _draw_beams
    from collections import namedtuple

    StemInfo = namedtuple(
        "StemInfo", ["tick", "x", "sx", "stem_root_y", "sy", "stem_up", "db", "staff"]
    )

    # Base geometry constants at zoom 1.0 — instance vars are set by
    # _apply_zoom() which scales these by _vzoom. All drawing code uses
    # self.SLG / self.SH / self.TPAD etc. so scaling just works everywhere.
    _B_SLG = 12  # staff line gap
    _B_TPAD = 58  # grand-staff top pad (label + clef)
    _B_TPAD1 = 36  # single-staff top pad
    _B_TPAD1_TOP = 28  # single-staff treble_top offset
    _B_BGAP = 52  # gap between treble bottom and bass top
    _B_BPAD = 26  # grand-staff bottom pad
    _B_BPAD1 = 16  # single-staff bottom pad
    _B_LM = 60  # left margin (brace zone)
    _B_STRIP_RESERVE = 40  # v22v: extra headroom above track 0 so the
    # measure strip has room to float above high
    # notes without going off the top of the canvas
    MW = 320  # pixels/measure at zoom 1 (horizontal only)
    FIRST_EXTRA = 80  # extra px in measure 0 for clef+timesig

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        # v22ze-65 fix: user-requested default -- the score at initial
        # load was too large, specifically cutting off full visibility
        # of a grand staff (treble+bass together) without scrolling.
        # Reduced by exactly one "Zoom -" step (÷1.33, the same factor
        # the Zoom -/+ buttons themselves use) from the previous
        # defaults, on both axes -- "the score should be one size
        # smaller" is most literally exactly that: one zoom step down
        # from where it started. The zoom controls remain available to
        # go back up from here for anyone who prefers the larger view.
        self._zoom = 0.75  # horizontal zoom — was 1.0
        self._vzoom = 0.62  # vertical zoom — was 0.82 (see prior tuning
        # note below on why 0.82 was chosen over an
        # even-smaller 0.67; this new default is a
        # direct, explicit user request overriding
        # that earlier tuning call, not a reversal
        # of the reasoning behind it)
        # v22ze: was 0.67 ("2/3 to fit
        # more tracks"), but that made noteheads and
        # accidentals read uncomfortably small at the
        # default view (SLG=8px). 0.82 (SLG=9px) was a
        # modest bump favoring initial readability;
        # still well short of full size (1.0, SLG=12px)
        # so multiple tracks still fit reasonably --
        # the zoom controls remain available for
        # either direction from here.
        self._score_dirty = True
        self._last_sr = None  # song changed, force full scrollregion recalc
        self._last_note_count = 0
        # v22ze-25 (housekeeping item 5): playback flash-highlight state.
        # Defaulted here too (not just in _draw_inner) so _ui_tick_update
        # is always safe to call even before the first draw.
        self._flash_index = []
        self._flash_ticks_only = None
        self._currently_lit = {}
        self.configure(bg="#fffff8")
        self._apply_zoom()  # set self.SLG / SH / TPAD … from _vzoom
        self._build_ui()
        self._draw()

    def _apply_zoom(self):
        """Recompute all vertical geometry from current _vzoom."""
        z = self._vzoom
        self.SLG = max(4, int(self._B_SLG * z))
        self.SH = 4 * self.SLG
        self.TPAD = max(18, int(self._B_TPAD * z))
        self.TPAD1 = max(12, int(self._B_TPAD1 * z))
        self.TPAD1_TOP = max(8, int(self._B_TPAD1_TOP * z))
        self.BGAP = max(8, int(self._B_BGAP * z))
        self.BPAD = max(6, int(self._B_BPAD * z))
        self.BPAD1 = max(4, int(self._B_BPAD1 * z))
        self.LM = max(20, int(self._B_LM * z))
        self.STRIP_RESERVE = max(20, int(self._B_STRIP_RESERVE * z))

    # ── geometry ──────────────────────────────────────────────────────────────
    # GM programs that warrant a grand staff (piano, organ, harpsichord family)
    _GRAND_STAFF_PROGRAMS = frozenset(range(0, 8)) | frozenset(range(16, 24))

    def _uses_grand_staff(self, tr):
        """Return True if this track should be rendered as a grand staff.

        Respects tr.staff_mode:
          "grand"  -> always True  (user chose keyboard / grand staff)
          "single" -> always False (user chose single-line instrument)
          "auto"   -> decide by GM program number (backward-compatible)
        """
        mode = getattr(tr, "staff_mode", "auto")
        if mode == "grand":
            return True
        if mode == "single":
            return False
        # "auto": use GM program family
        return tr.program in self._GRAND_STAFF_PROGRAMS

    def _sys_h(self, tr=None):
        if tr is not None and not self._uses_grand_staff(tr):
            return self.TPAD1 + self.SH + self.BPAD1  # single staff
        return self.TPAD + self.SH + self.BGAP + self.SH + self.BPAD

    def _track_yo(self, ti, tracks=None):
        _top = 4 + getattr(self, "STRIP_RESERVE", 40)  # v22v: strip headroom
        if tracks is None:
            return _top + ti * (self.TPAD + self.SH + self.BGAP + self.SH + self.BPAD)
        y = _top
        for i in range(ti):
            y += self._sys_h(tracks[i])
        return y

    def _treble_top(self, ti, tracks=None):
        tr = tracks[ti] if tracks else None
        if tr is not None and not self._uses_grand_staff(tr):
            return self._track_yo(ti, tracks) + self.TPAD1_TOP
        return self._track_yo(ti, tracks) + self.TPAD

    def _bass_top(self, ti, tracks=None):
        tr = tracks[ti] if tracks else None
        if tr is None or not self._uses_grand_staff(tr):
            return None  # sentinel — callers must check before drawing bass staff
        return self._treble_top(ti, tracks) + self.SH + self.BGAP

    def _mw(self):
        return int(self.MW * self._zoom)

    def _fe(self):
        return int(self.FIRST_EXTRA * self._zoom)

    def _sp_to_y_treble(self, pos, tt):
        """Convert staff position to canvas y.
        E4 (pos=2)  = bottom line = tt+SH
        F5 (pos=10) = top line    = tt"""
        return (tt + self.SH) - (pos - 2) * (self.SLG / 2)

    def _sp_to_y_bass(self, pos, bt):
        """Convert staff position to canvas y.
        G2 (pos=-10) = bottom line = bt+SH
        A3 (pos=-2)  = top line    = bt"""
        return (bt + self.SH) - (pos - (-10)) * (self.SLG / 2)

    @property
    def _px_per_tick(self):
        """Pixels per tick at current zoom.  At zoom=1, a 4/4 measure = MW px."""
        tpb = self.app.song.ticks_per_beat
        return self.MW * self._zoom / max(1, tpb * 4)

    def _tick_to_x(self, tick):
        """Tick → canvas x.  Linear in tick so variable-length measures scale correctly."""
        return self.LM + self._fe() + int(tick * self._px_per_tick)

    def _x_to_tick(self, x):
        ppt = self._px_per_tick
        if ppt <= 0:
            return 0
        return max(0, int((x - self.LM - self._fe()) / ppt))

    # ── UI ────────────────────────────────────────────────────────────────────
    def _build_ui(self):
        tb = tk.Frame(self, bg="#e8e8e0", pady=2)
        tb.pack(fill=tk.X)
        bs = dict(relief=tk.FLAT, bg="#d0d0c8", padx=6, pady=1)
        _tt(
            tk.Button(tb, text="Zoom +", command=self._zoom_in, **bs),
            "Zoom in on the score. Vertical and horizontal scale together.",
        ).pack(side=tk.LEFT, padx=2)
        _tt(
            tk.Button(tb, text="Zoom −", command=self._zoom_out, **bs),
            "Zoom out on the score.",
        ).pack(side=tk.LEFT, padx=2)
        _tt(
            tk.Button(tb, text="Fit Width", command=self._fit, **bs),
            "Scale the whole piece to fit the visible window width exactly.",
        ).pack(side=tk.LEFT, padx=2)
        _tt(
            tk.Button(tb, text="Fit Width +", command=self._fit_wider, **bs),
            "Show one more measure across the screen (zooms out by one "
            "measure's width, without changing vertical zoom).",
        ).pack(side=tk.LEFT, padx=2)
        _tt(
            tk.Button(tb, text="Fit Width −", command=self._fit_narrower, **bs),
            "Show one fewer measure across the screen (zooms in by one "
            "measure's width, without changing vertical zoom).",
        ).pack(side=tk.LEFT, padx=2)
        # ── Editing toolbar: tabbed tool palette ──────────────────────────────
        # v22ze-35: replaces the standalone "Note value" dropdown with a
        # full tabbed palette (Note/Rest, Accidental, Dynamics,
        # Articulation, Measures), per the housekeeping-list follow-up
        # request. Which tab is active determines what a canvas click
        # does -- see _on_click, which dispatches on self._active_tool.
        self._active_tool = "note_rest"  # note_rest | accidental | dynamics | articulation
        self._entry_mode_var = tk.StringVar(value="note")  # note | rest
        self._dur_var = tk.StringVar(value="quarter")
        self._accidental_var = tk.StringVar(value="sharp")
        self._dynamic_var = tk.StringVar(value="mf")
        self._articulation_var = tk.StringVar(value="staccato")

        nb = ttk.Notebook(self, height=42)
        nb.pack(fill=tk.X, side=tk.TOP)

        def _on_tab_changed(event=None):
            idx = nb.index(nb.select())
            self._active_tool = [
                "note_rest",
                "accidental",
                "dynamics",
                "articulation",
                "measures",
            ][idx]

        nb.bind("<<NotebookTabChanged>>", _on_tab_changed)

        tabbg = "#e8e8e0"

        # -- Tab 1: Note / Rest --------------------------------------------
        t1 = tk.Frame(nb, bg=tabbg)
        nb.add(t1, text="Note/Rest")
        tk.Radiobutton(t1, text="Note", variable=self._entry_mode_var, value="note", bg=tabbg).pack(
            side=tk.LEFT, padx=(8, 2), pady=6
        )
        tk.Radiobutton(t1, text="Rest", variable=self._entry_mode_var, value="rest", bg=tabbg).pack(
            side=tk.LEFT, padx=2
        )
        tk.Label(t1, text="  Duration:", bg=tabbg).pack(side=tk.LEFT, padx=(10, 2))
        ttk.Combobox(
            t1,
            textvariable=self._dur_var,
            values=["whole", "half", "quarter", "eighth", "16th"],
            width=8,
            state="readonly",
        ).pack(side=tk.LEFT)
        tk.Label(
            t1,
            text="  Click the staff to insert. Right-click a note to delete.",
            bg=tabbg,
            fg="#666",
            font=("TkDefaultFont", 8),
        ).pack(side=tk.LEFT, padx=10)

        # -- Tab 2: Accidental ------------------------------------------------
        t2 = tk.Frame(nb, bg=tabbg)
        nb.add(t2, text="Accidental")
        _acc_labels = [
            ("double_flat", "𝄫"),
            ("flat", "♭"),
            ("natural", "♮"),
            ("sharp", "♯"),
            ("double_sharp", "𝄪"),
        ]
        for val, sym in _acc_labels:
            tk.Radiobutton(
                t2,
                text=sym,
                variable=self._accidental_var,
                value=val,
                bg=tabbg,
                indicatoron=0,
                width=3,
                font=("TkDefaultFont", 11),
            ).pack(side=tk.LEFT, padx=2, pady=6)
        tk.Label(
            t2,
            text="  Click an existing note to apply.",
            bg=tabbg,
            fg="#666",
            font=("TkDefaultFont", 8),
        ).pack(side=tk.LEFT, padx=10)

        # -- Tab 3: Dynamics ---------------------------------------------------
        t3 = tk.Frame(nb, bg=tabbg)
        nb.add(t3, text="Dynamics")
        for val in ["ppp", "pp", "p", "mp", "mf", "f", "ff", "fff"]:
            tk.Radiobutton(
                t3,
                text=val,
                variable=self._dynamic_var,
                value=val,
                bg=tabbg,
                indicatoron=0,
                width=4,
                font=("TkDefaultFont", 9, "italic"),
            ).pack(side=tk.LEFT, padx=1, pady=6)
        tk.Label(
            t3,
            text="  Click below the staff to place.",
            bg=tabbg,
            fg="#666",
            font=("TkDefaultFont", 8),
        ).pack(side=tk.LEFT, padx=10)

        # -- Tab 4: Articulation ------------------------------------------------
        t4 = tk.Frame(nb, bg=tabbg)
        nb.add(t4, text="Articulation")
        _art_labels = [
            ("staccato", "Staccato"),
            ("accent", "Accent"),
            ("tenuto", "Tenuto"),
            ("legato", "Legato"),
            ("marcato", "Marcato"),
            ("pizzicato", "Pizz."),
            ("arco", "Arco"),
        ]
        for val, label in _art_labels:
            tk.Radiobutton(
                t4,
                text=label,
                variable=self._articulation_var,
                value=val,
                bg=tabbg,
                indicatoron=0,
                padx=4,
            ).pack(side=tk.LEFT, padx=1, pady=6)
        tk.Label(
            t4,
            text="  Click an existing note to toggle.",
            bg=tabbg,
            fg="#666",
            font=("TkDefaultFont", 8),
        ).pack(side=tk.LEFT, padx=10)

        # -- Tab 5: Measures ------------------------------------------------
        t5 = tk.Frame(nb, bg=tabbg)
        nb.add(t5, text="Measures")
        tk.Label(
            t5,
            text="  Right-click any measure on the staff for " "Insert / Delete / Cut options.",
            bg=tabbg,
            fg="#333",
        ).pack(side=tk.LEFT, padx=8, pady=6)

        # ── Mini transport (synced to main app) ──────────────────────────────
        tk.Frame(tb, width=1, bg="#aaa").pack(side=tk.LEFT, fill=tk.Y, padx=8, pady=2)
        mbs = dict(relief=tk.FLAT, bg="#c8c8c0", padx=5, pady=1, font=("TkDefaultFont", 12))
        tk.Button(tb, text="⏮", command=self._t_rewind, **mbs).pack(side=tk.LEFT, padx=1)
        mbs2 = dict(relief=tk.FLAT, bg="#c8c8c0", padx=5, pady=1, font=("TkDefaultFont", 9))
        self._score_play_btn = tk.Button(tb, text="▶ Play", command=self._t_play_pause, **mbs2)
        self._score_play_btn.pack(side=tk.LEFT, padx=1)
        tk.Button(tb, text="⏹ Stop", command=self._t_stop, **mbs2).pack(side=tk.LEFT, padx=1)
        self._score_rec_btn = tk.Button(
            tb,
            text="⏺ Rec",
            command=self._t_rec,
            bg="#0f3320",
            fg="#3fb950",
            relief=tk.FLAT,
            padx=5,
            pady=1,
            font=("TkDefaultFont", 9),
        )
        self._score_rec_btn.pack(side=tk.LEFT, padx=1)
        # Manual hand-split override (MIDI pitch; 0 = auto gap detection)
        tk.Frame(tb, width=1, bg="#aaa").pack(side=tk.LEFT, fill=tk.Y, padx=6, pady=2)
        tk.Label(tb, text="Split pitch:", bg="#e8e8e0").pack(side=tk.LEFT)
        self._split_var = tk.IntVar(value=0)
        sp = tk.Spinbox(
            tb,
            from_=0,
            to=127,
            textvariable=self._split_var,
            width=4,
            command=self._draw,
        )
        sp.pack(side=tk.LEFT, padx=2)
        sp.bind("<Return>", lambda e: self._draw())
        tk.Label(tb, text="(0=auto)", bg="#e8e8e0", font=("TkDefaultFont", 8)).pack(side=tk.LEFT)
        # v22ze-66 fix: user feedback -- this control's units (a raw MIDI
        # pitch 0-127, the fixed line above which notes render in the
        # treble staff) were easy to confuse with the completely
        # different "max hand span" setting (semitones of INTERVAL, not
        # an absolute pitch) used by Rationalize/Separate Hands. Both
        # happen to land near similar practical values for a typical
        # piece (e.g. ~55, just below middle C), which made the mix-up
        # easy: this is a live, per-note DISPLAY split point (every note
        # >= this pitch draws in treble, no matter what else is on the
        # page), not a span-based reassignment computed once, so 1
        # pushes nearly everything up (pitch 1 is close to the bottom of
        # the MIDI range) rather than doing anything resembling a
        # semitone-span split.
        _tt(
            sp,
            "Manual staff-split PITCH (0-127), not a hand-span setting.\n"
            "Every note at or above this MIDI pitch draws in the treble\n"
            "staff; everything below draws in the bass staff. This is a\n"
            "live display override, recomputed on every redraw -- it\n"
            "does not change any note data.\n\n"
            "0 = auto (gap-detection picks a sensible split per chord).\n"
            "A typical manual value is around 55-60 (just below middle C).\n\n"
            "This is a different setting from \u201cMax hand span\u201d in the\n"
            "Rationalize Score dialog or Edit \u25b8 Separate Hands, which\n"
            "measures the INTERVAL (in semitones) a hand can comfortably\n"
            "reach, not a fixed pitch line.",
        )
        fr = tk.Frame(self, bg="#fffff8")
        fr.pack(fill=tk.BOTH, expand=True)
        self.canvas = tk.Canvas(fr, bg="#fffff8", cursor="crosshair")
        hb = ttk.Scrollbar(fr, orient=tk.HORIZONTAL, command=self.canvas.xview)
        vb = ttk.Scrollbar(fr, orient=tk.VERTICAL, command=self.canvas.yview)
        self.canvas.configure(xscrollcommand=hb.set, yscrollcommand=vb.set)
        vb.pack(side=tk.RIGHT, fill=tk.Y)
        hb.pack(side=tk.BOTTOM, fill=tk.X)
        self.canvas.pack(fill=tk.BOTH, expand=True)
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self.canvas.bind("<Button-1>", self._on_click)
        self.canvas.bind("<Button-3>", self._on_right)

    def _current_cursor_tick(self):
        """Current transport position, safely, for redraws triggered by
        something other than an actual playback tick (zoom, fit, resize).

        v22ze-64 fix: _zoom_in/_zoom_out/_fit/_fit_n all called bare
        self._draw() with no cursor_tick -- the same mistake just fixed
        for window-resize redraws in _deferred_configure_redraw (see
        v22ze-63), just triggered by the Zoom +/-/Fit buttons instead of
        an actual widget resize. Per this codebase's convention,
        cursor_tick=None means "draw with NO playhead line at all," so
        every zoom/fit action was silently erasing the cursor outright,
        coming back only once Play was pressed again (which re-triggers
        the fast-path fallback that recreates a lost playhead -- but
        only on an actual tick, so nothing brought it back while
        stopped). Centralizing this avoids repeating the same
        try/except at every call site.
        """
        try:
            return self.app.transport.position_ticks
        except Exception:
            return None

    def _zoom_in(self):
        self._zoom = min(4.0, self._zoom * 1.33)
        self._vzoom = min(2.0, self._vzoom * 1.33)
        self._last_sr = None  # force scrollregion recalc at new zoom
        self._apply_zoom()
        self._draw(cursor_tick=self._current_cursor_tick())

    def _zoom_out(self):
        self._zoom = max(0.2, self._zoom / 1.33)
        self._vzoom = max(0.2, self._vzoom / 1.33)
        self._last_sr = None  # force scrollregion recalc at new zoom
        self._apply_zoom()
        self._draw(cursor_tick=self._current_cursor_tick())

    def _fit(self):
        song = self.app.song
        total_ticks = song.total_ticks()
        if total_ticks <= 0:
            return
        w = self.canvas.winfo_width() - self.LM - int(self._fe()) - 40
        tpb = song.ticks_per_beat
        # _px_per_tick * total_ticks == w  →  zoom = w*tpb*4 / (total_ticks*MW)
        self._zoom = max(0.2, w * tpb * 4 / (total_ticks * self.MW))
        self._draw(cursor_tick=self._current_cursor_tick())

    def _n_visible_measures(self):
        """Return the number of measures currently visible across the canvas width."""
        w = self.canvas.winfo_width() - self.LM - int(self._fe()) - 40
        if w <= 0:
            return 1
        meas_w = self.MW * self._zoom
        if meas_w <= 0:
            return 1
        return max(1, round(w / meas_w))

    def _fit_n(self, n):
        """Set zoom so exactly n measures fit across the visible canvas width.

        This is a view-only operation (like zoom +/-).  No undo needed.
        Vertical zoom (_vzoom) is not affected.
        """
        n = max(1, int(n))
        w = self.canvas.winfo_width() - self.LM - int(self._fe()) - 40
        if w <= 0:
            return
        self._zoom = max(0.05, w / (n * self.MW))
        self._last_sr = None  # force scrollregion recalc at new zoom
        self._apply_zoom()
        self._draw(cursor_tick=self._current_cursor_tick())

    def _fit_wider(self):
        """Show one more measure across the canvas (zoom out by one measure step)."""
        self._fit_n(self._n_visible_measures() + 1)

    def _fit_narrower(self):
        """Show one fewer measure across the canvas (zoom in by one measure step).
        Minimum is 1 measure visible.
        """
        self._fit_n(max(1, self._n_visible_measures() - 1))

    def _ui_tick_update(self, tick):
        """
        UI-only update hook.
        MUST NOT affect playback timing.

        v22ze-25 (housekeeping item 5): temporarily fills the notehead(s)
        struck at/near the current playback tick in neon green, then
        reverts them to their normal fill once a brief flash window
        passes -- matching the original MidiSoft Studio4's behavior of
        lighting up notes as they're played. _flash_index is a
        (tick, item_id, orig_fill) list built once per redraw by
        _draw_chord (see _draw_inner reset + notehead registration
        above); sorted by tick so bisect can find the small window of
        candidates near `tick` without scanning the whole piece.
        """
        try:
            idx = self._flash_index
            if not idx:
                return
            song = self.app.song
            tpb = song.ticks_per_beat if song and getattr(song, "ticks_per_beat", None) else 480
            flash_span = max(1, tpb // 8)  # briefly -- roughly a 32nd note's worth of ticks
            lo = tick - flash_span
            ticks_only = self._flash_ticks_only
            if ticks_only is None:
                ticks_only = [t for t, _, _ in idx]
                self._flash_ticks_only = ticks_only
            i_lo = bisect.bisect_left(ticks_only, lo)
            i_hi = bisect.bisect_right(ticks_only, tick)
            new_lit = {}
            for t, item_id, orig_fill in idx[i_lo:i_hi]:
                new_lit[item_id] = orig_fill
            prev_lit = self._currently_lit
            c = self.canvas
            for item_id, orig_fill in prev_lit.items():
                if item_id not in new_lit:
                    try:
                        c.itemconfig(item_id, fill=orig_fill)
                    except Exception:
                        pass
            for item_id in new_lit:
                if item_id not in prev_lit:
                    try:
                        c.itemconfig(item_id, fill="#39FF14")  # neon green
                    except Exception:
                        pass
            self._currently_lit = new_lit
        except Exception:
            pass

    def clear_flash_highlights(self):
        """Revert any currently-lit noteheads to their normal fill --
        call on stop/rewind so playback stopping doesn't leave a note
        stuck neon green (housekeeping item 5)."""
        try:
            c = self.canvas
            for item_id, orig_fill in getattr(self, "_currently_lit", {}).items():
                try:
                    c.itemconfig(item_id, fill=orig_fill)
                except Exception:
                    pass
            self._currently_lit = {}
        except Exception:
            pass

    # ── main draw ─────────────────────────────────────────────────────────────
    # Number of placeholder empty staves shown before any file is loaded
    _PLACEHOLDER_TRACKS = 6

    def _on_canvas_configure(self, event=None):
        """Debounced handler for canvas <Configure> events.

        The canvas fires <Configure> whenever the window is resized OR when a
        tk.Toplevel is created/destroyed near it (geometry change propagates).
        Without debouncing, opening the Score Setup panel fires <Configure>
        mid-construction, which calls _draw() while the panel's internal state
        is partially initialised and produces phantom canvas items.

        We cancel any pending redraw job and schedule a fresh one 50 ms later.
        50 ms is imperceptible to the user but long enough for Toplevel
        construction to complete and for rapid resize events to collapse into
        a single repaint.
        """
        job = getattr(self, "_configure_job", None)
        if job is not None:
            try:
                self.canvas.after_cancel(job)
            except Exception:
                pass
        self._configure_job = self.canvas.after(50, self._deferred_configure_redraw)

    def _deferred_configure_redraw(self):
        # v22ze-38 fix: a <Configure> event (which scrollregion/xview_
        # moveto changes can trigger on some platforms -- see the
        # comments above and on _draw()) used to force a full redraw
        # here unconditionally. On a large piece a full redraw takes
        # over a second; forcing one mid-playback blocks the entire
        # event loop for that long, during which the cursor can't move
        # or scroll at all while audio (on its own thread) keeps
        # playing -- confirmed by direct reproduction to be a real
        # contributor to the "cursor goes off-screen and gets stuck"
        # symptom. The fast-path cursor update in update_cursor already
        # keeps the score correctly positioned during playback without
        # needing a full redraw, so just defer this until playback stops.
        try:
            if self.app.transport.is_playing():
                self._configure_job = self.canvas.after(200, self._deferred_configure_redraw)
                return
        except Exception:
            pass
        # v22ze-63 fix: this used to be a bare self._draw() -- per the
        # established convention here (see _load_file's fix, and _draw's
        # own signature below), cursor_tick=None means "draw with NO
        # playhead line at all," not "draw at whatever the current
        # position is." So ANY resize of the score panel -- playing or
        # not -- silently erased the cursor outright, regardless of
        # wherever playback (or a paused/stopped position) actually was.
        # It only ever came back because pressing Play re-triggers
        # update_cursor's fast path, which has its own "playhead tag was
        # lost, recreate it" fallback -- but that fallback only runs on
        # an actual tick, so with playback stopped there was no tick to
        # trigger it, and the cursor just stayed gone. Passing the
        # transport's own current position keeps the cursor exactly
        # where it belongs through a resize, playing or not.
        try:
            cursor_tick = self.app.transport.position_ticks
        except Exception:
            cursor_tick = None
        self._draw(cursor_tick=cursor_tick)

    def _draw(self, cursor_tick=None):
        # Re-entrancy guard: <Configure> can fire while _draw() is running
        # (e.g. when we configure scrollregion or xview_moveto scrolls the
        # canvas).  Without the guard that causes an infinite redraw loop
        # visible as rapid flickering during playback at high zoom.
        if getattr(self, "_drawing", False):
            return
        self._drawing = True
        try:
            self._draw_inner(cursor_tick=cursor_tick)
        finally:
            self._drawing = False

    def _draw_inner(self, cursor_tick=None):
        self._score_dirty = False
        c = self.canvas
        c.delete("all")
        song = self.app.song
        # v22ze-38 fix: this was the actual root cause of the "cursor
        # goes off-screen and gets stuck during playback" bug on any
        # real-sized piece. _last_note_count started at 0 and was ONLY
        # ever updated inside update_cursor's own dirty-check -- never
        # here, on a full redraw. That meant the very FIRST update_cursor
        # call during playback always saw a mismatch (0 vs the real
        # count), unconditionally forcing an unnecessary full redraw --
        # which on a large piece (orchestra scale) took ~1.5 SECONDS,
        # blocking the entire event loop, during which the cursor could
        # not move or scroll at all while audio (on its own thread) kept
        # playing. That redraw's scrollregion reconfiguration also
        # plausibly re-triggers a <Configure> event, cascading into a
        # SECOND unnecessary full redraw via the debounced handler below
        # -- confirmed by direct reproduction: exactly 2 spurious ~1.5s
        # redraws per playback session, matching this trigger chain
        # exactly. Keeping this synced here eliminates the false
        # mismatch at its source.
        self._last_note_count = sum(len(tr.notes) for tr in song.tracks)
        # v22ze-25 (housekeeping item 5): rebuild the playback flash-
        # highlight index every redraw, since all previous canvas item
        # ids are invalidated by the delete("all") above. Populated by
        # _draw_chord as it draws each notehead; consumed by
        # _ui_tick_update during playback.
        self._flash_index = []
        self._flash_ticks_only = None
        self._currently_lit = {}

        if not song.tracks:
            # Note 0: draw placeholder empty staves so the score area looks
            # like a real score editor rather than a blank white box.
            self._draw_placeholder_staves(c)
            c.update_idletasks()
            return

        # Auto-set the notation grid for this song (v22q).
        # NOTATION_DIVISION is a module global used by bake_to_score() and
        # to_ly() but we override it locally for this render pass so every
        # note the synthesizer plays appears on the screen.
        # Result: 1/16 and 1/32 notes visible on initial load.
        import sys as _draw_sys

        global NOTATION_DIVISION
        _detected_div = song.detect_notation_division()
        if _detected_div != NOTATION_DIVISION:
            NOTATION_DIVISION = _detected_div
        mmap = song.get_measure_map()
        nm = len(mmap)
        total_ticks = song.total_ticks()

        # ── Merge RH/LH pairs into one grand staff ────────────────────────
        # Two naming conventions are recognized:
        #   1. rationalize()'s own suffix: 'Piano (RH)' + 'Piano (LH)'
        #   2. Common hand-naming keywords: 'Piano right'/'Piano left',
        #      'Right Hand'/'Left Hand', 'RH'/'LH' as whole words — e.g.
        #      files prepared in other software or by hand, which use
        #      "right"/"left" rather than our own "(RH)"/"(LH)" suffix.
        #      Without this, an already well-separated file (exactly the
        #      kind "Preserve existing hand tracks" is meant to help) still
        #      rendered as two separate grand staves instead of one.
        # Merging into one track before drawing gives 2 staves, not 4 —
        # the grand-staff renderer splits treble/bass by pitch automatically
        # regardless of which original track a note came from.
        import copy as _sv_copy
        import re as _sv_re

        def _sv_hand_hint(name):
            n = name.lower()
            if _sv_re.search(r"\bright\b|\brh\b", n):
                return "R"
            if _sv_re.search(r"\bleft\b|\blh\b", n):
                return "L"
            return None

        def _sv_rh_lh(ta, tb):
            if (
                ta.name.endswith(" (RH)")
                and tb.name.endswith(" (LH)")
                and ta.name[:-5] == tb.name[:-5]
            ):
                return True
            if _sv_hand_hint(ta.name) == "R" and _sv_hand_hint(tb.name) == "L":
                return True
            # v22zc: fallback — two consecutive same-instrument-family piano
            # tracks merge into one grand staff even without a name match.
            # to_ly() has always done this (confirmed correct by inspecting
            # an actual printed page: the combined texture reads as one
            # coherent musical idea, hand-crossing figures spanning both
            # staves, hairpins covering both — not two awkwardly-stitched
            # parts).  The screen renderer previously had NO equivalent,
            # so a file with generically-named piano tracks ("Track 2",
            # "Track 3") showed two separate grand staves on screen while
            # the exported PDF correctly showed one.  This brings the two
            # renderers back into agreement using the SAME criterion.
            return (
                ta.program in self._GRAND_STAFF_PROGRAMS
                and tb.program in self._GRAND_STAFF_PROGRAMS
            )

        def _sv_merged_name(name):
            if name.endswith(" (RH)"):
                return name[:-5]
            stripped = _sv_re.sub(
                r"\s*\b(right|rh)\b\s*", " ", name, flags=_sv_re.IGNORECASE
            ).strip()
            return stripped if stripped else name

        raw = song.tracks
        tracks = []
        _i = 0
        while _i < len(raw):
            if _i + 1 < len(raw) and _sv_rh_lh(raw[_i], raw[_i + 1]):
                m = _sv_copy.copy(raw[_i])
                m.name = _sv_merged_name(raw[_i].name)
                m.program = 0  # ensure piano grand staff
                # v22ze-28 fix (housekeeping item 8 regression): this used
                # to merge RH+LH notes into one pitch-mixed list and
                # re-derive the hand split via a gap heuristic, discarding
                # the DP's actual hand assignment entirely -- to_ly()
                # never did this ("No pitch re-splitting: DP hand
                # separation already ran"), so the two renderers could
                # disagree, sometimes badly (a single outlier note anywhere
                # in the piece could skew a whole-track gap search enough
                # to dump nearly everything into one hand). Copy each
                # note (never mutate the real song data) and tag the copy
                # with which side of the pair it came from via the
                # existing `channel` slot (0=RH, 1=LH) -- _draw_chords
                # below trusts this tag directly for any track marked
                # _prehand_split, bypassing pitch-based splitting for it
                # completely, the same as to_ly does.
                rh_copies = [_sv_copy.copy(n) for n in raw[_i].notes]
                lh_copies = [_sv_copy.copy(n) for n in raw[_i + 1].notes]
                for n in rh_copies:
                    n.channel = 0
                for n in lh_copies:
                    n.channel = 1
                m.notes = sorted(rh_copies + lh_copies, key=lambda n: n.tick)
                m._prehand_split = True
                tracks.append(m)
                _i += 2
            else:
                tracks.append(raw[_i])
                _i += 1

        # Suppress tracks that carry no notes — blank staves add no information.
        # Empty tracks remain accessible via the track list and mixer.
        tracks = [tr for tr in tracks if tr.notes]
        if not tracks:
            self._draw_placeholder_staves(c)
            c.update_idletasks()
            return

        total_w = self.LM + self._fe() + int(total_ticks * self._px_per_tick) + 80
        total_h = self._track_yo(len(tracks), tracks) + 20
        # Only reconfigure scrollregion when dimensions change — setting it
        # unconditionally fires a <Configure> event on some platforms, which
        # re-triggers _draw() and creates a rapid flickering loop at high zoom.
        _new_sr = (0, 0, total_w, total_h)
        if getattr(self, "_last_sr", None) != _new_sr:
            c.configure(scrollregion=_new_sr)
            self._last_sr = _new_sr
        # Draw per-measure status strip above the first stave
        self._draw_measure_strip(c, mmap, song, tracks)

        for ti, tr in enumerate(tracks):
            self._draw_system(c, ti, tr, song, nm, mmap, total_w, tracks)
        if cursor_tick is not None:
            cx = self._tick_to_x(cursor_tick)
            c.create_line(
                cx,
                0,
                cx,
                total_h,
                fill="#dd2222",
                width=2,
                dash=(5, 3),
                tags="playhead",
            )
            self._scroll_to(cx, total_w)
        # Note 1: force immediate visual refresh so quantize / edit operations
        # are visible without needing a zoom event to trigger a repaint.
        c.update_idletasks()

    def _draw_placeholder_staves(self, c):
        """Draw N empty staves so the score looks ready to use on startup."""
        n = self._PLACEHOLDER_TRACKS
        w = max(c.winfo_width(), 900)
        # Use a dummy single-staff height since no tracks exist yet
        row_h = self.TPAD1 + self.SH + self.BPAD1
        total_h = 4 + n * row_h + 20
        c.configure(scrollregion=(0, 0, w, total_h))
        names = [f"Track {i+1}" for i in range(n)]
        for ti in range(n):
            tt = 4 + ti * row_h + self.TPAD1_TOP
            # Track label
            c.create_text(
                6,
                tt - 8,
                text=names[ti],
                font=("TkDefaultFont", 8, "bold"),
                fill="#aaa",
                anchor="w",
            )
            # Treble clef
            c.create_text(
                self.LM + 4,
                tt + self.SH * 0.55,
                text="𝄞",
                font=("serif", int(self.SLG * 2.8)),
                fill="#bbb",
                anchor="w",
            )
            # Staff lines
            for line in range(5):
                y = tt + line * self.SLG
                c.create_line(self.LM, y, w - 10, y, fill="#ccc", width=1)
            # Thin bar line at left margin
            c.create_line(self.LM, tt, self.LM, tt + self.SH, fill="#bbb", width=1)

    def _scroll_to(self, cx, total_w):
        """Center-lock scrolling (v22p/q).

        total_w is recomputed from the current song on every call (v22q fix)
        because after rationalization the song's tick range changes but the
        canvas scrollregion may not yet be updated.  Using stale total_w
        makes cx/total_w wildly out of range, sending xview_moveto to 0
        (far left) — the "cursor jumps off left immediately on Play" bug.
        """
        _MIN_PX_MOVE = 1
        try:
            # Always recompute from current song geometry — never use the
            # passed-in total_w which may be stale after song replacement.
            song = self.app.song
            live_total_w = self.LM + self._fe() + int(song.total_ticks() * self._px_per_tick) + 80
            if live_total_w <= 0:
                live_total_w = max(total_w, 1)
            cx_clamped = max(0, min(cx, live_total_w))

            canvas_px = max(self.canvas.winfo_width(), 400)
            frac = cx_clamped / live_total_w
            half_vis = (canvas_px / 2.0) / live_total_w

            if frac <= half_vis:
                target_lo = 0.0  # Phase 1
            elif frac >= 1.0 - half_vis:
                target_lo = max(0.0, 1.0 - 2 * half_vis)  # Phase 3
            else:
                target_lo = frac - half_vis  # Phase 2: center lock

            lo, _ = self.canvas.xview()
            if abs(target_lo - lo) * live_total_w >= _MIN_PX_MOVE:
                self.canvas.xview_moveto(target_lo)
        except Exception:
            pass

    def _draw_system(self, c, ti, tr, song, nm, mmap, total_w, tracks=None):
        grand = self._uses_grand_staff(tr)
        tt = self._treble_top(ti, tracks)
        bt = self._bass_top(ti, tracks)  # None for single-staff tracks
        fe = self._fe()
        x0 = self.LM + fe  # x where measure 0 downbeat sits

        # ── Track label ───────────────────────────────────────────────────
        # v22v: renumber a generic "Track N" name to match its sequential
        # position in this (already filtered/merged) tracks list, so the
        # on-screen staff label agrees with the track list and mixer panels
        # rather than showing whatever number the source file happened to
        # assign (e.g. "Track 2" when track 1 was an empty meta track never
        # even imported).  Meaningful custom names ("Piano right", etc.)
        # are left untouched.
        import re as _lbl_re

        if _lbl_re.match(r"^Track\s+\d+$", tr.name or ""):
            label = f"Track {ti + 1}"
        else:
            label = f"{tr.name}"
        if len(label) > 28:
            label = label[:26] + "…"
        c.create_text(
            6,
            tt - 10,
            text=label,
            font=("TkDefaultFont", 9, "bold"),
            fill="#333",
            anchor="w",
        )

        # ── Brace (grand staff only) ───────────────────────────────────────
        if grand and bt is not None:
            bx = 18
            c.create_line(bx, tt, bx, bt + self.SH, width=3, fill="black")
            for yy in (tt, bt + self.SH):
                c.create_arc(
                    bx - 7,
                    yy - 7,
                    bx + 7,
                    yy + 7,
                    start=0,
                    extent=180,
                    style=tk.ARC,
                    outline="black",
                    width=2,
                )

        # ── Clef symbols ──────────────────────────────────────────────────
        # v22ze-25 fix (housekeeping item 7): the opening clef of each
        # staff in a grand-staff line was always treble (top) / bass
        # (bottom), regardless of what the first measure's notes
        # actually need. If a piece opens with the RH sitting low
        # enough that measure 0 already falls into the "temporary bass
        # clef in the treble staff" case (the same test _draw_chords
        # uses for the small inline clef-change symbols mid-line), the
        # large opening clef should already show bass -- not open on a
        # treble clef the very first chord immediately contradicts.
        # Mirrored for the bass staff opening on treble when the LH
        # starts high. Same "isolate a plausible cluster, then test if
        # it's uncomfortable" logic as the inline mid-line check,
        # restricted to measure 0 only.
        top_clef, bot_clef = "𝄞", "𝄢"  # defaults
        if grand and bt is not None and mmap:
            _use_flats0 = _song_uses_flats(self.app.song)
            _ms0, _me0 = mmap[0][1], mmap[0][2]
            m0_notes = [n for n in tr.notes if _ms0 <= n.tick < _me0]
            treble_notes0 = [n for n in m0_notes if note_staff_pos(n, _use_flats0)[0] >= -2]
            # v22ze-67 fix: on a RAW, not-yet-hand-split file (the normal
            # state right after loading, before Rationalize/Separate
            # Hands has run), m0_notes is BOTH hands mixed together --
            # there's no real "RH" yet, just whichever notes in the
            # merged pool happen to clear the treble-position threshold.
            # The old check only required pitch<64 (includes E4/F4,
            # ordinary treble-register notes) and just ONE such note --
            # a single note that happens to sit right at that boundary
            # (e.g. a B3 in a low opening chord that a real hand-split
            # would assign to the LEFT hand) was enough to flip the
            # WHOLE top staff to bass clef, even though a proper split
            # would put clearly-higher content up there. Reproduced
            # directly: a bass-heavy opening chord with its highest note
            # at pitch 59 flipped BOTH staves to bass clef. Requiring
            # strictly-below-middle-C (not the more lenient <64) AND at
            # least 2 corroborating notes makes a single borderline note
            # in an unsplit pool far less able to flip the clef, while a
            # piece that's genuinely low in both hands (the original
            # v22ze-25 fix this heuristic exists for) still clears both
            # bars easily.
            if len(treble_notes0) >= 2 and all(n.pitch < 60 for n in treble_notes0):
                top_clef = "𝄢"  # RH opens low -- bass clef in treble staff
            bass_notes0 = [n for n in m0_notes if note_staff_pos(n, _use_flats0)[0] < 2]
            if len(bass_notes0) >= 2 and all(n.pitch > 64 for n in bass_notes0):
                bot_clef = "𝄞"  # LH opens high -- treble clef in bass staff

        clef_x = self.LM + 4
        c.create_text(
            clef_x,
            tt + self.SH * 0.55,
            text=top_clef,
            font=("serif", int(self.SLG * 2.8)),
            fill="#111",
            anchor="w",
        )
        if grand and bt is not None:
            c.create_text(
                clef_x,
                bt + self.SLG * 1.8,
                text=bot_clef,
                font=("serif", int(self.SLG * 2.8)),
                fill="#111",
                anchor="w",
            )

        # ── Key signature ────────────────────────────────────────────────
        # Draw flats or sharps on the staff lines/spaces at standard positions.
        # Key name from MIDI meta-event e.g. "Bb", "F#", "Gm", "C".
        key_str = getattr(song, "key_sig", "C") or "C"

        # Circle-of-fifths: standard sharp/flat accidental order for engraving
        # (n_sharps/n_flats below come from key_sig_accidentals(), not from
        # these lists directly).
        # Positions on treble staff (staff-position from top line = 0, each line/space = 0.5 SLG)
        # Sharp positions (F#,C#,G#,D#,A#,E#,B#) on treble: line4,sp2,line5,sp3,sp1,line3,sp5
        _SHARP_POS_T = [
            0.0,
            1.5,
            -0.5,
            1.0,
            2.5,
            0.5,
            2.0,
        ]  # in SLG units from treble top
        _FLAT_POS_T = [1.5, 0.5, 2.0, 1.0, 2.5, 1.5, 3.0]  # Bb,Eb,Ab,Db,Gb,Cb,Fb
        # Bass staff offsets — each accidental is 3 staff positions (1.5 SLG) lower
        _SHARP_POS_B = [p + 1.5 for p in _SHARP_POS_T]
        _FLAT_POS_B = [p + 1.5 for p in _FLAT_POS_T]

        # v22ze fix: this used to do `key_str.rstrip('m')` and look the
        # result up in the MAJOR-key tables above -- which silently
        # mistreated every minor key as if it were the major key of the
        # same letter name. "Gm".rstrip('m') = "G", and "G" IS in
        # _SHARP_KEYS (1 sharp) -- so G minor (correctly 2 FLATS, same
        # signature as its relative major Bb) got drawn with 1 sharp
        # instead. key_sig_accidentals() looks this up correctly via
        # each key's relative major, matching what to_ly()'s \key
        # directive (and any real edition) actually shows.
        n_sharps, n_flats = key_sig_accidentals(key_str)

        clef_w = int(self.SLG * 2.8)  # approximate clef glyph width
        key_x0 = self.LM + 4 + clef_w + 2  # start just after clef
        acc_w = max(6, int(self.SLG * 0.85))  # spacing between accidentals
        acc_font = ("serif", max(8, int(self.SLG * 1.3)), "bold")

        # v22ze fix: same font optical-center offset as the per-note
        # accidentals below -- anchor="w" still vertically centers on
        # the font's bounding-box metrics, which sit visually lower than
        # geometric center for these glyphs in most fonts.
        _key_acc_dy = -self.SLG * 0.30
        if n_sharps > 0:
            for k in range(n_sharps):
                x = key_x0 + k * acc_w
                yt = tt + _SHARP_POS_T[k] * self.SLG + _key_acc_dy
                c.create_text(x, yt, text="♯", font=acc_font, fill="#111", anchor="w")
                if grand and bt is not None:
                    yb = bt + _SHARP_POS_B[k] * self.SLG + _key_acc_dy
                    c.create_text(x, yb, text="♯", font=acc_font, fill="#111", anchor="w")
        elif n_flats > 0:
            for k in range(n_flats):
                x = key_x0 + k * acc_w
                yt = tt + _FLAT_POS_T[k] * self.SLG + _key_acc_dy
                c.create_text(x, yt, text="♭", font=acc_font, fill="#111", anchor="w")
                if grand and bt is not None:
                    yb = bt + _FLAT_POS_B[k] * self.SLG + _key_acc_dy
                    c.create_text(x, yb, text="♭", font=acc_font, fill="#111", anchor="w")

        # Advance time-sig x to clear the key signature
        key_sig_w = max(0, (n_sharps or n_flats) * acc_w + acc_w)

        # ── Initial time signature (measure 0) ────────────────────────────
        ts_x = key_x0 + key_sig_w + 4
        m0_num, m0_den = mmap[0][3], mmap[0][4]
        for top_y in ([tt] if not grand or bt is None else [tt, bt]):
            mid = top_y + self.SH / 2
            c.create_text(
                ts_x,
                mid - self.SLG * 0.9,
                text=str(m0_num),
                font=("serif", int(self.SLG * 1.8), "bold"),
                fill="black",
            )
            c.create_text(
                ts_x,
                mid + self.SLG * 0.9,
                text=str(m0_den),
                font=("serif", int(self.SLG * 1.8), "bold"),
                fill="black",
            )

        # ── Tempo marking ─────────────────────────────────────────────────
        bpm = max(1, round(60_000_000 / song.tempo))
        c.create_text(
            ts_x + 2,
            tt - 16,
            text=f"♩ = {bpm}",
            font=("TkDefaultFont", 9),
            fill="#333",
            anchor="w",
        )

        # ── Staff lines ───────────────────────────────────────────────────
        staves = [tt] if not grand or bt is None else [tt, bt]
        for top_y in staves:
            for line in range(5):
                y = top_y + line * self.SLG
                c.create_line(self.LM, y, total_w - 10, y, fill="#444", width=1)

        # ── Bar lines + measure numbers + inline time sig changes ─────────
        # v22ze-30 fix: this was the actual source of the "unsupported
        # operand type(s) for +: NoneType and int" crash on orchestral
        # files -- every OTHER staff-geometry calculation in this function
        # correctly guards "bt is None" for single-staff (non-piano)
        # tracks (see the ternaries just above), but this one line
        # computed bt+self.SH unconditionally. Any single-staff track
        # (e.g. Flute, or any non-keyboard instrument) has bt=None, so
        # this crashed on the very first measure's barline -- explaining
        # why that staff showed no notes and no measures at all: the
        # exception aborted _draw_system() before anything past this
        # point for that track ever got drawn.
        y1 = tt
        y2 = (bt + self.SH) if (grand and bt is not None) else (tt + self.SH)
        c.create_line(x0, y1, x0, y2, fill="#666", width=1)  # opening barline
        prev_num, prev_den = m0_num, m0_den
        for m_idx, ms, me, num, den, tpm in mmap:
            xs = self._tick_to_x(ms)
            xe = self._tick_to_x(me)
            # Closing barline of this measure
            c.create_line(xe, y1, xe, y2, fill="#666", width=1)
            # Measure number above treble staff
            c.create_text(
                xs + 3,
                tt - 14,
                text=str(m_idx + 1),
                font=("TkFixedFont", 8),
                fill="#aaa",
                anchor="w",
            )
            # Inline time sig change (drawn at the START of the new measure)
            if m_idx > 0 and (num != prev_num or den != prev_den):
                tsig_x = xs + 4
                # v22ze-30 fix: same missing "bt is None" guard as the
                # barline fix above -- a single-staff track has bt=None,
                # so this loop's second iteration hit the identical
                # crash the moment a piece with an inline time signature
                # change (rarer than the barline case, which is why this
                # one wasn't the first thing hit) reached a non-piano
                # track.
                for top_y in ([tt] if not grand or bt is None else [tt, bt]):
                    mid = top_y + self.SH / 2
                    c.create_text(
                        tsig_x,
                        mid - self.SLG * 0.75,
                        text=str(num),
                        font=("serif", int(self.SLG * 1.4), "bold"),
                        fill="#555",
                    )
                    c.create_text(
                        tsig_x,
                        mid + self.SLG * 0.75,
                        text=str(den),
                        font=("serif", int(self.SLG * 1.4), "bold"),
                        fill="#555",
                    )
                prev_num, prev_den = num, den
        # Final double barline
        last_xe = self._tick_to_x(mmap[-1][2])
        c.create_line(last_xe - 3, y1, last_xe - 3, y2, fill="black", width=3)

        # ── Notes and rests ───────────────────────────────────────────────
        nr = max(3, int(self.SLG * 0.70))  # v22ze: was doubled to 0.88, corrected -20% per feedback
        self._draw_chords(c, tr, tt, bt, nr, song, nm, mmap, ti=ti)
        self._draw_rests(c, tr, tt, bt, nm, song, mmap, ti=ti)

    # ─── Chord-aware note drawing ────────────────────────────────────────────

    CHORD_TOL = 20  # ticks — notes within this range are treated as one chord

    def _group_chords(self, notes):
        """Group notes into chords.  Two notes belong to the same chord when
        their tick values differ by at most CHORD_TOL.  We compare each new
        note against the FIRST note of the current group (not the previous
        note), so a run of notes 18 ticks apart does NOT cascade into one
        giant chord — only notes genuinely close to the group's anchor tick
        are merged.  Each group is sorted low→high by pitch."""
        if not notes:
            return []
        sorted_n = sorted(notes, key=lambda n: n.tick)
        groups = []
        cur = [sorted_n[0]]
        anchor_tick = sorted_n[0].tick
        for n in sorted_n[1:]:
            if n.tick - anchor_tick <= self.CHORD_TOL:
                cur.append(n)  # same chord — compare vs anchor, not prev
            else:
                groups.append(sorted(cur, key=lambda n: n.pitch))
                cur = [n]
                anchor_tick = n.tick  # new anchor for next chord
        groups.append(sorted(cur, key=lambda n: n.pitch))
        return groups

    # v22ze-27 fix (housekeeping item 8): _find_gap_split used to live
    # here as a SEPARATE, per-chord hand-split algorithm -- see
    # _find_split_pitch_for_track() at module level for the full
    # explanation of why that caused the screen and the Lilypond export
    # to disagree. Removed; ScoreView now calls the shared whole-piece
    # function once per track (see manual_split handling below) instead
    # of recomputing a split fresh for every individual chord.

    def _draw_chords(self, c, tr, tt, bt, nr, song, nm, mmap, ti=0):
        tpb = song.ticks_per_beat

        # Score-only quantization copy (does not modify song data)
        class _TmpTrack:
            pass

        qtr = _TmpTrack()
        qtr.name = getattr(tr, "name", "track")
        qtr.notes = []
        qtr.events = getattr(tr, "events", [])  # v22q: needed by _draw_pedal
        # v22ze-50 fix: dynamics markings (mf, ff, etc.) live on
        # Track.markings, not Track.notes/events -- _click_dynamics()
        # already appends to it correctly, but nothing ever carried it
        # onto this render-only copy or drew it, so "Dynamics does
        # nothing" was really "Dynamics silently succeeds, never
        # rendered." Carried through the same way qtr.events already is.
        qtr.markings = getattr(tr, "markings", [])
        # v22ze-28 fix: carry the pre-hand-split tag (see the RH/LH merge
        # code above _draw_system) through this quantization copy so the
        # per-group split logic below can still see it after `tr = qtr`.
        qtr._prehand_split = getattr(tr, "_prehand_split", False)
        for n in tr.notes:
            cpy = type("QNote", (), {})()
            cpy.tick = int(n.tick)
            cpy.pitch = int(n.pitch)
            cpy.velocity = getattr(n, "velocity", 100)
            cpy.duration = int(n.duration)
            cpy.channel = getattr(n, "channel", 0)
            # v22ze-50 fix: articulation was never copied onto this
            # render-only note, so nothing downstream that reads
            # n.articulation (grace-note sizing, and the new articulation-
            # mark drawing below) ever saw anything but the getattr
            # default -- silently doing nothing regardless of what was
            # actually stored on the real note.
            cpy.articulation = getattr(n, "articulation", "")
            cpy.spelling = getattr(n, "spelling", "")  # v22ze-51
            qtr.notes.append(cpy)

        div_map = {4: 1, 8: 2, 16: 4, 32: 8}
        score_div = div_map.get(getattr(self.app, "quantize_division", 8), 2)

        # Score-display onset snap: move note onsets to nearest grid position
        # for visual alignment.  Duration is NEVER changed — raw duration drives
        # notehead shape (filled vs open) and beam-flag count in _draw_chord.
        # Quantizing duration was the root cause of sixteenth notes appearing
        # as eighth notes on screen: a 200-tick note at 480-tick grid rounded
        # to 0 → clamped to 1 tick; a 350-tick note rounded to 480 (eighth).
        grid = max(1, tpb // (score_div * 2))  # finer onset grid (16th default)
        for n in qtr.notes:
            n.tick = int(round(n.tick / grid) * grid)
        tr = qtr

        # v22ze-49 fix (was the flagged IN-PROGRESS item from the last
        # handoff): bake_to_score()'s v22ze-48 fix made it CORRECT for a
        # tied note that crosses a barline to end up as ONE continuous
        # MidiNote spanning both measures (that's what fixed the "double
        # strike" bug). But this renderer lays notes out per-measure with
        # no barline awareness, and _draw_ties() needs TWO separate notes
        # of the same pitch meeting exactly at a barline to draw its arc
        # (purely geometric, no marker involved -- see its docstring).
        # Left unsplit, a cross-barline note also risks visually running
        # into the next measure's content, not just losing its tie arc.
        #
        # Fix: split any such note into display-only pieces here, clipped
        # exactly at each barline it crosses, using the same strategy as
        # rationalize()'s Pass A (see Song.rationalize) but applied only
        # to this render-only qtr copy -- real song data (tr.notes on the
        # actual Track, and the baked Song) is never touched. _draw_ties
        # then picks the pieces up automatically with zero changes of its
        # own, since it already looks for exactly this shape.
        _mmap_starts_r = [ms for (_mi, ms, me, *_r) in mmap]

        def _measure_bounds_r(tick):
            i = bisect.bisect_right(_mmap_starts_r, tick) - 1
            if 0 <= i < len(mmap):
                _mi, ms, me, _n, _d, _tpm = mmap[i]
                return ms, me
            return None, None

        _split_notes = []
        for n in qtr.notes:
            cur = n
            _guard = 0  # safety cap -- a note can only cross so many
            # real barlines; this just prevents a runaway
            # loop if mmap/tick data is ever malformed.
            while _guard < 64:
                _guard += 1
                ms, me = _measure_bounds_r(cur.tick)
                if ms is None:
                    _split_notes.append(cur)
                    cur = None
                    break
                max_dur = me - cur.tick
                if max_dur <= 0 or cur.duration <= max_dur:
                    _split_notes.append(cur)
                    cur = None
                    break
                # Piece 1: clip to the barline, keep in this measure.
                piece = type("QNote", (), {})()
                piece.tick = cur.tick
                piece.pitch = cur.pitch
                piece.velocity = cur.velocity
                piece.channel = cur.channel
                piece.articulation = getattr(cur, "articulation", "")
                piece.spelling = getattr(cur, "spelling", "")  # v22ze-51
                piece.duration = max_dur
                _split_notes.append(piece)
                # Piece 2 (continuation): starts at the barline, carries
                # the remainder.  Loop again in case it crosses ANOTHER
                # barline (a note tied across 2+ measures).
                nxt = type("QNote", (), {})()
                nxt.tick = me
                nxt.pitch = cur.pitch
                nxt.velocity = cur.velocity
                nxt.channel = cur.channel
                nxt.articulation = getattr(cur, "articulation", "")
                nxt.spelling = getattr(cur, "spelling", "")  # v22ze-51
                nxt.duration = cur.duration - max_dur
                cur = nxt
            if cur is not None:
                _split_notes.append(cur)
        qtr.notes = _split_notes  # tr IS qtr (see `tr = qtr` above), so
        # this update is already visible via tr

        manual_split = self._split_var.get()  # 0 = auto
        # v22ze-27 fix (housekeeping item 8): ONE split point for the
        # whole track, computed the same way to_ly() computes it for
        # export -- not a fresh split recomputed per chord (see
        # _find_split_pitch_for_track for the full rationale). This is
        # what actually keeps the raw on-screen view and the Lilypond
        # export in agreement.
        auto_split = _find_split_pitch_for_track(
            tr.notes,
            prefer_lh_octaves=getattr(self.app.song, "prefer_lh_octaves", True),
        )

        # ── Detect runs of measures where bass notes go high ────────────────
        _use_flats = _song_uses_flats(self.app.song)
        bass_treble_measures = set()
        for m_idx, ms, me, num, den, tpm in mmap:
            bass_notes = [
                n for n in tr.notes if ms <= n.tick < me and note_staff_pos(n, _use_flats)[0] < 2
            ]
            if bass_notes and all(n.pitch > 59 for n in bass_notes):
                bass_treble_measures.add(m_idx)

        # v22ze: symmetric case -- runs of measures where TREBLE notes go
        # low. This was entirely missing before; only the LH-climbs-high
        # direction existed, so a passage like a low opening theme (RH
        # sitting in bass register from the very start, common in
        # marches and similar writing) had no equivalent temporary
        # bass-clef-in-treble-staff treatment on screen at all -- it just
        # accumulated ledger lines under a fixed treble clef, exactly the
        # readability problem a real engraved edition avoids by using two
        # bass clefs for that passage instead. Confirmed against a real
        # published score (Rachmaninoff Op.23 No.5's opening) showing
        # exactly this -- see screenshot comparison.
        #
        # NOTE on the threshold: a naive mirror of the bass_treble check
        # above (pos>=2 AND pitch<60) is mathematically impossible --
        # pos>=2 already implies pitch>=64 by construction (position is a
        # monotonic function of pitch), so that condition could never
        # fire (confirmed by direct check across the full practical
        # pitch range before settling on this version). The correct
        # mirror excludes clearly-bass-register content first (pos<-2,
        # almost certainly genuine LH material) to isolate whatever's
        # left -- the upper/RH-plausible cluster -- then asks whether
        # THAT cluster's entire content sits uncomfortably low (<E4)
        # for treble reading. This is the same "isolate a plausible
        # single-hand cluster, then test if it's uncomfortable" strategy
        # the bass_treble check uses, mirrored onto the other boundary.
        treble_bass_measures = set()
        for m_idx, ms, me, num, den, tpm in mmap:
            treble_notes = [
                n for n in tr.notes if ms <= n.tick < me and note_staff_pos(n, _use_flats)[0] >= -2
            ]
            if treble_notes and all(n.pitch < 64 for n in treble_notes):
                treble_bass_measures.add(m_idx)

        def _find_runs(measure_set):
            """Contiguous (start, end) measure-index runs from a set."""
            runs = []
            if measure_set:
                sorted_ms = sorted(measure_set)
                run_start = run_end = sorted_ms[0]
                for m in sorted_ms[1:]:
                    if m == run_end + 1:
                        run_end = m
                    else:
                        runs.append((run_start, run_end))
                        run_start = run_end = m
                runs.append((run_start, run_end))
            return runs

        runs = _find_runs(bass_treble_measures)
        treble_bass_runs = _find_runs(treble_bass_measures)

        # Draw: small inline treble clef at run start, dashed line through run,
        # bass clef return symbol at run end.
        #
        # v22ze fix: x0 previously landed at essentially the same x as the
        # run's first note (mmap[rs][1] + 2 -- almost no offset at all),
        # so the clef glyph and the first chord's noteheads/stems drew
        # directly on top of each other. Shifted left into the existing
        # barline gap (which already has some reserved blank space before
        # notes begin) instead of trying to carve out brand-new space in
        # the note-layout pass, and reduced slightly so it's less likely
        # to need more room than that gap actually has.
        # v22ze-24 fix (housekeeping item 6): inline clef-change symbols
        # were sized independently of the grand-staff clef (SLG*1.5 here
        # vs SLG*2.8 for the line-opening clef), so at normal staff sizes
        # they read as noticeably small -- easy to miss a clef change at
        # a glance, which is exactly what caused the D3/G3/Bb3 chord to
        # get misread earlier. Spec: about 70% of the grand-staff clef
        # size. Derived from the same SLG*2.8 constant used for the main
        # clef rather than a new hardcoded literal, so the two stay in
        # proportion if the grand-staff clef size is ever changed.
        clef_sz = int(self.SLG * 2.8 * 0.7)
        # v22ze-30 fix: same missing "bt is None" guard as the two
        # _draw_system fixes above -- this whole block only means
        # anything for a grand-staff (piano) track with a real bass
        # staff to draw an inline clef change into, but the assignment
        # itself ran unconditionally, crashing on any single-staff
        # track before ever reaching the (harmlessly empty) loop below.
        clef_y = (
            (bt + self.SH * 0.52) if bt is not None else (tt + self.SH * 0.52)
        )  # vertical centre of bass staff
        dash_y = tt + self.SH + self.BGAP // 2  # midway between staves
        for rs, re in runs:
            x0 = (
                (self._tick_to_x(mmap[rs][1]) - clef_sz * 0.9)
                if rs < len(mmap)
                else self._tick_to_x(0) - clef_sz * 0.9
            )
            x1 = (self._tick_to_x(mmap[re][2]) - 4) if re < len(mmap) else self._tick_to_x(0)
            # v22ze-25 fix: if this run starts at measure 0, the opening
            # staff clef (item 7) already shows the correct clef for the
            # whole line -- drawing the small inline clef glyph again
            # right after it is a redundant duplicate. Only the dashed
            # "still in this clef" line and the eventual return-clef at
            # the end of the run are still needed; the dash simply
            # starts at x0 instead of x0+clef_sz since no glyph is
            # reserving that space.
            if rs == 0:
                dash_x0 = x0
            else:
                c.create_text(
                    x0,
                    clef_y,
                    text="𝄞",
                    font=("serif", clef_sz),
                    fill="black",
                    anchor="w",
                    tags="clef_change",
                )
                dash_x0 = x0 + clef_sz
            # Dashed horizontal line from after clef to end of run
            c.create_line(dash_x0, dash_y, x1, dash_y, fill="#444", width=1, dash=(6, 4))
            # Closing bracket at end of run
            c.create_line(x1, dash_y, x1, dash_y + self.SLG, fill="#444", width=1)
            # Return bass clef (slightly smaller than main)
            if re + 1 < nm:
                rx = (
                    (self._tick_to_x(mmap[re + 1][1]) - clef_sz * 0.9)
                    if re + 1 < len(mmap)
                    else self._tick_to_x(mmap[-1][2]) - clef_sz * 0.9
                )
                c.create_text(
                    rx,
                    clef_y,
                    text="𝄢",
                    font=("serif", clef_sz),
                    fill="black",
                    anchor="w",
                    tags="clef_change",
                )

        # v22ze: symmetric drawing for the RH-too-low case -- same idea,
        # mirrored into the treble staff's vertical band: inline bass
        # clef at the run's start, return treble clef at its end.
        clef_y_tr = tt + self.SH * 0.52  # vertical centre of treble staff
        dash_y_tr = tt - self.BGAP // 2  # just above the treble staff
        for rs, re in treble_bass_runs:
            x0 = (
                (self._tick_to_x(mmap[rs][1]) - clef_sz * 0.9)
                if rs < len(mmap)
                else self._tick_to_x(0) - clef_sz * 0.9
            )
            x1 = (self._tick_to_x(mmap[re][2]) - 4) if re < len(mmap) else self._tick_to_x(0)
            # v22ze-25 fix: same redundancy fix as the bass-staff loop
            # above -- skip the inline glyph when the run opens the line.
            if rs == 0:
                dash_x0_tr = x0
            else:
                c.create_text(
                    x0,
                    clef_y_tr,
                    text="𝄢",
                    font=("serif", clef_sz),
                    fill="black",
                    anchor="w",
                    tags="clef_change",
                )
                dash_x0_tr = x0 + clef_sz
            c.create_line(dash_x0_tr, dash_y_tr, x1, dash_y_tr, fill="#444", width=1, dash=(6, 4))
            c.create_line(x1, dash_y_tr, x1, dash_y_tr - self.SLG, fill="#444", width=1)
            if re + 1 < nm:
                rx = (
                    (self._tick_to_x(mmap[re + 1][1]) - clef_sz * 0.9)
                    if re + 1 < len(mmap)
                    else self._tick_to_x(mmap[-1][2]) - clef_sz * 0.9
                )
                c.create_text(
                    rx,
                    clef_y_tr,
                    text="𝄞",
                    font=("serif", clef_sz),
                    fill="black",
                    anchor="w",
                    tags="clef_change",
                )

        # ── Pass 1: collect every prospective chord entry without drawing ──
        # v22ze: previously drew each chord's stem direction independently,
        # per-chord, with no knowledge of whether it would end up beamed
        # to a neighbor. Real engraving requires a beamed GROUP to share
        # one stem direction (chosen from the group's combined pitch
        # content), not each note picking its own -- reported as beams
        # visibly connecting notes with opposite stem directions, and an
        # isolated chord getting pulled into a beam it shouldn't be part
        # of. Collecting every entry first, predicting shared directions
        # for whatever will actually end up beamed, THEN drawing with
        # that answer already known, fixes this at the root instead of
        # patching stems after they're already on the canvas.
        entries = []  # (notes, force_treble, is_v2)
        for group in self._group_chords(tr.notes):
            if bt is None:
                # v22ze-30 fix: this was the root cause of the orchestral-
                # file crash ("unsupported operand type(s) for +:
                # NoneType and int") -- every branch below this assumed
                # SOME notes might need to go to a bass/LH staff, but a
                # single-staff (non-piano) track like Violin or Flute has
                # no second staff at all (bt is None). Any note whose
                # pitch happened to fall below the auto-split threshold
                # got bucketed into `lh` and later drawn with
                # force_treble=False, which tries to position it on a
                # bass staff that doesn't exist for this track. All
                # notes on a single-staff track belong on that one
                # staff, full stop -- no pitch-based splitting applies.
                rh, lh = group, []
            elif getattr(tr, "_prehand_split", False):
                # v22ze-28 fix: trust the DP's already-decided hand
                # assignment (tagged via channel: 0=RH, 1=LH at merge
                # time) instead of re-deriving a split from pitch --
                # manual_split override still wins if the user explicitly
                # set one, same as the pitch-based path below.
                if manual_split > 0:
                    rh = [n for n in group if n.pitch >= manual_split]
                    lh = [n for n in group if n.pitch < manual_split]
                else:
                    rh = [n for n in group if n.channel == 0]
                    lh = [n for n in group if n.channel == 1]
            else:
                split = manual_split if manual_split > 0 else auto_split
                rh = [n for n in group if n.pitch >= split]
                lh = [n for n in group if n.pitch < split]

            def split_voices(notes):
                """If chord has mixed durations, return (voice1, voice2).
                voice1 = longer notes (stem down), voice2 = shorter (stem up).
                If all same duration, return (notes, [])."""
                if len(notes) < 2:
                    return notes, []
                durs = sorted(set(n.duration for n in notes), reverse=True)
                if len(durs) == 1:
                    return notes, []
                # Split at median duration
                med = durs[len(durs) // 2]
                v1 = [n for n in notes if n.duration >= med]
                v2 = [n for n in notes if n.duration < med]
                if not v2:
                    return notes, []
                return v1, v2

            for hand_notes, force_t in [(rh, True), (lh, False)]:
                if not hand_notes:
                    continue
                v1, v2 = split_voices(hand_notes)
                entries.append((v1, force_t, False))
                if v2:
                    entries.append((v2, force_t, True))

        # ── Pass 2: predict beam groups and their shared stem direction ──
        forced_dir = self._predict_beam_stem_directions(
            entries,
            tt,
            bt,
            tpb,
            mmap,
            _use_flats,
            bass_treble_measures,
            treble_bass_measures,
        )

        # ── Pass 3: draw using the predicted direction where applicable ──
        stems = []  # collect StemInfo for beam drawing
        # v22ze: separate courtesy-accidental memory per hand/staff --
        # accidental persistence is a per-staff concept, RH and LH don't
        # share it. entries are already in tick order (built by iterating
        # _group_chords in tick order), so within each hand's own
        # sequence this naturally processes oldest-to-newest.
        accidental_state_rh = {}
        accidental_state_lh = {}
        for notes, force_t, is_v2 in entries:
            # v2 (the shorter-duration voice within a mixed-duration
            # chord) keeps its existing always-stem-up rule regardless of
            # beam prediction -- that's a different, unrelated engraving
            # rule (voice separation within one chord), not something
            # beam-group prediction should override.
            fsu = True if is_v2 else forced_dir.get(id(notes))
            si = self._draw_chord(
                c,
                notes,
                tt,
                bt,
                nr,
                tpb,
                mmap,
                bass_treble_measures,
                force_treble=force_t,
                force_stem_up=fsu,
                treble_bass_measures=treble_bass_measures,
                accidental_state=(accidental_state_rh if force_t else accidental_state_lh),
            )
            if si:
                stems.append(si)

        # Draw beams (replaces flags for beamed groups)
        self._draw_beams(c, stems, tpb, song)
        # Draw ties for notes crossing barlines
        self._draw_ties(c, tr, tt, bt, nr, tpb, mmap, ti=ti)
        # Draw pedal marks
        self._draw_pedal(c, tr, tt, bt, tpb, mmap)
        # Draw dynamics markings (v22ze-50 fix -- see qtr.markings above)
        self._draw_dynamics(c, tr, tt, bt, tpb, mmap)

    def _clef_branch_for_chord(
        self,
        notes,
        tt,
        bt,
        mmap,
        force_treble,
        bass_treble_measures,
        treble_bass_measures,
        _use_flats,
    ):
        """Determine which staff/clef branch a chord draws on, and the
        resulting (sp_to_y, top_y, bot_sp, top_sp, mid_sp, measure, use_treble).

        v22ze: extracted out of _draw_chord so a stem-direction PREDICTION
        pass (see _predict_beam_stem_directions) can compute the exact
        same mid_sp a chord will actually be drawn with, without risking
        a second, independently-written copy of this branching logic
        drifting out of sync with the real one -- exactly the kind of
        screen-vs-something duplicate-logic bug this session kept
        finding and fixing elsewhere. Both call sites now share one
        source of truth.
        """
        positions = [note_staff_pos(n, _use_flats)[0] for n in notes]
        med_pos = sorted(positions)[len(positions) // 2]
        if force_treble is True:
            use_treble = True
        elif force_treble is False:
            use_treble = False
        else:
            use_treble = med_pos >= 2  # corrected: treble bottom line = pos 2

        measure = 0
        for m_idx, ms, me, _n, _d, _t in mmap:
            if ms <= notes[0].tick < me:
                measure = m_idx
                break
        use_treble_clef_in_bass = not use_treble and measure in bass_treble_measures
        use_bass_clef_in_treble = (
            use_treble and treble_bass_measures is not None and measure in treble_bass_measures
        )

        if use_treble:
            sp_to_y = self._sp_to_y_treble
            top_y = tt
            bot_sp, top_sp = 2, 10  # E4 (bottom) to F5 (top)
            mid_sp = 6  # B4 = middle line of treble staff
        elif use_treble_clef_in_bass:
            sp_to_y = self._sp_to_y_treble
            top_y = bt  # render in bass strip but treble positions
            bot_sp, top_sp = 2, 10
            mid_sp = 6
        else:
            sp_to_y = self._sp_to_y_bass
            top_y = bt
            bot_sp, top_sp = -10, -2  # G2 (bottom) to A3 (top)
            mid_sp = -6  # D3 = middle line of bass staff

        if use_bass_clef_in_treble:
            sp_to_y = self._sp_to_y_bass
            top_y = tt  # render in treble strip but bass positions
            bot_sp, top_sp = -10, -2
            mid_sp = -6

        return sp_to_y, top_y, bot_sp, top_sp, mid_sp, measure, use_treble

    def _draw_chord(
        self,
        c,
        notes,
        tt,
        bt,
        nr,
        tpb,
        mmap,
        bass_treble_measures,
        force_treble=None,
        force_stem_up=None,
        treble_bass_measures=None,
        accidental_state=None,
    ):
        """Draw a chord (1–N simultaneous notes) following LilyPond engraving rules.

        force_treble=True  → draw in treble staff (right hand)
        force_treble=False → draw in bass staff (left hand)
        force_treble=None  → auto-assign by median pitch
        """
        if not notes:
            return

        _use_flats = _song_uses_flats(self.app.song)
        _key_str = getattr(self.app.song, "key_sig", "C") or "C"

        sp_to_y, top_y, bot_sp, top_sp, mid_sp, measure, use_treble = self._clef_branch_for_chord(
            notes,
            tt,
            bt,
            mmap,
            force_treble,
            bass_treble_measures,
            treble_bass_measures,
            _use_flats,
        )

        # v22ze: courtesy-accidental tracking. A sharp/flat only needs to
        # be drawn once per measure for a given specific line/space
        # (same letter AND octave) -- traditional notation assumes it
        # holds for the rest of that measure, the performer doesn't need
        # it repeated on every note. `pos` from pitch_to_staff is already
        # octave-specific, so it's the right key. Reset whenever the
        # measure changes; accidental_state may be None if a caller
        # doesn't want this behavior (falls back to always showing).
        if accidental_state is not None:
            if accidental_state.get("measure") != measure:
                accidental_state["measure"] = measure
                accidental_state["active"] = {}

        # Use median duration so one short note doesn't misclassify whole chord
        durs = sorted(n.duration for n in notes)
        db = durs[len(durs) // 2] / tpb
        # Round to nearest integer rather than truncating — both RH and LH
        # staves compute x from _tick_to_x(tick) which returns a float.
        # Truncating (int()) can give different pixel positions for the same
        # tick when floating-point rounding differs slightly between calls.
        # round() guarantees both staves land on the same pixel column.
        x = round(self._tick_to_x(notes[0].tick)) + nr + 2

        # ── Collect notehead y-positions (staff positions, accidentals) ──────
        # ys: list of (staff_pos, accidental, canvas_y, MidiNote)  low→high pitch
        ys = []
        for n in notes:
            pos, acc = note_staff_pos(n, _use_flats)
            y = sp_to_y(pos, top_y)
            ys.append((pos, acc, y, n))

        # ── LilyPond stem direction rule ─────────────────────────────────────
        if force_stem_up is not None:
            stem_up = force_stem_up
        else:

            def dist(pos):
                return abs(pos - mid_sp)

            furthest = max(ys, key=lambda t: dist(t[0]))
            stem_up = True if dist(furthest[0]) == 0 else furthest[0] < mid_sp

        # ── Stem geometry (LilyPond NR §1.3.3) ──────────────────────────────────
        # Base: 3.5 staff-spaces from closest notehead to tip.
        # Extend for wide chords (> 1 octave span).
        # Cap: tip must reach middle line but not go more than 4 spaces past it.
        sl_spaces = 3.5
        # v22ze fix: `positions` was computed inside _clef_branch_for_chord
        # (extracted out of this function) and never came back here --
        # this line referenced a variable that no longer existed in this
        # scope, a direct regression from that refactor (NameError at
        # runtime). `ys` (built just above, one (pos, acc, y, note) tuple
        # per note) already has the same per-note staff positions, so use
        # that instead of re-threading `positions` through the return
        # value of a function that has its own, unrelated reason to exist.
        span = max(t[0] for t in ys) - min(t[0] for t in ys)
        if span > 7:
            sl_spaces += (span - 7) * 0.5

        sl = self.SLG * sl_spaces

        # Canvas y increases downward; high pitch = small y
        mid_y = sp_to_y(mid_sp, top_y)  # canvas y of staff middle line

        # stem_root_y = notehead end of stem (spans all noteheads);
        # sy = free tip. Stem drawn from stem_root_y to sy covers all notes.
        if stem_up:
            stem_root_y = max(t[2] for t in ys)  # BOTTOM notehead (largest y)
            tip_anchor = min(t[2] for t in ys)  # TOP notehead (smallest y)
            sy = tip_anchor - sl  # tip above topmost note
            sy = min(sy, mid_y)  # must reach middle line
            sy = max(sy, mid_y - self.SLG * 4)  # not >4 spaces above it
            # prevent up-stem from a bass-staff chord entering the treble area
            sy = max(sy, top_y - self.SLG * 1.5)
        else:
            stem_root_y = min(t[2] for t in ys)  # TOP notehead (smallest y)
            tip_anchor = max(t[2] for t in ys)  # BOTTOM notehead (largest y)
            sy = tip_anchor + sl  # tip below bottommost note
            sy = max(sy, mid_y)  # must reach middle line
            sy = min(sy, mid_y + self.SLG * 4)  # not >4 spaces below it

        sx = x + (nr if stem_up else -nr)

        # ── Detect notehead conflicts needing offset ──────────────────────────
        # Two adjacent (by staff position) notes ALWAYS conflict at a 2nd
        # (diff==1) -- noteheads literally touch. A bare 3rd (diff==2)
        # never conflicts on its own, even with an accidental: the two
        # noteheads themselves are far enough apart that an accidental
        # glyph on either one doesn't reach the other when nothing else
        # is crowding that space. v22ze-21 fix: a plain triad with one
        # altered tone and no note anywhere touching a neighbor (e.g.
        # Eb4-G4-B4) was wrongly getting split, because the previous rule
        # treated ANY 3rd-with-an-accidental as a standalone conflict.
        # The accidental-third rule only makes sense as an EXTENSION of
        # an already-crowded run: once a real 2nd forces the engraver to
        # narrow the horizontal spacing in that region, an accidental on
        # the note chained onto it can then reach into the neighbor a
        # 3rd further out (confirmed correct for C3-D3(2nd) chaining out
        # to F#3 and A3 via their accidentals). It must never be the
        # thing that STARTS a cluster. So: build clusters from real 2nds
        # only, then grow outward from any cluster that already contains
        # >=2 notes (i.e. a genuine 2nd) via accidental-third links,
        # repeating until nothing more attaches. A note with an
        # accidental sitting in an otherwise clean, non-touching chord
        # never gets pulled into a cluster at all.
        sorted_ys = sorted(ys, key=lambda t: t[0])
        n = len(sorted_ys)
        parent = list(range(n))

        def _find(i):
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i

        def _union(i, j):
            ri, rj = _find(i), _find(j)
            if ri != rj:
                parent[ri] = rj

        # Phase 1: real 2nds AND unisons -- these are the only conflicts
        # that can seed a cluster. v22ze-51 fix: this used to only catch
        # diff==1 (an actual 2nd); two notes at the EXACT same pitch
        # (diff==0 -- e.g. a divisi unison, or simply the same pitch
        # doubled across two input tracks/voices merged into one) landed
        # on identical canvas coordinates and were never flagged as a
        # conflict, so the second notehead was drawn directly on top of
        # the first -- both notes were genuinely there in the data, only
        # one was ever visible.
        for i in range(n - 1):
            if sorted_ys[i + 1][0] - sorted_ys[i][0] <= 1:
                _union(i, i + 1)

        # Phase 2: grow seeded clusters outward via accidental-thirds,
        # repeating to a fixed point so a chain of several altered tones
        # (e.g. C3-D3-F#3-A3) extends as far as the accidentals continue.
        changed = True
        while changed:
            changed = False
            root_size = {}
            for i in range(n):
                root_size[_find(i)] = root_size.get(_find(i), 0) + 1
            for i in range(n - 1):
                diff = sorted_ys[i + 1][0] - sorted_ys[i][0]
                if diff != 2:
                    continue
                if not (sorted_ys[i][1] != 0 or sorted_ys[i + 1][1] != 0):
                    continue
                ri, rj = _find(i), _find(j := i + 1)
                if ri != rj and (root_size.get(ri, 1) >= 2 or root_size.get(rj, 1) >= 2):
                    _union(i, j)
                    changed = True

        clusters_by_root = {}
        for i in range(n):
            clusters_by_root.setdefault(_find(i), []).append(i)
        clusters = list(clusters_by_root.values())  # each already ascending (built in index order)

        offset_set = set()  # note ids that get mirrored to the far side of the stem
        for cluster in clusters:
            if len(cluster) < 2:
                continue  # isolated note, no conflict -- stays normal
            # anchor end: topmost for stem-up, bottommost for stem-down
            order = list(reversed(cluster)) if stem_up else list(cluster)
            for k, idx in enumerate(order):
                if k % 2 == 1:  # alternate: anchor normal, then offset, normal, ...
                    offset_set.add(id(sorted_ys[idx][3]))

        # ── Draw ledger lines, accidentals, noteheads ────────────────────────
        for pos, acc, y, n in ys:
            # v22ze-19 fix: offset noteheads must mirror to the side of the
            # stem OPPOSITE the normal notes -- not always shift right.
            # Normal notes touch the stem at x +/- nr depending on stem
            # direction (stem-up: stem at the note's right edge, x+nr;
            # stem-down: stem at the note's left edge, x-nr). A conflicting
            # note mirrored to the far side has ITS near edge touching that
            # same stem point, so its center lands at x+2*nr (stem-up) or
            # x-2*nr (stem-down) -- flush, no gap. The old code always used
            # x+2*nr+1 regardless of stem direction: correct side (but with
            # a stray 1px gap) for stem-up, but for stem-down it pushed the
            # "offset" note further in the SAME direction as the normal
            # notes instead of mirroring it to the other side of the stem --
            # exactly the "note placed off the stem behind the rest of the
            # chord" symptom originally reported.
            if id(n) in offset_set:
                nx = x + (2 * nr if stem_up else -2 * nr)
            else:
                nx = x
            for lp in range(int(bot_sp) - 2, int(pos) - 1, -2):
                ly = sp_to_y(lp, top_y)
                c.create_line(nx - nr - 4, ly, nx + nr + 4, ly, fill="black", width=1)
            for lp in range(int(top_sp) + 2, int(pos) + 1, 2):
                ly = sp_to_y(lp, top_y)
                c.create_line(nx - nr - 4, ly, nx + nr + 4, ly, fill="black", width=1)
            if n.pitch == 60:
                ly = self._sp_to_y_treble(0, tt)
                c.create_line(nx - nr - 4, ly, nx + nr + 4, ly, fill="black", width=1)
            # v22ze fix: courtesy-accidental suppression. Without
            # accidental_state tracking, every note redundantly redrew
            # its sharp/flat even when the SAME specific line/space was
            # already altered earlier in the same measure -- traditional
            # notation only needs it once per measure per position, with
            # a natural sign only if a later note in that measure reverts
            # away from the earlier alteration. key_implied_accidental()
            # also means a plain B in a piece keyed to 2 flats shows
            # nothing at all (already covered by the key signature),
            # not a flat on its first occurrence in every measure.
            show_glyph = None  # None=nothing, 1='#', -1='b', 0=natural
            if accidental_state is not None:
                letter_idx = int(pos) % 7
                key_default = key_implied_accidental(letter_idx, _key_str)
                prev = accidental_state["active"].get(pos, key_default)
                if acc != prev:
                    show_glyph = acc
                    accidental_state["active"][pos] = acc
            else:
                show_glyph = acc if acc != 0 else None

            # v22ze fix: Tkinter's anchor="center" centers on the font's
            # bounding-box metrics, but the ♯/♭ Unicode glyphs in most
            # serif fonts sit visually lower than that geometric center
            # (their ink isn't symmetric top/bottom) -- so even with a y
            # matching the notehead exactly, the symbol reads as sitting
            # just under the line/space it's meant to be on. Nudged up a
            # small, SLG-proportional amount (so it holds across zoom
            # levels) rather than a fixed pixel count. v22ze round 2:
            # more lift + bold weight + larger size per direct feedback
            # against a real screenshot (noteheads were also doubled in
            # this pass, so accidentals needed to scale up to match).
            _acc_y = y - self.SLG * 0.30
            if show_glyph == 1:
                c.create_text(
                    nx - nr - 10,
                    _acc_y,
                    text="♯",
                    font=("serif", int(self.SLG * 1.8), "bold"),
                    fill="#111",
                    anchor="center",
                )
            elif show_glyph == -1:
                c.create_text(
                    nx - nr - 10,
                    _acc_y,
                    text="♭",
                    font=("serif", int(self.SLG * 1.8), "bold"),
                    fill="#111",
                    anchor="center",
                )
            elif show_glyph == 0:
                c.create_text(
                    nx - nr - 10,
                    _acc_y,
                    text="♮",
                    font=("serif", int(self.SLG * 1.8), "bold"),
                    fill="#111",
                    anchor="center",
                )
            # Notehead as proper oval (wider than tall) that doesn't touch staff lines
            # h_rad = horizontal radius (width/2), v_rad = vertical radius (height/2)
            # Scale so noteheads fit snugly between staff lines (gap of ~0.1*SLG on each side)
            h_rad = nr * 0.90  # horizontal (slightly wider)
            v_rad = nr * 0.60  # vertical (noticeably shorter — fits between lines)
            # Grace notes: smaller notehead, drawn in dark grey to distinguish
            is_grace = any(getattr(n, "articulation", "") == "grace" for n in notes)
            if is_grace:
                h_rad *= 0.65
                v_rad *= 0.65
            fill_col = "black"
            outline_col = "black"
            if is_grace:
                fill_col = outline_col = "#444444"
            if db >= 4:
                # Whole note: outline only. v22ze: fill="" (not "white")
                # so a staff line already drawn underneath shows through
                # the open interior, matching real engraving -- "white"
                # painted over and hid the line instead.
                _nh_id = _draw_notehead(c, nx, y, h_rad, v_rad, outline_col, "", width=2)
                _nh_orig_fill = ""
            elif db >= 2:
                # Half note: outline only, same reasoning as whole note above.
                _nh_id = _draw_notehead(c, nx, y, h_rad, v_rad, outline_col, "", width=2)
                _nh_orig_fill = ""
            else:
                # Quarter, eighth, etc: filled
                _nh_id = _draw_notehead(c, nx, y, h_rad, v_rad, outline_col, fill_col)
                _nh_orig_fill = fill_col
            # v22ze-25 (housekeeping item 5): register this notehead so
            # _ui_tick_update can flash it neon green as playback strikes
            # it, reverting to _nh_orig_fill once the flash window passes.
            if not is_grace:
                self._flash_index.append((int(n.tick), _nh_id, _nh_orig_fill))

            # v22ze-50 fix: _click_articulation() correctly set/toggled
            # n.articulation on the underlying note (and pushed a proper
            # undo step), but nothing in ScoreView ever drew any mark for
            # it -- "Articulation generates the correct menu, but does not
            # apply the requested mark" was really "applies the data
            # change, never draws it." Marks are placed on the side of
            # the notehead away from the stem, per standard engraving.
            art = getattr(n, "articulation", "")
            if art and art not in ("grace", "pedal_extended", "tie_continuation"):
                art_y = y + (self.SLG * 1.15 if stem_up else -self.SLG * 1.15)
                if art == "staccato":
                    r = max(1.5, self.SLG * 0.14)
                    c.create_oval(
                        nx - r,
                        art_y - r,
                        nx + r,
                        art_y + r,
                        fill="black",
                        outline="black",
                    )
                elif art == "accent":
                    w = self.SLG * 0.55
                    c.create_line(
                        nx - w,
                        art_y - w * 0.7,
                        nx + w,
                        art_y,
                        nx - w,
                        art_y + w * 0.7,
                        fill="black",
                        width=1.6,
                        smooth=False,
                    )
                elif art == "marcato":
                    w = self.SLG * 0.5
                    c.create_line(
                        nx - w,
                        art_y + w * 0.8,
                        nx,
                        art_y - w * 0.9,
                        nx + w,
                        art_y + w * 0.8,
                        fill="black",
                        width=1.6,
                        smooth=False,
                    )
                elif art == "tenuto":
                    w = self.SLG * 0.55
                    c.create_line(nx - w, art_y, nx + w, art_y, fill="black", width=2.2)
                elif art in ("pizzicato", "arco"):
                    label = "pizz." if art == "pizzicato" else "arco"
                    c.create_text(
                        nx,
                        art_y + (self.SLG * 0.9 if stem_up else -self.SLG * 0.9),
                        text=label,
                        font=("serif", max(7, int(self.SLG * 1.0)), "italic"),
                        fill="#222",
                        anchor="center",
                    )

        # ── Single stem for the whole chord (not for whole notes) ────────────
        if db < 4:
            c.create_line(
                sx,
                stem_root_y,
                sx,
                sy,
                fill="black",
                width=max(2, int(self.SLG * 0.16)),
            )  # v22ze: bolder stem

        # ── Return StemInfo for beam drawing; flags drawn later by _draw_beams ─
        if db < 4:
            staff_id = "treble" if use_treble else "bass"
            return self.StemInfo(
                tick=notes[0].tick,
                x=x,
                sx=sx,
                stem_root_y=stem_root_y,
                sy=sy,
                stem_up=stem_up,
                db=db,
                staff=staff_id,
            )
        return None

    # ─── Beam drawing ────────────────────────────────────────────────────────

    def _draw_flag(self, c, sx, sy, stem_up, n_flags):
        """Draw note flags (tails) as engraved hook shapes.
        Each flag sweeps right from the stem tip, drops, then curls back left
        like a real engraved flag — resembling a large tilde/curl, not a U.
        stem_up=True  → flags hang downward from tip (fd=+1 in canvas y)
        stem_up=False → flags rise upward from tip  (fd=-1 in canvas y)"""
        fd = 1 if stem_up else -1  # direction away from notehead
        flag_sp = self.SLG * 1.15  # vertical spacing between stacked flags
        fw = self.SLG * 1.4  # maximum rightward reach
        fh = self.SLG * 1.5  # total vertical travel of one flag

        def cubic_pts(p0, p1, p2, p3, steps=20):
            pts = []
            for i in range(steps + 1):
                t = i / steps
                mt = 1 - t
                x = mt**3 * p0[0] + 3 * mt**2 * t * p1[0] + 3 * mt * t**2 * p2[0] + t**3 * p3[0]
                y = mt**3 * p0[1] + 3 * mt**2 * t * p1[1] + 3 * mt * t**2 * p2[1] + t**3 * p3[1]
                pts.extend([x, y])
            return pts

        for fi in range(n_flags):
            fy0 = sy + fi * flag_sp * fd  # root of this flag at stem

            # Control points designed for the classic engraved flag shape:
            #  P0: root at stem (left)
            #  P1: swing right and slightly along fd → starts the rightward arc
            #  P2: far right, travelled fd*fh*0.55 → peak of the bulge
            #  P3: curl back left to ~40% of fw, travelled fd*fh → tip of hook
            #
            # This produces: a stroke that leaves the stem going right, swells
            # outward, then curls back inward — a tilde/hook, not a U or loop.
            p0 = (sx, fy0)
            p1 = (sx + fw * 0.7, fy0 + fh * 0.15 * fd)
            p2 = (sx + fw, fy0 + fh * 0.55 * fd)
            p3 = (sx + fw * 0.4, fy0 + fh * 1.00 * fd)

            pts = cubic_pts(p0, p1, p2, p3, steps=22)

            # Draw twice: once thick (body), once thin (highlight) for weight
            c.create_line(pts, fill="black", width=2.2, smooth=False)
            # Thin inner highlight to give the impression of a tapered stroke
            hi_pts = cubic_pts(
                (sx + 0.5, fy0 + 0.5 * fd),
                (sx + fw * 0.65, fy0 + fh * 0.18 * fd),
                (sx + fw * 0.9, fy0 + fh * 0.52 * fd),
                (sx + fw * 0.35, fy0 + fh * 0.95 * fd),
                steps=22,
            )
            c.create_line(hi_pts, fill="#555", width=0.8, smooth=False)

    @staticmethod
    def _is_triplet_ioi(ioi, tpb, tol=0.12):
        """Return True if ioi matches a triplet inter-onset interval.

        A triplet IOI is 2/3 of a standard note value.  This helper fires
        only when:
          (a) ioi ≈ std_val * 2/3  for some standard value, AND
          (b) ioi is NOT ≈ any standard value itself
              (to exclude three regular beamed eighth-notes whose IOI happens
               to be equal — they pass an equal-spacing test but are not triplets)
        """
        if ioi <= 0:
            return False
        std_vals = (tpb * 2, tpb, tpb // 2, tpb // 4, tpb // 8)
        # Gate (b): if ioi is close to any standard value, it is a regular note
        for sv in std_vals:
            if sv > 0 and abs(ioi - sv) / sv < tol * 0.6:
                return False
        # Gate (a): ioi ≈ std_val * 2/3
        for sv in std_vals:
            triplet_ioi = sv * 2 / 3
            if triplet_ioi > 0 and abs(ioi - triplet_ioi) / triplet_ioi < tol:
                return True
        return False

    def _predict_beam_stem_directions(
        self,
        entries,
        tt,
        bt,
        tpb,
        mmap,
        _use_flats,
        bass_treble_measures,
        treble_bass_measures,
    ):
        """Predict which chord entries will end up in the same beam group
        (mirroring _draw_beams's own grouping rule exactly, including its
        use of song.ticks_per_measure() for the measure boundary, not a
        per-measure mmap lookup -- so this prediction and the real
        grouping that happens later can never disagree about where a
        group starts or ends) and, for any group with 2+ notes, compute
        ONE shared stem direction for the whole group -- based on the
        note furthest from that group's staff middle line across ALL its
        members, the standard engraving rule -- rather than each note
        picking its own direction independently.

        Returns {id(notes): stem_up} for every entry that's part of such
        a group; entries not in the dict fall back to their own
        independent per-chord decision (force_stem_up=None), which is
        correct for genuinely isolated notes.
        """
        song = self.app.song
        tpm = song.ticks_per_measure()

        by_force_treble = {True: [], False: []}
        for notes, force_t, is_v2 in entries:
            if is_v2:
                continue  # the always-stem-up mixed-duration voice sits
                # outside this prediction -- unrelated rule
            durs = sorted(n.duration for n in notes)
            db = durs[len(durs) // 2] / tpb
            _sp_to_y, _top_y, _bot_sp, _top_sp, mid_sp, _measure, _use_treble = (
                self._clef_branch_for_chord(
                    notes,
                    tt,
                    bt,
                    mmap,
                    force_t,
                    bass_treble_measures,
                    treble_bass_measures,
                    _use_flats,
                )
            )
            positions = [note_staff_pos(n, _use_flats)[0] for n in notes]
            by_force_treble[force_t].append(
                {
                    "notes": notes,
                    "tick": notes[0].tick,
                    "db": db,
                    "mid_sp": mid_sp,
                    "positions": positions,
                }
            )

        MAX_BEAM = 8
        forced = {}
        for _force_t, stream in by_force_treble.items():
            stream.sort(key=lambda e: e["tick"])
            groups, cur = [], []
            for e in stream:
                beat = int(e["tick"] // tpb)
                meas = int(e["tick"] // tpm)
                if e["db"] > 0.5:
                    if cur:
                        groups.append(cur)
                        cur = []
                    continue
                if cur:
                    prev = cur[-1]
                    prev_beat = int(prev["tick"] // tpb)
                    prev_meas = int(prev["tick"] // tpm)
                    if prev_meas != meas or prev_beat != beat or len(cur) >= MAX_BEAM:
                        groups.append(cur)
                        cur = []
                cur.append(e)
            if cur:
                groups.append(cur)

            for grp in groups:
                if len(grp) < 2:
                    continue  # isolated notes keep their own independent decision
                all_positions = []
                for e in grp:
                    all_positions.extend(e["positions"])
                mid_sp = grp[0]["mid_sp"]  # same staff for the whole group by construction
                furthest = max(all_positions, key=lambda p: abs(p - mid_sp))
                stem_up = True if abs(furthest - mid_sp) == 0 else furthest < mid_sp
                for e in grp:
                    forced[id(e["notes"])] = stem_up
        return forced

    def _draw_beams(self, c, stems, tpb, song):
        # Beam groups of short notes; draw flags on isolated short notes.
        if not stems:
            return

        stems = sorted(stems, key=lambda s: (s.tick, s.staff))
        bw = max(2, int(self.SLG * 0.38))  # beam bar thickness
        tpm = song.ticks_per_measure()  # hard break at barlines

        for staff_id in ("treble", "bass"):
            ss = [s for s in stems if s.staff == staff_id]
            if not ss:
                continue

            # -- Pre-compute IOI-based written duration for each stem --------
            # Standard engraving uses inter-onset interval (gap to next note
            # onset) as the written note value, not the MIDI note-off time.
            # A staccato 8th held only 100 ticks still sits in a 240-tick
            # (8th-note) slot and should beam as an 8th, not a 16th.
            _wdb = {}
            for _i, _s in enumerate(ss):
                if _i < len(ss) - 1:
                    _ioi = ss[_i + 1].tick - _s.tick
                    _wdb[id(_s)] = max(_s.db, _ioi / tpb) if _ioi > 0 else _s.db
                else:
                    _wdb[id(_s)] = _s.db

            def _wdb_get(s):
                return _wdb.get(id(s), s.db)

            # ── Partition into beam groups ────────────────────────────────
            # Breaks on: non-beamable note (db>=0.5), beat boundary,
            # measure boundary, OR max group size of 8 notes.
            MAX_BEAM = 8
            groups = []
            cur = []
            for s in ss:
                beat = int(s.tick // tpb)
                meas = int(s.tick // tpm)
                if _wdb_get(s) > 0.5:
                    if cur:
                        groups.append(cur)
                        cur = []
                else:
                    if cur:
                        prev_beat = int(cur[-1].tick // tpb)
                        prev_meas = int(cur[-1].tick // tpm)
                        if prev_meas != meas or prev_beat != beat or len(cur) >= MAX_BEAM:
                            groups.append(cur)
                            cur = []
                    cur.append(s)
            if cur:
                groups.append(cur)

            for grp in groups:
                # ── Isolated note: just draw flag ─────────────────────────
                if len(grp) == 1:
                    s = grp[0]
                    wdb = _wdb_get(s)
                    nf = 1 if wdb <= 0.5 else 0
                    if wdb <= 0.25:
                        nf = 2
                    if wdb <= 0.125:
                        nf = 3
                    # v22ze fix: nf was computed correctly here and then
                    # just discarded -- this branch never actually called
                    # _draw_flag at all, for ANY isolated short note,
                    # anywhere. _draw_flag itself was fine; it simply had
                    # zero call sites in the whole file. Every isolated
                    # eighth/sixteenth/etc. was left with a bare stem and
                    # no flag, and whatever beam-partitioning artifacts
                    # showed up around it (per the screenshot report)
                    # were a separate, secondary symptom of notes that
                    # should have terminated cleanly with a flag instead
                    # not doing so.
                    if nf > 0:
                        self._draw_flag(c, s.sx, s.sy, s.stem_up, nf)
                    continue

                # ── Beam group ────────────────────────────────────────────
                # Unified stem direction: majority vote
                beam_up = sum(1 for s in grp if s.stem_up) >= len(grp) / 2

                # Beam anchor y: use the stem tip that is most extreme
                # (furthest from noteheads) to anchor the beam level,
                # then slope gently toward last note.
                # Slope: use median of first-half vs median of second-half
                # tips, capped at SLG*0.4 total across the group.
                half = max(1, len(grp) // 2)
                y_lo = sum(s.sy for s in grp[:half]) / half
                y_hi = sum(s.sy for s in grp[half:]) / max(1, len(grp) - half)
                raw = y_hi - y_lo
                cap = self.SLG * 0.4
                rise = max(-cap, min(cap, raw))

                x0 = grp[0].sx
                x1 = grp[-1].sx
                # Anchor: outermost tip (highest for beam_up, lowest for beam_down)
                if beam_up:
                    anchor_y = min(s.sy for s in grp)  # highest point (min y)
                else:
                    anchor_y = max(s.sy for s in grp)

                # Place beam so the most extreme stem just touches it
                # and apply slope from there
                if beam_up:
                    # beam line runs along the tops of stems
                    # find x of the most extreme stem
                    anchor_s = min(grp, key=lambda s: s.sy)
                    beam_at_anchor = anchor_s.sy  # beam touches this tip
                else:
                    anchor_s = max(grp, key=lambda s: s.sy)
                    beam_at_anchor = anchor_s.sy

                def beam_y_at(sx):
                    if x1 == x0:
                        return beam_at_anchor
                    frac = (sx - x0) / (x1 - x0)
                    return beam_at_anchor + rise * (frac - (anchor_s.sx - x0) / (x1 - x0 + 1e-9))

                # Extend stems to meet beam (never shorten past notehead)
                for s in grp:
                    target = beam_y_at(s.sx)
                    if beam_up:
                        new_sy = min(s.sy, target)
                    else:
                        new_sy = max(s.sy, target)
                    # Redraw stem in canvas (raise it to front implicitly)
                    c.create_line(
                        s.sx,
                        s.stem_root_y,
                        s.sx,
                        new_sy,
                        fill="black",
                        width=max(2, int(self.SLG * 0.16)),
                    )

                # ── Draw beam bars ────────────────────────────────────────
                fd = -1 if beam_up else 1  # direction away from noteheads
                bar_gap = self.SLG * 0.62  # gap between successive beam bars

                for bar_level in range(3):
                    threshold = 0.5 / (2**bar_level)  # 0.5, 0.25, 0.125
                    eligible = [s for s in grp if _wdb_get(s) <= threshold]
                    if not eligible:
                        continue

                    offset = bar_level * bar_gap  # offset from primary beam

                    # Find contiguous runs of eligible notes
                    runs = []
                    run = [eligible[0]]
                    gi = {s: i for i, s in enumerate(grp)}
                    for s in eligible[1:]:
                        if gi[s] == gi[run[-1]] + 1:
                            run.append(s)
                        else:
                            runs.append(run)
                            run = [s]
                    runs.append(run)

                    for run in runs:
                        if len(run) < 2 and bar_level > 0:
                            # Partial stub (one beam-width wide)
                            #
                            # v22ze fix: this always extended the stub
                            # RIGHTWARD (bx0 + stub), regardless of the
                            # note's position in the group. For the LAST
                            # note in a beam group, there's no note to
                            # its right to visually connect toward -- a
                            # rightward stub there floats disconnected
                            # past the end of the beam instead of
                            # pointing back at its own group, which is
                            # exactly the "beam attached mid-air, not
                            # meeting a flag at either end" appearance
                            # reported against a real screenshot. Partial
                            # beams point toward the side that has a
                            # neighboring note; only the true first note
                            # of the group has a well-defined "next note
                            # to the right" to point toward, so every
                            # other position (including genuinely
                            # isolated single mid-group 16ths) points
                            # backward instead.
                            s = run[0]
                            stub = self.SLG * 1.0
                            bx0 = s.sx
                            if gi[s] == 0:
                                bx1 = bx0 + stub  # first note: point forward
                            else:
                                bx1 = bx0 - stub  # last/mid note: point backward
                            # v22ze-18 fix: secondary/tertiary beams (bar_level>0)
                            # must stack toward the NOTEHEADS, not past the tip.
                            # fd points away from the noteheads (the direction the
                            # stem extends to reach the primary beam), so adding
                            # +offset*fd pushed each extra beam further out past
                            # the primary -- exactly the "16th beam sits over/under
                            # the main beam" collision reported when up-stems and
                            # down-stems from opposite staves meet. Subtracting
                            # instead walks each additional beam back in, toward
                            # the stem root/notehead, which is where engraving
                            # convention stacks them.
                            by0 = beam_y_at(bx0) - offset * fd
                            by1 = beam_y_at(bx1) - offset * fd
                        else:
                            bx0 = run[0].sx
                            bx1 = run[-1].sx
                            by0 = beam_y_at(bx0) - offset * fd
                            by1 = beam_y_at(bx1) - offset * fd
                        half_bw = bw / 2
                        c.create_polygon(
                            bx0,
                            by0 - half_bw,
                            bx1,
                            by1 - half_bw,
                            bx1,
                            by1 + half_bw,
                            bx0,
                            by0 + half_bw,
                            fill="black",
                            outline="black",
                        )

                # ── Triplet "3" bracket ───────────────────────────────────
                # Fire only on exactly-3-note beamed groups whose IOI matches
                # a triplet pattern (2/3 of a standard note value).
                # Isolated triplet quarters (non-beamed) are deferred to v22d.
                if len(grp) == 3:
                    ioi_01 = grp[1].tick - grp[0].tick
                    ioi_12 = grp[2].tick - grp[1].tick
                    if ioi_01 > 0 and ioi_12 > 0:
                        avg_ioi = (ioi_01 + ioi_12) / 2
                        # Equal spacing gate: both IOIs within 20% of average
                        equal_spaced = (
                            abs(ioi_01 - avg_ioi) / avg_ioi < 0.20
                            and abs(ioi_12 - avg_ioi) / avg_ioi < 0.20
                        )
                        if equal_spaced and self._is_triplet_ioi(avg_ioi, tpb):
                            # Bracket geometry
                            gap = self.SLG * 1.3  # clearance above/below beam
                            stub_h = self.SLG * 0.55  # vertical stub height
                            fd = -1 if beam_up else 1  # direction away from notes
                            bx_l = grp[0].sx
                            bx_r = grp[-1].sx
                            # Bracket y: above beam if stems up, below if stems down
                            if beam_up:
                                by = min(beam_y_at(s.sx) for s in grp) - gap
                            else:
                                by = max(beam_y_at(s.sx) for s in grp) + gap
                            # Horizontal bar
                            c.create_line(
                                bx_l,
                                by,
                                bx_r,
                                by,
                                fill="#333333",
                                width=1,
                                tags="triplet_bracket",
                            )
                            # Left stub
                            c.create_line(
                                bx_l,
                                by,
                                bx_l,
                                by + stub_h * fd,
                                fill="#333333",
                                width=1,
                                tags="triplet_bracket",
                            )
                            # Right stub
                            c.create_line(
                                bx_r,
                                by,
                                bx_r,
                                by + stub_h * fd,
                                fill="#333333",
                                width=1,
                                tags="triplet_bracket",
                            )
                            # "3" numeral centred on the bracket
                            c.create_text(
                                (bx_l + bx_r) / 2,
                                by - stub_h * fd * 0.9,
                                text="3",
                                font=("serif", max(7, int(self.SLG * 0.9))),
                                fill="#333333",
                                tags="triplet_bracket",
                            )

        # Raise all triplet bracket items above beam bars so they are readable
        c.tag_raise("triplet_bracket")

    # ── Measure status strip ─────────────────────────────────────────────────
    STRIP_H = 18  # px height of the strip band
    STRIP_MIN_MEAS_PX = 40  # hide strip entirely below this measure width

    def _draw_measure_strip(self, c, mmap, song, tracks):
        """Draw the per-measure beat-count status strip above the first stave.

        Each cell shows the actual beat count vs. the time-signature expectation
        and is colour-coded:
          • no fill            — clean (actual ≈ expected)
          • amber #5a4200      — over/under by ≤ 1 beat
          • red   #5a1010      — over/under by > 1 beat
          • blue  #1a3a5a      — currently selected measure
          • green #1a4a1a      — user-accepted / corrected

        The strip is hidden entirely when the first measure is narrower than
        STRIP_MIN_MEAS_PX pixels (i.e. at low zoom levels).
        """
        if not mmap or not tracks:
            return

        tpb = song.ticks_per_beat
        app = self.app

        # Threshold check on first measure
        _, ms0, me0, _, _, _ = mmap[0]
        if self._tick_to_x(me0) - self._tick_to_x(ms0) < self.STRIP_MIN_MEAS_PX:
            return  # strip hidden at this zoom level

        # Strip sits in the TPAD space just above the top stave — but must
        # never overlap a high note's stem/ledger lines.  Previously this
        # was a fixed offset (treble_top - 2), which collided with high
        # treble notes whose stems reach well above the staff (reported:
        # the strip hid notes in measure 3 of a Rachmaninoff passage).
        #
        # Fix: find the highest-pitched note that renders in the treble
        # clef (pos >= 2, per the same convention used for stem/tie
        # placement elsewhere) across the top staff's track(s), compute
        # the y-coordinate its notehead — and a typical stem reaching up
        # from it — would occupy, and float the whole strip band above
        # that instead of using a fixed gap.
        tt = self._treble_top(0, tracks)
        strip_bot = tt - 2
        strip_top = strip_bot - self.STRIP_H

        _max_pos = None
        _use_flats = _song_uses_flats(app.song)
        for _tr in tracks[:1]:  # top staff's track (grand-staff merge puts
            # both hands here when applicable)
            for _n in _tr.notes:
                _pos, _ = note_staff_pos(_n, _use_flats)
                if _pos >= 2 and (_max_pos is None or _pos > _max_pos):
                    _max_pos = _pos
        if _max_pos is not None:
            _notehead_y = self._sp_to_y_treble(_max_pos, tt)
            # Typical stem length (~3.5 staff spaces) plus a small buffer,
            # so the band clears the stem tip, not just the notehead.
            _stem_clearance = self.SLG * 3.5 + 6
            _top_reach_y = _notehead_y - _stem_clearance
            if _top_reach_y < strip_bot:
                strip_bot = _top_reach_y - 4  # small gap above the stem tip
                strip_top = strip_bot - self.STRIP_H

        # Safety clamp (v22v): even with reserved headroom above, an
        # extreme passage could still compute a negative strip_top, which
        # would place the strip outside the canvas scrollregion entirely —
        # invisible rather than merely imperfectly placed.  A strip that
        # can't fully clear the tallest stem but is still ON SCREEN is
        # better than one that has vanished completely.
        if strip_top < 2:
            strip_top = 2
            strip_bot = strip_top + self.STRIP_H

        # App-level state
        accepted = getattr(app, "_accepted_measures", set())
        selected = getattr(app, "_selected_measure_idx", None)
        global_bpm = song.bpm

        f_main = ("TkDefaultFont", 8)
        f_small = ("TkDefaultFont", 7)

        for m_idx, ms, me, num, den, tpm in mmap:
            x0 = self._tick_to_x(ms)
            x1 = self._tick_to_x(me)
            cw = x1 - x0
            if cw < 6:
                continue

            # ── Compute actual beat content ───────────────────────────────
            # Use the latest note-end that starts within the measure as a
            # proxy for how much content the measure contains.  This is the
            # most direct answer to "does this measure overflow the barline?"
            latest_end = ms  # fallback: empty measure
            for tr in tracks:
                for n in tr.notes:
                    if ms <= n.tick < me:
                        latest_end = max(latest_end, n.tick + n.duration)

            actual_ticks = max(0, latest_end - ms)
            expected_ticks = tpm
            if actual_ticks == 0:
                actual_ticks = expected_ticks  # empty = neutral

            actual_q = actual_ticks / tpb
            expected_q = expected_ticks / tpb
            delta = actual_q - expected_q  # positive = overflow

            # ── Choose cell colour ────────────────────────────────────────
            if m_idx == selected:
                fill = "#1a3a5a"
            elif m_idx in accepted:
                fill = "#1a4a1a"
            elif abs(delta) < 0.15:
                fill = None  # clean
            elif abs(delta) <= 1.0:
                fill = "#5a4200"  # amber
            else:
                fill = "#5a1010"  # red

            # ── Draw cell background ──────────────────────────────────────
            pad = 1
            if fill:
                c.create_rectangle(
                    x0 + pad,
                    strip_top + pad,
                    x1 - pad,
                    strip_bot - pad,
                    fill=fill,
                    outline="",
                    tags="strip",
                )

            # ── Beat-count label (omit when clean and not selected) ───────
            cx = (x0 + x1) / 2
            if abs(delta) >= 0.15 or m_idx == selected:
                label = f"{round(actual_q)}/{round(expected_q)}"
                txt_col = "#ffffff" if fill else "#888888"
                c.create_text(
                    cx,
                    strip_top + self.STRIP_H * 0.42,
                    text=label,
                    font=f_main,
                    fill=txt_col,
                    tags="strip",
                )

                # Local BPM below the fraction when it differs by > 3 BPM
                if actual_ticks > 0 and actual_ticks != expected_ticks:
                    local_bpm = global_bpm * (expected_ticks / actual_ticks)
                    if abs(local_bpm - global_bpm) > 3:
                        c.create_text(
                            cx,
                            strip_bot - 3,
                            text=f"{local_bpm:.0f}",
                            font=f_small,
                            fill="#aaaaaa",
                            anchor="s",
                            tags="strip",
                        )

            # ── Clickable overlay ─────────────────────────────────────────
            tag = f"strip_m{m_idx}"
            c.create_rectangle(
                x0, strip_top, x1, strip_bot, fill="", outline="", tags=("strip", tag)
            )
            c.tag_bind(tag, "<Button-1>", lambda e, idx=m_idx: self._on_strip_click(idx))
            c.tag_bind(tag, "<Enter>", lambda e: c.configure(cursor="hand2"))
            c.tag_bind(
                tag,
                "<Leave>",
                # v22ze-68 fix: this used to reset to "" (the
                # system default arrow) -- but ScoreView's canvas
                # is created with cursor="crosshair" as its own
                # normal state, not the system default. Once the
                # user hovered over ANY clickable measure-strip
                # overlay even once, leaving it permanently
                # overwrote the canvas cursor to the arrow, with
                # nothing anywhere restoring "crosshair" -- so it
                # never came back for the rest of the session.
                lambda e: c.configure(cursor="crosshair"),
            )

    def _on_strip_click(self, measure_idx):
        """Handle click on a measure strip cell.

        The explicit _draw() that repaints the blue selection highlight is
        scheduled 60 ms into the future rather than called immediately.
        This ensures it fires AFTER any tk.Toplevel that _open_score_setup()
        creates has fully constructed and settled — preventing the Toplevel's
        geometry changes from triggering a second <Configure>-driven _draw()
        mid-construction that would produce phantom canvas items.

        60 ms > the 50 ms debounce window, so by the time the scheduled
        _draw() fires the debounce job has already been cancelled and this
        single repaint is the only one that runs.
        """
        self.app._selected_measure_idx = measure_idx
        app = self.app
        if app._score_setup_dlg is not None and app._score_setup_dlg.winfo_exists():
            app._score_setup_dlg._populate_measure_detail(measure_idx)
        else:
            app._open_score_setup()
        # Delay past Toplevel construction + debounce window (50 ms)
        self.canvas.after(60, self._draw)

    def _draw_dynamics(self, c, tr, tt, bt, tpb, mmap):
        """Draw dynamics markings (pp, mf, ff, etc.) below the staff.

        v22ze-50 fix: _click_dynamics() correctly appended a MidiEvent to
        Track.markings and pushed an undo step, but no drawing code ever
        read Track.markings -- so the marking was really being added, just
        never rendered, making the feature look completely inert.  Style
        matches _draw_pedal() (below the bottom staff), using the standard
        bold-italic dynamics typeface convention.
        """
        markings = getattr(tr, "markings", None)
        if not markings:
            return
        dyn_y = (
            (bt + self.SH + self.SLG * 3.2) if bt is not None else (tt + self.SH + self.SLG * 1.6)
        )
        for ev in markings:
            # v22ze-35: markings hold a ("dynamic", value) tuple in .msg,
            # not a real mido message -- guard the shape before reading it.
            msg = getattr(ev, "msg", None)
            if not (isinstance(msg, tuple) and len(msg) == 2 and msg[0] == "dynamic"):
                continue
            x = self._tick_to_x(ev.tick)
            c.create_text(
                x,
                dyn_y,
                text=msg[1],
                font=("serif", max(9, int(self.SLG * 1.6)), "bold italic"),
                fill="#222",
                anchor="w",
                tags="dynamic_mark",
            )

    def _draw_pedal(self, c, tr, tt, bt, tpb, mmap):
        """Draw sustain-pedal marks below the bass staff.

        v22ze-69 fix: two user-requested changes, following the standard
        described at https://en.wikipedia.org/wiki/List_of_musical_symbols
        (Piano > Pedal marks):
          1. Use literal "Ped." text (bold italic) rather than the Unicode
             pedal glyph -- clearer, and universally renderable regardless
             of font support -- and end each segment with a short vertical
             tick rather than an asterisk, matching the "variable pedal
             mark" convention Wikipedia describes as the more precise form
             (short vertical lines at depress/release, connected by a
             horizontal line for the held duration).
          2. Placement: this used to sit at a small FIXED offset below the
             bass staff's own bottom line, with no regard for how far below
             that line the piece's own lowest notes (and their ledger
             lines) actually reach -- on a piece with genuinely low bass
             content, the pedal mark could end up drawn right through
             those ledger lines and noteheads instead of clearly below all
             of them. Compute the real lowest rendered position for this
             track (via the same note_staff_pos/_sp_to_y_bass math actual
             noteheads use) and place the pedal mark below THAT, not just
             below the staff line.

        v22q: reads CC64 sustain-pedal events directly from tr.events rather
        than inferring pedal from note duration clustering.  After v22p,
        rationalized tracks carry the original CC64 events so this is now
        reliable.  Falls back to the old heuristic if no CC64 events found.
        """
        if bt is None:
            return  # single-staff track — no bass staff to mark below

        _use_flats_pd = _song_uses_flats(self.app.song)
        # Staff position -10 = the bass staff's own bottom line (G2). Any
        # note actually reaching further below than that needs its ledger
        # lines cleared too -- take whichever is lower.
        _min_pos_pd = -10
        if tr.notes:
            _min_pos_pd = min(
                _min_pos_pd, min(note_staff_pos(n, _use_flats_pd)[0] for n in tr.notes)
            )
        _lowest_y = self._sp_to_y_bass(_min_pos_pd, bt)
        ped_y = _lowest_y + self.SLG * 1.1  # clearance below the lowest content

        # ── Read CC64 events ──────────────────────────────────────────────
        # v22ze-35 fix: Track.events can now also hold lightweight
        # tuple-based markers (dynamics, via EventEditAction) alongside
        # real mido pedal messages -- guard that ev.msg actually HAS a
        # .type before reading it, not just that ev itself has a .msg.
        cc64 = [
            (ev.tick, ev.msg.value)
            for ev in getattr(tr, "events", [])
            if (
                hasattr(ev, "msg")
                and hasattr(ev.msg, "type")
                and ev.msg.type == "control_change"
                and ev.msg.control == 64
            )
        ]
        cc64.sort(key=lambda x: x[0])

        if not cc64:
            return  # no pedal data — skip rendering

        # Build pedal segments: on when value ≥ 64, off when value < 64
        segs = []
        ped_on_tick = None
        for tick, val in cc64:
            if val >= 64 and ped_on_tick is None:
                ped_on_tick = tick
            elif val < 64 and ped_on_tick is not None:
                segs.append((ped_on_tick, tick))
                ped_on_tick = None
        if ped_on_tick is not None:
            # Pedal still held at end of events — close at last note end
            last_note_end = max((n.tick + n.duration for n in tr.notes), default=ped_on_tick)
            segs.append((ped_on_tick, last_note_end))

        # ── Draw each pedal segment ───────────────────────────────────────
        _ped_fill = "#222"
        _tick_h = self.SLG * 0.5  # half-line-gap tall, matching a light bracket
        for ped_start, ped_end in segs:
            x0 = self._tick_to_x(ped_start)
            x1 = self._tick_to_x(ped_end)
            if x1 - x0 < 4:
                continue
            # "Ped." text at start (bold italic, per the requested WP style)
            c.create_text(
                x0,
                ped_y,
                text="Ped.",
                font=("serif", max(9, int(self.SLG * 1.3)), "bold italic"),
                fill=_ped_fill,
                anchor="w",
            )
            # Short vertical tick marking the initial depress, right after
            # the text -- and the sustain line for the held duration.
            lx0 = x0 + max(8, int(self.SLG * 2.4))
            c.create_line(lx0, ped_y - _tick_h, lx0, ped_y + _tick_h, fill=_ped_fill, width=2)
            c.create_line(lx0, ped_y, x1, ped_y, fill=_ped_fill, width=2)
            # Short vertical tick marking the release.
            c.create_line(x1, ped_y - _tick_h, x1, ped_y + _tick_h, fill=_ped_fill, width=2)

    def _draw_ties(self, c, tr, tt, bt, nr, tpb, mmap, ti=0):
        """Draw tie arcs for notes whose duration crosses a barline."""
        fe = self._fe()
        # Max tie = 2 measures (longer = recording artifact)
        first_tpm = mmap[0][5] if mmap else tpb * 4
        MAX_TIE_TICKS = first_tpm * 2

        # Build a fast lookup: for each measure index, (start_tick, end_tick)
        meas_bounds = {m_idx: (ms, me) for m_idx, ms, me, _n, _d, _t in mmap}

        # tick → measure index helper
        def meas_of(tick):
            for m_idx, ms, me, _n, _d, _t in mmap:
                if ms <= tick < me:
                    return m_idx
            return len(mmap) - 1

        notes_by_pitch: dict[int, list] = {}
        for n in tr.notes:
            notes_by_pitch.setdefault(n.pitch, []).append(n)
        for lst in notes_by_pitch.values():
            lst.sort(key=lambda n: n.tick)

        for note in tr.notes:
            if note.duration > MAX_TIE_TICKS:
                continue

            end_tick = note.tick + note.duration
            note_meas = meas_of(note.tick)
            end_meas = meas_of(end_tick)
            if end_meas <= note_meas:
                continue  # doesn't cross a barline

            # Require continuation note in the immediately next measure
            if note_meas + 1 not in meas_bounds:
                continue
            next_ms, next_me = meas_bounds[note_meas + 1]
            cont_note = None
            for cn in notes_by_pitch.get(note.pitch, []):
                if next_ms <= cn.tick < next_me and cn is not note:
                    cont_note = cn
                    break
            if cont_note is None:
                continue

            pos, _ = note_staff_pos(note, _song_uses_flats(self.app.song))
            tracks = self.app.song.tracks
            use_treble = pos >= 2
            if use_treble:
                y = self._sp_to_y_treble(pos, self._treble_top(ti, tracks))
                tie_above = pos >= 5.5
            else:
                bt_y = self._bass_top(ti, tracks)
                if bt_y is None:
                    continue  # single-staff track — skip bass ties
                y = self._sp_to_y_bass(pos, bt_y)
                tie_above = pos >= 5.5

            x1 = int(self._tick_to_x(note.tick)) + nr + 2
            x2 = int(self._tick_to_x(cont_note.tick)) - nr - 2
            if x2 <= x1:
                continue

            arc_w = x2 - x1
            arc_h = max(5, min(int(self.SLG * 1.2), int(arc_w * 0.12)))
            h_dir = -1 if tie_above else 1

            pts = []
            steps = 24
            for i in range(steps + 1):
                t = i / steps
                mt = 1 - t
                bx = (
                    mt**3 * x1
                    + 3 * mt**2 * t * (x1 + arc_w * 0.25)
                    + 3 * mt * t**2 * (x2 - arc_w * 0.25)
                    + t**3 * x2
                )
                by = (
                    mt**3 * y
                    + 3 * mt**2 * t * (y + h_dir * arc_h)
                    + 3 * mt * t**2 * (y + h_dir * arc_h)
                    + t**3 * y
                )
                pts.extend([bx, by])
            c.create_line(pts, fill="#222", width=1.8, smooth=False)

    def _draw_note(self, c, note, tt, bt, nr, tpb):
        # Legacy single-note draw — kept for compatibility; chord path is used instead.
        pos, acc = note_staff_pos(note, _song_uses_flats(self.app.song))
        db = note.duration / tpb
        use_treble = pos >= -2
        if use_treble:
            y = self._sp_to_y_treble(pos, tt)
            top_y = tt
            sp_to_y = self._sp_to_y_treble
            bot_sp = -3
            top_sp = 5
        else:
            y = self._sp_to_y_bass(pos, bt)
            top_y = bt
            sp_to_y = self._sp_to_y_bass
            bot_sp = -10
            top_sp = -4

        x = int(self._tick_to_x(note.tick)) + nr + 2

        # ledger lines below staff
        lp = bot_sp - 1
        while lp >= pos:
            if (lp - bot_sp) % 2 == 0:
                ly = sp_to_y(lp, top_y)
                c.create_line(x - nr - 3, ly, x + nr + 3, ly, fill="black", width=1)
            lp -= 1
        # ledger lines above staff
        lp = top_sp + 1
        while lp <= pos:
            if (lp - top_sp) % 2 == 0:
                ly = sp_to_y(lp, top_y)
                c.create_line(x - nr - 3, ly, x + nr + 3, ly, fill="black", width=1)
            lp += 1
        # middle C ledger
        if note.pitch == 60:
            ly = sp_to_y(0, tt) if use_treble else sp_to_y(0, bt)
            c.create_line(x - nr - 3, ly, x + nr + 3, ly, fill="black", width=1)

        # accidental
        # v22ze fix: same font optical-center offset as the main chord
        # drawing path above -- see that comment for the full reasoning.
        # v22ze round 2: more lift + bold + larger, matching the main path.
        _acc_y = y - self.SLG * 0.30
        if acc == 1:
            c.create_text(
                x - nr - 9,
                _acc_y,
                text="♯",
                font=("serif", int(self.SLG * 1.9), "bold"),
                fill="black",
                anchor="center",
            )
        elif acc == -1:
            c.create_text(
                x - nr - 9,
                _acc_y,
                text="♭",
                font=("serif", int(self.SLG * 1.9), "bold"),
                fill="black",
                anchor="center",
            )

        # stem direction: up when note is below the middle line (B4=pos 2)
        stem_up = pos < 2
        sl = self.SLG * 3.5
        sx = x + (nr if stem_up else -nr)

        if db >= 4:  # whole
            _draw_notehead(c, x, y, nr + 1, nr - 2, "black", "", width=2)
        elif db >= 2:  # half
            _draw_notehead(c, x, y, nr, nr - 1, "black", "", width=2)
            sy = y - sl if stem_up else y + sl
            c.create_line(sx, y, sx, sy, fill="black", width=2)
        else:  # quarter or shorter — filled
            _draw_notehead(c, x, y, nr, nr - 1, "black", "black")
            sy = y - sl if stem_up else y + sl
            c.create_line(sx, y, sx, sy, fill="black", width=2)
            # flags (tails)
            n_flags = 0
            if db < 0.5:
                n_flags = 1  # 8th
            if db < 0.25:
                n_flags = 2  # 16th
            if db < 0.125:
                n_flags = 3  # 32nd
            # fd: direction flags stack FROM stem tip, always toward notehead
            # stem_up → tip is high (small y), flags hang downward (+y)
            # stem_down → tip is low (large y), flags go upward (-y)
            fd = 1 if stem_up else -1
            flag_sp = self.SLG * 0.85  # spacing between consecutive flags
            for fi in range(n_flags):
                fy0 = sy + fi * flag_sp * fd  # start of this flag at stem tip side
                # Flag sweeps right then curls back; curve points go away then return
                # All y offsets are relative to fy0, in the fd direction
                c.create_line(
                    sx,
                    fy0,
                    sx + 10,
                    fy0 + self.SLG * 0.5 * fd,
                    sx + 10,
                    fy0 + self.SLG * 1.0 * fd,
                    sx,
                    fy0 + self.SLG * 1.2 * fd,
                    fill="black",
                    width=1.5,
                    smooth=True,
                )

    def _draw_rest_shape(self, c, rest_type, cx, y, slg):
        """Draw a rest symbol geometrically (no font dependency).
        rest_type: 'whole','half','quarter','eighth','16th','32nd'
        cx: horizontal center, y: vertical centre reference, slg: staff-line-gap px"""
        rw = max(int(slg * 0.9), 6)  # rest rectangle width
        rh = max(int(slg * 0.55), 4)  # rest rectangle height

        if rest_type == "whole":
            # Filled rectangle hanging BELOW a staff line
            c.create_rectangle(cx - rw, y - rh, cx + rw, y, fill="black", outline="black")
        elif rest_type == "half":
            # Filled rectangle sitting ON TOP of a staff line
            c.create_rectangle(cx - rw, y, cx + rw, y + rh, fill="black", outline="black")
        elif rest_type == "quarter":
            # Zigzag stroke (classic quarter rest shape)
            s = slg * 0.45
            pts = [
                cx + s * 0.5,
                y - slg * 1.0,
                cx - s * 0.5,
                y - slg * 0.4,
                cx + s * 0.7,
                y + slg * 0.1,
                cx - s * 0.4,
                y + slg * 0.6,
                cx + s * 0.15,
                y + slg * 1.0,
                cx - s * 0.2,
                y + slg * 1.35,
            ]
            c.create_line(
                pts,
                fill="black",
                width=max(2, int(slg * 0.18)),
                smooth=True,
                joinstyle=tk.ROUND,
                capstyle=tk.ROUND,
            )
        elif rest_type == "eighth":
            # Diagonal slash + filled dot
            dot_r = max(2, int(slg * 0.22))
            c.create_oval(
                cx - dot_r,
                y - dot_r,
                cx + dot_r,
                y + dot_r,
                fill="black",
                outline="black",
            )
            c.create_line(
                cx + dot_r,
                y - slg * 0.1,
                cx - dot_r,
                y + slg * 0.8,
                fill="black",
                width=max(2, int(slg * 0.16)),
            )
        elif rest_type == "16th":
            # Two stacked dots + two diagonal slashes
            dot_r = max(2, int(slg * 0.20))
            for dy_dot, dy_slash in ((-slg * 0.3, 0.05), (slg * 0.35, 0.55)):
                c.create_oval(
                    cx - dot_r,
                    y + dy_dot - dot_r,
                    cx + dot_r,
                    y + dy_dot + dot_r,
                    fill="black",
                    outline="black",
                )
                c.create_line(
                    cx + dot_r,
                    y + dy_slash * slg,
                    cx - dot_r,
                    y + (dy_slash + 0.7) * slg,
                    fill="black",
                    width=max(1, int(slg * 0.14)),
                )
        elif rest_type == "32nd":
            # Three stacked dots + slashes
            dot_r = max(1, int(slg * 0.18))
            for i, (dy_dot, dy_slash) in enumerate(
                [(-slg * 0.55, -0.25), (slg * 0.05, 0.25), (slg * 0.55, 0.75)]
            ):
                c.create_oval(
                    cx - dot_r,
                    y + dy_dot - dot_r,
                    cx + dot_r,
                    y + dy_dot + dot_r,
                    fill="black",
                    outline="black",
                )
                c.create_line(
                    cx + dot_r,
                    y + dy_slash * slg,
                    cx - dot_r,
                    y + (dy_slash + 0.6) * slg,
                    fill="black",
                    width=max(1, int(slg * 0.12)),
                )

    def _draw_rests(self, c, tr, tt, bt, nm, song, mmap, ti=0):
        """Draw rests: whole-measure rests where there are no notes, and
        beat-level rest shapes for gaps between notes within a measure."""
        tpb = song.ticks_per_beat

        # Use the same score-only quantized copy as _draw_chords()
        class _TmpTrack:
            pass

        qtr = _TmpTrack()
        qtr.name = getattr(tr, "name", "track")
        qtr.notes = []
        qtr.events = getattr(tr, "events", [])  # v22q: needed by _draw_pedal
        # v22ze-37 fix: carry the pre-hand-split tag through, same as
        # _draw_chords does, so the hand-split below can trust it.
        qtr._prehand_split = getattr(tr, "_prehand_split", False)

        for n in tr.notes:
            cpy = type("QNote", (), {})()
            cpy.tick = int(n.tick)
            cpy.pitch = int(n.pitch)
            cpy.velocity = getattr(n, "velocity", 100)
            cpy.duration = int(n.duration)
            cpy.channel = getattr(n, "channel", 0)
            qtr.notes.append(cpy)

        div_map = {4: 1, 8: 2, 16: 4, 32: 8}
        score_div = div_map.get(getattr(self.app, "quantize_division", 8), 2)

        # v22ze-42 fix (was a flagged, unfinished WIP item): this used to
        # call quantize_notes(), which snaps BOTH onset AND duration onto
        # a uniform power-of-2 grid. That grid is too coarse for tuplet
        # timing (e.g. a 16th-note triplet's 160-tick spacing doesn't
        # divide evenly into a 120-tick 16th-note grid), so this produced
        # a view of note boundaries that could differ from what
        # _draw_chords actually draws by up to half a beat -- confirmed
        # directly: the same tuplet notes came out with completely
        # different start/end ticks under the two quantization schemes.
        # That's what caused a "phantom" rest to appear where a real note
        # still existed underneath (so clicking it hit a real tuplet note
        # instead of doing nothing), and could just as easily distort
        # which duration value a neighboring note appeared to have.
        # _draw_chords only ever snaps the ONSET, never duration -- match
        # that exactly here, so rest-gap detection uses the identical
        # view of note timing that's actually rendered as noteheads.
        grid = max(1, tpb // (score_div * 2))
        for n in qtr.notes:
            n.tick = int(round(n.tick / grid) * grid)

        tr = qtr

        tt_local = self._treble_top(ti, self.app.song.tracks)
        bt_local = self._bass_top(ti, self.app.song.tracks)  # None for single-staff
        slg = self.SLG

        REST_VALS = [
            (tpb * 4, "whole"),
            (tpb * 2, "half"),
            (tpb, "quarter"),
            (tpb // 2, "eighth"),
            (tpb // 4, "16th"),
            (tpb // 8, "32nd"),
        ]

        def _rest_seq(gap_ticks):
            remaining = int(gap_ticks)
            parts = []
            for val, rtype in REST_VALS:
                if val <= 0:
                    continue
                while remaining >= val:
                    parts.append((val, rtype))
                    remaining -= val
            return parts

        def _draw_rests_for_hand(hand_notes, y_top):
            """Run the whole-measure + beat-gap rest logic for ONE hand's
            notes, drawn against ONE staff's y-coordinate. v22ze-37 fix:
            this used to run ONCE for the entire track (both hands mixed
            together) using only the treble y-coordinate -- so a rest that
            conceptually belonged on the bass staff (LH silent while RH
            plays) got drawn at the wrong vertical position entirely, and
            a hand that had nothing to play could get its rests suppressed
            simply because the OTHER hand was playing something. Splitting
            by hand and calling this once per staff fixes both."""
            notes_sorted = sorted(hand_notes, key=lambda n: n.tick)
            mid_y = y_top + slg * 2

            for m_idx, ms, me, num, den, tpm in mmap:
                meas_notes = [n for n in notes_sorted if ms <= n.tick < me]

                # ── Whole-measure rest ─────────────────────────────────
                if not meas_notes:
                    mx = (self._tick_to_x(ms) + self._tick_to_x(me)) // 2
                    ry = y_top + slg
                    self._draw_rest_shape(c, "whole", mx, ry, slg)
                    continue

                # ── Beat-level gaps within the measure ──────────────────
                cursor = ms
                events = []
                for n in meas_notes:
                    events.append((n.tick, +1))
                    events.append((min(n.tick + n.duration, me), -1))
                events.sort()

                active = 0
                for tick, delta in events:
                    if active == 0 and tick > cursor:
                        gap = tick - cursor
                        if gap >= tpb // 8:
                            parts = _rest_seq(gap)
                            gx = self._tick_to_x(cursor)
                            for val, rtype in parts:
                                pw = val * self._px_per_tick
                                mid = gx + pw / 2
                                if rtype == "whole":
                                    ry = y_top + slg
                                elif rtype == "half":
                                    ry = y_top + slg * 2
                                else:
                                    ry = mid_y
                                self._draw_rest_shape(c, rtype, mid, ry, slg)
                                gx += pw
                    active += delta
                    if active == 0:
                        cursor = tick

                # Gap after last sounding note
                if active == 0 and cursor < me:
                    gap = me - cursor
                    if gap >= tpb // 8:
                        parts = _rest_seq(gap)
                        gx = self._tick_to_x(cursor)
                        for val, rtype in parts:
                            pw = val * self._px_per_tick
                            mid = gx + pw / 2
                            if rtype == "whole":
                                ry = y_top + slg
                            elif rtype == "half":
                                ry = y_top + slg * 2
                            else:
                                ry = mid_y
                            self._draw_rest_shape(c, rtype, mid, ry, slg)
                            gx += pw

        if bt_local is None:
            # Single-staff track -- no hand split needed, same as before.
            _draw_rests_for_hand(tr.notes, tt_local)
        else:
            # v22ze-37: split by hand the same way _draw_chords does, so
            # each staff's rests are computed and drawn independently.
            if getattr(tr, "_prehand_split", False):
                rh_notes = [n for n in tr.notes if n.channel == 0]
                lh_notes = [n for n in tr.notes if n.channel == 1]
            else:
                split = self._split_var.get()
                if split <= 0:
                    split = _find_split_pitch_for_track(
                        tr.notes,
                        prefer_lh_octaves=getattr(self.app.song, "prefer_lh_octaves", True),
                    )
                rh_notes = [n for n in tr.notes if n.pitch >= split]
                lh_notes = [n for n in tr.notes if n.pitch < split]
            _draw_rests_for_hand(rh_notes, tt_local)
            _draw_rests_for_hand(lh_notes, bt_local)

    # ── click editing ─────────────────────────────────────────────────────────
    def _cxy(self, e):
        return self.canvas.canvasx(e.x), self.canvas.canvasy(e.y)

    def _display_tick(self, tick):
        """Map a note's raw (unsnapped) tick to the same onset-snapped grid
        position _draw_chords() actually draws it at.

        v22ze-50 fix: every click-based hit test in this section (rest
        deletion, accidental, articulation, right-click delete) was
        comparing the click's derived tick against notes' RAW ticks from
        the real Track -- but the score renders notes at a SNAPPED
        position (_draw_chords's onset-snap grid; see the comment there:
        "Duration is NEVER changed", only onset ticks are). Any note not
        already exactly on-grid (e.g. from a live performance, or a file
        with natural micro-timing) is drawn in one place but hit-tested
        in another, slightly different place -- this is exactly the
        "same concept implemented independently in two places, silently
        drift apart" pattern flagged in the last handoff as this
        project's single largest source of bugs, and it explains reports
        like "I right-clicked what looks like a rest and a nearby note
        got deleted instead." Using the identical grid formula here means
        a click is always tested against exactly what's on screen.
        """
        tpb = self.app.song.ticks_per_beat
        div_map = {4: 1, 8: 2, 16: 4, 32: 8}
        score_div = div_map.get(getattr(self.app, "quantize_division", 8), 2)
        grid = max(1, tpb // (score_div * 2))
        return int(round(tick / grid) * grid)

    def _xy_to_pitch(self, cx, cy):
        tracks = self.app.song.tracks
        for ti, tr in enumerate(tracks):
            tt = self._treble_top(ti, tracks)
            bt = self._bass_top(ti, tracks)  # None for single-staff
            grand = bt is not None
            bot = (bt + self.SH + self.BPAD) if grand else (tt + self.SH + 16)
            if not (self._track_yo(ti, tracks) <= cy <= bot):
                continue
            step = self.SLG / 2
            # v22ze-36 fix: this treble-branch constant (-3) didn't match
            # _sp_to_y_treble's actual rendering formula ((tt+SH)-(pos-2)*
            # step) -- a drift of 5 staff positions, consistently placing
            # every added/clicked note about a 6th too low. Two separate
            # implementations of the same staff-position math again; the
            # bass branch below was already correct (its -10 matches
            # _sp_to_y_bass exactly), only this one had drifted.
            if not grand or cy <= tt + self.SH + self.BGAP / 2:
                pos = round(2 + (tt + self.SH - cy) / step)
            else:
                pos = round(-10 + (bt + self.SH - cy) / step)
            return ti, self._pos_to_pitch(pos)
        return None, None

    def _pos_to_pitch(self, pos):
        total_d = pos + 35
        oct_ = total_d // 7
        step = total_d % 7
        semi = [0, 2, 4, 5, 7, 9, 11][max(0, min(6, step))]
        return max(0, min(127, oct_ * 12 + semi))

    def _dur_to_ticks(self, name, tpb):
        return {
            "whole": tpb * 4,
            "half": tpb * 2,
            "quarter": tpb,
            "eighth": tpb // 2,
            "16th": tpb // 4,
        }.get(name, tpb)

    def _on_click(self, event):
        cx, cy = self._cxy(event)
        if cx < self.LM:
            return
        # v22ze-35: which tab is active in the editing toolbar determines
        # what a canvas click does. "measures" has no click behavior of
        # its own -- it's handled entirely through the right-click menu,
        # same as Delete/Cut measure already were.
        if self._active_tool == "note_rest":
            self._click_note_rest(cx, cy)
        elif self._active_tool == "accidental":
            self._click_accidental(cx, cy)
        elif self._active_tool == "dynamics":
            self._click_dynamics(cx, cy)
        elif self._active_tool == "articulation":
            self._click_articulation(cx, cy)

    def _click_note_rest(self, cx, cy):
        ti, pitch = self._xy_to_pitch(cx, cy)
        if ti is None:
            return
        tr = self.app.song.tracks[ti]
        tpb = self.app.song.ticks_per_beat
        dur = self._dur_to_ticks(self._dur_var.get(), tpb)
        # Snap the inserted tick to the nearest grid position (same grid as
        # the score display) so notes land on beat/sub-beat positions rather
        # than at an arbitrary sub-pixel offset.
        raw_tick = self._x_to_tick(cx)
        grid = max(1, tpb // 4)  # 16th-note grid for insertion
        tick = round(raw_tick / grid) * grid

        if self._entry_mode_var.get() == "rest":
            # v22ze-39 fix: this used to clear every note overlapping a
            # span equal to the TOOLBAR's selected duration, regardless
            # of what's actually at the click point. If the selected
            # duration was longer than the actual note or gap there
            # (e.g. "quarter" selected while clicking an existing eighth
            # rest), the span reached past the gap into the NEXT note
            # and deleted that instead -- confirmed as the cause of
            # "clicked the rest, a following note got deleted." A
            # precise point hit-test is both the fix and the more
            # intuitive interaction: turn into a rest whichever single
            # note (if any) is actually sounding at the exact clicked
            # tick, regardless of the toolbar's duration setting.
            hit = [
                n
                for n in tr.notes
                if self._display_tick(n.tick) <= tick < self._display_tick(n.tick) + n.duration
            ]
            if not hit:
                return  # already silent here -- nothing to do, no undo step
            for n in hit:
                tr.notes.remove(n)
                self.app._push_undo(
                    NoteEditAction(
                        description=f"Insert rest (cleared pitch {n.pitch})",
                        track_index=ti,
                        before_note=n,
                        after_note=None,
                    )
                )
        else:
            new_note = MidiNote(tick, pitch, 80, dur, tr.channel)
            tr.notes.append(new_note)
            tr.notes.sort(key=lambda n: n.tick)
            self.app._push_undo(
                NoteEditAction(
                    description=f"Add note (pitch {pitch})",
                    track_index=ti,
                    before_note=None,
                    after_note=new_note,
                )
            )

        self.app.song.modified = True
        self.app._update_title()
        self._draw()

    def _click_accidental(self, cx, cy):
        """Click an existing note to change its accidental. The note's
        PITCH is what actually changes -- accidentals aren't a separate
        stored field anywhere else in this app either; they're always
        derived from pitch + key signature at render/export time (see
        pitch_to_staff), so this stays consistent with that."""
        ti, click_pitch = self._xy_to_pitch(cx, cy)
        if ti is None:
            return
        tr = self.app.song.tracks[ti]
        tick = self._x_to_tick(cx)
        tpb = self.app.song.ticks_per_beat
        best, bestd = None, 9999
        threshold = int(tpb * 1.5 + tpb // 4 * 3)  # same generous hit-test as delete-note
        for i, n in enumerate(tr.notes):
            d = abs(self._display_tick(n.tick) - tick) + abs(n.pitch - click_pitch) * tpb // 8
            if d < bestd:
                best, bestd = i, d
        if best is None or bestd >= threshold:
            return
        import copy as _copy

        old_note = tr.notes[best]
        _use_flats = _song_uses_flats(self.app.song)
        _, cur_acc = note_staff_pos(old_note, _use_flats)
        natural_pitch = old_note.pitch - cur_acc  # strip whatever accidental it has now
        delta = {
            "double_flat": -2,
            "flat": -1,
            "natural": 0,
            "sharp": 1,
            "double_sharp": 2,
        }[self._accidental_var.get()]
        new_pitch = max(0, min(127, natural_pitch + delta))
        new_spelling = self._accidental_var.get()
        # v22ze-51 fix: previously this only checked whether the PITCH
        # changed, so re-clicking the same accidental on an
        # already-correct note was (rightly) a no-op -- but it also
        # meant there was no way to force a courtesy accidental (e.g. an
        # explicit natural sign shown even though the pitch is already a
        # plain natural). Comparing spelling too lets that through while
        # still treating a genuine repeat click as a no-op.
        if new_pitch == old_note.pitch and getattr(old_note, "spelling", "") == new_spelling:
            return  # already exactly this accidental -- no-op, no undo step
        new_note = _copy.copy(old_note)
        new_note.pitch = new_pitch
        # v22ze-51 fix: pin the spelling the user actually asked for, so
        # future renders (and further edits) read the same letter/
        # accidental back off this note instead of re-deriving it from
        # the song's key signature -- which is what caused a note to
        # visibly jump to a different line/space after applying an
        # accidental (see note_staff_pos's docstring for the full story).
        new_note.spelling = new_spelling
        tr.notes[best] = new_note
        self.app.song.modified = True
        self.app._update_title()
        self.app._push_undo(
            NoteEditAction(
                description=f"Change accidental (pitch {old_note.pitch}\u2192{new_pitch})",
                track_index=ti,
                before_note=old_note,
                after_note=new_note,
            )
        )
        self._draw()

    def _click_dynamics(self, cx, cy):
        """Place a dynamics marking (pp, mf, ff, etc.) at the clicked
        point in time. Stored as a Track event (same mechanism as pedal
        marks), not attached to a specific note -- dynamics are a
        time-point marking in real notation, not a note property."""
        ti, _ = self._xy_to_pitch(cx, cy)
        if ti is None:
            return
        tr = self.app.song.tracks[ti]
        tick = self._x_to_tick(cx)
        new_event = MidiEvent(tick, ("dynamic", self._dynamic_var.get()))
        tr.markings.append(new_event)
        tr.markings.sort(key=lambda e: e.tick)
        self.app.song.modified = True
        self.app._update_title()
        self.app._push_undo(
            EventEditAction(
                description=f"Add dynamic marking ({self._dynamic_var.get()})",
                track_index=ti,
                before_event=None,
                after_event=new_event,
            )
        )
        self._draw()

    def _click_articulation(self, cx, cy):
        """Click an existing note to toggle the selected articulation on
        it. Stored on MidiNote.articulation (a field that already existed
        for exactly this purpose)."""
        ti, click_pitch = self._xy_to_pitch(cx, cy)
        if ti is None:
            return
        tr = self.app.song.tracks[ti]
        tick = self._x_to_tick(cx)
        tpb = self.app.song.ticks_per_beat
        best, bestd = None, 9999
        threshold = int(tpb * 1.5 + tpb // 4 * 3)
        for i, n in enumerate(tr.notes):
            d = abs(self._display_tick(n.tick) - tick) + abs(n.pitch - click_pitch) * tpb // 8
            if d < bestd:
                best, bestd = i, d
        if best is None or bestd >= threshold:
            return
        import copy as _copy

        old_note = tr.notes[best]
        chosen = self._articulation_var.get()
        # Toggle: clicking the same articulation again clears it back to none.
        new_articulation = "" if old_note.articulation == chosen else chosen
        new_note = _copy.copy(old_note)
        new_note.articulation = new_articulation
        tr.notes[best] = new_note
        self.app.song.modified = True
        self.app._update_title()
        label = new_articulation if new_articulation else "none"
        self.app._push_undo(
            NoteEditAction(
                description=f"Set articulation ({label})",
                track_index=ti,
                before_note=old_note,
                after_note=new_note,
            )
        )
        self._draw()

    def _on_right(self, event):
        cx, cy = self._cxy(event)
        ti, pitch = self._xy_to_pitch(cx, cy)
        tick = self._x_to_tick(cx)
        tpb = self.app.song.ticks_per_beat
        tpm = self.app.song.ticks_per_measure()
        meas = int(tick // tpm)

        # v22ze-56 fix: was tk.Menu — see TkPopupMenu's docstring. This
        # right-click menu goes through _popup_menu_safe below, which
        # already knows how to post a TkPopupMenu correctly.
        menu = TkPopupMenu(self, tearoff=0)

        # v22ze-50 fix: when the Rest tool is active, right-click must use
        # the SAME precise point hit-test _click_note_rest's rest branch
        # uses (v22ze-39) -- not the generous "nearest note within 1.5
        # beats" search below, which is meant for Accidental/Articulation
        # clicking and is exactly why right-clicking empty space where a
        # rest is shown could offer to delete an unrelated nearby note.
        # If nothing is actually sounding at the exact clicked tick, no
        # delete option is offered at all -- there's genuinely nothing
        # there to delete.
        if (
            ti is not None
            and self._active_tool == "note_rest"
            and self._entry_mode_var.get() == "rest"
        ):
            tr = self.app.song.tracks[ti]
            precise_hit = [
                n
                for n in tr.notes
                if self._display_tick(n.tick) <= tick < self._display_tick(n.tick) + n.duration
            ]
            if precise_hit:
                n = precise_hit[0]
                idx = tr.notes.index(n)
                menu.add_command(
                    label=f"Delete note here (leaves a rest)  " f"(pitch {n.pitch}, meas {meas+1})",
                    command=lambda i=idx, t=tr, tix=ti: self._del_note(t, i, tix),
                )
            menu.add_separator()
            menu.add_command(
                label=f"Insert measure before {meas+1}",
                command=lambda m=meas: self._insert_measure(m, after=False),
            )
            menu.add_command(
                label=f"Insert measure after {meas+1}",
                command=lambda m=meas: self._insert_measure(m, after=True),
            )
            menu.add_command(
                label=f"Delete measure {meas+1}  (clear all tracks)",
                command=lambda m=meas: self._delete_measure(m, close_gap=False),
            )
            menu.add_command(
                label=f"Cut measure {meas+1}  (delete & shift left)",
                command=lambda m=meas: self._delete_measure(m, close_gap=True),
            )
            _popup_menu_safe(menu, event.x_root, event.y_root)
            return

        # Delete nearest note — hit-test radius scales with zoom so it's
        # easier to click a note at low zoom without missing it.
        if ti is not None:
            tr = self.app.song.tracks[ti]
            best, bestd = None, 9999
            # Generous threshold: 1.5 beats in tick distance or 3 semitones
            threshold = int(tpb * 1.5 + tpb // 4 * 3)
            for i, n in enumerate(tr.notes):
                d = abs(self._display_tick(n.tick) - tick) + abs(n.pitch - pitch) * tpb // 8
                if d < bestd:
                    best, bestd = i, d
            if best is not None and bestd < threshold:
                n = tr.notes[best]
                # v22ze-44 fix: right-click used to ALWAYS say "Delete
                # note" no matter which editing tool was active, which
                # was confusing in Accidental/Articulation mode --
                # right-click is the natural thing to try there too, but
                # it only ever deleted. Surface the current tool's actual
                # action as the primary item first, reusing the exact
                # same logic the left-click handlers use (so both click
                # types stay perfectly consistent), with Delete note kept
                # as an always-available secondary option.
                if self._active_tool == "accidental":
                    acc_label = {
                        "double_flat": "\U0001d12b",
                        "flat": "\u266d",
                        "natural": "\u266e",
                        "sharp": "\u266f",
                        "double_sharp": "\U0001d12a",
                    }.get(self._accidental_var.get(), "?")
                    menu.add_command(
                        label=f"Apply {acc_label} to this note "
                        f"(pitch {n.pitch}, meas {meas+1})",
                        command=lambda cx=cx, cy=cy: self._click_accidental(cx, cy),
                    )
                elif self._active_tool == "articulation":
                    art = self._articulation_var.get()
                    menu.add_command(
                        label=f"Toggle {art} on this note " f"(pitch {n.pitch}, meas {meas+1})",
                        command=lambda cx=cx, cy=cy: self._click_articulation(cx, cy),
                    )
                menu.add_command(
                    label=f"Delete note  (pitch {n.pitch}, meas {meas+1})",
                    command=lambda i=best, t=tr, tix=ti: self._del_note(t, i, tix),
                )

        # Insert / Delete / Cut measure (all tracks)
        menu.add_command(
            label=f"Insert measure before {meas+1}",
            command=lambda m=meas: self._insert_measure(m, after=False),
        )
        menu.add_command(
            label=f"Insert measure after {meas+1}",
            command=lambda m=meas: self._insert_measure(m, after=True),
        )
        menu.add_command(
            label=f"Delete measure {meas+1}  (clear all tracks)",
            command=lambda m=meas: self._delete_measure(m, close_gap=False),
        )
        menu.add_command(
            label=f"Cut measure {meas+1}  (delete & shift left)",
            command=lambda m=meas: self._delete_measure(m, close_gap=True),
        )

        # v22ze-44 fix: this was missing the grab_release() that the
        # other popup menu in this app already does correctly (see
        # below). Without it, the menu's grab isn't cleanly released,
        # which is the likely cause of the menu appearing to "stick"
        # across virtual desktops / requiring an extra click elsewhere
        # to dismiss after switching windows -- proper grab release is
        # the standard fix for exactly this class of Tk popup-menu
        # window-manager quirk.
        # v22ze-55: routed through _popup_menu_safe, which both releases
        # the grab AND arms a FocusOut safety net — see its docstring.
        _popup_menu_safe(menu, event.x_root, event.y_root)

    def _del_note(self, tr, idx, track_index):
        deleted_note = tr.notes.pop(idx)
        self.app.song.modified = True
        self.app._update_title()
        # v22ze-34: per-edit undo -- each deleted note is its own step.
        self.app._push_undo(
            NoteEditAction(
                description=f"Delete note (pitch {deleted_note.pitch})",
                track_index=track_index,
                before_note=deleted_note,
                after_note=None,
            )
        )
        self._draw()

    def _delete_measure(self, meas_idx, close_gap=False):
        """Remove all notes in measure meas_idx from every track.
        If close_gap=True, shift all subsequent notes left by one measure."""
        import copy as _copy

        song = self.app.song
        tpm = song.ticks_per_measure()
        ms = meas_idx * tpm
        me = ms + tpm

        # v22ze-34: this touches every track at once (and can shift
        # tick positions with close_gap), so it uses the same bulk
        # snapshot pattern as Quantize/Cleanup rather than the
        # lightweight per-note NoteEditAction -- still one undo step,
        # just a heavier one, appropriate for a bulk operation.
        before_tracks = _copy.deepcopy(song.tracks)
        before_map = _copy.deepcopy(song.rationalized_measure_map)

        for tr in song.tracks:
            # Remove notes that start in this measure
            tr.notes = [n for n in tr.notes if not (ms <= n.tick < me)]
            # Also clip notes that start before and extend into the measure
            for n in tr.notes:
                if n.tick < ms and n.tick + n.duration > ms:
                    n.duration = ms - n.tick  # truncate at measure boundary
            if close_gap:
                # Shift everything after the deleted measure one measure left
                for n in tr.notes:
                    if n.tick >= me:
                        n.tick -= tpm
            # Remove events in this measure too
            tr.events = [ev for ev in tr.events if not (ms <= ev.tick < me)]
            if close_gap:
                for ev in tr.events:
                    if ev.tick >= me:
                        ev.tick -= tpm

        song.modified = True
        self.app._update_title()
        self.app._push_undo(
            RationalizationAction(
                description=(
                    f"Cut measure {meas_idx + 1}" if close_gap else f"Delete measure {meas_idx + 1}"
                ),
                before_tracks=before_tracks,
                after_tracks=_copy.deepcopy(song.tracks),
                before_map=before_map,
                after_map=_copy.deepcopy(song.rationalized_measure_map),
            )
        )
        self._draw()

    def _insert_measure(self, meas_idx, after=False):
        """Insert one empty measure before (or after) meas_idx, in every
        track. Everything at or past the insertion point shifts right by
        one measure's worth of ticks -- the exact inverse of Cut measure."""
        import copy as _copy

        song = self.app.song
        tpm = song.ticks_per_measure()
        cut_point = (meas_idx + 1) * tpm if after else meas_idx * tpm

        before_tracks = _copy.deepcopy(song.tracks)
        before_map = _copy.deepcopy(song.rationalized_measure_map)

        for tr in song.tracks:
            for n in tr.notes:
                if n.tick >= cut_point:
                    n.tick += tpm
            for ev in tr.events:
                if ev.tick >= cut_point:
                    ev.tick += tpm

        song.modified = True
        self.app._update_title()
        self.app._push_undo(
            RationalizationAction(
                description=f"Insert measure {'after' if after else 'before'} {meas_idx + 1}",
                before_tracks=before_tracks,
                after_tracks=_copy.deepcopy(song.tracks),
                before_map=before_map,
                after_map=_copy.deepcopy(song.rationalized_measure_map),
            )
        )
        self._draw()

    # ── Mini transport handlers (delegate to main app) ───────────────────────
    def _t_rewind(self):
        self.app._rewind_to_start()

    def _t_stop(self):
        self.app._stop()
        self._sync_transport_btns()

    def _t_play_pause(self):
        self.app._toggle_play()
        self._sync_transport_btns()

    def _t_rec(self):
        self.app._toggle_record()
        self._sync_transport_btns()

    def _sync_transport_btns(self):
        # Keep mini buttons consistent with main transport state.
        if not self.winfo_exists():
            return
        playing = self.app.transport.is_playing()
        recording = self.app.transport.is_recording()
        self._score_play_btn.configure(text="⏸ Pause" if playing else "▶ Play")
        self._score_rec_btn.configure(
            bg="#880000" if recording else "#0f3320",
            fg="#ff4444" if recording else "#3fb950",
        )

    # ── cursor update called from main thread ──────────────────────────────────
    def update_cursor(self, tick):
        if not self.winfo_exists():
            return
        c = self.canvas
        song = self.app.song

        # During recording, check if notes were added since last draw
        total_notes = sum(len(tr.notes) for tr in song.tracks)
        if total_notes != self._last_note_count:
            self._score_dirty = True
            self._last_note_count = total_notes

        # Full redraw when content changed — then place cursor on top
        if self._score_dirty:
            self._draw(cursor_tick=tick)
            return

        # Fast path: just move the cursor line
        tpm = song.ticks_per_measure()
        nm = max(4, math.ceil(song.total_ticks() / tpm) + 1)
        total_w = self.LM + self._fe() + nm * self._mw() + 40
        # v22ze-61 fix: defensively clamp the tick used for drawing to
        # the CURRENT song's own range. Playback position is reported
        # from a background-adjacent source (Transport, via a marshaled
        # callback) and can, under some state-desync scenarios this
        # session couldn't fully pin down live (e.g. around switching
        # between differently-sized files), end up reporting a tick
        # beyond what this song's own total_ticks() covers. Left
        # unclamped, that draws the red cursor line past the score's own
        # rendered content -- "the cursor runs off the screen" -- even
        # though _tick_to_x/_scroll_to are individually self-consistent
        # (see _scroll_to's docstring). Clamping here can't fix whatever
        # is feeding a bad tick value, but it does guarantee the cursor
        # itself always stays within the bounds of what's actually drawn.
        clamped_tick = max(0, min(tick, song.total_ticks()))
        cx = self._tick_to_x(clamped_tick)
        existing = c.find_withtag("playhead")
        if existing:
            try:
                sr = c.cget("scrollregion").split()
                total_h = int(sr[3]) if len(sr) >= 4 else 2000
            except Exception:
                total_h = 2000
            c.coords(existing[0], cx, 0, cx, total_h)
        else:
            # Playhead tag was lost (e.g. after a resize) — restore it
            total_h = self._track_yo(len(song.tracks), song.tracks) + 20
            c.create_line(
                cx,
                0,
                cx,
                total_h,
                fill="#dd2222",
                width=2,
                dash=(5, 3),
                tags="playhead",
            )
        self._scroll_to(cx, total_w)


# ─────────────────────────────────────────────────────────────────────────────
# Main Application
# ─────────────────────────────────────────────────────────────────────────────


# ── Hover tooltip utility (v22t) ─────────────────────────────────────────────
class ToolTip:
    """Lightweight hover tooltip for any tkinter widget.

    Usage:  ToolTip(some_button, "Explanation of what this does.")

    Shows a small dark popup near the widget after a short hover delay,
    hides on mouse-leave or click.  Added because the calibration →
    rationalize → cleanup → bake workflow accumulated enough controls that
    users need in-place explanations rather than hunting through menus.
    """

    def __init__(self, widget, text, delay=500, wraplength=280):
        self.widget = widget
        self.text = text
        self.delay = delay
        self.wraplength = wraplength
        self.tip_window = None
        self._after_id = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def _schedule(self, event=None):
        self._unschedule()
        try:
            self._after_id = self.widget.after(self.delay, self._show)
        except Exception:
            pass

    def _unschedule(self):
        if self._after_id:
            try:
                self.widget.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None

    def _show(self):
        if self.tip_window or not self.text:
            return
        try:
            x = self.widget.winfo_rootx() + 12
            y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6
            tw = tk.Toplevel(self.widget)
            self.tip_window = tw
            tw.wm_overrideredirect(True)
            tw.wm_geometry(f"+{x}+{y}")
            try:
                tw.attributes("-topmost", True)
            except Exception:
                pass
            tk.Label(
                tw,
                text=self.text,
                justify=tk.LEFT,
                bg="#1a1a1a",
                fg="#e8e8e0",
                relief=tk.SOLID,
                borderwidth=1,
                font=("TkDefaultFont", 8),
                wraplength=self.wraplength,
                padx=6,
                pady=4,
            ).pack()
        except Exception:
            self.tip_window = None

    def _hide(self, event=None):
        self._unschedule()
        if self.tip_window:
            try:
                self.tip_window.destroy()
            except Exception:
                pass
            self.tip_window = None


def _tt(widget, text, delay=500):
    """Shorthand: attach a ToolTip to widget, return widget for chaining."""
    ToolTip(widget, text, delay=delay)
    return widget


# ── Rationalization undo/redo support ────────────────────────────────────────
import copy as _copy


class RationalizationAction:
    """Memento for a single rationalization edit (undo/redo)."""

    __slots__ = (
        "description",
        "before_tracks",
        "after_tracks",
        "before_map",
        "after_map",
    )

    def __init__(self, description, before_tracks, after_tracks, before_map=None, after_map=None):
        self.description = description
        self.before_tracks = before_tracks  # deep-copy of track list before
        self.after_tracks = after_tracks  # deep-copy of track list after
        # v22ze-33 fix: song.rationalized_measure_map is a CACHE that can
        # be set independently of tracks (e.g. by an actual Rationalize
        # action) and stays valid across later, unrelated edits (e.g.
        # Quantize after Rationalize). The old undo/redo code either left
        # this cache untouched (RationalizationAction branch -- stale
        # map after undoing the action that created it) or blindly reset
        # it to None (CalibrationAction branch -- correct for that case,
        # but would have been WRONG here: undoing e.g. a Quantize that
        # happened after a Rationalize shouldn't throw away the still-
        # valid rationalized grid). Snapshotting it alongside tracks,
        # the same way, restores exactly what was actually there at
        # each point instead of guessing.
        self.before_map = before_map
        self.after_map = after_map


@dataclass
class NoteEditAction:
    """Memento for a single-note add/delete edit (undo/redo).

    Lightweight compared to RationalizationAction -- stores ONE note
    object, not a deep-copied snapshot of the whole song -- so per-click
    editing (add note, delete note) stays cheap even on a large multi-
    track score, matching the "each edit is its own undo step" design.
    Exactly one of before_note/after_note is None:
      before_note=None -- this was an ADD    (undo removes after_note)
      after_note=None  -- this was a DELETE  (undo re-inserts before_note)
    Notes are matched by object identity (is), not by tick/pitch, so
    this is unambiguous even when several notes share the same tick
    and pitch (e.g. a doubled note in different voices).
    """

    description: str
    track_index: int
    before_note: object  # MidiNote, or None if this action was an ADD
    after_note: object  # MidiNote, or None if this action was a DELETE


@dataclass
class EventEditAction:
    """Memento for a single track-event add/delete (undo/redo).

    Same lightweight, identity-based pattern as NoteEditAction, but for
    Track.events rather than Track.notes -- used for dynamics markings
    (and anything else event-based, e.g. pedal marks) that aren't
    attached to one specific note.
    """

    description: str
    track_index: int
    before_event: object  # MidiEvent, or None if this action was an ADD
    after_event: object  # MidiEvent, or None if this action was a DELETE


@dataclass
class CalibrationAction:
    """Memento for a BPM or time-signature change (undo/redo).

    Stored on the same _undo_stack as RationalizationAction; _undo() and
    _redo() check the type to know which fields to restore.
    """

    description: str
    before_tempo: int  # microseconds-per-beat
    after_tempo: int
    before_ts_num: int  # time signature numerator
    before_ts_den: int
    after_ts_num: int
    after_ts_den: int
class MidisoftStudio:
    APP_NAME = APP_FULL_NAME

    def visible_tracks(self):
        """Return [(orig_idx, track, display_name), ...] for tracks with notes.

        v22v: tracks with zero notes (typically a file's tempo/meta-only
        track, or a leftover unused track) are excluded from every UI list
        — track panel, mixer — matching the empty-track suppression the
        score view has had since v22a.  Previously each of these three
        places (score view, track list, mixer) had its own independent
        "for i, tr in enumerate(song.tracks)" loop; the track list and
        mixer had no filter at all, so a file whose note-bearing tracks
        happened to be named "Track 2"/"Track 3" (because track 1 in the
        source file was a meta-only track never even imported) displayed
        those confusing original numbers with an empty "Track 3" cluttering
        the list, while the score view alone quietly did the right thing.

        Tracks whose name matches the generic auto-generated pattern
        "Track N" are renumbered sequentially among the VISIBLE tracks
        (so the first one showing notes is always "Track 1", regardless
        of what number it happened to have in the source file).  Tracks
        with a meaningful custom name (e.g. "Piano right", "Rachmaninoff")
        are left completely untouched — only the generic placeholder
        pattern is ever renamed.

        Callers must use orig_idx (not the position in this returned list)
        for any mutation of self.song.tracks[orig_idx] — display order and
        storage order are related but not identical once tracks are
        reordered or renamed elsewhere.
        """
        import re as _vt_re
        result = []
        seq = 0
        for i, tr in enumerate(self.song.tracks):
            if not tr.notes and not getattr(tr, 'always_show', False):
                continue
            seq += 1
            if _vt_re.match(r'^Track\s+\d+$', tr.name or ''):
                display_name = f"Track {seq}"
            else:
                display_name = tr.name
            result.append((i, tr, display_name))
        return result

    def __init__(self,root:tk.Tk):
        self.quantize_division = 0   # Off — user must explicitly choose a grid
        self.grace_cleanup_ms = 40
        self.midi_thru_enabled = tk.BooleanVar(value=True)
        self.midi_thru_volume  = tk.IntVar(value=100)   # 0-127, matches track volume scale
        # v22ze-58 fix: _thru_cb (see _start_midi_monitor) reads these two
        # values, but it runs on the MIDI dispatcher's background thread —
        # calling .get() on a Tk variable from any thread but the main one
        # is the same class of cross-thread Tkinter bug fixed for playback
        # ticks above. Cache plain-Python copies here, kept in sync via a
        # trace that fires on the main thread whenever the real Tk
        # variable changes (i.e. whenever the user actually toggles the
        # UI control), so the background thread never touches a Tk
        # variable at all.
        self._midi_thru_enabled_val = True
        self._midi_thru_volume_val  = 100
        def _sync_thru_enabled(*_a):
            self._midi_thru_enabled_val = self.midi_thru_enabled.get()
        def _sync_thru_volume(*_a):
            self._midi_thru_volume_val = self.midi_thru_volume.get()
        self.midi_thru_enabled.trace_add('write', _sync_thru_enabled)
        self.midi_thru_volume.trace_add('write', _sync_thru_volume)
        self.root=root; self.song=Song(); self.transport=Transport(self.song)
        self._original_song = None   # preserved when in rationalized mode
        self._is_rationalized = False
        self._undo_stack = []         # list of RationalizationAction
        self._redo_stack = []
        self._rationalize_dlg = None  # reference to open dialog (if any)
        # Score Setup panel state
        self._score_setup_dlg       = None   # reference to open ScoreSetup panel
        self._selected_measure_idx  = None   # measure index last clicked in strip
        self._accepted_measures     = set()  # measure indices the user has confirmed
        self._measure_bpm_overrides = {}     # measure_idx → float BPM override
        self._sel_from = tk.IntVar(value=1)
        self._sel_to   = tk.IntVar(value=4)
        self._score_view: ScoreView|None=None; self._open_windows=[]; self._rec_armed=0
        self._overview_rolling=False; self._overview_row_heights={}; self._overview_drag=None
        root.title(APP_TITLE)
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        win_w, win_h = min(1280, sw - 60), min(960, sh - 80)
        root.geometry(f"{win_w}x{win_h}")
        root.configure(bg="#0d1117")
        self._build_menu(); self._build_toolbar(); self._build_track_area()
        self._build_status(); self._update_title(); self._update_status()
        root.protocol("WM_DELETE_WINDOW",self._on_quit)
        root.bind("<Control-r>", lambda e: self._rationalize_score())
        root.bind("<Control-z>", lambda e: self._undo())
        root.bind("<Control-y>", lambda e: self._redo())
        self._shutting_down = False
        self._tick_job = None
        if len(sys.argv)>1 and os.path.isfile(sys.argv[1]): self._load_file(sys.argv[1])
        self._tick_loop()
        self._start_midi_monitor()
        _maybe_show_no_synth_dialog(self.root)

    # ── MIDI input monitor (always-on thru when NOT recording) ───────────────
    def _start_midi_monitor(self):
        """Echo MIDI input to output so keyboard is always audible.
        Uses the single dispatcher thread — no port contention with recorder."""
        if not midi_io.MIDI_IN_OK or not midi_io.MIDI_OUT_OK:
            return
        def _thru_cb(msg):
            # Skip thru while recording — the recorder's _rec_cb handles echo
            if self.transport.is_recording():
                return
            # v22ze-58 fix: read the plain-Python cached copies (see
            # __init__), not the Tk variables directly — this callback
            # runs on the MIDI dispatcher's background thread.
            if not self._midi_thru_enabled_val:
                return
            try:
                if msg.type == "note_on" and msg.velocity > 0:
                    scale = self._midi_thru_volume_val / 127.0
                    msg = msg.copy(velocity=max(1, min(127, int(msg.velocity * scale))))
                _send(msg)
            except Exception: pass
        midi_input_subscribe(_thru_cb)   # runs for lifetime of app

    # ── tick loop ─────────────────────────────────────────────────────────────
    def _tick_loop(self):
        # Prune dead windows so the list doesn't grow forever
        self._open_windows = [w for w in self._open_windows
                              if _winfo_exists(w)]

        playing = self.transport.is_playing()
        if playing:
            # Interpolate the display tick from wall-clock time rather than
            # polling self.transport.position_ticks directly.  position_ticks
            # is updated by the playback thread at coarse intervals; reading it
            # every 80 ms causes visible cursor lag at fast tempos (170 BPM+).
            # Instead: record (position_ticks, wall_time) at playback start,
            # then compute display_tick = start_tick + elapsed_sec * ticks_per_sec.
            # This gives a smooth, accurate cursor at any tempo.
            try:
                tpb         = self.song.ticks_per_beat
                tempo_us    = self.song.tempo
                ticks_per_s = 1_000_000 / tempo_us * tpb
                pos_now  = self.transport.position_ticks
                wall_now = time.perf_counter()
                prev = getattr(self, '_cursor_anchor', None)
                if prev is None or pos_now != prev[0]:
                    self._cursor_anchor = (pos_now, wall_now)
                    tick = pos_now
                else:
                    anchor_tick, anchor_wall = prev
                    elapsed = wall_now - anchor_wall
                    tick = int(anchor_tick + elapsed * ticks_per_s)
                    # Cap strictly at pos_now — never project ahead.
                    # Forward projection caused cumulative drift to the right.
                    tick = min(tick, pos_now)
            except Exception:
                tick = self.transport.position_ticks
                self._cursor_anchor = None

            if self._score_view and _winfo_exists(self._score_view):
                self._score_view.update_cursor(tick)
                self._score_view._sync_transport_btns()
            tpm=self.song.ticks_per_measure()
            meas=tick//tpm+1; beat=(tick%tpm)//self.song.ticks_per_beat+1
            self._pos_var.set(f"Meas {meas}  Beat {beat}")
            # Move overview playhead cheaply (canvas item move, not full redraw)
            try: self._update_overview_playhead(tick)
            except: pass
            # Update active keys in any open piano roll windows
            active = set()
            tpb = self.song.ticks_per_beat
            for tr in self.song.tracks:
                if tr.mute: continue
                for n in tr.notes:
                    if n.tick <= tick < n.tick + n.duration:
                        active.add(n.pitch)
            for w in self._open_windows:
                try:
                    if isinstance(w, PianoRollView) and _winfo_exists(w):
                        w.update_active_notes(active)
                        w.update_playhead(tick)
                except: pass
        else:
            self._cursor_anchor = None   # reset anchor when stopped

        if not getattr(self, "_shutting_down", False):
            self._tick_job = self.root.after(40, self._tick_loop)   # 40ms = ~25 fps

    def _update_overview_playhead(self, tick):
        # Move the overview playhead line without redrawing everything.
        c = self.overview
        W = c.winfo_width()
        if W < 10: return
        total = max(self.song.total_ticks(), 1)
        if self._overview_rolling:
            tpm = self.song.ticks_per_measure(); win = tpm * 4
            t0  = max(0, tick - int(win * 0.75))
            cx  = (tick - t0) / win * W
        else:
            cx = (tick / total) * W
        tot_h = self._overview_total_h()
        existing = c.find_withtag("ov_playhead")
        if existing:
            c.coords(existing[0], cx, 0, cx, tot_h)
        else:
            # First time: do a full draw to establish all track rows,
            # then add the playhead on top
            self._draw_overview()
            c.create_line(cx, 0, cx, tot_h,
                          fill="#ff3333", width=2, dash=(4,3), tags="ov_playhead")

    # ── Menu ──────────────────────────────────────────────────────────────────
    def _build_menu(self):
        # v22ze-56 fix: replaced the native root.config(menu=...) menu bar
        # (and every tk.Menu cascade under it) with TkMenuBar/TkPopupMenu —
        # ordinary, fully WM-managed widgets — because the v22ze-55 FocusOut
        # safety net below was NOT enough to fix the menu-bar sticking-
        # across-virtual-desktops bug on the user's real KDE/KWin desktop
        # (confirmed: the splash fix worked, this one didn't). See
        # TkPopupMenu's docstring for the full story. TkMenuBar/TkPopupMenu
        # manage their own dismiss lifecycle, so the old FocusOut-based
        # safety net for the native menu bar is no longer needed here.
        mb = TkMenuBar(self.root)
        mb.pack(side="top", fill="x")
        fm=TkPopupMenu(mb,tearoff=0); mb.add_cascade(label="File",menu=fm)
        fm.add_command(label="New\tCtrl+N",command=self._new,accelerator="Ctrl+N")
        fm.add_command(label="Open…\tCtrl+O",command=self._open,accelerator="Ctrl+O")
        fm.add_command(label="Close Piece",command=self._close)
        fm.add_separator()
        fm.add_command(label="Save\tCtrl+S",command=self._save,accelerator="Ctrl+S")
        fm.add_command(label="Save As…",command=self._save_as)
        fm.add_separator()
        fm.add_command(label="Export MIDI…",command=self._save_as)
        fm.add_command(label="Save as .musicxml (standard)…",
                       command=self._export_musicxml,
                       tooltip="MuseScore/Sibelius/Finale can read this")
        fm.add_command(label="Open in MuseScore (via MIDI)…",command=self._open_in_musescore)
        fm.add_command(label="Export LilyPond (.ly)…",command=self._export_ly)
        fm.add_command(label="Print Score (via LilyPond)…",command=self._print_score)
        fm.add_separator()
        fm.add_command(label="Undo Correction\tCtrl+Z",command=self._undo,
                       accelerator="Ctrl+Z")
        fm.add_command(label="Redo Correction\tCtrl+Y",command=self._redo,
                       accelerator="Ctrl+Y")
        fm.add_separator()
        fm.add_command(label="Close Program",command=self._on_quit)
        em=TkPopupMenu(mb,tearoff=0); mb.add_cascade(label="Edit",menu=em)
        em.add_command(label="Add Track",command=self._add_track)
        em.add_command(label="Delete Track",command=self._del_track)
        em.add_separator()
        em.add_command(label="Combine Tracks…",command=self._combine_tracks)
        em.add_command(label="Separate Channels…",command=self._separate_channels)
        em.add_separator()
        em.add_command(label="Separate Hands…",command=self._separate_hands)
        vm=TkPopupMenu(mb,tearoff=0); mb.add_cascade(label="View",menu=vm)
        vm.add_command(label="Score View\tCtrl+1",command=self._open_score_view,accelerator="Ctrl+1")
        vm.add_command(label="Piano Roll\tCtrl+2",command=self._open_piano_roll,accelerator="Ctrl+2")
        vm.add_command(label="MIDI List\tCtrl+3",command=self._open_list_view,accelerator="Ctrl+3")
        vm.add_command(label="Mixer",command=self._open_mixer)
        sm=TkPopupMenu(mb,tearoff=0); mb.add_cascade(label="Setup",menu=sm)
        sm.add_command(label="MIDI I/O Info",command=self._midi_info)
        sm.add_command(label="MIDI Output Device…",command=self._choose_midi_output)
        hm=TkPopupMenu(mb,tearoff=0); mb.add_cascade(label="Help",menu=hm)

        nm=TkPopupMenu(mb,tearoff=0)
        mb.add_cascade(label="Song Settings", menu=nm)

        if not hasattr(self, "quantize_division"):
            self.quantize_division = 0

        self._quantize_var = tk.IntVar(value=self.quantize_division)

        def _on_quantize_change(*_):
            self.quantize_division = self._quantize_var.get()
            # Immediately redraw score so the new grid is visible
            try:
                sv = self._score_view
                if sv is not None and sv.winfo_exists():
                    sv._draw()
            except Exception:
                pass
        self._quantize_var.trace_add('write', _on_quantize_change)

        qm = TkPopupMenu(nm, tearoff=0)
        nm.add_cascade(label="Quantization", menu=qm)

        qm.add_radiobutton(label="Off", value=0, variable=self._quantize_var,
                           command=lambda: setattr(self, "quantize_division", 0))
        qm.add_separator()

        qm.add_radiobutton(label="Quarter Notes (1/4)", value=4, variable=self._quantize_var,
                           command=lambda: setattr(self, "quantize_division", 4))
        qm.add_radiobutton(label="Eighth Notes (1/8)", value=8, variable=self._quantize_var,
                           command=lambda: setattr(self, "quantize_division", 8))
        qm.add_radiobutton(label="Sixteenth Notes (1/16)", value=16, variable=self._quantize_var,
                           command=lambda: setattr(self, "quantize_division", 16))
        qm.add_radiobutton(label="Thirty-Second Notes (1/32)", value=32, variable=self._quantize_var,
                           command=lambda: setattr(self, "quantize_division", 32))

        if not hasattr(self, "grace_cleanup_ms"):
            self.grace_cleanup_ms = 40

        self._grace_var = tk.IntVar(value=self.grace_cleanup_ms)

        gm = TkPopupMenu(nm, tearoff=0)
        nm.add_cascade(label="Grace Cleanup", menu=gm)

        for _ms in (0,20,40,60,80):
            _label = "Off" if _ms == 0 else f"{_ms} ms"
            gm.add_radiobutton(
                label=_label,
                value=_ms,
                variable=self._grace_var,
                command=lambda ms=_ms: setattr(self, "grace_cleanup_ms", ms)
            )

        nm.add_separator()
        nm.add_command(label="Quantize…\tCtrl+Q", command=lambda: QuantizeDlg(self.root, self),
                       accelerator="Ctrl+Q")
        nm.add_command(label="Quantize Armed Track", command=self._quantize_armed_track)
        nm.add_separator()
        nm.add_command(label="Score Setup…\tCtrl+G", command=self._open_score_setup,
                       accelerator="Ctrl+G")
        nm.add_command(label="Song Elements…", command=self._song_settings)
        nm.add_command(label="Set Key Signature…", command=self._set_key_signature)
        nm.add_command(label="Rationalize Score…\tCtrl+R", command=self._rationalize_score,
                       accelerator="Ctrl+R")
        nm.add_separator()
        nm.add_command(label="About Song Settings...", command=lambda: messagebox.showinfo(
            "Song Settings",
            f"Quantization: {'Off' if not self.quantize_division else '1/'+str(self.quantize_division)}\n"
            f"Grace Cleanup: {self.grace_cleanup_ms} ms"))
        hm.add_command(label="About…",command=self._about)
        binds=[("<Control-n>",self._new),("<Control-o>",self._open),("<Control-s>",self._save),
               ("<Control-1>",self._open_score_view),("<Control-2>",self._open_piano_roll),
               ("<Control-3>",self._open_list_view),("<space>",self._toggle_play),
               ("<Home>",self._rewind_to_start),
               ("<Left>",lambda e=None:self._seek(-1)),("<Right>",lambda e=None:self._seek(1)),
               ("<Control-q>",lambda: QuantizeDlg(self.root, self)),
               ("<Control-g>",lambda e=None: self._open_score_setup())]
        for key,fn in binds: self.root.bind(key,lambda e,f=fn:f())

    # ── Toolbar ───────────────────────────────────────────────────────────────
    def _build_toolbar(self):
        tb=tk.Frame(self.root,bg="#161b22",pady=3); tb.pack(fill=tk.X)
        bc=dict(bg="#21262d",fg="white",activebackground="#30363d",activeforeground="white",
                relief=tk.FLAT,padx=7,pady=4,font=("TkDefaultFont",10))
        tk.Button(tb,text="⏮",command=self._rewind_to_start,
                  bg="#21262d",fg="white",activebackground="#30363d",activeforeground="white",
                  relief=tk.FLAT,padx=7,pady=4,font=("TkDefaultFont",14)
                  ).pack(side=tk.LEFT,padx=1)
        tk.Button(tb,text="◀◀",command=lambda:self._seek(-1),**bc).pack(side=tk.LEFT,padx=1)
        self.play_btn=tk.Button(tb,text="▶  Play",command=self._toggle_play,**bc)
        self.play_btn.pack(side=tk.LEFT,padx=1)
        tk.Button(tb,text="⏹  Stop",command=self._stop,**bc).pack(side=tk.LEFT,padx=1)
        tk.Button(tb,text="▶▶",command=lambda:self._seek(+1),**bc).pack(side=tk.LEFT,padx=1)
        self.rec_btn=tk.Button(tb,text="⏺  Rec",command=self._toggle_record,
                               bg="#0f3320",fg="#3fb950",activebackground="#1a4a2a",
                               activeforeground="#56d364",relief=tk.FLAT,padx=7,pady=4,
                               font=("TkDefaultFont",10))
        self.rec_btn.pack(side=tk.LEFT,padx=1)
        self._metro_on=False
        self.transport.set_metronome(False)
        self._metro_btn=tk.Button(tb,text="Click: OFF",command=self._toggle_metronome,
                                  bg="#21262d",fg="#666666",activebackground="#30363d",
                                  activeforeground="white",relief=tk.FLAT,padx=7,pady=4,
                                  font=("TkDefaultFont",10))
        self._metro_btn.pack(side=tk.LEFT,padx=1)
        _tt(self._metro_btn,
            "Toggle a metronome click during playback — useful for "
            "checking the cursor and score are tracking the beat "
            "correctly at the current tempo.")
        tk.Frame(tb,width=8,bg="#161b22").pack(side=tk.LEFT)
        tk.Button(tb,text="+ Track",command=self._add_track,**bc).pack(side=tk.LEFT,padx=1)
        tk.Button(tb,text="🎼 Score",command=self._open_score_view,**bc).pack(side=tk.LEFT,padx=1)
        tk.Button(tb,text="🎹 Roll",command=self._open_piano_roll,**bc).pack(side=tk.LEFT,padx=1)
        tk.Button(tb,text="📋 List",command=self._open_list_view,**bc).pack(side=tk.LEFT,padx=1)
        tk.Button(tb,text="🎚 Mixer",command=self._open_mixer,**bc).pack(side=tk.LEFT,padx=1)
        tk.Frame(tb,width=8,bg="#161b22").pack(side=tk.LEFT)
        tk.Label(tb,text="BPM:",bg="#161b22",fg="white").pack(side=tk.LEFT)
        self.bpm_var=tk.IntVar(value=self.song.bpm)
        sp=tk.Spinbox(tb,from_=20,to=300,textvariable=self.bpm_var,width=5,
                      bg="#21262d",fg="white",buttonbackground="#21262d",command=self._apply_bpm)
        sp.pack(side=tk.LEFT,padx=2); sp.bind("<Return>",lambda e:self._apply_bpm())
        self._pos_var=tk.StringVar(value="Meas 1  Beat 1")
        tk.Label(tb,textvariable=self._pos_var,bg="#161b22",fg="#58a6ff",
                 font=("TkFixedFont",9),width=14).pack(side=tk.LEFT,padx=4)
        # ── Play Selection controls ──────────────────────────────────────
        tk.Frame(tb,width=10,bg="#161b22").pack(side=tk.LEFT)
        tk.Label(tb,text="Sel:",bg="#161b22",fg="#8b949e",
                 font=("TkDefaultFont",9)).pack(side=tk.LEFT)
        _tt(tk.Spinbox(tb,from_=1,to=9999,textvariable=self._sel_from,width=4,
                   bg="#21262d",fg="white",buttonbackground="#21262d"),
            "First measure to play with ▶ Sel."
            ).pack(side=tk.LEFT,padx=1)
        tk.Label(tb,text="–",bg="#161b22",fg="#8b949e").pack(side=tk.LEFT)
        _tt(tk.Spinbox(tb,from_=1,to=9999,textvariable=self._sel_to,width=4,
                   bg="#21262d",fg="white",buttonbackground="#21262d"),
            "Last measure to play with ▶ Sel."
            ).pack(side=tk.LEFT,padx=1)
        _tt(tk.Button(tb,text="▶ Sel",command=self._play_selection,
                  bg="#21262d",fg="#58a6ff",activebackground="#30363d",
                  activeforeground="#79c0ff",relief=tk.FLAT,padx=6,pady=4,
                  font=("TkDefaultFont",10)),
            "Play only the measure range set by the two Sel spinboxes, "
            "instead of the whole piece."
            ).pack(side=tk.LEFT,padx=1)


    # ═══════════════════════════════════════════════════════════════════════════
    # RATIONALIZATION  —  Priority 1 implementation
    # ═══════════════════════════════════════════════════════════════════════════

    def _set_rationalized_song(self, song):
        """Switch the app into or out of rationalized mode.

        Passing a Song switches the app to rationalized mode:
          • self._original_song is preserved
          • self.song is swapped to the rationalized song
          • Transport is updated to play the new song
          • UI is refreshed

        Passing None discards the rationalization and reverts to original.
        """
        import copy as _copy
        if song is not None:
            # Entering rationalized mode
            if not self._is_rationalized:
                # First time: save the original
                self._original_song = self.song
            else:
                # Re-rationalizing: keep the already-saved original
                pass
            self.song = song
            self.transport.song = song
            self._is_rationalized = True
            self._undo_stack.clear()
            self._redo_stack.clear()
        else:
            # Discarding — revert to original
            if self._original_song is not None:
                self.song = self._original_song
                self.transport.song = self._original_song
            self._original_song = None
            self._is_rationalized = False
            self._undo_stack.clear()
            self._redo_stack.clear()

        self._update_status()
        self._update_title()
        self._refresh_views()
        # Refresh Score Setup panel cleanup gate if it is open
        if (self._score_setup_dlg is not None
                and self._score_setup_dlg.winfo_exists()):
            try:
                self._score_setup_dlg._refresh_panel()
            except Exception:
                pass   # panel may be partially constructed

    def _refresh_views(self):
        """Redraw all open score/roll/list views after song data changes."""
        if self._score_view and self._score_view.winfo_exists():
            try: self._score_view._draw()
            except Exception: pass
        for w in list(self._open_windows):
            if hasattr(w, '_draw') and w.winfo_exists():
                try: w._draw()
                except Exception: pass
        self._refresh_track_list()
        self._draw_overview()

    # ── Undo / Redo ────────────────────────────────────────────────────────────

    def _push_undo(self, action: RationalizationAction):
        """Push a RationalizationAction onto the undo stack."""
        self._undo_stack.append(action)
        self._redo_stack.clear()
        self._update_status()

    def _undo(self, *_):
        """Undo the most recent edit (quantize, rationalize, calibration, or manual edit)."""
        if not self._undo_stack:
            return
        import copy as _copy
        action = self._undo_stack.pop()

        if isinstance(action, CalibrationAction):
            # Restore song tempo and time signature
            redo_action = CalibrationAction(
                description=action.description,
                before_tempo=action.after_tempo,
                after_tempo=action.before_tempo,
                before_ts_num=action.after_ts_num,
                before_ts_den=action.after_ts_den,
                after_ts_num=action.before_ts_num,
                after_ts_den=action.before_ts_den,
            )
            self._redo_stack.append(redo_action)
            self.song.tempo      = action.before_tempo
            self.song.set_time_signature(action.before_ts_num, action.before_ts_den)
            self.song.rationalized_measure_map = None   # v22l: force grid rebuild
        elif isinstance(action, NoteEditAction):
            # v22ze-34: lightweight per-note undo (add/delete/modify a
            # single note) -- see NoteEditAction docstring. Undo always
            # removes whatever this action's "after" state was and
            # restores whatever its "before" state was; redo does the
            # opposite. Notes are matched by object identity, not
            # tick/pitch, so this is unambiguous even for doubled notes.
            tr = self.song.tracks[action.track_index]
            redo_action = NoteEditAction(
                description=action.description,
                track_index=action.track_index,
                before_note=action.before_note,
                after_note=action.after_note,
            )
            self._redo_stack.append(redo_action)
            if action.after_note is not None:
                tr.notes = [n for n in tr.notes if n is not action.after_note]
            if action.before_note is not None:
                tr.notes.append(action.before_note)
                tr.notes.sort(key=lambda n: n.tick)
        elif isinstance(action, EventEditAction):
            # Same identity-based pattern as NoteEditAction, for
            # Track.markings (dynamics, etc.) instead of notes.
            tr = self.song.tracks[action.track_index]
            redo_action = EventEditAction(
                description=action.description,
                track_index=action.track_index,
                before_event=action.before_event,
                after_event=action.after_event,
            )
            self._redo_stack.append(redo_action)
            if action.after_event is not None:
                tr.markings = [e for e in tr.markings if e is not action.after_event]
            if action.before_event is not None:
                tr.markings.append(action.before_event)
                tr.markings.sort(key=lambda e: e.tick)
        else:
            redo_action = RationalizationAction(
                description=action.description,
                before_tracks=_copy.deepcopy(self.song.tracks),
                after_tracks=action.after_tracks,
                before_map=_copy.deepcopy(self.song.rationalized_measure_map),
                after_map=action.after_map,
            )
            self._redo_stack.append(redo_action)
            self.song.tracks = _copy.deepcopy(action.before_tracks)
            self.song.rationalized_measure_map = _copy.deepcopy(action.before_map)

        self.transport.song = self.song
        self._update_status()
        self._refresh_views()
        # Refresh Score Setup panel undo label if open
        if self._score_setup_dlg and self._score_setup_dlg.winfo_exists():
            self._score_setup_dlg._refresh_undo_labels()

    def _redo(self, *_):
        """Redo the most recently undone edit."""
        if not self._redo_stack:
            return
        import copy as _copy
        action = self._redo_stack.pop()

        if isinstance(action, CalibrationAction):
            undo_action = CalibrationAction(
                description=action.description,
                before_tempo=action.after_tempo,
                after_tempo=action.before_tempo,
                before_ts_num=action.after_ts_num,
                before_ts_den=action.after_ts_den,
                after_ts_num=action.before_ts_num,
                after_ts_den=action.before_ts_den,
            )
            self._undo_stack.append(undo_action)
            self.song.tempo      = action.after_tempo
            self.song.set_time_signature(action.after_ts_num, action.after_ts_den)
            self.song.rationalized_measure_map = None   # v22l: force grid rebuild
        elif isinstance(action, NoteEditAction):
            tr = self.song.tracks[action.track_index]
            undo_action = NoteEditAction(
                description=action.description,
                track_index=action.track_index,
                before_note=action.before_note,
                after_note=action.after_note,
            )
            self._undo_stack.append(undo_action)
            if action.before_note is not None:
                tr.notes = [n for n in tr.notes if n is not action.before_note]
            if action.after_note is not None:
                tr.notes.append(action.after_note)
                tr.notes.sort(key=lambda n: n.tick)
        elif isinstance(action, EventEditAction):
            tr = self.song.tracks[action.track_index]
            undo_action = EventEditAction(
                description=action.description,
                track_index=action.track_index,
                before_event=action.before_event,
                after_event=action.after_event,
            )
            self._undo_stack.append(undo_action)
            if action.before_event is not None:
                tr.markings = [e for e in tr.markings if e is not action.before_event]
            if action.after_event is not None:
                tr.markings.append(action.after_event)
                tr.markings.sort(key=lambda e: e.tick)
        else:
            undo_action = RationalizationAction(
                description=action.description,
                before_tracks=_copy.deepcopy(self.song.tracks),
                after_tracks=action.after_tracks,
                before_map=_copy.deepcopy(self.song.rationalized_measure_map),
                after_map=action.after_map,
            )
            self._undo_stack.append(undo_action)
            self.song.tracks = _copy.deepcopy(action.after_tracks)
            self.song.rationalized_measure_map = _copy.deepcopy(action.after_map)

        self.transport.song = self.song
        self._update_status()
        self._refresh_views()
        if self._score_setup_dlg and self._score_setup_dlg.winfo_exists():
            self._score_setup_dlg._refresh_undo_labels()

    # ── Play Selection ────────────────────────────────────────────────────────

    def _play_selection(self):
        """Play only the measures specified by the Sel: spinboxes."""
        mmap = self.song.get_measure_map()
        if not mmap:
            return
        m0 = max(0, self._sel_from.get() - 1)
        m1 = min(len(mmap) - 1, self._sel_to.get() - 1)
        if m0 > m1:
            m0, m1 = m1, m0
        start_tick = mmap[m0][1]
        end_tick   = mmap[m1][2]

        was_playing = self.transport.is_playing()
        self.transport.stop()
        self.transport.position_ticks = start_tick
        self.transport.position_sec   = self.transport._t2s(start_tick)
        self.transport._play_until_tick = end_tick

        def _on_tick(tick):
            self.transport.position_ticks = tick
            # v22ze-58 fix: same cross-thread Tkinter bug as the main
            # _play() path (see its detailed comment) -- this callback
            # runs on Transport's background playback thread, so no Tk
            # calls may happen directly here. Marshal onto the main
            # thread via root.after(0, ...) instead.
            if not getattr(self, '_tick_update_pending', False):
                self._tick_update_pending = True
                def _do_update(t=tick):
                    self._tick_update_pending = False
                    try:
                        if self._score_view and self._score_view.winfo_exists():
                            self._score_view._ui_tick_update(t)
                    except Exception:
                        pass
                self.root.after(0, _do_update)

        self._on_tick_cb = _on_tick
        self.play_btn.configure(text="⏸  Pause")
        self.transport.play(on_tick=_on_tick)

        # Auto-clear end_tick after playback finishes so normal Play works
        def _clear_end():
            if not self.transport.is_playing():
                self.transport._play_until_tick = None
                self.play_btn.configure(text="▶  Play")
            else:
                self.root.after(200, _clear_end)
        self.root.after(200, _clear_end)

    # ── Score Setup Panel ────────────────────────────────────────────────────

    def _apply_global_bpm(self, new_bpm, source="manual"):
        """Change the song's global BPM, push to undo stack, refresh views."""
        import mido as _mido_bpm
        old_tempo  = self.song.tempo
        old_ts_num = self.song.time_sig_num
        old_ts_den = self.song.time_sig_den
        new_tempo  = int(60_000_000 / max(1, new_bpm))
        if new_tempo == old_tempo:
            return
        self._push_undo(CalibrationAction(
            description=f"BPM {round(60_000_000/old_tempo)} → {round(new_bpm)} ({source})",
            before_tempo=old_tempo,  after_tempo=new_tempo,
            before_ts_num=old_ts_num, before_ts_den=old_ts_den,
            after_ts_num=old_ts_num,  after_ts_den=old_ts_den,
        ))
        self.song.tempo = new_tempo
        self.song.modified = True
        self._update_title()
        self._refresh_views()

    def _apply_global_timesig(self, new_num, new_den, source="manual"):
        """Change the song's time signature, push to undo stack, refresh views."""
        old_tempo  = self.song.tempo
        old_ts_num = self.song.time_sig_num
        old_ts_den = self.song.time_sig_den
        if new_num == old_ts_num and new_den == old_ts_den:
            return
        self._push_undo(CalibrationAction(
            description=f"Time sig {old_ts_num}/{old_ts_den} → {new_num}/{new_den} ({source})",
            before_tempo=old_tempo,  after_tempo=old_tempo,
            before_ts_num=old_ts_num, before_ts_den=old_ts_den,
            after_ts_num=new_num,     after_ts_den=new_den,
        ))
        self.song.set_time_signature(new_num, new_den)
        # v22l: clear any cached rationalized measure map so get_measure_map()
        # falls back to build_measure_map() which now uses the new sig_changes[0].
        # Without this, the cached 6/4 (or whatever) rationalized_measure_map
        # is returned by get_measure_map() regardless of what set_time_signature()
        # just wrote, and the score redraws with the old grid.
        # The baked note data is preserved — only the cached grid is discarded.
        # The measure strip will flag any measures that now overflow or underflow
        # under the new grid, guiding the user to re-rationalize or run cleanup.
        self.song.rationalized_measure_map = None
        self._update_title()
        self._refresh_views()
        # v22k: if the Rationalize dialog is open, push the new meter into
        # its override spinboxes and uncheck Auto-detect so the user sees
        # immediately that their Score Setup choice will be used.
        if (self._rationalize_dlg is not None
                and self._rationalize_dlg.winfo_exists()):
            try:
                self._rationalize_dlg._detect_ts_var.set(False)
                self._rationalize_dlg._ts_num_var.set(new_num)
                self._rationalize_dlg._ts_den_var.set(new_den)
            except Exception:
                pass   # dialog may be partially constructed

    def _auto_detect_calibration(self):
        """Run IOI detection and return a suggestion dict (never commits)."""
        try:
            return self.song.detect_calibration()
        except Exception as exc:
            return {'bpm': None, 'confidence': 0.0, 'note': str(exc)}

    def _cleanup_measure(self, measure_idx):
        """Apply Option-D barline clamping + re-quantize to a single measure."""
        import copy as _cup
        mmap = self.song.get_measure_map()
        if measure_idx >= len(mmap):
            return
        _mi, ms, me, num, den, tpm = mmap[measure_idx]
        tpb  = self.song.ticks_per_beat
        grid = tpb // 8   # eighth-note grid as default cleanup resolution

        before_tracks = _cup.deepcopy(self.song.tracks)
        before_map    = _cup.deepcopy(self.song.rationalized_measure_map)

        for tr in self.song.tracks:
            for n in tr.notes:
                if ms <= n.tick < me:
                    # Clamp onset to measure
                    if n.tick < ms:
                        n.tick = ms
                    # Snap onset to grid within measure
                    rel    = n.tick - ms
                    snapped = round(rel / grid) * grid
                    snapped = max(0, min(int(tpm) - grid, snapped))
                    n.tick  = ms + snapped
                    # Clamp duration so note ends at or before barline
                    if n.tick + n.duration > me:
                        n.duration = me - n.tick
                    if n.duration <= 0:
                        n.duration = grid

        self._push_undo(RationalizationAction(
            description=f"Cleanup measure {measure_idx + 1}",
            before_tracks=before_tracks,
            after_tracks=_cup.deepcopy(self.song.tracks),
            before_map=before_map,
            after_map=_cup.deepcopy(self.song.rationalized_measure_map),
        ))
        self._accepted_measures.add(measure_idx)
        self.song.modified = True
        self._refresh_views()

    def _cleanup_all_measures(self):
        """Apply Option-D cleanup to every measure in the song."""
        import copy as _cup
        mmap = self.song.get_measure_map()
        if not mmap:
            return
        before_tracks = _cup.deepcopy(self.song.tracks)
        before_map    = _cup.deepcopy(self.song.rationalized_measure_map)
        tpb  = self.song.ticks_per_beat
        grid = tpb // 8

        for _mi, ms, me, num, den, tpm in mmap:
            for tr in self.song.tracks:
                for n in tr.notes:
                    if ms <= n.tick < me:
                        if n.tick < ms:
                            n.tick = ms
                        rel     = n.tick - ms
                        snapped = round(rel / grid) * grid
                        snapped = max(0, min(int(tpm) - grid, snapped))
                        n.tick  = ms + snapped
                        if n.tick + n.duration > me:
                            n.duration = me - n.tick
                        if n.duration <= 0:
                            n.duration = grid
            self._accepted_measures.add(_mi)

        self._push_undo(RationalizationAction(
            description="Cleanup all measures",
            before_tracks=before_tracks,
            after_tracks=_cup.deepcopy(self.song.tracks),
            before_map=before_map,
            after_map=_cup.deepcopy(self.song.rationalized_measure_map),
        ))
        self.song.modified = True
        self._refresh_views()

    def _set_key_signature(self):
        """Open a dialog to view/override the song's key signature.

        Auto-detection (Krumhansl-Schmuckler, see detect_key_signature())
        is offered as a suggestion only, never applied silently -- key-
        finding from note content is inherently a best-guess heuristic
        (modulation within a piece, heavy chromaticism, or non-tonal
        writing can all fool it), so the user always confirms or picks
        their own key from the full list rather than having one applied
        automatically on load.
        """
        BG    = "#0d1117"
        FG    = "#f0f6fc"
        MUTED = "#8b949e"
        BLUE  = "#58a6ff"
        ENTRY = "#161b22"
        bb    = dict(bg="#21262d", fg=FG, activebackground="#30363d",
                     activeforeground=FG, relief=tk.FLAT, padx=8, pady=3)

        dlg = tk.Toplevel(self.root)
        dlg.title("Key Signature")
        dlg.configure(bg=BG)
        dlg.resizable(False, False)
        # v22ze: transient()+lift() is the standard, safe way to keep a
        # dialog above its parent -- a prior version of this also
        # toggled -topmost on a timer, which turned out to be a real
        # hazard (see _clear_topmost_safe's docstring for the full
        # story: an intermittent, timing-dependent freeze). Dropped in
        # favor of just the well-tested pattern.
        dlg.transient(self.root)
        dlg.lift()
        dlg.focus_force()

        current = getattr(self.song, 'key_sig', 'C') or 'C'
        tk.Label(dlg, text="Key Signature", bg=BG, fg=FG,
                 font=("Segoe UI", 11, "bold")).pack(padx=16, pady=(14, 4), anchor="w")
        tk.Label(dlg, text=f"Current: {current}", bg=BG, fg=MUTED).pack(padx=16, anchor="w")

        all_notes = [n for tr in self.song.tracks for n in tr.notes]
        suggestion_var = tk.StringVar(value="(not checked yet)")
        if all_notes:
            sugg_key, sugg_conf = detect_key_signature(self.song)
            conf_word = "confident" if sugg_conf > 0.15 else "uncertain — piece may modulate or be non-tonal"
            suggestion_var.set(f"{sugg_key}  ({conf_word}, margin={sugg_conf:.2f})")
        else:
            sugg_key = current

        tk.Label(dlg, text="Suggested (auto-detected):", bg=BG, fg=MUTED).pack(
            padx=16, pady=(10, 0), anchor="w")
        tk.Label(dlg, textvariable=suggestion_var, bg=BG, fg=BLUE).pack(padx=16, anchor="w")

        # Deduplicated, major-then-minor key list for the dropdown
        all_keys = list(dict.fromkeys(_KEY_STR_MAJOR + _KEY_STR_MINOR))

        pick_var = tk.StringVar(value=current if current in all_keys else sugg_key)
        row = tk.Frame(dlg, bg=BG)
        row.pack(padx=16, pady=(10, 4), fill="x")
        tk.Label(row, text="Set to:", bg=BG, fg=FG).pack(side=tk.LEFT)
        combo = ttk.Combobox(row, textvariable=pick_var, values=all_keys,
                              width=8, state="readonly")
        combo.pack(side=tk.LEFT, padx=(8, 0))

        def _use_suggestion():
            pick_var.set(sugg_key)
        tk.Button(dlg, text="Use Suggested", command=_use_suggestion, **bb).pack(
            padx=16, pady=(2, 10), anchor="w")

        def _apply():
            self.song.key_sig = pick_var.get()
            self.modified = True
            self._update_title()
            try:
                if self._score_view and self._score_view.winfo_exists():
                    self._score_view._draw(cursor_tick=0)
            except Exception:
                pass
            dlg.destroy()

        btn_row = tk.Frame(dlg, bg=BG)
        btn_row.pack(padx=16, pady=(4, 14), anchor="e")
        tk.Button(btn_row, text="Cancel", command=dlg.destroy, **bb).pack(side=tk.LEFT, padx=(0, 6))
        tk.Button(btn_row, text="Apply", command=_apply, **bb).pack(side=tk.LEFT)

    def _open_score_setup(self):
        """Open (or raise) the Score Setup floating panel."""
        # Only one instance
        if self._score_setup_dlg and self._score_setup_dlg.winfo_exists():
            self._score_setup_dlg.lift()
            if self._selected_measure_idx is not None:
                self._score_setup_dlg._populate_measure_detail(
                    self._selected_measure_idx)
            return

        BG    = "#0d1117"
        FG    = "#f0f6fc"
        MUTED = "#8b949e"
        BLUE  = "#58a6ff"
        ENTRY = "#161b22"
        SEP   = "#30363d"
        sb    = dict(bg=ENTRY, fg=FG, buttonbackground="#30363d",
                     relief=tk.FLAT, width=5)
        bb    = dict(bg="#21262d", fg=FG, activebackground="#30363d",
                     activeforeground=FG, relief=tk.FLAT, padx=8, pady=3)

        dlg = tk.Toplevel(self.root)
        dlg.title("Score Setup")
        dlg.configure(bg=BG)
        # v22ze-57 fix: this used to just make the window resizable, with
        # no way to reach content once the window was shrunk below its
        # natural height — a prior session flagged the full fix (wrap the
        # content in a scrollable canvas) as too large to do safely in
        # the same pass as everything else in this ~450-line function.
        # Doing it now: dlg itself holds only the Canvas+Scrollbar
        # (via _make_scrollable), and `content` — the actual parent every
        # section below builds into — is the scrollable inner frame. A
        # window shrunk below its content now shows a vertical scrollbar
        # on the right edge instead of silently clipping controls with
        # no way back to them.
        dlg.resizable(True, True)
        dlg.lift()
        dlg.focus_force()
        self._score_setup_dlg = dlg
        content = _make_scrollable(dlg, bg=BG)

        def _lbl(parent, text, fg=FG, font=None, **kw):
            kw.setdefault('anchor', 'w')
            f = font or ("TkDefaultFont", 9)
            return tk.Label(parent, text=text, bg=BG, fg=fg, font=f, **kw)

        def _sep(parent):
            tk.Frame(parent, bg=SEP, height=1).pack(fill=tk.X, padx=10, pady=6)

        # ── Header ────────────────────────────────────────────────────────
        _lbl(content, "🎼  Score Setup",
             fg=BLUE, font=("TkDefaultFont", 12, "bold"),
             anchor="center").pack(pady=(14, 2))
        _lbl(content,
             "Calibrate BPM and time signature so measures contain "
             "the correct number of beats, then apply cleanup.",
             fg=MUTED, font=("TkDefaultFont", 9),
             justify=tk.CENTER, anchor="center").pack(padx=20, pady=(0, 8))

        # ══ SECTION A — Global calibration ═══════════════════════════════
        _sep(content)
        _lbl(content, "  Global Calibration",
             fg=BLUE, font=("TkDefaultFont", 10, "bold")).pack(fill=tk.X)

        gfrm = tk.Frame(content, bg=BG, padx=14, pady=4)
        gfrm.pack(fill=tk.X)

        # Time signature row
        ts_num_var = tk.IntVar(value=self.song.time_sig_num)
        ts_den_var = tk.IntVar(value=self.song.time_sig_den)

        ts_row = tk.Frame(gfrm, bg=BG)
        ts_row.pack(fill=tk.X, pady=3)
        _lbl(ts_row, "Time Signature:", width=18).pack(side=tk.LEFT)
        tk.Spinbox(ts_row, from_=1, to=16, textvariable=ts_num_var,                   **sb).pack(side=tk.LEFT, padx=(0, 2))
        _lbl(ts_row, "/").pack(side=tk.LEFT)
        den_menu = tk.OptionMenu(ts_row, ts_den_var, 1, 2, 4, 8, 16)
        den_menu.configure(bg=ENTRY, fg=FG, activebackground="#30363d",
                           relief=tk.FLAT, highlightthickness=0)
        den_menu["menu"].configure(bg=ENTRY, fg=FG)
        den_menu.pack(side=tk.LEFT, padx=(2, 8))
        _tt(tk.Button(ts_row, text="Apply",
                  command=lambda: self._apply_global_timesig(
                      ts_num_var.get(), ts_den_var.get()),
                  **bb),
            "Redraw the whole score's measure grid at this time signature. "
            "Existing notes keep their tick positions — measures that no "
            "longer contain the right number of beats will be flagged in "
            "the strip above the score.").pack(side=tk.LEFT)

        # Key signature row -- lives here too (not just the Set Key
        # Signature… menu item) since this is where a user calibrating
        # the score naturally looks for it, alongside time signature/BPM.
        key_row = tk.Frame(gfrm, bg=BG)
        key_row.pack(fill=tk.X, pady=3)
        _lbl(key_row, "Key Signature:", width=18).pack(side=tk.LEFT)
        key_display_var = tk.StringVar(
            value=getattr(self.song, 'key_sig', 'C') or 'C')

        def _refresh_key_display():
            key_display_var.set(getattr(self.song, 'key_sig', 'C') or 'C')

        _lbl(key_row, "", textvariable=key_display_var, fg=BLUE,
             font=("TkDefaultFont", 9, "bold"), width=6).pack(side=tk.LEFT)
        _tt(tk.Button(key_row, text="Change…",
                  command=lambda: (self._set_key_signature(), _refresh_key_display()),
                  **bb),
            "View the auto-detected suggestion and set the piece's key "
            "signature -- affects both this app's own on-screen notation "
            "and LilyPond export.").pack(side=tk.LEFT, padx=(4, 0))

        # BPM row
        bpm_var = tk.IntVar(value=round(self.song.bpm))
        bpm_row = tk.Frame(gfrm, bg=BG)
        bpm_row.pack(fill=tk.X, pady=3)
        _lbl(bpm_row, "BPM:", width=18).pack(side=tk.LEFT)
        tk.Spinbox(bpm_row, from_=20, to=300, textvariable=bpm_var,
                   **sb).pack(side=tk.LEFT, padx=(0, 6))
        bpm_scale = tk.Scale(bpm_row, from_=20, to=300, orient=tk.HORIZONTAL,
                             variable=bpm_var, length=120, showvalue=False,
                             bg=BG, fg=FG, troughcolor=ENTRY,
                             highlightthickness=0, bd=0)
        bpm_scale.pack(side=tk.LEFT, padx=(0, 8))
        _tt(tk.Button(bpm_row, text="Apply",
                  command=lambda: self._apply_global_bpm(bpm_var.get()),
                  **bb),
            "Set the song's tempo. This changes playback speed and how "
            "wide each measure is on screen — it does not move or "
            "requantize any notes by itself.").pack(side=tk.LEFT)

        # Auto-detect row
        detect_note_var = tk.StringVar(value="Not run yet")
        det_row = tk.Frame(gfrm, bg=BG)
        det_row.pack(fill=tk.X, pady=3)

        def _run_autodetect():
            # BPM detection
            bpm_result = self._auto_detect_calibration()
            if bpm_result['bpm'] is not None:
                bpm_var.set(round(bpm_result['bpm']))

            # Time signature detection (v22i — uses detect_time_signature())
            ts_num, ts_den, ts_conf, ts_note = self.song.detect_time_signature()
            if ts_conf >= 0.4:
                ts_num_var.set(ts_num)
                ts_den_var.set(ts_den)
                ts_summary = f"  |  Meter: {ts_num}/{ts_den} ({ts_conf:.0%})"
            else:
                ts_summary = f"  |  Meter: low confidence ({ts_conf:.0%}), check manually"

            if bpm_result['bpm'] is not None:
                detect_note_var.set(
                    f"BPM: {bpm_result['bpm']:.1f} ({bpm_result['confidence']:.0%})"
                    f"{ts_summary} — click Apply to use")
            else:
                detect_note_var.set(f"{bpm_result['note']}{ts_summary}")

        _tt(tk.Button(det_row, text="Auto-detect BPM + Meter",
                  command=_run_autodetect, **bb),
            "Analyse the recording to suggest a tempo and time signature. "
            "Fills in the fields above but does not apply them — review "
            "the suggestion, then click Apply if it looks right."
            ).pack(side=tk.LEFT)
        _lbl(det_row, "", fg=MUTED,
             textvariable=detect_note_var,
             font=("TkDefaultFont", 8),
             wraplength=260).pack(side=tk.LEFT, padx=8)

        # ══ SECTION B — Selected measure detail ══════════════════════════
        _sep(content)
        meas_title_var = tk.StringVar(value="  No measure selected — click a cell in the strip")
        _lbl(content, "", fg=BLUE,
             font=("TkDefaultFont", 10, "bold"),
             textvariable=meas_title_var).pack(fill=tk.X)

        mfrm = tk.Frame(content, bg=BG, padx=14, pady=4)
        mfrm.pack(fill=tk.X)

        beat_info_var  = tk.StringVar(value="")
        local_bpm_var  = tk.StringVar(value="")
        status_var     = tk.StringVar(value="")
        m_bpm_var      = tk.IntVar(value=round(self.song.bpm))

        _lbl(mfrm, "", fg=FG,
             textvariable=beat_info_var).pack(fill=tk.X, pady=1)
        _lbl(mfrm, "", fg=MUTED,
             font=("TkDefaultFont", 8),
             textvariable=local_bpm_var).pack(fill=tk.X, pady=1)
        _lbl(mfrm, "", fg=MUTED,
             font=("TkDefaultFont", 8),
             textvariable=status_var).pack(fill=tk.X, pady=1)

        m_bpm_row = tk.Frame(mfrm, bg=BG)
        m_bpm_row.pack(fill=tk.X, pady=3)
        _lbl(m_bpm_row, "BPM override:", width=18).pack(side=tk.LEFT)
        tk.Spinbox(m_bpm_row, from_=20, to=300, textvariable=m_bpm_var,
                   **sb).pack(side=tk.LEFT, padx=(0, 6))

        def _apply_meas_bpm():
            idx = self._selected_measure_idx
            if idx is None:
                return
            self._measure_bpm_overrides[idx] = m_bpm_var.get()
            self._accepted_measures.add(idx)
            self._refresh_views()

        def _apply_from_here():
            idx = self._selected_measure_idx
            if idx is None:
                return
            mmap = self.song.get_measure_map()
            bpm  = m_bpm_var.get()
            for mi in range(idx, len(mmap)):
                self._measure_bpm_overrides[mi] = bpm
                self._accepted_measures.add(mi)
            self._refresh_views()

        tk.Button(m_bpm_row, text="Apply to this measure",
                  command=_apply_meas_bpm, **bb).pack(side=tk.LEFT, padx=(0, 4))
        tk.Button(m_bpm_row, text="Apply from here to end",
                  command=_apply_from_here, **bb).pack(side=tk.LEFT)

        def _populate_measure_detail(idx):
            """Fill Section B from the clicked measure index."""
            self._selected_measure_idx = idx
            mmap = self.song.get_measure_map()
            if idx >= len(mmap):
                return
            _mi, ms, me, num, den, tpm = mmap[idx]
            tpb = self.song.ticks_per_beat

            # Compute beat content
            latest_end = ms
            for tr in self.song.tracks:
                for n in tr.notes:
                    if ms <= n.tick < me:
                        latest_end = max(latest_end, n.tick + n.duration)
            actual_ticks   = max(1, latest_end - ms)
            expected_ticks = tpm
            actual_q   = actual_ticks   / tpb
            expected_q = expected_ticks / tpb
            delta      = actual_q - expected_q

            meas_title_var.set(f"  Measure {idx + 1}")
            beat_info_var.set(
                f"Beat count:  {actual_q:.2f} / {expected_q:.0f}  "
                f"({'overflow' if delta > 0 else 'underfill'} "
                f"by {abs(delta):.2f} beats)" if abs(delta) >= 0.1
                else f"Beat count:  {actual_q:.2f} / {expected_q:.0f}  ✓ clean")

            local_bpm = self.song.bpm * (expected_ticks / actual_ticks)
            local_bpm_var.set(f"Derived local BPM:  {local_bpm:.1f}")

            if abs(delta) < 0.15:
                status_var.set("This measure looks clean.")
            elif abs(delta) <= 1.0:
                status_var.set(
                    "Moderate overflow — likely rubato at barline. "
                    "Try 'Clean up this measure'.")
            else:
                status_var.set(
                    "Large discrepancy — check time signature or "
                    "look for a missing/extra note.")

            override = self._measure_bpm_overrides.get(idx, round(self.song.bpm))
            m_bpm_var.set(round(override))

        # Attach so _on_strip_click can call it via the panel reference
        dlg._populate_measure_detail = _populate_measure_detail

        # Populate immediately if a measure is already selected
        if self._selected_measure_idx is not None:
            _populate_measure_detail(self._selected_measure_idx)

        # ══ SECTION C — Cleanup and Bake ═════════════════════════════════
        _sep(content)
        _lbl(content, "  Cleanup (Pass 3)",
             fg=BLUE, font=("TkDefaultFont", 10, "bold")).pack(fill=tk.X)

        cfrm = tk.Frame(content, bg=BG, padx=14, pady=4)
        cfrm.pack(fill=tk.X)

        cleanup_status_var = tk.StringVar(value="")

        # Gate label — explains why cleanup is disabled when not rationalized
        cleanup_gate_var = tk.StringVar(value="")
        gate_lbl = _lbl(cfrm, "", fg="#e3b341",
                        font=("TkDefaultFont", 8),
                        textvariable=cleanup_gate_var)
        gate_lbl.pack(fill=tk.X, pady=(0, 4))

        def _cleanup_this():
            idx = self._selected_measure_idx
            if idx is None:
                cleanup_status_var.set("Select a measure first.")
                return
            self._cleanup_measure(idx)
            cleanup_status_var.set(f"✓  Cleaned measure {idx + 1}.")
            _populate_measure_detail(idx)

        def _cleanup_all():
            self._cleanup_all_measures()
            cleanup_status_var.set(
                f"✓  Cleaned all {len(self.song.get_measure_map())} measures.")

        def _step_through():
            cleanup_status_var.set(
                "Step-through mode coming in v22g. "
                "Use 'Clean up this measure' one at a time for now.")

        def _run_bake():
            """Execute bake_to_score() and report result in the panel."""
            try:
                baked = self.song.bake_to_score()
                self._set_rationalized_song(baked)
                cleanup_status_var.set(
                    "✓  Baked.  Playback and MIDI export now match the score.")
            except Exception as exc:
                import traceback; traceback.print_exc()
                cleanup_status_var.set(f"Bake error: {exc}")

        def _do_bake():
            """Bake button handler — routes through rationalization if needed."""
            if not self._is_rationalized:
                # ── Three-button warning dialog ───────────────────────────
                warn = tk.Toplevel(dlg)
                warn.title("Bake — Rationalization Recommended")
                warn.configure(bg=BG)
                warn.resizable(False, False)
                # v22ze: grab_set() alone makes this modal relative to `dlg`,
                # but doesn't guarantee stacking order -- transient() ties
                # it to dlg for the window manager's benefit and lift()
                # raises it now. An earlier version of this also toggled
                # -topmost on a timer for extra insurance; that turned out
                # to be a real hazard in its own right (an intermittent,
                # timing-dependent freeze -- see _clear_topmost_safe's
                # docstring), so it's been dropped in favor of just the
                # standard, well-tested transient()+lift()+grab_set()
                # pattern, which should already be sufficient.
                warn.transient(dlg)
                warn.lift()
                warn.grab_set()   # modal

                tk.Label(warn,
                         text="⚠  This song has not been rationalized.",
                         bg=BG, fg="#e3b341",
                         font=("TkDefaultFont", 11, "bold"),
                         pady=10).pack(padx=20)
                tk.Label(warn,
                         text=(
                             "Baking a raw MIDI file may collapse ornaments,\n"
                             "remove fast notes, and alter chord voicings.\n\n"
                             "Rationalize Score first for best results."),
                         bg=BG, fg=FG,
                         font=("TkDefaultFont", 9),
                         justify=tk.CENTER).pack(padx=20, pady=(0, 12))

                chosen = tk.StringVar(value="")

                def _pick(val):
                    chosen.set(val)
                    warn.grab_release()
                    warn.destroy()

                btn_frm = tk.Frame(warn, bg=BG)
                btn_frm.pack(pady=(0, 16), padx=16)

                tk.Button(btn_frm,
                          text="Rationalize then Bake",
                          bg="#238636", fg="white",
                          activebackground="#2ea043",
                          relief=tk.FLAT, padx=8, pady=4,
                          command=lambda: _pick("rationalize")).pack(
                              side=tk.LEFT, padx=4)
                tk.Button(btn_frm,
                          text="Bake Anyway",
                          bg="#6e4a00", fg="white",
                          activebackground="#8a5c00",
                          relief=tk.FLAT, padx=8, pady=4,
                          command=lambda: _pick("bake")).pack(
                              side=tk.LEFT, padx=4)
                tk.Button(btn_frm,
                          text="Cancel",
                          **bb,
                          command=lambda: _pick("cancel")).pack(
                              side=tk.LEFT, padx=4)

                dlg.wait_window(warn)   # block until user chooses

                if chosen.get() == "cancel" or chosen.get() == "":
                    return
                elif chosen.get() == "rationalize":
                    # Open the Rationalize Score dialog.  When the user clicks
                    # Accept there, _accept() already calls bake_to_score()
                    # internally, so no further action is needed here.
                    cleanup_status_var.set(
                        "Rationalize dialog opened — click Accept when done "
                        "to complete the bake.")
                    self._rationalize_score()
                    return
                # else: "bake" — fall through to _run_bake() below

            # Final confirmation before committing (applies to both paths)
            # v22ze: messagebox stacks relative to `parent` -- if dlg itself
            # had fallen behind the main window, the messagebox would
            # inherit that problem, so lift dlg first. (A -topmost toggle
            # used to be added here too; dropped for the same reason as
            # the warn dialog above -- see _clear_topmost_safe's docstring.)
            dlg.lift()
            if not messagebox.askyesno(
                    "Bake",
                    "Baking commits all cleanup into the note data.\n\n"
                    "This cannot be undone once you save the file.\n\n"
                    "Continue?",
                    parent=dlg):
                return
            _run_bake()

        btn_row1 = tk.Frame(cfrm, bg=BG)
        btn_row1.pack(fill=tk.X, pady=2)
        _btn_this = _tt(tk.Button(btn_row1, text="Clean up this measure",
                              command=_cleanup_this, **bb),
            "Snap this measure's notes onto the beat grid and clip any "
            "note that overflows into the next measure. Only available "
            "after rationalizing.")
        _btn_this.pack(side=tk.LEFT, padx=(0, 4))
        _btn_all = _tt(tk.Button(btn_row1, text="Clean up all measures",
                             command=_cleanup_all, **bb),
            "Apply the same measure-by-measure cleanup to the entire "
            "piece in one step.")
        _btn_all.pack(side=tk.LEFT, padx=(0, 4))
        _btn_step = _tt(tk.Button(btn_row1, text="Step through…",
                              command=_step_through, **bb),
            "Walk through the piece one measure at a time, reviewing "
            "and confirming each cleanup before moving to the next.")
        _btn_step.pack(side=tk.LEFT)

        # "Rationalize Now" shortcut — visible only when not yet rationalized
        rat_row = tk.Frame(cfrm, bg=BG)
        rat_row.pack(fill=tk.X, pady=2)
        _btn_rat = _tt(tk.Button(rat_row,
                             text="Rationalize Now…  (opens Rationalize dialog)",
                             bg="#1f4a7a", fg="white",
                             activebackground="#2a5f9e",
                             relief=tk.FLAT, padx=8, pady=3,
                             command=self._rationalize_score),
            "Cleanup requires rationalizing first. Opens the Rationalize "
            "Score dialog — once you Accept there, cleanup and Bake below "
            "become available.")
        _btn_rat.pack(side=tk.LEFT)

        def _refresh_cleanup_state():
            """Enable or disable cleanup controls based on rationalization state."""
            rationalized = self._is_rationalized
            state = tk.NORMAL if rationalized else tk.DISABLED
            for btn in (_btn_this, _btn_all, _btn_step):
                btn.configure(state=state)
            if rationalized:
                cleanup_gate_var.set("")
                _btn_rat.pack_forget()
            else:
                cleanup_gate_var.set(
                    "⚠  Cleanup is available after Rationalize Score has been run.")
                _btn_rat.pack(side=tk.LEFT)

        # Run immediately to set initial state
        _refresh_cleanup_state()

        btn_row2 = tk.Frame(cfrm, bg=BG)
        btn_row2.pack(fill=tk.X, pady=2)
        _tt(tk.Button(btn_row2, text="Bake",
                  bg="#238636", fg="white",
                  activebackground="#2ea043",
                  relief=tk.FLAT, padx=8, pady=3,
                  command=_do_bake),
            "Commit all cleanup into the actual note data so playback and "
            "MIDI export exactly match what the score shows. Cannot be "
            "undone once you save the file.").pack(side=tk.LEFT, padx=(0, 8))
        _lbl(btn_row2, "", fg=MUTED,
             font=("TkDefaultFont", 8),
             textvariable=cleanup_status_var).pack(side=tk.LEFT)

        # ══ SECTION D — Undo / Redo ═══════════════════════════════════════
        _sep(content)
        undo_row = tk.Frame(content, bg=BG, padx=14, pady=6)
        undo_row.pack(fill=tk.X)

        undo_lbl_var = tk.StringVar(value="Nothing to undo")
        redo_lbl_var = tk.StringVar(value="Nothing to redo")

        def _refresh_undo_labels():
            undo_lbl_var.set(
                f"Undo: {self._undo_stack[-1].description}"
                if self._undo_stack else "Nothing to undo")
            redo_lbl_var.set(
                f"Redo: {self._redo_stack[-1].description}"
                if self._redo_stack else "Nothing to redo")

        tk.Button(undo_row, text="↩  Undo",
                  command=lambda: [self._undo(), _refresh_undo_labels()],
                  **bb).pack(side=tk.LEFT, padx=(0, 6))
        _lbl(undo_row, "", fg=MUTED,
             font=("TkDefaultFont", 8),
             textvariable=undo_lbl_var).pack(side=tk.LEFT)

        redo_row = tk.Frame(content, bg=BG, padx=14, pady=2)
        redo_row.pack(fill=tk.X)
        tk.Button(redo_row, text="↪  Redo",
                  command=lambda: [self._redo(), _refresh_undo_labels()],
                  **bb).pack(side=tk.LEFT, padx=(0, 6))
        _lbl(redo_row, "", fg=MUTED,
             font=("TkDefaultFont", 8),
             textvariable=redo_lbl_var).pack(side=tk.LEFT)

        def _refresh_panel():
            """Refresh all dynamic panel state: undo labels + cleanup gate."""
            _refresh_undo_labels()
            _refresh_cleanup_state()

        # Attach so external callers (_undo, _redo, _set_rationalized_song)
        # can update the panel without holding a reference to inner functions.
        dlg._refresh_undo_labels = _refresh_panel   # keeps existing call sites working
        dlg._refresh_panel       = _refresh_panel
        _refresh_panel()

        tk.Frame(content, bg=BG, height=10).pack()   # bottom padding

        # v22ze: clamp the initial window to fit the screen. Without a
        # scrollable content area (see note above), a window taller than
        # the screen still can't show everything even with resizing
        # enabled -- but at least sizing it to fit on open, positioned
        # near the top of the screen, means it starts in a state the
        # user can actually see and use, rather than opening already
        # off-screen with no way to tell anything is missing.
        dlg.update_idletasks()
        req_w = dlg.winfo_reqwidth()
        req_h = dlg.winfo_reqheight()
        screen_h = dlg.winfo_screenheight()
        margin = 80   # leave room for title bar / taskbar
        fit_h = min(req_h, max(300, screen_h - margin))
        dlg.geometry(f"{req_w}x{fit_h}+{dlg.winfo_x()}+20")

    # ── Rationalization Dialog ────────────────────────────────────────────────

    def _rationalize_score(self):
        """Open the (non-modal) Rationalize Score dialog."""
        # Only one instance allowed
        if self._rationalize_dlg and self._rationalize_dlg.winfo_exists():
            self._rationalize_dlg.lift()
            return

        if not self.song.tracks:
            messagebox.showinfo("Rationalize", "No tracks to rationalize.",
                                parent=self.root)
            return

        # Determine song length for measure range defaults
        mmap = (self._original_song or self.song).get_measure_map()
        total_measures = len(mmap) if mmap else 1

        dlg = tk.Toplevel(self.root)
        self._rationalize_dlg = dlg
        dlg.title("Rationalize Score")
        # v22ze-46: resizable + always-on-top per presentation request --
        # this dialog in particular was reported as taller than the
        # screen on some displays.
        dlg.resizable(True, True)
        dlg.attributes("-topmost", True)
        dlg.configure(bg="#0d1117")
        # Non-modal but always opens in front — user can move it
        dlg.lift()
        dlg.focus_force()

        BG    = "#0d1117"
        FG    = "#f0f6fc"
        MUTED = "#8b949e"
        BLUE  = "#58a6ff"
        WARN  = "#d29922"
        # v22ze-57: content lives in a scrollable inner frame (not `dlg`
        # directly) — this dialog was specifically flagged as taller
        # than the screen on some displays; a scrollbar means shrinking
        # it no longer clips controls with no way back to them.
        content = _make_scrollable(dlg, bg=BG)

        tk.Label(content, text="🎼  Rationalize Score",
                 bg=BG, fg=BLUE, font=("TkDefaultFont", 12, "bold")).pack(pady=(16, 4))
        tk.Label(content,
                 text="Convert a recorded performance into clean notation. "
                      "Original MIDI is preserved — rationalization creates a separate copy.",
                 bg=BG, fg=MUTED, font=("TkDefaultFont", 9),
                 justify=tk.CENTER).pack(padx=20, pady=(0, 10))

        # ── Parameters frame ─────────────────────────────────────────────────
        pfrm = tk.LabelFrame(content, text=" Parameters ", bg=BG, fg=FG,
                             font=("TkDefaultFont", 9), padx=14, pady=8)
        pfrm.pack(fill=tk.X, padx=16, pady=4)

        def _row(parent, label, widget_fn, row):
            tk.Label(parent, text=label, bg=BG, fg=FG,
                     font=("TkDefaultFont", 10), anchor="w",
                     width=22).grid(row=row, column=0, sticky="w", pady=3)
            w = widget_fn(parent)
            w.grid(row=row, column=1, sticky="w", padx=8, pady=3)
            return w

        # Tempo correction
        detect_var = tk.BooleanVar(value=True)
        _tt(_row(pfrm, "Auto-detect tempo:", lambda p: tk.Checkbutton(
            p, variable=detect_var, bg=BG, fg=FG,
            selectcolor="#21262d", activebackground=BG), 0),
            "Estimates the true performance tempo from the timing between "
            "bass notes. Uncheck to type in a known tempo instead.")

        # Tempo override (only active when detect=False)
        tempo_var = tk.IntVar(value=self.song.bpm)
        tempo_spin = _tt(tk.Spinbox(pfrm, from_=20, to=300, textvariable=tempo_var,
                                width=5, bg="#21262d", fg=FG,
                                buttonbackground="#30363d"),
            "Manual tempo in beats per minute. Only used when Auto-detect "
            "tempo is unchecked above.")
        tk.Label(pfrm, text="Tempo override (BPM):", bg=BG, fg=FG,
                 font=("TkDefaultFont", 10), anchor="w",
                 width=22).grid(row=1, column=0, sticky="w", pady=3)
        tempo_spin.grid(row=1, column=1, sticky="w", padx=8, pady=3)
        def _update_tempo_state(*_):
            tempo_spin.config(state="disabled" if detect_var.get() else "normal")
        detect_var.trace_add("write", _update_tempo_state)
        _update_tempo_state()

        # Auto-detect time signature (v22i)
        # v22ze-46 fix: this defaulted to True, silently running
        # detection on file open even though the loaded file's own
        # meter is right there and correct -- switched to default OFF
        # (user opt-in) so the override field (which already correctly
        # shows the file's own time signature below) is what's used
        # unless the user deliberately asks for detection. Also renamed
        # per request: "Auto-detect meter" -> "Time-Sig-auto-detect".
        detect_ts_var = tk.BooleanVar(value=False)
        _tt(_row(pfrm, "Time-Sig-auto-detect:", lambda p: tk.Checkbutton(
            p, variable=detect_ts_var, bg=BG, fg=FG,
            selectcolor="#21262d", activebackground=BG), 2),
            "Guesses the time signature from accent patterns in the bass "
            "line. If the piece is a well-known meter, verify the detected "
            "result below before running Preview — uncheck to set it "
            "manually if detection looks wrong.")

        # Time signature override row (only active when detect_ts=False)
        _ts_num_var = tk.IntVar(value=self.song.time_sig_num)
        _ts_den_var = tk.IntVar(value=self.song.time_sig_den)
        ts_row_r = tk.Frame(pfrm, bg=BG)
        tk.Label(pfrm, text="Time-Sig override:", bg=BG, fg=FG,
                 font=("TkDefaultFont", 10), anchor="w",
                 width=22).grid(row=3, column=0, sticky="w", pady=3)
        ts_row_r.grid(row=3, column=1, sticky="w", pady=3)
        ts_num_spin = _tt(tk.Spinbox(ts_row_r, from_=1, to=16, textvariable=_ts_num_var,
                                 width=3, bg="#21262d", fg=FG,
                                 buttonbackground="#30363d"),
            "Time signature numerator (beats per measure). Only used when "
            "Time-Sig-auto-detect is unchecked.")
        ts_num_spin.pack(side=tk.LEFT)
        tk.Label(ts_row_r, text="/", bg=BG, fg=FG).pack(side=tk.LEFT)
        ts_den_spin = tk.OptionMenu(ts_row_r, _ts_den_var, 1, 2, 4, 8, 16)
        ts_den_spin.configure(bg="#21262d", fg=FG, relief=tk.FLAT,
                              highlightthickness=0)
        ts_den_spin["menu"].configure(bg="#21262d", fg=FG)
        ts_den_spin.pack(side=tk.LEFT, padx=(2, 0))

        def _update_ts_state(*_):
            st = "disabled" if detect_ts_var.get() else "normal"
            ts_num_spin.config(state=st)
            ts_den_spin.config(state=st)
        detect_ts_var.trace_add("write", _update_ts_state)
        _update_ts_state()

        # Prominent detected-meter display (v22k) ─────────────────────────
        # Shows the result of auto-detection BEFORE Preview is clicked,
        # so the user can override it without having to run Preview first.
        detected_meter_var = tk.StringVar(value="")
        detected_meter_lbl = tk.Label(
            pfrm, textvariable=detected_meter_var,
            bg=BG, fg="#e3b341",   # amber — informational, not an error
            font=("TkDefaultFont", 9, "italic"), anchor="w", wraplength=340)
        detected_meter_lbl.grid(row=4, column=0, columnspan=2,
                                sticky="w", padx=4, pady=(0, 4))

        def _refresh_detected_meter(*_):
            """Run detection immediately when Auto-detect is checked."""
            if not detect_ts_var.get():
                detected_meter_var.set("")
                return
            try:
                n, d, conf, note = self.song.detect_time_signature()
                # v22ze-41 fix: this used to pre-populate the override
                # spinboxes with the detected value UNCONDITIONALLY, same
                # bug as the core rationalize logic (see v22ze-40) but in
                # a second, parallel place -- so even with that fix,
                # opening this dialog on already-rationalized data (where
                # the flattened dynamics make detection unreliable) still
                # silently overwrote the override fields with a weak,
                # often-wrong guess like "2/4", which is what you'd see
                # sitting in the field even before touching Preview.
                MIN_TIMESIG_CONFIDENCE = 0.3
                if conf < MIN_TIMESIG_CONFIDENCE:
                    detected_meter_var.set(
                        f"Auto-detect confidence too low ({conf:.0%}) to trust "
                        f"— keeping existing {self.song.time_sig_num}/"
                        f"{self.song.time_sig_den}. {note}")
                    _ts_num_var.set(self.song.time_sig_num)
                    _ts_den_var.set(self.song.time_sig_den)
                else:
                    detected_meter_var.set(
                        f"Auto-detected: {n}/{d}  (confidence {conf:.0%})  "
                        f"— uncheck to override")
                    # Pre-populate override spinboxes with detected values so
                    # unchecking gives the user a sensible starting point
                    _ts_num_var.set(n)
                    _ts_den_var.set(d)
            except Exception as exc:
                detected_meter_var.set(f"Detection error: {exc}")

        detect_ts_var.trace_add("write", _refresh_detected_meter)
        # Run immediately on dialog open
        dlg.after(100, _refresh_detected_meter)

        # Fingerprint of the meter used in the last Preview call (v22k).
        # Accept uses this to detect if the meter changed since Preview
        # and needs to re-run rationalize before baking.
        _last_preview_meter = [None]   # mutable cell: [None | (num, den)]

        # Expose references so _apply_global_timesig can push values in
        # (v22k: Score Setup → Rationalize dialog synchronisation)
        dlg._detect_ts_var  = detect_ts_var
        dlg._ts_num_var     = _ts_num_var
        dlg._ts_den_var     = _ts_den_var
        dlg._refresh_detected_meter = _refresh_detected_meter

        # ── Preserve existing hand tracks (v22t) ────────────────────────────
        # Detected automatically: if the file already has exactly two
        # note-bearing tracks (e.g. "Piano right" / "Piano left"), offer to
        # skip the DP hand-separation re-derivation entirely and trust the
        # file's own track assignment.  Re-running DP on already-correct
        # data can reassign individual notes in fast interleaved passages
        # where the file's ground truth and the DP's heuristics disagree —
        # this was reported as "the rationalized version sounds nothing
        # like the raw" on a well-prepared two-track file.
        _hand_info = self.song.detect_separated_hands()
        preserve_hands_var = tk.BooleanVar(value=_hand_info['separated'])
        ph_row = tk.Frame(pfrm, bg=BG)
        ph_row.grid(row=5, column=0, columnspan=2, sticky="w", pady=(4, 0))
        ph_check = _tt(tk.Checkbutton(
            ph_row, variable=preserve_hands_var, bg=BG, fg=FG,
            selectcolor="#21262d", activebackground=BG,
            state=("normal" if _hand_info['separated'] else "disabled")),
            "When the file already has exactly two note-bearing tracks "
            "(e.g. a piano piece already split into right-hand and "
            "left-hand parts), keep that original split instead of "
            "re-deriving it. Re-deriving can reassign individual notes in "
            "fast passages where hands interleave, even when the file's "
            "own separation was already correct.")
        ph_check.pack(side=tk.LEFT)
        if _hand_info['separated']:
            ph_label_text = (
                f"Preserve existing hand tracks  "
                f"(detected: RH={_hand_info['rh_notes']} notes, "
                f"LH={_hand_info['lh_notes']} notes)")
            ph_fg = "#3fb950"
        else:
            ph_label_text = ("Preserve existing hand tracks  "
                             "(not available — file has more or fewer than "
                             "2 note-bearing tracks)")
            ph_fg = MUTED
        tk.Label(ph_row, text=ph_label_text, bg=BG, fg=ph_fg,
                 font=("TkDefaultFont", 9)).pack(side=tk.LEFT, padx=4)

        # Quantize strength
        q_str_var = tk.IntVar(value=85)
        _tt(_row(pfrm, "Quantize strength (%):", lambda p: tk.Spinbox(
            p, from_=0, to=100, textvariable=q_str_var, width=5,
            bg="#21262d", fg=FG, buttonbackground="#30363d"), 6),
            "How firmly note onsets snap to the grid. 100% = hard snap "
            "(mechanical); 0% = no snapping (keeps all rubato/timing "
            "exactly as played). 85% is a good default for a human "
            "performance.")

        # Quantize grid
        q_div_var = tk.StringVar(value="8th")
        grid_opts = {"8th": 8, "16th": 16, "Quarter": 4, "32nd": 32}
        _tt(_row(pfrm, "Quantize grid:", lambda p: tk.OptionMenu(
            p, q_div_var, *grid_opts.keys()), 7),
            "The finest note value onsets can snap to. Choose 16th for "
            "pieces with fast ornamental notes; Quarter for simple slow "
            "pieces; 8th is the common default.")

        # Rest threshold
        rest_var = tk.StringVar(value="16th")
        # v22ze-68 fix: this used to be a hardcoded {30, 60, 120}, silently
        # assuming ticks_per_beat=480. For a file at a different tpb (the
        # user's own file uses 960 -- twice that), these values were HALF
        # of a real 32nd/16th/8th note's actual duration, so the rest-
        # removal threshold was roughly one note-value finer than its own
        # label promised. A genuine 16th-note-long rest could easily be
        # LONGER than what "16th" here actually cleared, so rests exactly
        # the size the user asked to remove often weren't caught at all --
        # matching a direct report of 1/8 and 1/16 rests surviving cleanup.
        # Scale with the song's own tpb, the same way every other note-
        # value-to-ticks conversion in this app already does.
        _tpb_r = self.song.ticks_per_beat
        rest_opts = {"Off": 0, "32nd": _tpb_r // 8,
                     "16th": _tpb_r // 4, "8th": _tpb_r // 2}
        _tt(_row(pfrm, "Remove rests shorter than:", lambda p: tk.OptionMenu(
            p, rest_var, *rest_opts.keys()), 8),
            "Gaps between notes shorter than this are merged away as "
            "performance noise rather than notated as real rests. "
            "'Off' preserves every gap exactly as played.")

        # Hand span
        span_var = tk.IntVar(value=14)
        _tt(_row(pfrm, "Max hand span (semitones):", lambda p: tk.Spinbox(
            p, from_=10, to=18, textvariable=span_var, width=4,
            bg="#21262d", fg=FG, buttonbackground="#30363d"), 9),
            "The widest interval one hand is assumed able to comfortably "
            "play. Notes wider than this within one hand are penalised "
            "during hand assignment. 14 semitones (a tenth) is a typical "
            "adult hand span.")

        # Arpeggio window (0 = auto-compute from song tempo)
        arp_var = tk.IntVar(value=0)
        _tt(_row(pfrm, "Arpeggio window (0=auto):", lambda p: tk.Spinbox(
            p, from_=0, to=200, textvariable=arp_var, width=5,
            bg="#21262d", fg=FG, buttonbackground="#30363d"), 10),
            "Notes within this many ticks of each other are treated as a "
            "rolled chord/arpeggio rather than sequential notes. 0 lets "
            "the app compute a sensible value from the detected tempo.")

        # ── Measure range ────────────────────────────────────────────────────
        rfrm = tk.LabelFrame(content, text=" Measure Range ", bg=BG, fg=FG,
                             font=("TkDefaultFont", 9), padx=14, pady=8)
        rfrm.pack(fill=tk.X, padx=16, pady=4)

        range_all = tk.BooleanVar(value=True)
        rng_from  = tk.IntVar(value=1)
        rng_to    = tk.IntVar(value=total_measures)

        tk.Checkbutton(rfrm, text="Whole piece", variable=range_all,
                       bg=BG, fg=FG, selectcolor="#21262d",
                       activebackground=BG).grid(row=0, column=0, columnspan=4,
                                                 sticky="w", pady=3)
        tk.Label(rfrm, text="From measure:", bg=BG, fg=FG,
                 font=("TkDefaultFont", 10)).grid(row=1, column=0, sticky="w", pady=3)
        from_spin = tk.Spinbox(rfrm, from_=1, to=total_measures,
                               textvariable=rng_from, width=5,
                               bg="#21262d", fg=FG, buttonbackground="#30363d")
        from_spin.grid(row=1, column=1, padx=6, pady=3)
        tk.Label(rfrm, text="To:", bg=BG, fg=FG).grid(row=1, column=2, pady=3)
        to_spin = tk.Spinbox(rfrm, from_=1, to=total_measures,
                             textvariable=rng_to, width=5,
                             bg="#21262d", fg=FG, buttonbackground="#30363d")
        to_spin.grid(row=1, column=3, padx=6, pady=3)

        def _update_range_state(*_):
            s = "disabled" if range_all.get() else "normal"
            from_spin.config(state=s); to_spin.config(state=s)
        range_all.trace_add("write", _update_range_state)
        _update_range_state()

        # ── Result message ───────────────────────────────────────────────────
        result_var = tk.StringVar(value="Press Preview to rationalize.")
        tk.Label(content, textvariable=result_var, bg=BG, fg=WARN,
                 font=("TkDefaultFont", 9), justify=tk.LEFT,
                 wraplength=340).pack(padx=16, pady=6)

        # ── Buttons ──────────────────────────────────────────────────────────
        bfrm = tk.Frame(content, bg=BG); bfrm.pack(pady=(4, 16))
        bs   = dict(relief=tk.FLAT, padx=12, pady=6,
                    font=("TkDefaultFont", 10), cursor="hand2")

        def _preview():
            import copy as _copy
            src = self._original_song if self._original_song else self.song
            params = {
                'arpeggio_window':   (arp_var.get() or None),  # 0 → None → auto
                'quantize_div':      grid_opts[q_div_var.get()],
                'quantize_strength': q_str_var.get() / 100.0,
                'rest_threshold':    rest_opts[rest_var.get()],
                'max_span':          span_var.get(),
                'detect_tempo':      detect_var.get(),
                'tempo_override':    None if detect_var.get() else tempo_var.get(),
                'detect_timesig':    detect_ts_var.get(),
                'timesig_override':  (None if detect_ts_var.get()
                                      else (_ts_num_var.get(), _ts_den_var.get())),
                'preserve_hands':    preserve_hands_var.get(),
            }
            m_range = None
            if not range_all.get():
                m_range = (rng_from.get(), rng_to.get())

            try:
                result_var.set("Running rationalization…")
                dlg.update()
                # Snapshot before-state for undo
                _before_song = (self._original_song or self.song)
                before = _copy.deepcopy(_before_song.tracks)
                before_map = _copy.deepcopy(_before_song.rationalized_measure_map)
                rationalized = src.rationalize(params=params,
                                               measure_range=m_range)
                # v22ze-47 fix: this used to show the RAW rationalize()
                # result in Preview, while Accept separately ran
                # bake_to_score() (duration-vocabulary snapping, tie
                # merging, staccato detection) on top of it -- two
                # independently-computed results, shown at different
                # times, that could disagree. That's what caused "the
                # result shown in Preview becomes something else when I
                # Accept": Accept was never committing what Preview
                # showed, it was computing something new. Bake HERE, so
                # what Preview displays and plays IS byte-for-byte what
                # Accept will commit -- no second, potentially-different
                # computation.
                rationalized = rationalized.bake_to_score()
                after = _copy.deepcopy(rationalized.tracks)
                after_map = _copy.deepcopy(rationalized.rationalized_measure_map)
                # Push undo action
                action = RationalizationAction(
                    description="Rationalize",
                    before_tracks=before,
                    after_tracks=after,
                    before_map=before_map,
                    after_map=after_map)
                self._push_undo(action)
                self._set_rationalized_song(rationalized)
                # Record which meter this Preview used (v22k)
                _last_preview_meter[0] = (rationalized.time_sig_num,
                                          rationalized.time_sig_den)
                # Sync selection spinboxes for Play Selection
                if m_range:
                    self._sel_from.set(m_range[0])
                    self._sel_to.set(m_range[1])
                rh = rationalized.tracks[0] if rationalized.tracks else None
                lh = rationalized.tracks[1] if len(rationalized.tracks) > 1 else None
                rh_n = len(rh.notes) if rh else 0
                lh_n = len(lh.notes) if lh else 0
                _mode_note = ("  |  hands preserved from source"
                              if preserve_hands_var.get() else "")
                result_var.set(
                    f"\u2713  Detected BPM: {rationalized.bpm}  |  "
                    f"Meter: {rationalized.time_sig_num}/{rationalized.time_sig_den}  |  "
                    f"RH: {rh_n} notes  LH: {lh_n} notes{_mode_note}\n"
                    "Press \u25b6 Sel to audition, Accept to commit, Discard to revert."
                )
            except Exception as exc:
                result_var.set(f"Error: {exc}")
                import traceback; traceback.print_exc()

        def _accept():
            if not self._is_rationalized:
                result_var.set("Nothing to accept — run Preview first.")
                return
            # v22k: if the meter has changed since Preview (user adjusted
            # Score Setup or override spinboxes after seeing the result),
            # re-run rationalize with the current meter before baking.
            current_meter = (
                (_ts_num_var.get(), _ts_den_var.get())
                if not detect_ts_var.get()
                else None   # auto-detect — no fixed override
            )
            preview_meter = _last_preview_meter[0]
            if (current_meter is not None
                    and preview_meter is not None
                    and current_meter != preview_meter):
                result_var.set(
                    f"Meter changed to {current_meter[0]}/{current_meter[1]} "
                    f"since Preview — re-running…")
                dlg.update()
                _preview()   # re-run with new meter
                if not self._is_rationalized:
                    return   # _preview hit an error

            # v22ze-47 fix: this used to call self.song.bake_to_score()
            # AGAIN here, on top of the already-baked result Preview
            # already computed and displayed. Verified directly that
            # bake_to_score() is NOT idempotent -- its staccato-detection
            # logic can produce a DIFFERENT duration/articulation on a
            # second pass over the same notes (confirmed: a baked eighth
            # note re-baked came out inflated and staccato-flagged when
            # it wasn't before). Re-baking here would have silently
            # reintroduced the exact "Accept changes what Preview showed"
            # bug this fix is for. self.song is already the fully baked
            # result at this point (set by _preview()); just commit it.
            self.song.modified = True
            self._update_title()
            result_var.set("✓  Accepted.  Playback and MIDI export match the score shown in Preview.")

        def _discard():
            self._set_rationalized_song(None)
            result_var.set("Discarded.  Reverted to original.")

        def _save_copy():
            if not self._is_rationalized:
                result_var.set("Nothing to save — run Preview first.")
                return
            import mido as _mido
            path = filedialog.asksaveasfilename(
                parent=dlg, title="Save Rationalized MIDI",
                defaultextension=".mid",
                filetypes=[("MIDI", "*.mid"), ("All", "*.*")])
            if not path:
                return
            try:
                self.song.to_mid(path)
                result_var.set(f"✓  Saved: {os.path.basename(path)}")
            except Exception as exc:
                result_var.set(f"Save error: {exc}")

        _tt(tk.Button(bfrm, text="Preview", bg="#1f6feb", fg="white",
                  activebackground="#388bfd", command=_preview, **bs),
            "Run the pipeline with the current settings and show/play the "
            "result. Does not change your file yet.").pack(side=tk.LEFT, padx=4)
        _tt(tk.Button(bfrm, text="Accept",  bg="#238636", fg="white",
                  activebackground="#2ea043", command=_accept,  **bs),
            "Commit the previewed result as your working score. "
            "Requires Preview to have been run first.").pack(side=tk.LEFT, padx=4)
        _tt(tk.Button(bfrm, text="Discard", bg="#21262d", fg=FG,
                  activebackground="#30363d", command=_discard, **bs),
            "Throw away the preview and go back to the original, "
            "unrationalized song.").pack(side=tk.LEFT, padx=4)
        _tt(tk.Button(bfrm, text="Save copy…", bg="#21262d", fg=MUTED,
                  activebackground="#30363d", command=_save_copy, **bs),
            "Save the previewed result as a new .mid file without "
            "changing your currently open song.").pack(side=tk.LEFT, padx=4)
        tk.Button(bfrm, text="Close",   bg="#21262d", fg=MUTED,
                  activebackground="#30363d", command=dlg.destroy, **bs).pack(side=tk.LEFT, padx=4)

        dlg.protocol("WM_DELETE_WINDOW", dlg.destroy)

    def _apply_bpm(self):
        self.song.bpm=self.bpm_var.get(); self.song.modified=True
        self._update_title(); self._update_status()

    # ── Track area ────────────────────────────────────────────────────────────
    def _build_track_area(self):
        # Vertical PanedWindow for three tiers — Score (dominant), Tracks,
        # Mixer. PanedWindow gives drag-to-resize sashes, proportional
        # defaults, and works correctly on any screen size. Previous grid +
        # fixed-height + pack_propagate approach caused a ~120px gap (Mixer
        # shell packing to bottom of its slot) and left Score with ~80px of
        # canvas on a 720px screen.
        container = tk.Frame(self.root, bg="#0d1117")
        container.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        vpane = tk.PanedWindow(container, orient=tk.VERTICAL, bg="#2a2a3a",
                               sashrelief=tk.FLAT, sashwidth=5,
                               sashpad=1, showhandle=False)
        vpane.pack(fill=tk.BOTH, expand=True)

        # ── Score slot (top, dominant) ────────────────────────────────────────
        self._score_dock_slot = tk.Frame(vpane, bg="#0d1117")
        vpane.add(self._score_dock_slot, minsize=120, stretch="always")

        # ── Tracks slot (middle, compact) ─────────────────────────────────────
        self._tracks_dock_slot = tk.Frame(vpane, bg="#0d1117")
        vpane.add(self._tracks_dock_slot, minsize=80, stretch="never")

        # ── Mixer slot (bottom, compact) ──────────────────────────────────────
        self._mixer_dock_slot = tk.Frame(vpane, bg="#0d1117")
        vpane.add(self._mixer_dock_slot, minsize=80, stretch="never")

        # Set initial pane sizes proportionally once the window is mapped.
        # 55% Score / 20% Tracks / 25% Mixer — the sash can be dragged freely.
        def _set_initial_sizes(event=None):
            h = vpane.winfo_height()
            if h < 50: return   # not yet laid out
            vpane.paneconfigure(self._score_dock_slot, height=max(120, int(h * 0.55)))
            vpane.paneconfigure(self._tracks_dock_slot, height=max(80,  int(h * 0.20)))
            vpane.paneconfigure(self._mixer_dock_slot,  height=max(80,  int(h * 0.25)))
            # Run once only
            vpane.unbind("<Map>")
        vpane.bind("<Map>", _set_initial_sizes)

        # ── Score DockablePane ────────────────────────────────────────────────
        def _score_factory(parent):
            sv = ScoreView(parent, self)
            self._score_view = sv
            return sv

        self._score_pane = DockablePane(
            app=self, dock_parent=self._score_dock_slot,
            content_factory=_score_factory,
            title="🎼 Score", floated=False, min_w=1100, min_h=400)

        # ── Tracks DockablePane ───────────────────────────────────────────────
        self._tracks_pane = DockablePane(
            app=self, dock_parent=self._tracks_dock_slot,
            content_factory=lambda parent: TracksView(parent, self),
            title="📋 Tracks", floated=False, min_w=700, min_h=200)

        # ── Mixer DockablePane ────────────────────────────────────────────────
        self._mixer_pane = DockablePane(
            app=self, dock_parent=self._mixer_dock_slot,
            content_factory=lambda parent: MixerView(parent, self),
            title="🎚 Mixer", floated=False, min_w=900, min_h=200)

    def _refresh_track_list(self):
        # v22v: only show tracks with notes; generic "Track N" names are
        # renumbered sequentially among visible tracks (see visible_tracks()
        # docstring for why).  _track_list_map translates a Listbox row
        # index back to the real self.song.tracks index — every consumer
        # of _selected_track_idx() (delete/rename/mute/solo/record-arm)
        # goes through that translation automatically, so none of them
        # needed to change.
        self.track_list.delete(0,tk.END)
        visible = self.visible_tracks()
        self._track_list_map = [orig_idx for orig_idx, tr, name in visible]
        for orig_idx, tr, display_name in visible:
            flags=("M" if tr.mute else " ")+("S" if tr.solo else " ")+("R" if orig_idx==self._rec_armed else " ")
            self.track_list.insert(tk.END,f"[{flags}] {display_name:<14} Ch{tr.channel+1:>2}  {GM_INSTRUMENTS[tr.program][:12]}")
        self._draw_overview()
        if getattr(self, "_mixer_pane", None) is not None:
            try: self._mixer_pane.refresh()
            except Exception: pass
        if self._score_view and self._score_view.winfo_exists():
            self._score_view._score_dirty = True
            if not self.transport.is_playing():
                self._score_view._draw()

    def _toggle_overview_mode(self):
        self._overview_rolling=not self._overview_rolling
        self._ov_mode_btn.configure(
            text="↔ Rolling" if self._overview_rolling else "⊞ Minimap")
        self._draw_overview()

    def _overview_row_h(self,idx): return self._overview_row_heights.get(idx,40)
    def _overview_y_of_row(self,idx):
        return 2+sum(self._overview_row_h(i) for i in range(idx))
    def _overview_total_h(self):
        return 2+sum(self._overview_row_h(i) for i in range(len(self.song.tracks)))

    def _overview_btn_press(self,event):
        if not self.song.tracks: return
        cy=self.overview.canvasy(event.y)
        for i in range(len(self.song.tracks)):
            y1=self._overview_y_of_row(i)+self._overview_row_h(i)
            if y1-6<=cy<=y1+3:
                self._overview_drag=(i,event.y_root,self._overview_row_h(i)); return

    def _overview_drag_motion(self,event):
        if self._overview_drag is None: return
        idx,sy,sh=self._overview_drag
        self._overview_row_heights[idx]=max(16,sh+event.y_root-sy)
        self._draw_overview()

    def _overview_btn_release(self,event): self._overview_drag=None

    def _on_overview_configure(self, event=None):
        """Debounced handler for the overview panel's <Configure> events.

        v22ze-60 fix: this used to be bound directly with no debouncing
        at all (unlike ScoreView's own <Configure> handler right next to
        this code, which already has the v22ze-38 debounce fix). Dragging
        to resize the MAIN window fires many rapid <Configure> events on
        every child widget as the layout re-flows, and _draw_overview()
        does a full, unthrottled redraw -- delete+recreate a line for
        EVERY note in EVERY track -- on each one, with no debounce to
        collapse a burst of resize events into a single repaint. For a
        large multi-track piece, dragging a window edge could fire this
        expensive O(total notes) redraw dozens of times per second,
        completely independent of whether anything is playing -- which
        matches a report of the whole system freezing during a plain
        window resize, with no MIDI playback involved at all. Debouncing
        this exactly like ScoreView's handler collapses a resize drag
        into one redraw after the dragging actually stops.
        """
        job = getattr(self, '_overview_configure_job', None)
        if job is not None:
            try:
                self.overview.after_cancel(job)
            except Exception:
                pass
        self._overview_configure_job = self.overview.after(50, self._deferred_overview_redraw)

    def _deferred_overview_redraw(self):
        self._overview_configure_job = None
        try:
            if self.overview.winfo_exists():
                self._draw_overview()
        except Exception:
            pass

    def _draw_overview(self):
        c=self.overview; c.delete("all")
        if not self.song.tracks: return
        W=c.winfo_width()
        if W<10: return
        total=max(self.song.total_ticks(),1)
        cols=["#1f6feb","#388bfd","#58a6ff","#79c0ff","#56d364",
              "#3fb950","#d29922","#f78166","#bc8cff","#79c0ff"]
        cur_tick=self.transport.position_ticks
        if self._overview_rolling:
            tpm=self.song.ticks_per_measure(); win=tpm*4
            t0=max(0,cur_tick-int(win*0.75)); t1=t0+win
            def tx(t): return (t-t0)/win*W
        else:
            t0,t1=0,total
            def tx(t): return (t/total)*W
        tot_h=self._overview_total_h()
        c.configure(scrollregion=(0,0,W,tot_h))
        for i,tr in enumerate(self.song.tracks):
            rh=self._overview_row_h(i); y=self._overview_y_of_row(i)
            c.create_rectangle(0,y,W,y+rh-2,fill="#161b22",outline="")
            c.create_rectangle(0,y+rh-3,W,y+rh-1,fill="#2d333b",outline="")
            col=cols[i%len(cols)]
            for note in tr.notes:
                if note.tick>t1 or note.tick+note.duration<t0: continue
                x1=tx(note.tick); x2=tx(note.tick+note.duration)
                ny=y+(1-note.pitch/127)*(rh-6)+3
                c.create_line(x1,ny,max(x1+2,x2),ny,fill=col,width=2)
            c.create_text(4,y+rh/2,text=tr.name,fill="#8b949e",
                          font=("TkDefaultFont",8),anchor="w")
        cx=tx(cur_tick)
        if 0<=cx<=W:
            c.create_line(cx,0,cx,tot_h,fill="#ff3333",width=2,dash=(4,3),tags="ov_playhead")

    def _overview_dbl_click(self,event):
        if not self.song.tracks: return
        H=self.overview.winfo_height(); n=len(self.song.tracks)
        idx=min(int(event.y/H*n),n-1)
        self.track_list.selection_clear(0,tk.END); self.track_list.selection_set(idx)
        self._open_piano_roll()

    def _track_ctx(self,event):
        # v22ze-56 fix: was tk.Menu — see TkPopupMenu's docstring.
        m=TkPopupMenu(self.root,tearoff=0)
        m.add_command(label="Score View",command=self._open_score_view)
        m.add_command(label="Piano Roll",command=self._open_piano_roll)
        m.add_command(label="MIDI List",command=self._open_list_view)
        m.add_separator()
        m.add_command(label="Rename",command=self._rename_track)
        m.add_command(label="Delete",command=self._del_track)
        m.add_separator()
        m.add_command(label="Mute/Unmute",command=self._toggle_mute)
        m.add_command(label="Solo/Unsolo",command=self._toggle_solo)
        m.add_command(label="Arm for Record", command=self._arm_record)
        m.add_separator()
        # Staff type — lets user change grand/single after initial choice
        idx = self._selected_track_idx()
        if idx is not None and idx < len(self.song.tracks):
            tr   = self.song.tracks[idx]
            mode = getattr(tr, "staff_mode", "auto")
            cur  = {"grand": "Grand staff", "single": "Single staff",
                    "auto":  "Auto (by program)"}.get(mode, mode)
            m.add_command(
                label=f"Staff type: {cur}  ▶ Change…",
                command=lambda t=tr: (
                    self._ask_staff_type(t),
                    self._refresh_track_list(),
                    self._score_view._draw() if self._score_view and
                        self._score_view.winfo_exists() else None
                ))
        _popup_menu_safe(m, event.x_root, event.y_root)

    # ── Status bar ────────────────────────────────────────────────────────────
    def _build_status(self):
        self.status_var=tk.StringVar()
        self._ration_var=tk.StringVar(value="")
        bar=tk.Frame(self.root,bg="#161b22"); bar.pack(fill=tk.X,side=tk.BOTTOM)
        tk.Label(bar,textvariable=self.status_var,anchor="w",
                 bg="#161b22",fg="#8b949e",font=("TkDefaultFont",9),padx=6,pady=3).pack(side=tk.LEFT,fill=tk.X,expand=True)
        self._ration_lbl=tk.Label(bar,textvariable=self._ration_var,anchor="e",
                 bg="#161b22",fg="#d29922",font=("TkDefaultFont",9,"bold"),padx=8,pady=3)
        self._ration_lbl.pack(side=tk.RIGHT)

    def _update_status(self):
        s=self.song; bars=s.total_ticks()/s.ticks_per_measure()
        out="MIDI OUT OK" if midi_io.MIDI_OUT_OK else "No MIDI out — run: timidity -B8,8 -Os -iA &"
        inp=" | MIDI IN OK" if midi_io.MIDI_IN_OK else ""
        self.status_var.set(f"BPM:{s.bpm}  {s.time_sig_num}/{s.time_sig_den}  "
                            f"Tracks:{len(s.tracks)}  Bars:{bars:.0f}  TPB:{s.ticks_per_beat}  {out}{inp}")
        # Rationalization indicator
        if hasattr(self,'_ration_var'):
            if self._is_rationalized:
                u=len(self._undo_stack); r=len(self._redo_stack)
                self._ration_var.set(f"🎵 Rationalized  ↩{u}  ↪{r}")
            else:
                self._ration_var.set("")

    def _update_title(self):
        nm  = os.path.basename(self.song.filename) if self.song.filename else "Untitled"
        mod = "*" if self.song.modified else ""
        self.root.title(f"{APP_TITLE}  —  {nm}{mod}")

    # ── File ──────────────────────────────────────────────────────────────────
    def _confirm_discard(self):
        if not self.song.modified: return True
        ans=messagebox.askyesnocancel("Unsaved Changes","Unsaved changes.\n\nSave before closing?",parent=self.root)
        if ans is None: return False
        if ans is True: self._save(); return not self.song.modified
        return True

    def _close_current(self):
        self.transport.stop()
        for w in list(self._open_windows):
            try:
                if w.winfo_exists(): w.destroy()
            except: pass
        self._open_windows.clear()
        # v22ze-62 fix: the two non-modal "work windows" -- Rationalize
        # Score and Score Setup -- are tracked in their own dedicated
        # attributes (singleton pattern: only one instance of each is
        # ever allowed open), not in self._open_windows, so the loop
        # above never touched them. Both hold a live reference back to
        # whatever song was open when they were created (rationalize
        # params, preview/accept state, measure-detail panels all
        # implicitly point at that song), so leaving either open across
        # a file close/switch means acting on it afterward is acting on
        # stale data tied to a song that's no longer current -- reported
        # directly as the Rationalize Score window staying open through
        # two subsequent file loads. A fresh file should mean a fresh
        # set of work windows, same as it already means a fresh
        # undo/redo stack (see below).
        for _dlg_attr in ('_rationalize_dlg', '_score_setup_dlg'):
            _dlg = getattr(self, _dlg_attr, None)
            if _dlg is not None:
                try:
                    if _dlg.winfo_exists():
                        _dlg.destroy()
                except Exception:
                    pass
                setattr(self, _dlg_attr, None)
        self.song=Song(); self.transport.song=self.song; self._rec_armed=0
        # v22ze-46 fix (presentation request 3): switching to a new/
        # different file left several pieces of state carried over from
        # the PREVIOUS file -- most importantly the undo/redo stacks,
        # which could let a stale RationalizationAction from the old
        # file get applied against the new one's completely different
        # note data. Also reset the rationalize preview/accept tracking
        # state, which is specific to whatever file was being worked on.
        self._undo_stack = []
        self._redo_stack = []
        self._original_song = None
        self._accepted_measures = set()
        self.play_btn.configure(text="▶  Play")
        self.rec_btn.configure(bg="#0f3320",fg="#3fb950")
        self._pos_var.set("Meas 1  Beat 1")
        self._refresh_track_list(); self._update_title(); self._update_status()
        # v22ze: closing a file without opening a new one previously left
        # the score view showing stale content from whatever was open
        # before -- same underlying cause as the open-file cursor/scroll
        # bug above (nothing tells the ScoreView pane to redraw on close
        # at all). Explicitly redraw against the new empty Song so it
        # falls back to the placeholder staves instead of showing the
        # old score.
        try:
            if self._score_view and self._score_view.winfo_exists():
                self._score_view._draw(cursor_tick=0)
        except Exception as _e:
            # v22ze-61 fix: see the matching note in _load_file — a bare
            # except here could hide a partial/inconsistent redraw and
            # leave stale geometry from the closed song behind.
            import sys as _sys
            print(f"[close] WARNING: score view redraw after close failed: {_e!r}",
                  file=_sys.stderr)

    def _new(self):
        if not self._confirm_discard(): return
        self._close_current()

    def _close(self):
        if not self._confirm_discard(): return
        self._close_current()

    def _open(self):
        if not self._confirm_discard(): return
        path=filedialog.askopenfilename(parent=self.root,title="Open MIDI",
            filetypes=[("MIDI","*.mid *.midi *.MID"),("All","*.*")])
        if path: self._close_current(); self._load_file(path)

    def _load_file(self,path):
        try:
            self.song=Song.from_mid(path); self.transport.song=self.song
            # v22ze-61 fix: reassigning transport.song did NOT reset
            # position_ticks/position_sec — a freshly loaded file inherited
            # whatever playback position was left over from the PREVIOUS
            # song (e.g. if the user stopped mid-piece, or closed a file
            # without returning to the start). Best case this just started
            # the new piece partway through unexpectedly; worst case the
            # leftover position was beyond the new (possibly shorter)
            # song's actual length entirely, which is also what let the
            # playback cursor end up reporting tick values past what the
            # new song's own total_ticks() covers -- exactly the "cursor
            # runs off the edge of the score, audio and display disagree"
            # symptom. A newly loaded file should always start at 0.
            self.transport.position_ticks = 0
            self.transport.position_sec   = 0.0
            total_notes = sum(len(t.notes) for t in self.song.tracks)
            print(f"[load] Loaded {len(self.song.tracks)} tracks, {total_notes} notes")
            print("[load] Original MIDI timing preserved (no auto-quantize)")
            self.bpm_var.set(self.song.bpm); self._refresh_track_list()
            self._update_title(); self._update_status()
            # Redraw score if open
            try:
                if self._score_view and self._score_view.winfo_exists():
                    # v22ze fix: _draw() with no cursor_tick draws NO
                    # playhead and never calls _scroll_to() -- both only
                    # happen inside `if cursor_tick is not None`. Leaving
                    # this as a bare _draw() meant opening a new file left
                    # the canvas scrolled to wherever the PREVIOUS file
                    # had been (or fully unscrolled with no cursor line
                    # at all), which looked like "the cursor got lost and
                    # there's no scrolling" when switching between scores.
                    # Passing 0 explicitly resets both to the start of
                    # the newly loaded song.
                    self._score_view._draw(cursor_tick=0)
                    # v22ze-65 fix: on the VERY FIRST file load of a fresh
                    # program session, the ScoreView's canvas was created
                    # during MidisoftStudio.__init__ -- before root.mainloop()
                    # ever started, meaning before the window manager has
                    # actually mapped the window. winfo_width()/height() can
                    # still report placeholder values at that point (Tk only
                    # settles real widget geometry once the window is truly
                    # mapped, which happens once the event loop is running).
                    # If the very first draw above computed cursor placement
                    # against those not-yet-real dimensions, the cursor could
                    # end up positioned somewhere never actually rendered --
                    # invisible, not merely "at 0". Every SUBSEQUENT file
                    # load in the same session doesn't have this problem,
                    # since the window has been mapped and settled for a
                    # while by then, matching the reported "only happens
                    # once, on first startup" pattern exactly. A cheap,
                    # low-risk self-heal: redraw again shortly after, once
                    # geometry has definitely settled either way.
                    self.root.after(150, lambda: (
                        self._score_view._draw(cursor_tick=self.transport.position_ticks)
                        if self._score_view and self._score_view.winfo_exists() else None))
            except Exception as _e:
                # v22ze-61 fix: this used to be a bare `except: pass` --
                # if the redraw threw partway through (e.g. one internal
                # cached value updated before the exception, another not),
                # the failure was completely invisible and could leave the
                # score view in a mixed, partially-stale state referencing
                # dimensions from the PREVIOUS song. Printing at least
                # means a failure here shows up instead of silently
                # explaining a later "cursor runs off the score" report.
                import sys as _sys
                print(f"[load] WARNING: score view redraw after load failed: {_e!r}",
                      file=_sys.stderr)
            mt=getattr(self.song,"midi_type","?"); n=len(self.song.tracks)
            self.root.title(f"{self.APP_NAME} — {os.path.basename(path)}  [Type {mt}, {n} tracks]")
            self.root.after(4000,self._update_title)
        except Exception as e: messagebox.showerror("Error",str(e),parent=self.root)

    def _save(self):
        if not self.song.filename: self._save_as()
        else:
            try: self.song.to_mid(self.song.filename); self._update_title()
            except Exception as e: messagebox.showerror("Save Error",str(e),parent=self.root)

    def _save_as(self):
        path=filedialog.asksaveasfilename(parent=self.root,title="Save MIDI",
            defaultextension=".mid",filetypes=[("MIDI","*.mid"),("All","*.*")])
        if path:
            try: self.song.to_mid(path); self._update_title()
            except Exception as e: messagebox.showerror("Error",str(e),parent=self.root)

    def _check_python_ly(self):
        """Return the ly module, or None if python-ly isn't installed.
        Shows a friendly 'not found' dialog if missing, matching
        _check_lilypond's pattern.
        """
        try:
            import ly.musicxml
            return ly.musicxml
        except ImportError:
            pass
        dlg = tk.Toplevel(self.root)
        dlg.title("python-ly Not Found")
        dlg.resizable(False, False)
        dlg.configure(bg="#0d1117")
        dlg.grab_set()
        dlg.attributes("-topmost", True)
        BG = "#0d1117"; FG = "#f0f6fc"; MUTED = "#8b949e"; WARN = "#d29922"
        tk.Label(dlg, text="⚠️  python-ly Not Found",
                 bg=BG, fg=WARN, font=("TkDefaultFont", 13, "bold")).pack(pady=(22, 8))
        tk.Label(dlg,
                 text="Saving as .musicxml requires the python-ly package,\n"
                      "which was not found on your system. Install it with:",
                 bg=BG, fg=FG, font=("TkDefaultFont", 10),
                 justify=tk.CENTER).pack(padx=28, pady=(0, 8))
        tk.Label(dlg, text="  pip install python-ly",
                 bg="#161b22", fg=MUTED, font=("TkFixedFont", 9),
                 justify=tk.LEFT, padx=12, pady=8).pack(fill=tk.X, padx=28, pady=(0, 14))
        tk.Button(dlg, text="OK", relief=tk.FLAT, padx=14, pady=6,
                  font=("TkDefaultFont", 10), cursor="hand2",
                  bg="#21262d", fg=FG, activebackground="#30363d",
                  command=dlg.destroy).pack(pady=(0, 18))
        self.root.wait_window(dlg)
        return None

    def _export_musicxml(self):
        """Save the current score as standard MusicXML, readable directly
        by MuseScore, Sibelius, Finale, and most other notation software.

        v22ze-69: routes through python-ly's musicxml writer, fed our own
        LilyPond text (the same to_ly() this app already uses for PDF
        export/printing) -- NOT a separate, from-scratch exporter. This
        was tested directly against real, verified failure before being
        used here: python-ly's parser does not implement the `\\absolute
        {...}` block our to_ly() wraps every part in (LilyPond itself
        treats bare pitches as absolute by default -- the wrapper is
        this app's own explicit-safety choice, not something LilyPond
        requires), and silently replaced un-parseable measures with
        rests instead of erroring -- real data loss, confirmed with a
        direct test before this feature existed. The fix is a narrow,
        LOCAL text substitution applied ONLY to the temporary copy fed
        to python-ly here (stripping "\\absolute {" -> "{"); the actual
        .ly file to_ly() writes elsewhere (used for PDF/printing) is
        completely untouched by this, so that path's already-verified
        behavior can't be affected by this change. Verified after the
        fix: real two-handed content with sharps, correct octaves, and
        correct durations all survive the round trip correctly.
        """
        ly_mod = self._check_python_ly()
        if ly_mod is None:
            return
        path = filedialog.asksaveasfilename(
            parent=self.root,
            title="Save as MusicXML",
            defaultextension=".musicxml",
            filetypes=[("MusicXML", "*.musicxml *.xml"), ("All", "*.*")])
        if not path:
            return
        import tempfile
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                ly_path = os.path.join(tmpdir, "score.ly")
                self.song.to_ly(ly_path)   # same generator PDF export uses
                with open(ly_path, encoding="utf-8") as f:
                    ly_text = f.read()
            # Local-only substitutions -- see docstrings. Only affect this
            # in-memory copy fed to python-ly, never the file to_ly() wrote.
            ly_text_for_xml = ly_text.replace("\\absolute {", "{")
            ly_text_for_xml = _strip_ly_block(ly_text_for_xml, "layout")
            writer = ly_mod.writer()
            writer.parse_text(ly_text_for_xml)
            xml_doc = writer.musicxml()
            # v22ze-70 fix: python-ly's writer emits <score-partwise
            # version="3.0"> but pairs it with a DOCTYPE declaring the
            # MusicXML 2.0 Partwise DTD -- a real internal mismatch (the
            # DOCTYPE says one schema, the root element claims another),
            # which is exactly the kind of inconsistency a strict
            # validating reader flags a file as invalid/corrupted over.
            # Correct the version attribute to match what the DOCTYPE
            # this library actually emits declares, rather than the
            # riskier alternative of trying to upgrade the DOCTYPE to a
            # newer DTD this library's output isn't verified to satisfy.
            xml_doc.tree.getroot().set("version", "2.0")
            _backfill_musicxml_staff_tags(xml_doc)
            xml_doc.write(path)
        except Exception as e:
            messagebox.showerror("MusicXML Export Failed", str(e), parent=self.root)
            return
        messagebox.showinfo(
            "MusicXML Saved",
            f"Saved to:\n{path}\n\n"
            "This is a standard .musicxml file — open it directly in "
            "MuseScore, Sibelius, Finale, or most other notation software.",
            parent=self.root)

    def _open_in_musescore(self):
        """Save a .mid file and instruct the user to open it in MuseScore.
        MuseScore's own MIDI importer produces better notation than we can
        generate directly, so we hand off rather than write .mscx ourselves.
        Kept as a secondary option alongside the direct .musicxml export
        (see _export_musicxml), since it's a genuinely different path --
        MuseScore's own MIDI import heuristics, rather than this app's own
        rationalized notation round-tripped through MusicXML.
        """
        import os, subprocess
        path = filedialog.asksaveasfilename(
            parent=self.root,
            title="Save MIDI for MuseScore",
            defaultextension=".mid",
            filetypes=[("MIDI", "*.mid *.midi"), ("All", "*.*")])
        if not path:
            return
        try:
            self.song.to_mid(path)
        except Exception as e:
            messagebox.showerror("Export failed", str(e), parent=self.root)
            return

        # Try to open MuseScore automatically; fall back to instructions.
        musescore_bins = ["mscore4", "musescore4", "mscore", "musescore", "MuseScore4"]
        launched = False
        for bin_name in musescore_bins:
            try:
                subprocess.Popen([bin_name, path])
                launched = True
                break
            except FileNotFoundError:
                continue

        if launched:
            messagebox.showinfo(
                "Opening in MuseScore",
                f"MuseScore is opening:\n{path}\n\n"
                "Use File → Export in MuseScore to save as .mscz if needed.",
                parent=self.root)
        else:
            messagebox.showinfo(
                "Open in MuseScore",
                f"MIDI saved to:\n{path}\n\n"
                "To open in MuseScore:\n"
                "  1. Launch MuseScore\n"
                "  2. File → Open → select the .mid file above\n"
                "  3. MuseScore will import and display the notation\n"
                "  4. File → Export to save as .mscz if needed\n\n"
                "(MuseScore was not found on PATH — you may need to open it manually.)",
                parent=self.root)

    def _check_lilypond(self):
        """Return the lilypond executable path, or None if not found.
        Shows the 'not found' dialog if missing.
        """
        import shutil, webbrowser
        lp = shutil.which("lilypond")
        if lp:
            return lp
        # Not found — show friendly dialog
        dlg = tk.Toplevel(self.root)
        dlg.title("LilyPond Not Found")
        dlg.resizable(False, False)
        dlg.configure(bg="#0d1117")
        dlg.grab_set()
        dlg.attributes("-topmost", True)
        BG = "#0d1117"; FG = "#f0f6fc"; MUTED = "#8b949e"; WARN = "#d29922"
        tk.Label(dlg, text="⚠️  LilyPond Not Found",
                 bg=BG, fg=WARN, font=("TkDefaultFont", 13, "bold")).pack(pady=(22, 8))
        tk.Label(dlg,
                 text="Printing and PDF export require LilyPond, a free\n"
                      "music engraving program, which was not found on\n"
                      "your system.  Would you like to download it?",
                 bg=BG, fg=FG, font=("TkDefaultFont", 10),
                 justify=tk.CENTER).pack(padx=28, pady=(0, 8))
        tk.Label(dlg,
                 text="  Linux  : pacman -S lilypond  /  apt install lilypond\n"
                      "  Windows: installer at lilypond.org\n"
                      "  macOS  : brew install lilypond",
                 bg="#161b22", fg=MUTED, font=("TkFixedFont", 9),
                 justify=tk.LEFT, padx=12, pady=8).pack(fill=tk.X, padx=28, pady=(0, 14))
        btn_frame = tk.Frame(dlg, bg=BG); btn_frame.pack(pady=(0, 18))
        bs = dict(relief=tk.FLAT, padx=14, pady=6,
                  font=("TkDefaultFont", 10), cursor="hand2")
        tk.Button(btn_frame, text="Open LilyPond Website",
                  bg="#238636", fg="white", activebackground="#2ea043",
                  command=lambda: [webbrowser.open("https://lilypond.org"), dlg.destroy()],
                  **bs).pack(side=tk.LEFT, padx=6)
        tk.Button(btn_frame, text="I'll Install It Myself",
                  bg="#21262d", fg=FG, activebackground="#30363d",
                  command=dlg.destroy, **bs).pack(side=tk.LEFT, padx=6)
        self.root.wait_window(dlg)
        return None

    def _ly_options_dialog(self):
        """Show export options dialog.  Returns (show_bar_numbers, staff_size)
        or None if the user cancelled.
        """
        dlg = tk.Toplevel(self.root)
        dlg.title("LilyPond Export Options")
        dlg.resizable(False, False)
        dlg.configure(bg="#0d1117")
        dlg.grab_set()
        BG = "#0d1117"; FG = "#f0f6fc"; MUTED = "#8b949e"

        tk.Label(dlg, text="🎼  LilyPond Export Options",
                 bg=BG, fg="#58a6ff",
                 font=("TkDefaultFont", 12, "bold")).pack(pady=(18, 12))

        frm = tk.Frame(dlg, bg=BG); frm.pack(padx=28, pady=4, anchor="w")

        # Bar numbers toggle
        bar_var = tk.BooleanVar(value=True)
        tk.Checkbutton(frm, text="Show bar numbers (at each system start)",
                       variable=bar_var,
                       bg=BG, fg=FG, selectcolor="#21262d",
                       activebackground=BG, activeforeground=FG,
                       font=("TkDefaultFont", 10)).pack(anchor="w", pady=4)

        # Staff size
        sfrm = tk.Frame(frm, bg=BG); sfrm.pack(anchor="w", pady=4)
        tk.Label(sfrm, text="Staff size (points):  ", bg=BG, fg=FG,
                 font=("TkDefaultFont", 10)).pack(side=tk.LEFT)
        size_var = tk.IntVar(value=16)
        size_spin = tk.Spinbox(sfrm, from_=12, to=20, increment=1,
                               textvariable=size_var, width=4,
                               bg="#21262d", fg=FG, buttonbackground="#30363d",
                               font=("TkDefaultFont", 10))
        size_spin.pack(side=tk.LEFT)
        tk.Label(sfrm,
                 text="  (16 = compact, 20 = LilyPond default)",
                 bg=BG, fg=MUTED, font=("TkDefaultFont", 9)).pack(side=tk.LEFT)

        tk.Frame(dlg, bg="#21262d", height=1).pack(fill=tk.X, padx=20, pady=12)

        result = [None]
        def _ok():
            result[0] = (bar_var.get(), size_var.get())
            dlg.destroy()
        def _cancel():
            dlg.destroy()

        btn_frame = tk.Frame(dlg, bg=BG); btn_frame.pack(pady=(0, 16))
        bs = dict(relief=tk.FLAT, padx=16, pady=6, font=("TkDefaultFont", 10))
        tk.Button(btn_frame, text="Export", bg="#238636", fg="white",
                  activebackground="#2ea043", command=_ok, **bs).pack(side=tk.LEFT, padx=6)
        tk.Button(btn_frame, text="Cancel", bg="#21262d", fg=FG,
                  activebackground="#30363d", command=_cancel, **bs).pack(side=tk.LEFT, padx=6)

        self.root.wait_window(dlg)
        return result[0]

    def _export_ly(self):
        if not self._check_lilypond():
            return
        opts = self._ly_options_dialog()
        if opts is None:
            return
        show_bar_numbers, staff_size = opts
        path = filedialog.asksaveasfilename(
            parent=self.root, title="Export LilyPond",
            defaultextension=".ly",
            filetypes=[("LilyPond", "*.ly"), ("All", "*.*")])
        if path:
            try:
                _src = self.song   # already swapped to rationalized version when active
                _src.to_ly(path,
                           show_bar_numbers=show_bar_numbers,
                           staff_size=staff_size)
                messagebox.showinfo("Exported",
                    f"Saved {os.path.basename(path)}\n\n"
                    f"Compile to PDF with:\n  lilypond {os.path.basename(path)!r}",
                    parent=self.root)
            except Exception as e:
                messagebox.showerror("Error", str(e), parent=self.root)

    def _print_score(self):
        """Export a temporary .ly file, compile to PDF with LilyPond,
        then open the PDF in the system viewer.  No file dialog — the
        temp files are cleaned up automatically.
        """
        import shutil, subprocess, tempfile, platform
        lp = self._check_lilypond()
        if not lp:
            return
        opts = self._ly_options_dialog()
        if opts is None:
            return
        show_bar_numbers, staff_size = opts
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                ly_path  = os.path.join(tmpdir, "score.ly")
                pdf_path = os.path.join(tmpdir, "score.pdf")
                self.song.to_ly(ly_path,
                                show_bar_numbers=show_bar_numbers,
                                staff_size=staff_size)  # uses active song
                result = subprocess.run(
                    [lp, "--pdf", "-o", os.path.join(tmpdir, "score"), ly_path],
                    capture_output=True, text=True)
                if result.returncode != 0 or not os.path.isfile(pdf_path):
                    err = result.stderr[-800:] if result.stderr else "(no output)"
                    messagebox.showerror("LilyPond Error",
                        f"LilyPond failed to compile the score:\n\n{err}",
                        parent=self.root)
                    return
                # Copy PDF to a stable temp location so the viewer can open it
                # after tmpdir context exits
                import shutil as _sh
                stable = tempfile.NamedTemporaryFile(
                    suffix=".pdf", delete=False,
                    prefix="midistudio_score_")
                stable.close()
                _sh.copy2(pdf_path, stable.name)

            # Open with system PDF viewer
            _plat = platform.system()
            if _plat == "Linux":
                subprocess.Popen(["xdg-open", stable.name])
            elif _plat == "Darwin":
                subprocess.Popen(["open", stable.name])
            elif _plat == "Windows":
                os.startfile(stable.name)
            else:
                subprocess.Popen(["xdg-open", stable.name])

        except Exception as exc:
            messagebox.showerror("Print Error", str(exc), parent=self.root)

    # ── Track ops ─────────────────────────────────────────────────────────────
    def _selected_track_idx(self):
        # v22v: track_list rows are now filtered/renumbered display rows
        # (see _refresh_track_list / visible_tracks) — translate the
        # Listbox row index through _track_list_map to get the real
        # index into self.song.tracks.  Falls back gracefully if the map
        # doesn't exist yet or is stale.
        sel = self.track_list.curselection()
        tmap = getattr(self, '_track_list_map', None)
        if sel:
            row = sel[0]
            if tmap and 0 <= row < len(tmap):
                return tmap[row]
            return row   # map unavailable — best effort, old behavior
        if tmap:
            return tmap[-1] if tmap else None
        return len(self.song.tracks) - 1 if self.song.tracks else None

    def _add_track(self):
        self.song.add_track(); self._refresh_track_list()
        self.track_list.selection_set(len(self.song.tracks)-1)
        self._update_title(); self._update_status()

    def _del_track(self):
        idx=self._selected_track_idx()
        if idx is None: return
        if messagebox.askyesno("Delete",f"Delete '{self.song.tracks[idx].name}'?",parent=self.root):
            self.song.delete_track(idx); self._refresh_track_list()
            self._update_title(); self._update_status()

    def _rename_track(self):
        idx=self._selected_track_idx()
        if idx is None: return
        v=simpledialog.askstring("Rename","New name:",parent=self.root,
                                  initialvalue=self.song.tracks[idx].name)
        if v: self.song.tracks[idx].name=v; self.song.modified=True; self._refresh_track_list(); self._update_title()

    def _toggle_mute(self):
        idx=self._selected_track_idx()
        if idx is not None: self.song.tracks[idx].mute=not self.song.tracks[idx].mute; self._refresh_track_list()

    def _toggle_solo(self):
        idx=self._selected_track_idx()
        if idx is not None: self.song.tracks[idx].solo=not self.song.tracks[idx].solo; self._refresh_track_list()

    def _arm_record(self):
        """Arm a track for MIDI recording.

        If the selected track has never had its staff type explicitly set
        (staff_mode == "auto" AND program number is 0, i.e. a blank new
        track), ask the user whether it is a keyboard instrument (grand
        staff) or a single-line instrument (single staff).  Tracks loaded
        from existing MIDI files already have a meaningful program number
        and are left on "auto" so that _uses_grand_staff() can decide.
        """
        idx = self._selected_track_idx()
        if idx is None:
            return
        tr = self.song.tracks[idx]
        # v22v: the record-armed track must remain visible in the list even
        # if it currently has zero notes (e.g. re-arming an existing but
        # empty track to record into) — otherwise arming it could make its
        # own row disappear from the list that was used to select it.
        tr.always_show = True
        # Ask for staff type only for blank tracks that have not been
        # explicitly set yet.  "auto" + program 0 means "freshly created".
        if getattr(tr, "staff_mode", "auto") == "auto" and tr.program == 0:
            self._ask_staff_type(tr)
        self._rec_armed = idx
        self._refresh_track_list()
        if self._score_view and self._score_view.winfo_exists():
            self._score_view._last_sr = None   # staff height may have changed
            self._score_view._draw()

    def _ask_staff_type(self, tr):
        """Show a small dialog to choose grand staff or single staff.

        Sets tr.staff_mode to "grand" or "single".  Called when arming a
        blank recording track whose staff type has not yet been decided.
        """
        dlg = tk.Toplevel(self.root)
        dlg.title("Staff Type")
        dlg.resizable(False, False)
        dlg.grab_set()
        dlg.transient(self.root)

        tk.Label(dlg,
            text="Choose staff layout for recording:",
            font=("TkDefaultFont", 10, "bold"),
            pady=8).pack(padx=16)

        choice = tk.StringVar(value="grand")

        opts = [
            ("grand",
             "Grand staff  (keyboard, piano, organ)",
             "Treble + Bass clef — two staves joined by a brace.\n"
             "Use for any two-handed keyboard instrument."),
            ("single",
             "Single staff  (guitar, violin, flute, voice …)",
             "One treble-clef staff.\n"
             "Use for any single-line or single-hand instrument."),
        ]
        for val, label, tip in opts:
            frm = tk.Frame(dlg)
            frm.pack(fill=tk.X, padx=16, pady=4)
            tk.Radiobutton(
                frm, text=label, variable=choice, value=val,
                font=("TkDefaultFont", 10),
                anchor="w").pack(anchor="w")
            tk.Label(
                frm, text=tip,
                font=("TkDefaultFont", 8), fg="#666",
                justify=tk.LEFT, anchor="w").pack(anchor="w", padx=20)

        def _ok():
            tr.staff_mode = choice.get()
            dlg.destroy()

        tk.Button(dlg, text="OK", command=_ok,
                  width=10).pack(pady=10)
        dlg.bind("<Return>", lambda e: _ok())
        dlg.bind("<Escape>", lambda e: dlg.destroy())

        # Centre dialog on main window
        dlg.update_idletasks()
        rx = self.root.winfo_rootx() + (self.root.winfo_width()  - dlg.winfo_width())  // 2
        ry = self.root.winfo_rooty() + (self.root.winfo_height() - dlg.winfo_height()) // 2
        dlg.geometry(f"+{rx}+{ry}")
        self.root.wait_window(dlg)

    def _quantize_armed_track(self):
        QuantizeDlg(self.root, self)

    def _separate_hands(self):
        """Standalone one-click hand separation.

        v22ze-65: user-requested standalone Edit menu action -- previously
        the DP hand-split algorithm was only reachable buried inside the
        full Rationalize Score dialog, mixed in with tempo detection,
        quantization, and cleanup the user might not want to touch just
        to split hands. Runs the SAME rationalize() pipeline with the
        timing-altering steps turned off (quantize_strength=0 -- 0=none
        per its own docstring -- plus tempo/timesig detection off), so
        this reassigns notes between Right Hand / Left Hand staves and
        nothing else changes. Reuses the exact apply/undo mechanism the
        Rationalize dialog's own Preview button already uses
        (_set_rationalized_song + RationalizationAction), so the
        Rationalize dialog's Discard button can still revert this too,
        and everything downstream (undo stack semantics, Score Setup's
        cleanup gate refresh) behaves exactly as it already does for a
        regular rationalization -- no new, parallel state-management
        path to keep in sync with that one.
        """
        if not self.song.tracks:
            messagebox.showinfo("Separate Hands", "No tracks to separate.",
                                parent=self.root)
            return
        if not messagebox.askyesno(
                "Separate Hands",
                "This will reassign notes between Right Hand and Left "
                "Hand staves based on pitch and hand span, without "
                "changing note timing. Continue?",
                parent=self.root):
            return
        import copy as _copy
        try:
            before = _copy.deepcopy(self.song.tracks)
            before_map = _copy.deepcopy(self.song.rationalized_measure_map)
            params = {
                'quantize_strength': 0,      # 0 = none -- timing untouched
                'detect_tempo':      False,
                'detect_timesig':    False,
                'preserve_hands':    False,  # actually run the DP split
            }
            result = self.song.rationalize(params=params)
            result = result.bake_to_score()
            after = _copy.deepcopy(result.tracks)
            after_map = _copy.deepcopy(result.rationalized_measure_map)
            action = RationalizationAction(
                description="Separate Hands",
                before_tracks=before, after_tracks=after,
                before_map=before_map, after_map=after_map)
            self._push_undo(action)
            self._set_rationalized_song(result)
            self.song.modified = True
            self._update_title()
            rh = result.tracks[0] if result.tracks else None
            lh = result.tracks[1] if len(result.tracks) > 1 else None
            rh_n = len(rh.notes) if rh else 0
            lh_n = len(lh.notes) if lh else 0
            messagebox.showinfo(
                "Separate Hands",
                f"Done.  RH: {rh_n} notes   LH: {lh_n} notes\n\n"
                "Open Setup \u25b8 Rationalize Score if you'd like to "
                "Discard and revert to the original.",
                parent=self.root)
        except Exception as exc:
            messagebox.showerror("Separate Hands", f"Error: {exc}",
                                 parent=self.root)

    def _combine_tracks(self):
        if len(self.song.tracks)<2:
            messagebox.showinfo("Combine","Need ≥2 tracks.",parent=self.root); return
        dlg=tk.Toplevel(self.root); dlg.title("Combine Tracks"); dlg.grab_set()
        tk.Label(dlg,text="Select tracks to combine:").pack(padx=10,pady=4)
        lb=tk.Listbox(dlg,selectmode=tk.MULTIPLE,height=min(10,len(self.song.tracks)))
        for t in self.song.tracks: lb.insert(tk.END,t.name)
        lb.pack(padx=10)
        def do():
            sel=lb.curselection()
            if len(sel)<2: messagebox.showwarning("Combine","Select ≥2.",parent=dlg); return
            base=self.song.tracks[sel[0]]
            for i in sorted(sel[1:],reverse=True):
                base.notes.extend(self.song.tracks[i].notes); self.song.tracks.pop(i)
            base.notes.sort(key=lambda n:n.tick); self.song.modified=True
            self._refresh_track_list(); self._update_title(); dlg.destroy()
        tk.Button(dlg,text="Combine",command=do).pack(pady=6)

    def _separate_channels(self):
        idx=self._selected_track_idx()
        if idx is None: return
        tr=self.song.tracks[idx]; chs={}
        for n in tr.notes: chs.setdefault(n.channel,[]).append(n)
        if len(chs)<=1: messagebox.showinfo("Separate","Only one channel.",parent=self.root); return
        ch0=sorted(chs)[0]; tr.notes=chs[ch0]; tr.channel=ch0
        for ch in sorted(chs)[1:]:
            nt=Track(name=f"{tr.name} Ch{ch+1}",channel=ch,program=tr.program); nt.notes=chs[ch]
            self.song.tracks.insert(idx+1,nt)
        self.song.modified=True; self._refresh_track_list(); self._update_title()

    # ── Transport ─────────────────────────────────────────────────────────────
    def _toggle_play(self):
        if self.transport.is_playing(): self._stop()
        else: self._play()

    def _play(self):
        if not self.song.tracks:
            messagebox.showinfo("Play","No tracks.",parent=self.root); return
        if not midi_io.MIDI_OUT_OK:
            messagebox.showwarning("No MIDI","Run: timidity -B8,8 -Os -iA &\nthen restart. (-B8,8 prevents audio buzz)",parent=self.root); return
        if self.transport.is_playing():
            self._stop(); return
        self.play_btn.configure(text="⏸  Pause")
        def _on_tick(tick):
            self.transport.position_ticks = tick
            # v22ze-58 fix: this used to call self._score_view._ui_tick_update
            # (and check .winfo_exists()) DIRECTLY -- but _on_tick_cb is
            # invoked from inside Transport._run_body()'s loop, which runs
            # on a BACKGROUND thread (see Transport.play/_run: a daemon
            # threading.Thread). Tkinter is not thread-safe; touching a
            # Canvas (winfo_exists, itemconfig -- both of which
            # _ui_tick_update does, to flash struck noteheads) from any
            # thread but the main Tk event-loop thread is undefined
            # behavior. This is the likely root cause of playback that
            # stutters for several beats, sometimes recovers, and can
            # eventually freeze the whole system hard enough to survive
            # Ctrl+Alt+Del: concurrent unsynchronized access to Tcl's
            # interpreter state from two threads can corrupt it badly
            # enough to wedge the X11 connection itself, not just this
            # process. Fix: do NOTHING Tk-related on the background
            # thread -- only schedule the real update via root.after(0,
            # ...), which marshals it onto the main thread the way
            # Tkinter actually expects. A pending-flag means a burst of
            # ticks during a dense passage collapses into at most one
            # queued update rather than flooding the main thread's event
            # queue with a growing backlog of stale ones.
            if not getattr(self, '_tick_update_pending', False):
                self._tick_update_pending = True
                def _do_update(t=tick):
                    self._tick_update_pending = False
                    try:
                        if self._score_view and self._score_view.winfo_exists():
                            self._score_view._ui_tick_update(t)
                    except Exception:
                        pass
                self.root.after(0, _do_update)
        self._on_tick_cb = _on_tick
        self.transport.play(on_tick=_on_tick)
    #=======================================

    def _stop(self):
        self.transport.stop()
        self.play_btn.configure(text="▶  Play")
        self.rec_btn.configure(bg="#0f3320", fg="#3fb950")   # green = idle
        # v22ze-25 (housekeeping item 5): don't leave a note stuck neon
        # green after stopping mid-flash.
        if self._score_view and self._score_view.winfo_exists():
            self._score_view.clear_flash_highlights()

    def _rewind_to_start(self):
        was_playing = self.transport.is_playing()
        self.transport.rewind()
        self._pos_var.set("Meas 1  Beat 1")
        if self._score_view and self._score_view.winfo_exists():
            self._score_view.update_cursor(0)
            self._score_view.clear_flash_highlights()
        try: self._draw_overview()
        except: pass
        if was_playing:
            # Resume playback from the start
            self.play_btn.configure(text="⏸  Pause")
            self.transport.play(self._on_tick_cb if hasattr(self,"_on_tick_cb") else None)
        else:
            self.play_btn.configure(text="▶  Play")

    def _seek(self,delta):
        self.transport.seek_measures(delta)
        if not self.transport.is_playing():
            meas=self.transport.position_ticks//self.song.ticks_per_measure()+1
            self._pos_var.set(f"Meas {meas}  Beat 1")

    def _offer_trim_leading_measures(self):
        # After recording, detect empty leading measures and offer to remove them.
        song = self.song
        if not song.tracks: return
        tpm = song.ticks_per_measure()
        # Find the tick of the very first note across all tracks
        first_tick = None
        for tr in song.tracks:
            for n in tr.notes:
                if first_tick is None or n.tick < first_tick:
                    first_tick = n.tick
        if first_tick is None: return   # nothing recorded
        empty_measures = int(first_tick // tpm)
        if empty_measures < 1: return   # first note is already in measure 1
        shift = empty_measures * tpm
        ans = messagebox.askyesno(
            "Trim leading silence",
            f"Recording starts {empty_measures} empty measure(s) before the first note.\n\n"
            f"Remove the {empty_measures} empty measure(s) and shift everything left?",
            parent=self.root)
        if not ans: return
        for tr in song.tracks:
            for n in tr.notes:
                n.tick = max(0, n.tick - shift)
            for ev in tr.events:
                ev.tick = max(0, ev.tick - shift)
        song.modified = True
        self._update_title()
        self._refresh_track_list()

    def _toggle_metronome(self):
        self._metro_on = not self._metro_on
        self.transport.set_metronome(self._metro_on)
        if self._metro_on:
            self._metro_btn.configure(text="Click: ON",  fg="#ffcc00", bg="#2a2a10")
        else:
            self._metro_btn.configure(text="Click: OFF", fg="#666666", bg="#21262d")

    def _toggle_record(self):
        if self.transport.is_recording():
            self._stop()
            self.rec_btn.configure(bg="#0f3320", fg="#3fb950")
            # Restore MIDI Thru to its pre-recording state
            if hasattr(self, '_thru_before_rec') and self._thru_before_rec:
                self.midi_thru_enabled.set(True)
                self._thru_before_rec = None
            self._refresh_track_list()
            # Offer to trim empty leading measures created by walk-to-piano delay
            self._offer_trim_leading_measures()
        else:
            if not self.song.tracks: messagebox.showinfo("Record","Add a track first.",parent=self.root); return
            if not midi_io.MIDI_OUT_OK: messagebox.showwarning("No MIDI","Run: timidity -B8,8 -Os -iA &",parent=self.root); return
            if not midi_io.MIDI_IN_OK:
                messagebox.showwarning("No MIDI Input",
                    "No MIDI input port found.\n\n"
                    "Check that your keyboard is connected, then\n"
                    "use Help → MIDI Info to verify ports.",
                    parent=self.root); return
            # Auto-arm the selected track if none armed yet
            if self._rec_armed is None or self._rec_armed >= len(self.song.tracks):
                idx = self._selected_track_idx()
                self._rec_armed = idx if idx is not None else 0
            # Auto-disable MIDI Thru during recording to prevent the
            # keyboard's app-side echo (keyboard local sound + TiMidity).
            # Restore the user's thru setting when recording stops.
            self._thru_before_rec = self.midi_thru_enabled.get()
            if self._thru_before_rec:
                self.midi_thru_enabled.set(False)
            self.play_btn.configure(text="⏸  Pause")
            self.rec_btn.configure(bg="#880000", fg="#ff4444")   # red = recording
            self.transport.record(self._rec_armed)

    # ── Windows ───────────────────────────────────────────────────────────────
    def _open_score_view(self):
        # Dismiss any open menu (File/Notation/…) by returning focus to the
        # root window — fixes the "File menu ghost" on Linux/X11.
        self.root.focus_set()
        # Score is a permanent dockable pane, built automatically at startup.
        # When docked it's already visible — clicking "Score View" must never
        # relocate it unexpectedly. Only act when it's floated, to bring the
        # existing window forward.
        if self._score_pane.floated:
            try:
                self._score_pane.shell.lift()
                self._score_pane.shell.focus_force()
            except Exception:
                pass
        # else: already docked and visible — nothing to do.

    def _open_piano_roll(self):
        self.root.focus_set()   # dismiss any open menu
        idx=self._selected_track_idx()
        if idx is None: messagebox.showinfo("Piano Roll","Select a track first.",parent=self.root); return
        # Bring existing window to front if already open for this track
        for w in self._open_windows:
            try:
                if isinstance(w, PianoRollView) and w.track_idx==idx and w.winfo_exists():
                    w.lift(); w.focus_force(); return
            except: pass
        pr = PianoRollView(self.root,self,idx)
        self._open_windows.append(pr)

    def _open_list_view(self):
        self.root.focus_set()   # dismiss any open menu
        idx = self._selected_track_idx()
        if idx is None:
            messagebox.showinfo("MIDI List", "Select a track first.",
                                parent=self.root); return
        # Clamp to valid range — guards against off-by-one on multi-track files
        n = len(self.song.tracks)
        idx = max(0, min(idx, n - 1)) if n else 0
        # If a List window is already open, bring it forward and
        # switch its track selector to the requested track.
        for w in self._open_windows:
            try:
                if isinstance(w, MidiListView) and w.winfo_exists():
                    w.track_idx = idx
                    w._refresh_track_list()
                    w._populate()
                    w._populate_events()
                    w.lift(); w.focus_force(); return
            except Exception:
                pass
        lv = MidiListView(self.root, self, idx)
        self._open_windows.append(lv)

    def _open_mixer(self):
        # The Mixer is now a permanent dockable pane (built at startup).
        # "Open Mixer" floats it out if docked, or brings it forward if
        # already floated — it can no longer be duplicated or fully closed.
        if self._mixer_pane.floated:
            try:
                self._mixer_pane.shell.lift()
                self._mixer_pane.shell.focus_force()
            except Exception:
                pass
        else:
            self._mixer_pane.toggle()

    def _song_settings(self): SongSettingsDlg(self.root,self)

    def _choose_midi_output(self):
        """Let the user switch MIDI output device without restarting.

        Lists all currently visible MIDI ports plus "FluidSynth (built-in)"
        if the fluidsynth module is available, regardless of whether each
        one was auto-detected as "trusted" — this is an explicit user
        action, so we don't second-guess their choice the way startup
        auto-detection does.
        """
        try:
            outs = mido.get_output_names()
        except Exception:
            outs = []

        options = list(outs)
        fs_available = False
        try:
            import fluidsynth
            fs_available = True
            options.append("FluidSynth (built-in)")
        except ImportError:
            pass

        if not options:
            messagebox.showinfo("MIDI Output Device",
                "No MIDI output ports were found, and FluidSynth is not "
                "available either.", parent=self.root)
            return

        dlg = tk.Toplevel(self.root)
        dlg.title("MIDI Output Device")
        dlg.configure(bg="#0d1117")
        dlg.resizable(False, False)
        dlg.lift(); dlg.focus_force()

        tk.Label(dlg, text="Choose MIDI Output Device",
                 bg="#0d1117", fg="#58a6ff",
                 font=("TkDefaultFont", 11, "bold")).pack(padx=20, pady=(16, 4))

        current = (midi_io._midi_out.name if midi_io._midi_out and hasattr(midi_io._midi_out, 'name')
                  else ("FluidSynth (built-in)" if midi_io._fs_active else options[0]))
        var = tk.StringVar(value=current if current in options else options[0])
        for name in options:
            tk.Radiobutton(dlg, text=name, variable=var, value=name,
                          bg="#0d1117", fg="white", selectcolor="#21262d",
                          activebackground="#0d1117", activeforeground="white",
                          anchor="w").pack(fill=tk.X, padx=24, pady=2)

        def _apply():
            chosen = var.get()
            try:
                if midi_io._midi_out:
                    try: midi_io._midi_out.close()
                    except Exception: pass
                    midi_io._midi_out = None

                if chosen == "FluidSynth (built-in)":
                    midi_io.MIDI_OUT_OK = False
                    if not midi_io._fs_active:
                        _init_fluidsynth()
                    _save_settings({"preferred_midi_port": None})
                else:
                    midi_io._midi_out   = mido.open_output(chosen)
                    midi_io.MIDI_OUT_OK = True
                    _save_settings({"preferred_midi_port": chosen})

                self._update_status()
                dlg.destroy()
            except Exception as exc:
                messagebox.showerror("MIDI Output Device",
                    f"Could not switch to '{chosen}':\n{exc}", parent=dlg)

        tk.Button(dlg, text="Use This", command=_apply,
                 bg="#238636", fg="white", relief=tk.FLAT,
                 padx=12, pady=4).pack(pady=(10, 16))

    def _midi_info(self):
        try: outs="\n  ".join(mido.get_output_names() or ["(none)"])
        except: outs="(error)"
        try: ins="\n  ".join(mido.get_input_names() or ["(none)"])
        except: ins="(error)"
        out_port = midi_io._midi_out.name if midi_io._midi_out and hasattr(midi_io._midi_out,'name') else "(none)"
        in_port  = midi_io._midi_in.name  if midi_io._midi_in  and hasattr(midi_io._midi_in, 'name') else "(none)"
        messagebox.showinfo("MIDI I/O",
            f"Output: {'OK  →  ' + out_port if midi_io.MIDI_OUT_OK else 'NOT CONNECTED'}\n\n"
            f"Input:  {'OK  →  ' + in_port  if midi_io.MIDI_IN_OK  else 'NOT CONNECTED'}\n\n"
            f"All output ports:\n  {outs}\n\n"
            f"All input ports:\n  {ins}\n\n"
            "Tip: run  pkill timidity && timidity -B8,8 -Os -iA &\n"
            "to ensure only one TiMidity instance is active.",parent=self.root)

    def _about(self):
        import webbrowser
        dlg = tk.Toplevel(self.root)
        dlg.title(f"About  v{APP_VERSION}")
        dlg.resizable(False, False)
        dlg.configure(bg="#0d1117")
        dlg.grab_set()

        BG = "#0d1117"; FG = "white"; MUTED = "#8b949e"

        tk.Label(dlg, text="🎹  Midi-Studio",
                 bg=BG, fg="#58a6ff",
                 font=("TkDefaultFont", 18, "bold")).pack(pady=(24, 4))
        tk.Label(dlg, text="Work-Alike — No code from the original",
                 bg=BG, fg=MUTED, font=("TkDefaultFont", 9)).pack()
        tk.Label(dlg, text=f"Version {APP_VERSION}   ·   {APP_TIMESTAMP}",
                 bg=BG, fg="#3fb950", font=("TkDefaultFont", 9)).pack(pady=(4, 14))

        tk.Frame(dlg, bg="#21262d", height=1).pack(fill=tk.X, padx=28)

        # ── Sterling Lions Club section ───────────────────────────────────────
        tk.Label(dlg, text="Supporting the Sterling Lions Club",
                 bg=BG, fg="#d29922",
                 font=("TkDefaultFont", 10, "italic")).pack(pady=(14, 4))

        lf = tk.Frame(dlg, bg=BG); lf.pack()
        for txt, url in [("🦁  Make a Donation", LIONS_DONATE_URL),
                         ("🌐  Visit Website",   LIONS_WEBSITE_URL)]:
            lk = tk.Label(lf, text=txt, bg=BG, fg="#58a6ff",
                          font=("TkDefaultFont", 10, "underline"),
                          cursor="hand2")
            lk.pack(pady=2)
            lk.bind("<Button-1>", lambda e, u=url: webbrowser.open(u))
            lk.bind("<Enter>", lambda e, w=lk: w.configure(fg="#79c0ff"))
            lk.bind("<Leave>", lambda e, w=lk: w.configure(fg="#58a6ff"))

        tk.Frame(dlg, bg="#21262d", height=1).pack(fill=tk.X, padx=28, pady=14)

        # ── Technical info ────────────────────────────────────────────────────
        info = (
            "Built in Python 3 + tkinter + mido + python-rtmidi\n"
            "Original inspiration: MidiSoft Studio4 © 1991–1995 MidiSoft\n"
            "Corporation, created by Raymond Bily\n"
            "Developed by Michael F. Winthrop in collaboration with Claude Sonnet 4.6\n\n"
            "Keys:  Space = Play / Stop     Home = Rewind\n"
            "       ← / → = Prev / Next measure\n"
            "       Ctrl+1/2/3 = Score / Piano Roll / List"
        )
        tk.Label(dlg, text=info, bg=BG, fg=MUTED,
                 font=("TkDefaultFont", 9), justify=tk.LEFT).pack(padx=28, pady=(0, 6))

        _credit_lf = tk.Frame(dlg, bg=BG); _credit_lf.pack(pady=(0, 10))
        for txt, url in [("MidiSoft.com", "https://midisoft.com/"),
                          ("MIDISOFT Studio 4.0 archive (vetusware.com)",
                           "https://vetusware.com/download/MIDISOFT%20Studio%204.0%204.0/?id=5666")]:
            _clk = tk.Label(_credit_lf, text=txt, bg=BG, fg=MUTED,
                            font=("TkDefaultFont", 8, "underline"),
                            cursor="hand2")
            _clk.pack()
            _clk.bind("<Button-1>", lambda e, u=url: webbrowser.open(u))
            _clk.bind("<Enter>", lambda e, w=_clk: w.configure(fg="#58a6ff"))
            _clk.bind("<Leave>", lambda e, w=_clk: w.configure(fg=MUTED))

        tk.Button(dlg, text="Close", command=dlg.destroy,
                  bg="#21262d", fg=FG,
                  activebackground="#30363d", activeforeground=FG,
                  relief=tk.FLAT, padx=20, pady=5,
                  font=("TkDefaultFont", 10)).pack(pady=14)

    def _on_quit(self):
        if getattr(self, "_shutting_down", False):
            return
        if not self._confirm_discard():
            return
        self._do_quit()

    def _do_quit(self):
        if getattr(self, "_shutting_down", False):
            return
        self._shutting_down = True

        import threading
        import time

        print("QUIT: begin shutdown")
        try:
            print("QUIT: active threads at start:")
            for t in threading.enumerate():
                try:
                    print(f"  thread name={t.name!r} daemon={t.daemon} alive={t.is_alive()}")
                except Exception as e:
                    print("  thread print exception:", e)
        except Exception as e:
            print("QUIT: enumerate threads failed:", e)

        try:
            print("QUIT: setting _midi_shutdown_evt")
            _midi_shutdown_evt.set()
        except Exception as e:
            print("QUIT: failed to set _midi_shutdown_evt:", e)

        try:
            if getattr(self, "_tick_job", None):
                print(f"QUIT: canceling _tick_job={self._tick_job}")
                self.root.after_cancel(self._tick_job)
                self._tick_job = None
        except Exception as e:
            print("QUIT: after_cancel failed:", e)

        for w in list(getattr(self, "_open_windows", [])):
            try:
                if w and w.winfo_exists():
                    print("QUIT: destroying auxiliary window", w)
                    w.destroy()
            except Exception as e:
                print("QUIT: auxiliary window destroy failed:", e)

        try:
            if getattr(self, "_score_view", None) and self._score_view.winfo_exists():
                print("QUIT: destroying score view")
                self._score_view.destroy()
        except Exception as e:
            print("QUIT: score view destroy failed:", e)

        # Try transport.stop() only; do not call transport.close() here.
        try:
            if getattr(self, "transport", None):
                print("QUIT: calling transport.stop()")
                t0 = time.time()
                self.transport.stop()
                print(f"QUIT: transport.stop() returned after {time.time() - t0:.3f}s")
        except Exception as e:
            print("QUIT: transport.stop() exception:", e)

        # Destroy root on Tk thread
        try:
            if self.root and self.root.winfo_exists():
                print("QUIT: destroying root")
                self.root.destroy()
        except Exception as e:
            print("QUIT: root.destroy() exception:", e)


#!/usr/bin/env python3
"""Main entry point for MIDI Studio application."""

import os
import sys
import time
import tkinter as tk
from tkinter import messagebox

# Import modules
from sys_platform import APP_FULL_NAME, APP_VERSION

# v22ze-138: the "Starting..." window is only worth showing on a slow
# computer.  The seconds the sounds took to load last time are kept in a
# tiny file; fast starts (< 3 s) skip the window.  No record = show it.
_LOAD_FILE = os.path.join(os.path.expanduser("~"), ".midi_studio_load_seconds")
_SLOW_SECONDS = 3.0


def _last_load_seconds():
    try:
        with open(_LOAD_FILE, encoding="utf-8") as f:
            return float(f.read().strip())
    except Exception:
        return None


def _save_load_seconds(seconds):
    try:
        with open(_LOAD_FILE, "w", encoding="utf-8") as f:
            f.write(f"{seconds:.2f}\n")
    except Exception:
        pass


def main():
    """Launch the MIDI Studio application."""
    root = tk.Tk()
    try:
        root.tk.call("tk", "scaling", 1.25)
    except Exception:
        pass

    try:
        # v22ze-126b: the message lives in its OWN small window; the main
        # root stays hidden and never gets a size/position of its own.
        root.withdraw()
        _msg = tk.Toplevel(root)
        _msg.title("MIDI Studio")
        _t_start = time.time()
        _last = _last_load_seconds()
        if _last is not None and _last < _SLOW_SECONDS:
            _msg.withdraw()  # fast computer: never shown
        _msg.configure(bg="#0d1117")
        _w, _h = 560, 130
        # v22ze-144: upper-left corner, so the synthesizer-choice window
        # (which opens in the middle) can never cover it.
        _msg.geometry(f"{_w}x{_h}+20+20")
        tk.Label(
            _msg,
            text="Starting MIDI Studio\u2026",
            bg="#0d1117",
            fg="#58a6ff",
            font=("TkDefaultFont", 18, "bold"),
        ).pack(pady=(24, 4))
        tk.Label(
            _msg,
            text="Loading sounds. This can take a while on older computers.",
            bg="#0d1117",
            fg="#e6edf3",
            font=("TkDefaultFont", 12),
            wraplength=520,
            justify=tk.CENTER,
        ).pack()
        _msg.update()

        # gui is imported only now: importing it loads the soundfont
        # (~12 s on old PCs), so the message above must already be showing.
        from gui import MidisoftStudio, SplashScreen

        _save_load_seconds(time.time() - _t_start)
        _msg.destroy()
        root.deiconify()

        # Initialize the main application window.
        # (MidisoftStudio.__init__ shows the "no synthesizer detected"
        # dialog itself, once the window exists.)
        app = MidisoftStudio(root)

        # Centres on the main window's monitor; stays until dismissed.
        SplashScreen(root, app)

        # Run the event loop
        root.mainloop()

    except Exception as e:
        messagebox.showerror("Fatal Error", f"Failed to start MIDI Studio:\n{e}")
        sys.exit(1)


if __name__ == "__main__":
    main()

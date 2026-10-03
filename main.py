#!/usr/bin/env python3
"""Main entry point for MIDI Studio application."""

import sys
import tkinter as tk
from tkinter import messagebox

# v22ze-126: gui is imported inside main(), AFTER the 'Starting...' window
# is on screen (importing gui loads the soundfont, ~12 s on old PCs).

# Import modules
from sys_platform import APP_FULL_NAME, APP_VERSION


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
        _msg.configure(bg="#0d1117")
        _w, _h = 440, 120
        _msg.geometry(
            f"{_w}x{_h}+{max(0, (_msg.winfo_screenwidth() - _w) // 2)}"
            f"+{max(0, (_msg.winfo_screenheight() - _h) // 3)}"
        )
        tk.Label(_msg, text="Starting MIDI Studio\u2026", bg="#0d1117",
                 fg="#58a6ff", font=("TkDefaultFont", 14, "bold")
                 ).pack(pady=(24, 4))
        tk.Label(_msg, text="Loading sounds. This can take a while on older computers.",
                 bg="#0d1117", fg="#8b949e", font=("TkDefaultFont", 9)
                 ).pack()
        _msg.update()

        from gui import MidisoftStudio, SplashScreen

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

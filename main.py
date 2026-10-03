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
        # v22ze-126: show a message first, then do the slow import.
        root.title("MIDI Studio")
        _w, _h = 440, 120
        root.geometry(
            f"{_w}x{_h}+{max(0, (root.winfo_screenwidth() - _w) // 2)}"
            f"+{max(0, (root.winfo_screenheight() - _h) // 3)}"
        )
        root.configure(bg="#0d1117")
        tk.Label(root, text="Starting MIDI Studio\u2026", bg="#0d1117",
                 fg="#58a6ff", font=("TkDefaultFont", 14, "bold")
                 ).pack(pady=(24, 4))
        tk.Label(root, text="Loading sounds. This can take a while on older computers.",
                 bg="#0d1117", fg="#8b949e", font=("TkDefaultFont", 9)
                 ).pack()
        root.update()

        from gui import MidisoftStudio, SplashScreen

        # Remove the message and let the real window size itself.
        for _child in root.winfo_children():
            _child.destroy()
        root.geometry("")

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

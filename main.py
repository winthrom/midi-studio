#!/usr/bin/env python3
"""Main entry point for MIDI Studio application."""

import sys
import tkinter as tk
from tkinter import messagebox

from gui import MidisoftStudio, SplashScreen

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

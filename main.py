#!/usr/bin/env python3
"""Main entry point for MIDI Studio application."""

import sys
import tkinter as tk
from tkinter import messagebox

# Import modules
from platform import APP_VERSION, APP_FULL_NAME
from midi_io import MIDI_OUT_OK, _fs_active, midi_input_subscribe, midi_input_unsubscribe
from gui import MidisoftStudio, _maybe_show_no_synth_dialog

def main():
    """Launch the MIDI Studio application."""
    root = tk.Tk()
    root.withdraw()
    
    try:
        # Initialize the main application window
        app = MidisoftStudio(root)
        
        # Show setup dialog if no synthesizer detected
        _maybe_show_no_synth_dialog(root)
        
        # Run the event loop
        root.deiconify()
        root.mainloop()
        
    except Exception as e:
        messagebox.showerror("Fatal Error", f"Failed to start MIDI Studio:\n{e}")
        sys.exit(1)

if __name__ == "__main__":
    main()

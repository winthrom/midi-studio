#!/usr/bin/env python3
"""MIDI I/O initialization, output, and input dispatching."""

import sys
import threading
import time

# Global state
MIDI_OUT_OK = False
MIDI_IN_OK  = False
_midi_out   = None
_midi_in    = None
_unverified_out_port_name = None
_midi_shutdown_evt = threading.Event()

# Listener dispatch
_midi_listeners = {}
_midi_listener_lock = threading.Lock()
_midi_dispatch_thread = None

def midi_input_subscribe(callback):
    """Register callback for all incoming MIDI messages."""
    token = id(callback)
    with _midi_listener_lock:
        _midi_listeners[token] = callback
    return token

def midi_input_unsubscribe(token):
    """Unregister a MIDI input callback."""
    with _midi_listener_lock:
        _midi_listeners.pop(token, None)

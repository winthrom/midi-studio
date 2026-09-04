#!/usr/bin/env python3
"""MIDI I/O initialization, output, and input dispatching."""

import sys
import threading
import time
import mido
import mido.backends.rtmidi
import queue as _queue

# Global state
MIDI_OUT_OK = False
MIDI_IN_OK  = False
_midi_out   = None
_midi_in    = None
_unverified_out_port_name = None
_midi_shutdown_evt = threading.Event()

# Settings and configuration
_SETTINGS_PATH = None  # Will be set by sys_platform module

# Listener dispatch
_midi_listeners = {}
_midi_listener_lock = threading.Lock()
_midi_dispatch_thread = None

# This module provides:
# - MIDI output routing (hardware/virtual ports or FluidSynth fallback)
# - MIDI input dispatching (single thread, multiple listeners)
# - Settings persistence for preferred MIDI ports
# - FluidSynth initialization as a software synthesizer fallback

def midi_input_subscribe(callback) -> int:
    """Register *callback(msg)* for all incoming MIDI messages.
    Returns an integer token; pass it to midi_input_unsubscribe to remove."""
    _start_dispatch_thread()
    token = id(callback)
    with _midi_listener_lock:
        _midi_listeners[token] = callback
    return token

def midi_input_unsubscribe(token: int):
    with _midi_listener_lock:
        _midi_listeners.pop(token, None)

_start_dispatch_thread()   # start immediately so thru works before any record

def _winfo_exists(widget) -> bool:
    # Safe winfo_exists() — returns False if the widget has been destroyed.
    try:


def midi_input_subscribe(callback):
    """Register callback for all incoming MIDI messages."""
    _start_dispatch_thread()
    token = id(callback)
    with _midi_listener_lock:
        _midi_listeners[token] = callback
    return token

def midi_input_unsubscribe(token):
    """Unregister a MIDI input callback."""
    with _midi_listener_lock:
        _midi_listeners.pop(token, None)

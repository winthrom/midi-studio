#!/usr/bin/env python3
"""Audio backend interface for MIDI Studio.  (v22ze-114)

One small interface (AudioBackend) with two implementations:

  MidiPortBackend    -- an external/system MIDI output port (TiMidity,
                        hardware, VirtualMIDISynth, CoreMIDI ...)
  FluidSynthBackend  -- the built-in, in-process FluidSynth synth

plus ONE module-level "active backend" that the rest of the app talks to:

    audio_backend.set_active(backend)
    audio_backend.send(mido_msg)        # what midi_io._send() will call
    audio_backend.ready()               # replaces MIDI_OUT_OK / _fs_active

This module imports nothing heavy (no mido, no fluidsynth, no tkinter) so it
can be tested anywhere.  As of v22ze-114 NOTHING calls it yet -- app behaviour
is unchanged; v22ze-115 switches midi_io.py / gui.py over.
"""
from __future__ import annotations

import sys

NUM_CHANNELS = 16
CC_SUSTAIN = 64
CC_ALL_NOTES_OFF = 123


class AudioBackend:
    """Interface + shared behaviour.  Subclasses implement the primitives."""

    name = "none"

    # ── lifecycle ────────────────────────────────────────────────────────
    def start(self) -> bool:
        """Make the backend ready.  Return True on success."""
        return self.is_ready()

    def stop(self) -> None:
        """Release resources.  Safe to call more than once."""

    def is_ready(self) -> bool:
        return False

    # ── primitives (override) ────────────────────────────────────────────
    def note_on(self, ch: int, note: int, vel: int) -> None:
        raise NotImplementedError

    def note_off(self, ch: int, note: int) -> None:
        raise NotImplementedError

    def cc(self, ch: int, control: int, value: int) -> None:
        raise NotImplementedError

    def program(self, ch: int, prog: int, bank: int = 0) -> None:
        raise NotImplementedError

    def set_master_volume(self, level: float) -> bool:
        """level 0.0-1.0.  Return True if the backend applied/sent it.
        Backends that cannot do this return False (never raise)."""
        return False

    # ── derived (shared) ─────────────────────────────────────────────────
    def pedal(self, ch: int, down: bool) -> None:
        self.cc(ch, CC_SUSTAIN, 127 if down else 0)

    def all_notes_off(self) -> None:
        for ch in range(NUM_CHANNELS):
            self.cc(ch, CC_ALL_NOTES_OFF, 0)

    def send(self, msg) -> None:
        """Dispatch a mido-style Message (uses .type/.channel/.note ...)."""
        t = msg.type
        if t == "note_on":
            if msg.velocity > 0:
                self.note_on(msg.channel, msg.note, msg.velocity)
            else:
                self.note_off(msg.channel, msg.note)
        elif t == "note_off":
            self.note_off(msg.channel, msg.note)
        elif t == "control_change":
            self.cc(msg.channel, msg.control, msg.value)
        elif t == "program_change":
            self.program(msg.channel, msg.program)
        # other message types (pitchwheel, sysex ...) are ignored, exactly
        # as midi_io._send() does today.


class MidiPortBackend(AudioBackend):
    """Send to a mido output port.

    port          an already-open mido output port (has .send / .close), or
    port_name +   a name plus `opener` (e.g. mido.open_output) used by start().
    opener
    msg_factory   builds a mido Message from (type, **kw); defaults to
                  mido.Message, imported lazily.
    """

    def __init__(self, port=None, port_name=None, opener=None, msg_factory=None):
        self._port = port
        self._port_name = port_name
        self._opener = opener
        self._msg_factory = msg_factory

    @property
    def name(self) -> str:  # type: ignore[override]
        if self._port_name:
            return self._port_name
        return getattr(self._port, "name", None) or "MIDI port"

    def _make(self, mtype, **kw):
        f = self._msg_factory
        if f is None:
            import mido  # lazy: keeps this module import-light

            f = mido.Message
        return f(mtype, **kw)

    def start(self) -> bool:
        if self._port is None and self._port_name and self._opener:
            try:
                self._port = self._opener(self._port_name)
            except Exception as exc:
                print(f"[audio] cannot open port {self._port_name!r}: {exc}",
                      file=sys.stderr)
                self._port = None
        return self.is_ready()

    def stop(self) -> None:
        port, self._port = self._port, None
        if port is not None:
            try:
                port.close()
            except Exception:
                pass

    def is_ready(self) -> bool:
        return self._port is not None

    def _out(self, mtype, **kw):
        self._port.send(self._make(mtype, **kw))

    def note_on(self, ch, note, vel):
        self._out("note_on", channel=ch, note=note, velocity=vel)

    def note_off(self, ch, note):
        self._out("note_off", channel=ch, note=note, velocity=0)

    def cc(self, ch, control, value):
        self._out("control_change", channel=ch, control=control, value=value)

    def program(self, ch, prog, bank=0):
        self._out("program_change", channel=ch, program=prog)

    def set_master_volume(self, level: float) -> bool:
        """Best effort: MIDI Universal Real-Time SysEx 'Master Volume'.
        Many synths honour it, some ignore it -- True means 'sent'."""
        if not self.is_ready():
            return False
        v = int(max(0.0, min(1.0, level)) * 16383)
        try:
            self._out("sysex", data=[0x7F, 0x7F, 0x04, 0x01, v & 0x7F, (v >> 7) & 0x7F])
            return True
        except Exception:
            return False


class FluidSynthBackend(AudioBackend):
    """Wrap an already-created, started pyfluidsynth Synth plus its soundfont
    id.  (Creating/starting the synth stays in midi_io._init_fluidsynth for
    now; v22ze-115 moves it in here.)"""

    name = "FluidSynth (built-in)"

    def __init__(self, synth, sfid):
        self._synth = synth
        self._sfid = sfid

    def is_ready(self) -> bool:
        return self._synth is not None and self._sfid is not None

    def stop(self) -> None:
        synth, self._synth = self._synth, None
        if synth is not None:
            try:
                synth.delete()
            except Exception:
                pass

    def note_on(self, ch, note, vel):
        self._synth.noteon(ch, note, vel)

    def note_off(self, ch, note):
        self._synth.noteoff(ch, note)

    def cc(self, ch, control, value):
        self._synth.cc(ch, control, value)

    def program(self, ch, prog, bank=0):
        self._synth.program_select(ch, self._sfid, bank, prog)

    def set_master_volume(self, level: float) -> bool:
        """0.0-1.0 maps directly to FluidSynth gain 0.0-1.0 (its own default
        is 0.2; MIDI Studio's is 0.7)."""
        if not self.is_ready():
            return False
        try:
            self._synth.setting("synth.gain", max(0.0, min(1.0, float(level))))
            return True
        except Exception:
            return False


# ── the single active backend ────────────────────────────────────────────
_active: AudioBackend | None = None


def set_active(backend: AudioBackend | None, stop_previous: bool = True) -> None:
    """Install `backend` as the active one (None = silence)."""
    global _active
    old, _active = _active, backend
    if stop_previous and old is not None and old is not backend:
        try:
            old.all_notes_off()
        except Exception:
            pass
        old.stop()


def get_active() -> AudioBackend | None:
    return _active


def ready() -> bool:
    b = _active
    return b is not None and b.is_ready()


def active_name() -> str:
    b = _active
    return b.name if b is not None and b.is_ready() else "(none)"


def send(msg) -> bool:
    """Route a mido Message to the active backend.  Never raises (this runs
    on realtime/MIDI threads).  Returns True if it was handed to a backend."""
    b = _active
    if b is None or not b.is_ready():
        return False
    try:
        b.send(msg)
        return True
    except Exception:
        return False


def set_master_volume(level: float) -> bool:
    b = _active
    return bool(b is not None and b.set_master_volume(level))


def shutdown() -> None:
    set_active(None)

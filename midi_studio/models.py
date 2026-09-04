"""
Core data models for MIDI Studio
- MeasureEvent: Unified timeline event (note or rest)
- MidiNote: A single note in a track
- MidiEvent: A MIDI message event
- Track: One MIDI track with notes and events
- Song: The complete composition
"""

from dataclasses import dataclass
from typing import List, Tuple, Optional, Dict, Any


@dataclass
class MeasureEvent:
    """Unified event in a measure timeline."""
    kind: str      # "note" or "rest"
    start: int     # tick
    duration: int  # ticks
    pitch: Optional[int] = None


class MidiNote:
    """A single note in a track."""
    __slots__ = ("tick", "pitch", "velocity", "duration", "channel", "articulation", "spelling")
    
    def __init__(self, tick, pitch, velocity, duration, channel=0, articulation="", spelling=""):
        self.tick = tick
        self.pitch = pitch
        self.velocity = velocity
        self.duration = duration
        self.channel = channel
        self.articulation = articulation
        self.spelling = spelling  # Explicit accidental override


class MidiEvent:
    """A MIDI message event."""
    __slots__ = ("tick", "msg")
    
    def __init__(self, tick, msg):
        self.tick = tick
        self.msg = msg


class Track:
    """One MIDI track: notes, events, and display properties.
    
    staff_mode controls rendering:
      "auto"   -- use program number (piano -> grand staff, else single)
      "grand"  -- always grand staff (treble + bass)
      "single" -- always single staff
    """
    
    def __init__(self, name="Track", channel=0, program=0, volume=100):
        self.name = name
        self.channel = channel
        self.program = program
        self.volume = volume
        self.mute = False
        self.solo = False
        self.staff_mode = "auto"  # "auto" | "grand" | "single"
        self.notes: List[MidiNote] = []
        self.events: List[MidiEvent] = []
        self.markings: List[MidiEvent] = []  # Notation-only (dynamics, etc.)
        self.always_show = False  # Always show in track list even if empty
    
    def note_count(self):
        return len(self.notes)


class Song:
    """The complete composition."""
    
    def __init__(self):
        self.ticks_per_beat = 480
        self.tempo = 500000  # microseconds per beat
        self.time_sig_num = 4
        self.time_sig_den = 4
        self.sig_changes: List[Tuple[int, int, int]] = []  # [(tick, num, den), ...]
        self.key_sig: str = "C"  # e.g. "C", "Bb", "F#", "Gm"
        self.tracks: List[Track] = []
        self.filename: Optional[str] = None
        self.modified = False
        self.rationalized_measure_map: Optional[List[Tuple]] = None
    
    @property
    def bpm(self):
        """Beats per minute."""
        return round(60_000_000 / self.tempo)
    
    @bpm.setter
    def bpm(self, v):
        self.tempo = int(60_000_000 / max(1, v))
    
    def ticks_per_measure(self):
        """Ticks per measure for current time signature."""
        return int(self.ticks_per_beat * 4 * self.time_sig_num / self.time_sig_den)
    
    def set_time_signature(self, num, den):
        """Set time signature and sync with sig_changes."""
        self.time_sig_num = num
        self.time_sig_den = den
        self.sig_changes = [
            (t, n, d) for (t, n, d) in (self.sig_changes or []) if t != 0
        ]
        self.sig_changes.insert(0, (0, num, den))
        self.modified = True
    
    def total_ticks(self):
        """Total ticks span of all notes."""
        mx = self.ticks_per_beat * 4
        for t in self.tracks:
            for n in t.notes:
                mx = max(mx, n.tick + n.duration)
        return mx
    
    def add_track(self, name=None):
        """Add a new track to the song."""
        n = len(self.tracks) + 1
        ch = min(15, len(self.tracks))
        if ch >= 9:
            ch += 1
        ch = ch % 16
        t = Track(name or f"Track {n}", channel=ch)
        t.always_show = True
        self.tracks.append(t)
        self.modified = True
        return t
    
    def delete_track(self, idx):
        """Delete a track by index."""
        if 0 <= idx < len(self.tracks):
            self.tracks.pop(idx)
            self.modified = True

#!/usr/bin/env python3
"""MIDI synthesis engine: data structures, quantization, and transport."""

import bisect
import math
import time
from dataclasses import dataclass


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

    def __init__(
        self, tick, pitch, velocity, duration, channel=0, articulation="", spelling=""
    ):
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
        self.key_sig: str = (
            "C"  # e.g. "C", "Bb", "F#", "Gm" — from MIDI key_signature meta
        )
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
        self.sig_changes = [
            (t, n, d) for (t, n, d) in (self.sig_changes or []) if t != 0
        ]
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
                elif msg.type in ("note_off",) or (
                    msg.type == "note_on" and msg.velocity == 0
                ):
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
                    elif msg.type in ("note_off",) or (
                        msg.type == "note_on" and msg.velocity == 0
                    ):
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
                mido.MetaMessage(
                    "key_signature", key=getattr(self, "key_sig", "C") or "C", time=0
                )
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
                    mido.Message(
                        "program_change", channel=tr.channel, program=tr.program, time=0
                    ),
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
                    ET.SubElement(
                        stub, "bracket", type="1", span="2", col="0", visible="1"
                    )
                    ET.SubElement(stub, "barLineSpan").text = "1"
                if n_staves == 2 and si == 1:
                    ET.SubElement(stub, "defaultClef").text = "F"

            ET.SubElement(part, "trackName").text = tr.name

            instr_id = _program_to_instrument_id(tr.program)
            instr = ET.SubElement(part, "Instrument", id=instr_id)
            ET.SubElement(instr, "longName").text = GM_INSTRUMENTS[tr.program]
            ET.SubElement(instr, "shortName").text = (
                GM_INSTRUMENTS[tr.program][:4] + "."
            )
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
                        ET.SubElement(keysig, "concertKey").text = str(
                            getattr(self, "key_sig", 0)
                        )
                        tsig = ET.SubElement(voice_el, "TimeSig")
                        ET.SubElement(tsig, "sigN").text = str(self.time_sig_num)
                        ET.SubElement(tsig, "sigD").text = str(self.time_sig_den)
                        tempo_el = ET.SubElement(voice_el, "Tempo")
                        ET.SubElement(tempo_el, "tempo").text = str(
                            round(self.bpm / 60.0, 6)
                        )
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
                            ET.SubElement(note_el, "tpc").text = str(
                                _midi_to_tpc(note.pitch)
                            )
                            ET.SubElement(note_el, "velocity").text = str(note.velocity)

                        cursor = tick + chord_dur

                    # Rest after last chord to end of measure
                    tail = me - cursor
                    if tail > 0:
                        _write_rest_sequence(voice_el, tail, tpb)

        # ── Serialise ─────────────────────────────────────────────────────
        raw = ET.tostring(root, encoding="unicode", xml_declaration=False)
        nice = minidom.parseString(
            '<?xml version="1.0" encoding="UTF-8"?>' + raw
        ).toprettyxml(indent="  ")
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
                        r
                        for r in ringing
                        if max(rn.tick + rn.duration for rn in r[1]) > ev_tick
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
            _pedal_duration_correct(
                all_notes, pedal_segs, voice_limit=p["pedal_voice_limit"]
            )
            _pedal_extended_count = n_extended_count[0]
            print(
                f"[rationalize] Pedal correction applied "
                f"({len(pedal_segs)} segments, {_pedal_extended_count} notes extended)",
                file=sys.stderr,
            )
        else:
            print(
                "[rationalize] No CC64 pedal events — "
                "skipping pedal duration correction",
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
            _chord_live = [
                n for n in _chord if getattr(n, "articulation", "") != "pedal_extended"
            ]
            if not _chord_live:
                continue  # every note here is pedal-extended -- see below
            _idx = _bisect_stac.bisect_right(_all_tick, _tick)
            _next_mean = next(
                (t for t in _all_tick[_idx:] if t - _tick > _arp_win), None
            )
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

        chord_groups, chord_src_ids = _collapse(
            all_notes, src_track_ids, p["arpeggio_window"]
        )
        chord_onsets = [g[0].tick for g in chord_groups]

        performed_tpb = tpb  # may be updated below
        if p["tempo_override"]:
            new_bpm = p["tempo_override"]
            performed_tpb = int(round(tpb * self.bpm / new_bpm))
        elif p["detect_tempo"]:
            bass_onsets = sorted(
                set(round(n.tick / 10) * 10 for n in all_notes if n.pitch < 55)
            )
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
                        if best_ratio is None or abs(ratio - 1.0) < abs(
                            best_ratio - 1.0
                        ):
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
                    detected_bpm = round(
                        60_000_000 / (performed_tpb * (self.tempo / tpb))
                    )
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
                    "[rationalize] Not enough bass onsets for tempo detection; "
                    "using song BPM.",
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
            detected_num, detected_den, ts_confidence, ts_note = (
                self.detect_time_signature()
            )
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
            chord_groups, chord_src_ids = _collapse(
                all_notes, src_track_ids, p["arpeggio_window"]
            )
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
        _extent = max(
            (n.tick + n.duration for group in q_groups for n in group), default=tpb * 4
        )
        new_mmap = _build_measure_map_core(
            tpb, [(0, detected_num, detected_den)], _extent
        )

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
                    diffs = [
                        pitches[k + 1] - pitches[k] for k in range(len(pitches) - 1)
                    ]
                    ascending = sum(1 for d in diffs if d > 0)
                    descending = sum(1 for d in diffs if d < 0)
                    directional = (
                        ascending >= len(diffs) // 2 or descending >= len(diffs) // 2
                    )

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
            print(
                f"[rationalize] Arpeggio groups detected: {n_groups}", file=sys.stderr
            )

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
                near_c4_count = sum(
                    1 for p in pitches_rh if abs(p - 60) <= NEAR_C4_RANGE
                )
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
                if (
                    pitches_lh
                    and min(pitches_lh) > 60
                    and pitches_rh
                    and min(pitches_rh) < 60
                ):
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
                if (
                    hasattr(ev, "msg")
                    and ev.msg.type == "control_change"
                    and ev.msg.control == 64
                ):
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
        iois = [
            ticks[i + 1] - ticks[i]
            for i in range(len(ticks) - 1)
            if ticks[i + 1] > ticks[i]
        ]
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
                "note": f"Weak IOI match (conf={best_conf:.2f}). "
                "Try setting BPM manually.",
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

            out_tr = Track(
                name=tr.name, channel=tr.channel, program=tr.program, volume=tr.volume
            )
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
                    if n.duration >= min_dur
                    or getattr(n, "articulation", "") == "grace"
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
        tpm = (
            mmap[0][5] if mmap else self.ticks_per_measure()
        )  # first measure tpm (for compat)
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
        _longest_name_len = max(
            (len(tr.name) for tr in _ly_track_list_preview), default=5
        )
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
            midi_pitch = (
                note_or_pitch.pitch
                if hasattr(note_or_pitch, "pitch")
                else note_or_pitch
            )
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

        def write_voice(
            f, vn, notes, clef_name, mmap, density_map=None, emit_spacing=False
        ):
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
                                (
                                    i
                                    for i, t in enumerate(tokens)
                                    if t and t.startswith("<")
                                ),
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
                stripped = re.sub(
                    r"\s*\b(right|rh)\b\s*", " ", name, flags=re.IGNORECASE
                ).strip()
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
                        base_name = (
                            tr.name.split(" - ")[-1] if " - " in tr.name else tr.name
                        )
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
                    write_voice(
                        f, vbase, notes, clef, mmap, _density_map, emit_spacing=True
                    )
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
        (ms, me)
        for m_idx, ms, me, _n, _d, _t in mmap
        if m_start_idx <= m_idx <= m_end_idx
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
        f"[quantize-legacy] '{track.name}': {len(track.notes)} notes "
        f"grid-snapped (div={div})",
        file=sys.stderr,
    )

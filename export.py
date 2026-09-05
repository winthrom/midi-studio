#!/usr/bin/env python3
"""Export utilities for MusicXML, LilyPond, and MIDI formats."""

import math
import sys
import xml.etree.ElementTree as ET
from xml.dom import minidom


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

#!/usr/bin/env python3
"""Audit: what do Separate Hands and Rationalize do to the SOUND of a MIDI file?

Usage (from the repo folder):   python3 audit_midi_pipeline.py "song.mid"

For the given file it runs, exactly as the app does,
   (A) Separate Hands   (rationalize with timing untouched, then bake_to_score)
   (B) Rationalize      (default settings, then bake_to_score)
saves each result with the app's own MIDI export, re-reads the saved files
with mido, and compares them with the ORIGINAL file note by note, in real
seconds (so tempo changes count).  Nothing in the repo is modified.
"""
import sys, os, io, tempfile, contextlib, statistics as st
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if os.environ.get("AUDIT_STUB_TK"):                 # sandbox without Tk only
    sys.path.insert(0, os.environ["AUDIT_STUB_TK"])
import mido
with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
    import gui

def notes_in_seconds(path):
    """[(pitch, start_s, end_s, velocity)], plus {cc_number: count}, programs."""
    mid = mido.MidiFile(path); tpb = mid.ticks_per_beat
    tempos = [(0, 500000)]
    for tr in mid.tracks:
        t = 0
        for m in tr:
            t += m.time
            if m.type == "set_tempo": tempos.append((t, m.tempo))
    tempos.sort()
    def to_s(tick):
        s, last_t, last_tempo = 0.0, 0, tempos[0][1]
        for tt, tp in tempos[1:]:
            if tt >= tick: break
            s += (tt - last_t) * last_tempo / 1e6 / tpb; last_t, last_tempo = tt, tp
        return s + (tick - last_t) * last_tempo / 1e6 / tpb
    notes, ccs, progs = [], {}, set()
    for tr in mid.tracks:
        t = 0; on = {}
        for m in tr:
            t += m.time
            if m.type == "note_on" and m.velocity > 0: on.setdefault((m.channel, m.note), []).append((t, m.velocity))
            elif m.type in ("note_off", "note_on"):
                k = (m.channel, m.note)
                if on.get(k):
                    t0, v = on[k].pop(0); notes.append((m.note, to_s(t0), to_s(t), v))
            elif m.type == "control_change": ccs[m.control] = ccs.get(m.control, 0) + 1
            elif m.type == "program_change": progs.add((m.channel, m.program))
    return sorted(notes, key=lambda n: (n[1], n[0])), ccs, progs

def compare(orig, new):
    """Match each original note to the unused new note of the same pitch with the nearest start."""
    by = {}
    for n in new: by.setdefault(n[0], []).append(n)
    used, d_on, d_dur, d_vel, lost = set(), [], [], [], 0
    for p, s, e, v in orig:
        c = [(abs(x[1] - s), i, x) for i, x in enumerate(by.get(p, [])) if (p, i) not in used and abs(x[1] - s) < 1.0]
        if not c: lost += 1; continue
        _, i, x = min(c); used.add((p, i))
        d_on.append((x[1] - s) * 1000); d_dur.append(((x[2] - x[1]) - (e - s)) * 1000); d_vel.append(x[3] - v)
    extra = len(new) - len(used)
    return d_on, d_dur, d_vel, lost, extra

def report(label, orig_n, orig_cc, orig_pr, path):
    new_n, new_cc, new_pr = notes_in_seconds(path)
    d_on, d_dur, d_vel, lost, extra = compare(orig_n, new_n)
    print(f"\n=== {label} ===")
    print(f"notes: original {len(orig_n)}   result {len(new_n)}   (unmatched original {lost}, extra in result {extra})")
    if d_on:
        a = [abs(x) for x in d_on]
        print(f"start time moved:  mean {st.mean(a):.1f} ms   max {max(a):.0f} ms   >10 ms: {sum(x>10 for x in a)} notes ({100*sum(x>10 for x in a)/len(a):.0f}%)")
        b = [abs(x) for x in d_dur]
        print(f"length changed:    mean {st.mean(b):.1f} ms   max {max(b):.0f} ms   >20 ms: {sum(x>20 for x in b)} notes ({100*sum(x>20 for x in b)/len(b):.0f}%)")
        print(f"velocity changed:  {sum(x!=0 for x in d_vel)} notes")
    print(f"total length: original {max(n[2] for n in orig_n):.2f} s   result {max(n[2] for n in new_n):.2f} s")
    print(f"pedal/controller events: original {dict(sorted(orig_cc.items()))}   result {dict(sorted(new_cc.items()))}")
    print(f"program changes: original {sorted(orig_pr)}   result {sorted(new_pr)}")

def main(path):
    orig_n, orig_cc, orig_pr = notes_in_seconds(path)
    print(f"file: {path}\noriginal: {len(orig_n)} notes, {max(n[2] for n in orig_n):.1f} s")
    tmp = tempfile.mkdtemp()
    new_way = hasattr(gui.Song, "rationalize_keep_audio")
    SH = {"quantize_strength": 0, "detect_tempo": False, "detect_timesig": False,
          "preserve_hands": False, "correct_pedal_durations": False}
    with contextlib.redirect_stderr(io.StringIO()):
        s0 = gui.Song.from_mid(path)
        p0 = os.path.join(tmp, "plain_roundtrip.mid"); s0.to_mid(p0)
        if new_way:
            sh = gui.Song.from_mid(path).rationalize_keep_audio(params=SH)
            ra = gui.Song.from_mid(path).rationalize_keep_audio(params=None)
        else:
            sh = gui.Song.from_mid(path).rationalize(params=SH).bake_to_score()
            ra = gui.Song.from_mid(path).rationalize(params=None).bake_to_score()
        p1 = os.path.join(tmp, "separate_hands.mid"); sh.to_mid(p1)
        p2 = os.path.join(tmp, "rationalize.mid"); ra.to_mid(p2)
    report("OPEN + SAVE, nothing else (baseline)", orig_n, orig_cc, orig_pr, p0)
    report("SEPARATE HANDS", orig_n, orig_cc, orig_pr, p1)
    report("RATIONALIZE (defaults)", orig_n, orig_cc, orig_pr, p2)

if __name__ == "__main__":
    if len(sys.argv) != 2: sys.exit(__doc__)
    main(sys.argv[1])

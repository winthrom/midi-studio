#!/usr/bin/env python3
"""Plain-assert tests for audio_backend (v22ze-114).  Run:  python3 test_audio_backend.py
(also collected by pytest).  Needs neither mido nor fluidsynth."""
from types import SimpleNamespace as NS
import audio_backend as ab


class FakePort:
    name = "Fake:port 1"
    def __init__(self): self.sent = []; self.closed = False
    def send(self, m): self.sent.append(m)
    def close(self): self.closed = True

def fake_msg(mtype, **kw): return NS(type=mtype, **kw)

class FakeSynth:
    def __init__(self): self.calls = []; self.deleted = False
    def noteon(self, *a): self.calls.append(("noteon",) + a)
    def noteoff(self, *a): self.calls.append(("noteoff",) + a)
    def cc(self, *a): self.calls.append(("cc",) + a)
    def program_select(self, *a): self.calls.append(("program_select",) + a)
    def setting(self, *a): self.calls.append(("setting",) + a)
    def delete(self): self.deleted = True


def setup_function(_=None): ab.shutdown()


def test_port_backend_passthrough():
    # v22ze-115: ports get every message exactly as given (incl. pitchwheel)
    p = FakePort(); b = ab.MidiPortBackend(port=p, msg_factory=fake_msg)
    assert b.is_ready() and b.name == "Fake:port 1"
    msgs = [NS(type="note_on", channel=1, note=60, velocity=90),
            NS(type="note_on", channel=1, note=60, velocity=0),
            NS(type="pitchwheel", channel=0, pitch=100),
            NS(type="sysex", data=[1, 2])]
    for m in msgs: b.send(m)
    assert p.sent == msgs and all(a is c for a, c in zip(p.sent, msgs))

def test_port_primitives():
    p = FakePort(); b = ab.MidiPortBackend(port=p, msg_factory=fake_msg)
    b.note_on(1, 60, 90); b.note_off(1, 60); b.cc(2, 7, 99); b.program(3, 40)
    assert [m.type for m in p.sent] == ["note_on", "note_off", "control_change", "program_change"]
    assert (p.sent[0].note, p.sent[0].velocity) == (60, 90)


def test_pedal_and_all_notes_off():
    p = FakePort(); b = ab.MidiPortBackend(port=p, msg_factory=fake_msg)
    b.pedal(0, True); b.pedal(0, False)
    assert [(m.control, m.value) for m in p.sent] == [(64, 127), (64, 0)]
    p.sent.clear(); b.all_notes_off()
    assert len(p.sent) == 16 and all(m.control == 123 for m in p.sent)

def test_port_start_opens_by_name_and_stop_closes():
    p = FakePort(); b = ab.MidiPortBackend(port_name="X", opener=lambda n: p, msg_factory=fake_msg)
    assert not b.is_ready() and b.start() and b.is_ready()
    b.stop(); assert p.closed and not b.is_ready(); b.stop()        # idempotent

def test_port_open_failure():
    def boom(n): raise OSError("nope")
    b = ab.MidiPortBackend(port_name="X", opener=boom, msg_factory=fake_msg)
    assert b.start() is False

def test_port_master_volume_sysex():
    p = FakePort(); b = ab.MidiPortBackend(port=p, msg_factory=fake_msg)
    assert b.set_master_volume(1.0)
    assert p.sent[0].type == "sysex" and p.sent[0].data == [0x7F, 0x7F, 4, 1, 0x7F, 0x7F]
    assert b.set_master_volume(0.0) and p.sent[1].data[-2:] == [0, 0]

def test_fluid_backend():
    s = FakeSynth(); b = ab.FluidSynthBackend(s, sfid=5)
    assert b.is_ready()
    b.send(NS(type="note_on", channel=0, note=64, velocity=80))
    b.send(NS(type="note_on", channel=0, note=64, velocity=0))
    b.send(NS(type="program_change", channel=4, program=19))
    b.pedal(1, True)
    assert s.calls == [("noteon", 0, 64, 80), ("noteoff", 0, 64),
                       ("program_select", 4, 5, 0, 19), ("cc", 1, 64, 127)]
    assert b.set_master_volume(0.5) and s.calls[-1] == ("setting", "synth.gain", 0.75)
    assert b.set_master_volume(9) and s.calls[-1][2] == ab.FLUIDSYNTH_GAIN_MAX   # clamped
    assert abs(ab.DEFAULT_MASTER_VOLUME * ab.FLUIDSYNTH_GAIN_MAX - 0.7) < 1e-9
    b.stop(); assert s.deleted and not b.is_ready() and not b.set_master_volume(.5)

def test_registry():
    assert not ab.ready() and ab.send(NS(type="note_on", channel=0, note=1, velocity=1)) is False
    assert ab.active_name() == "(none)"
    s1, s2 = FakeSynth(), FakeSynth()
    b1, b2 = ab.FluidSynthBackend(s1, 1), ab.FluidSynthBackend(s2, 1)
    ab.set_active(b1); assert ab.ready() and ab.active_name() == "FluidSynth (built-in)"
    assert ab.send(NS(type="note_on", channel=0, note=60, velocity=50))
    ab.set_active(b2)                                   # stops b1 (after all-notes-off)
    assert s1.deleted and not b1.is_ready() and not s2.deleted
    assert sum(1 for c in s1.calls if c[:3] == ("cc", 0, 123)) == 1
    assert ab.set_master_volume(0.3) and s2.calls[-1] == ("setting", "synth.gain", 0.3 * ab.FLUIDSYNTH_GAIN_MAX)
    ab.shutdown(); assert not ab.ready() and s2.deleted

def test_send_never_raises():
    class Bad(ab.AudioBackend):
        def is_ready(self): return True
        def note_on(self, *a): raise RuntimeError("boom")
    ab.set_active(Bad())
    assert ab.send(NS(type="note_on", channel=0, note=1, velocity=1)) is False


if __name__ == "__main__":
    n = 0
    for k, f in list(globals().items()):
        if k.startswith("test_"):
            setup_function(); f(); n += 1
    print(f"{n} tests passed")

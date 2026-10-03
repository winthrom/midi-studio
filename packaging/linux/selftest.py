#!/usr/bin/env python3
"""Headless check of what a build contains (no window is opened).
Run as:  MIDI-Studio-x86_64.AppImage --selftest      (exit 0 = all required OK)
"""
import os, sys, time

_T0 = time.time()   # when the selftest script itself started
ok = True


def line(label, good, detail="", required=True):
    global ok
    mark = "OK  " if good else ("FAIL" if required else "warn")
    if required and not good:
        ok = False
    print("[%s] %s%s  [+%.1fs]" % (mark, label, (": " + str(detail)) if detail else "",
                                   time.time() - _T0))


line("python", True, sys.version.split()[0])

try:
    import tkinter
    line("tkinter", True, "Tcl/Tk %s" % tkinter.TkVersion)
except Exception as e:
    line("tkinter", False, e)

try:
    import mido
    import mido.backends.rtmidi  # noqa: F401
    try:
        from importlib.metadata import version as _v
        _mv = _v("mido")
    except Exception:
        _mv = "?"
    line("mido + rtmidi backend", True, "mido %s" % _mv)
except Exception as e:
    line("mido + rtmidi backend", False, e)

try:
    import ly  # noqa: F401
    line("python-ly", True)
except Exception as e:
    line("python-ly", False, e)

try:
    import app_resources
    lib = app_resources.setup_fluidsynth_library()
    line("bundled libfluidsynth", lib is not None, lib or "none bundled (system one will be used)", required=False)
    sf = app_resources.find_bundled_soundfont()
    line("bundled soundfont", sf is not None, sf or "none bundled", required=False)
    try:
        import fluidsynth
        line("pyfluidsynth + libfluidsynth loads", True)
        if sf:
            # Load (decode) the soundfont WITHOUT opening any audio device.
            try:
                import time
                _s = fluidsynth.Synth()
                _dyn = os.environ.get("MIDI_STUDIO_DYNAMIC_SAMPLES") == "1"
                if _dyn:
                    _s.setting("synth.dynamic-sample-loading", 1)
                _t0 = time.time()
                _id = _s.sfload(sf)
                line("soundfont loads (SF3/Vorbis decoding)", _id != -1,
                     "%s in %.1fs (on-demand samples: %s)" % (
                         os.path.basename(sf), time.time() - _t0, "on" if _dyn else "off"))
                _s.delete()
            except Exception as e:
                line("soundfont loads (SF3/Vorbis decoding)", False, e)
    except Exception as e:
        line("pyfluidsynth + libfluidsynth loads", False, e, required=False)
except Exception as e:
    line("app_resources", False, e)

print("RESULT:", "PASS" if ok else "FAIL", " (script ran %.1fs; total wall time minus this = program start-up)"
      % (time.time() - _T0))
sys.exit(0 if ok else 1)

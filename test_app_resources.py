#!/usr/bin/env python3
"""Tests for app_resources (v22ze-116).  Run: python3 test_app_resources.py"""
import ctypes.util, os, sys, tempfile
import app_resources as ar


def _mk(root, rel, data=b"x"):
    p = os.path.join(root, rel); os.makedirs(os.path.dirname(p), exist_ok=True)
    open(p, "wb").write(data); return p

def _env(root):
    os.environ["MIDI_STUDIO_APP_DIR"] = root

def teardown():
    ar._undo_patch_for_tests(); os.environ.pop("MIDI_STUDIO_APP_DIR", None)


def test_nothing_bundled_changes_nothing():
    d = tempfile.mkdtemp(); real = ar.app_roots
    ar.app_roots = lambda: [d]                       # an empty app root
    try:
        before = ctypes.util.find_library
        assert ar.find_bundled_library() is None and ar.find_bundled_soundfont() is None
        assert ar.setup_fluidsynth_library() is None
        assert ctypes.util.find_library is before    # untouched
    finally:
        ar.app_roots = real; teardown()

def test_bundled_library_patch():
    d = tempfile.mkdtemp(); _env(d)
    name = ("libfluidsynth-3.dll" if sys.platform.startswith("win") else
            "libfluidsynth.3.dylib" if sys.platform == "darwin" else "libfluidsynth.so.3")
    p = _mk(d, "lib/" + name)
    assert ar.find_bundled_library() == p
    assert ar.setup_fluidsynth_library() == p
    for n in ("fluidsynth", "libfluidsynth", "fluidsynth-3", "libfluidsynth-3"):
        assert ctypes.util.find_library(n) == p
    orig = ar._orig_find_library
    assert ctypes.util.find_library("c") == orig("c")          # other libs untouched
    ar.setup_fluidsynth_library()                               # idempotent, no double wrap
    assert ar._orig_find_library is orig
    teardown()

def test_soundfont_preference():
    d = tempfile.mkdtemp(); _env(d)
    _mk(d, "sound/zzz.sf2"); _mk(d, "sound/other.sf3")
    assert ar.find_bundled_soundfont().endswith("other.sf3")   # sf3 beats sf2
    _mk(d, "sound/MuseScore_General.sf3")
    assert ar.find_bundled_soundfont().endswith("MuseScore_General.sf3")
    _mk(d, "sound/readme.txt")                                  # ignored
    teardown()

def test_frozen_roots():
    d = tempfile.mkdtemp()
    sys.frozen = True; sys._MEIPASS = d
    try:
        assert d in ar.app_roots()
        _mk(d, "sound/MuseScore_General.sf3")
        assert ar.find_bundled_soundfont().startswith(d)
    finally:
        del sys.frozen; del sys._MEIPASS; teardown()

def test_roots_deduplicated_and_env_first():
    here = os.path.dirname(os.path.abspath(ar.__file__)); _env(here)
    r = ar.app_roots(); assert r[0] == here and r.count(here) == 1
    teardown()


if __name__ == "__main__":
    n = 0
    for k, f in list(globals().items()):
        if k.startswith("test_"):
            f(); n += 1
    print(f"{n} tests passed")

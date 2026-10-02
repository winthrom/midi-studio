#!/usr/bin/env python3
"""Locate files that ship INSIDE the app (v22ze-116): a bundled libfluidsynth
and bundled soundfonts.  Import-light; safe to import anywhere.

Bundle layout (relative to an "app root"):
    lib/     native libraries   (libfluidsynth.so*, libfluidsynth-3.dll, libfluidsynth*.dylib)
    sound/   soundfonts         (MuseScore_General.sf3, ... .sf2)

App roots, in order (all are searched):
    1. $MIDI_STUDIO_APP_DIR       (override, for packaging tests / debugging)
    2. PyInstaller/Briefcase-frozen bundle: sys._MEIPASS, then the exe's folder
    3. the folder containing this file  (plain source checkout, AppImage AppDir)

When NO bundled library exists, setup_fluidsynth_library() does nothing at
all, so an ordinary system-installed FluidSynth behaves exactly as before.
"""
from __future__ import annotations

import ctypes.util
import glob
import os
import sys

_FLUID_NAMES = {
    "fluidsynth", "fluidsynth-3", "libfluidsynth",
    "libfluidsynth-3", "libfluidsynth-2", "libfluidsynth-1",
}
_LIB_PATTERNS = {
    "linux": ["libfluidsynth.so*"],
    "darwin": ["libfluidsynth*.dylib"],
    "win32": ["libfluidsynth-3.dll", "libfluidsynth*.dll", "fluidsynth.dll"],
}
_orig_find_library = None  # set once we patch


def app_roots() -> list[str]:
    roots = []
    env = os.environ.get("MIDI_STUDIO_APP_DIR")
    if env:
        roots.append(env)
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            roots.append(meipass)
        roots.append(os.path.dirname(os.path.abspath(sys.executable)))
    roots.append(os.path.dirname(os.path.abspath(__file__)))
    seen, out = set(), []
    for r in roots:
        if r not in seen:
            seen.add(r)
            out.append(r)
    return out


def find_bundled_library() -> str | None:
    """Path of a bundled libfluidsynth for this OS, or None."""
    key = "win32" if sys.platform.startswith("win") else (
        "darwin" if sys.platform == "darwin" else "linux")
    for root in app_roots():
        for sub in ("lib", "."):
            for pat in _LIB_PATTERNS[key]:
                hits = sorted(glob.glob(os.path.join(root, sub, pat)))
                hits = [h for h in hits if os.path.isfile(h)]
                if hits:
                    return hits[0]
    return None


def find_bundled_soundfont() -> str | None:
    """Best bundled soundfont: MuseScore_General first, then any .sf3, then .sf2."""
    for root in app_roots():
        for sub in ("sound", "soundfonts"):
            d = os.path.join(root, sub)
            if not os.path.isdir(d):
                continue
            files = sorted(f for f in os.listdir(d)
                           if f.lower().endswith((".sf3", ".sf2"))
                           and os.path.isfile(os.path.join(d, f)))
            if not files:
                continue
            files.sort(key=lambda f: (
                "musescore" not in f.lower(),   # MuseScore_General first
                not f.lower().endswith(".sf3"),  # then compressed sf3
                f.lower()))
            return os.path.join(d, files[0])
    return None


def setup_fluidsynth_library() -> str | None:
    """Make `import fluidsynth` (pyfluidsynth) use a bundled libfluidsynth.

    pyfluidsynth looks the library up with ctypes.util.find_library at import
    time, so this MUST run before the first `import fluidsynth`.  Returns the
    library path it installed, or None if there is no bundled library (then
    nothing is changed).

    The library's OWN dependencies (glib, sndfile, ...) are found by the
    dynamic loader, not by us: on Linux the AppImage launcher must set
    LD_LIBRARY_PATH (or the libs must carry an $ORIGIN rpath); on macOS the
    dylibs need @loader_path install names; on Windows the DLLs sit beside it
    and we add that folder with os.add_dll_directory + PATH.
    """
    global _orig_find_library
    lib = find_bundled_library()
    if lib is None:
        return None
    libdir = os.path.dirname(lib)
    if sys.platform.startswith("win"):
        try:
            os.add_dll_directory(libdir)  # Python 3.8+
        except (AttributeError, OSError):
            pass
        os.environ["PATH"] = libdir + os.pathsep + os.environ.get("PATH", "")
    if _orig_find_library is None:
        _orig_find_library = ctypes.util.find_library

    def _patched(name, _orig=_orig_find_library, _lib=lib):
        if name in _FLUID_NAMES:
            return _lib
        return _orig(name)

    ctypes.util.find_library = _patched
    return lib


def _undo_patch_for_tests() -> None:
    """Restore ctypes.util.find_library (tests only)."""
    global _orig_find_library
    if _orig_find_library is not None:
        ctypes.util.find_library = _orig_find_library
        _orig_find_library = None

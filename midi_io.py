#!/usr/bin/env python3
"""MIDI I/O initialization, output, and input dispatching.

Provides:
- MIDI output routing (hardware/virtual ports or FluidSynth fallback)
- MIDI input dispatching (single thread, multiple listeners)
- Settings persistence for preferred MIDI ports
- FluidSynth initialization as a software synthesizer fallback
"""

from __future__ import annotations

import json
import os
import platform
import sys
import threading
import time

import mido
import mido.backends.rtmidi

try:
    import mido
    import mido.backends.rtmidi
except ImportError:
    mido = None

# MIDI I/O initialisation
# ─────────────────────────────────────────────────────────────────────────────
import app_resources  # v22ze-116: bundled-library / bundled-soundfont lookup

# v22ze-116: must run BEFORE anything imports pyfluidsynth (it finds
# libfluidsynth via ctypes.util.find_library at import time).  No-op unless a
# libfluidsynth is bundled next to the app.
app_resources.setup_fluidsynth_library()

import audio_backend  # v22ze-115: single routing point for all output
from audio_backend import FluidSynthBackend, MidiPortBackend

MIDI_OUT_OK = False
MIDI_IN_OK = False
_midi_out = None
_midi_in = None
_unverified_out_port_name = None  # v22w: candidate port, not yet trusted
_midi_shutdown_evt = threading.Event()

# ── Simple settings persistence (v22z-2) ────────────────────────────────────
# Minimal, self-contained — just remembers the user's chosen MIDI output
# port across sessions.  Not a general preferences system.
import json as _settings_json

_SETTINGS_PATH = os.path.expanduser("~/.midistudio_settings.json")


def _load_settings():
    try:
        with open(_SETTINGS_PATH, "r") as f:
            return _settings_json.load(f)
    except Exception:
        return {}


def _save_settings(d):
    try:
        with open(_SETTINGS_PATH, "w") as f:
            _settings_json.dump(d, f)
    except Exception as e:
        print(f"[Settings] Could not save: {e}", file=sys.stderr)


# ── TiMidity launch flags ─────────────────────────────────────────────────────
# -iA          : ALSA sequencer server mode
# -B8,8        : 8 buffer fragments of 8192 samples — eliminates the 60-80 Hz
#                underrun buzz that occurs with the default tiny buffer
# -Os          : ALSA audio output (not OSS)
# -s 44100     : explicit sample rate to match ALSA default and prevent resampling
# --reverb=d   : disable reverb (reduces CPU → fewer underruns on slow machines)
# --chorus=d   : same for chorus
TIMIDITY_ARGS = [
    "-iA",
    "-B8,8",
    "-Os",
    "-s",
    "44100",
    "--reverb=d",
    "--chorus=d",
    "-A150",  # v22ze-113: amplification 150% (TiMidity default is 70)
]
TIMIDITY_HINT = "timidity " + " ".join(TIMIDITY_ARGS)

_timidity_proc = None  # subprocess.Popen handle if we launched it ourselves

# ─────────────────────────────────────────────────────────────────────────────
# FluidSynth soft-synth backend
# Used as a fallback when no MIDI output port (TiMidity, VirtualMIDISynth,
# CoreMIDI virtual port, etc.) is found by _init_midi().
# Requires:  pip install pyfluidsynth --break-system-packages
# The native library (libfluidsynth.so / fluidsynth.dll / libfluidsynth.dylib)
# must be installed separately — we never bundle it.
# ─────────────────────────────────────────────────────────────────────────────

_fs_synth = None  # fluidsynth.Synth instance, or None
_fs_sfid = None  # SoundFont ID returned by fs.sfload()
_fs_active = False  # True once FluidSynth is ready to receive notes

# v22ze-31 (housekeeping: setup guidance): WHY FluidSynth wasn't set up,
# in plain language for the GUI dialog -- not just the stderr prints,
# which an average user launching the app by double-clicking (not from
# a terminal) never sees at all. One of:
#   "no_binding"   -- pyfluidsynth not pip-installed
#   "no_soundfont" -- pyfluidsynth is fine, no .sf2 file found anywhere
#   "no_driver"    -- pyfluidsynth + soundfont both fine, but every
#                      audio driver we tried failed to start (usually
#                      means the audio server itself isn't reachable)
#   "load_failed"  -- soundfont file found but fs.sfload() rejected it
#   None           -- FluidSynth was never even attempted (shouldn't
#                      happen in practice, but keeps the dialog logic simple)
# v22ze-112: the "built-in FluidSynth" choice, as offered in the startup
# window and stored in settings when the user ticks "Remember".
FLUIDSYNTH_BUILTIN = "FluidSynth (built-in)"


def _fluidsynth_importable():
    """v22ze-112: True if pyfluidsynth (and libfluidsynth) can be imported,
    i.e. built-in FluidSynth is worth offering as a startup choice."""
    try:
        import fluidsynth  # noqa: F401
        return True
    except Exception:
        return False


_fs_fail_reason = None
_fs_fail_detail = ""  # the actual exception text, for the "Show details" expander
_fs_driver = None  # v22ze-117: name of the audio driver that really opened


def _detect_linux_distro():
    """Best-effort Linux distro family, for showing ONE relevant install
    command instead of a wall of every distro's syntax. Returns one of
    'arch', 'debian', 'fedora', 'suse', or None (unknown/non-Linux) --
    None falls back to showing all of them."""
    if platform.system() != "Linux":
        return None
    try:
        with open("/etc/os-release") as f:
            text = f.read().lower()
    except OSError:
        return None
    # id_like often carries the useful family info even on derivative
    # distros (e.g. Manjaro says ID=manjaro but ID_LIKE=arch).
    for family, needles in (
        ("arch", ("id=arch", "id_like=arch", "manjaro", "endeavouros")),
        ("debian", ("id=debian", "id=ubuntu", "id_like=debian", "mint")),
        (
            "fedora",
            ("id=fedora", "id=rhel", "id=centos", "id_like=fedora", "id_like=rhel"),
        ),
        ("suse", ("id=opensuse", "id_like=suse", "suse")),
    ):
        if any(n in text for n in needles):
            return family
    return None


# Common SoundFont search paths, ordered by preference / file size
_SF2_SEARCH_PATHS = [
    # Arch / EndeavourOS / Manjaro
    "/usr/share/soundfonts/default.sf2",
    "/usr/share/soundfonts/FluidR3_GM.sf2",
    "/usr/share/soundfonts/GeneralUser_GS.sf2",
    "/usr/share/soundfonts/TimGM6mb.sf2",
    # Debian / Ubuntu / Mint
    "/usr/share/sounds/sf2/FluidR3_GM.sf2",
    "/usr/share/sounds/sf2/TimGM6mb.sf2",
    # Fedora / RHEL
    "/usr/share/fluidsynth/FluidR3_GM.sf2",
    # macOS (Homebrew)
    "/opt/homebrew/share/sounds/sf2/FluidR3_GM.sf2",
    "/usr/local/share/sounds/sf2/FluidR3_GM.sf2",
    # Windows (common manual install locations)
    r"C:\soundfonts\FluidR3_GM.sf2",
    r"C:\soundfonts\GeneralUser_GS.sf2",
    r"C:\Program Files\FluidSynth\FluidR3_GM.sf2",
]


def _find_soundfont():
    """Return the soundfont to use, or None.

    v22ze-116 order: 1) "soundfont" path saved in the settings file (a user
    override), 2) a soundfont bundled with the app (<app>/sound/), 3) the
    system locations below (unchanged behaviour)."""
    import glob

    _user_sf = _load_settings().get("soundfont")
    if isinstance(_user_sf, str) and os.path.isfile(os.path.expanduser(_user_sf)):
        return os.path.expanduser(_user_sf)
    _bundled_sf = app_resources.find_bundled_soundfont()
    if _bundled_sf:
        return _bundled_sf

    for path in _SF2_SEARCH_PATHS:
        if os.path.isfile(path):
            return path
    # Fallback: glob for any .sf2 anywhere under /usr/share
    for hit in glob.glob("/usr/share/**/*.sf2", recursive=True):
        return hit
    return None


def _saved_master_volume():
    """v22ze-115b: built-in FluidSynth volume as a 0..1 slider position.
    Reads "master_volume"; falls back to the older "fluidsynth_gain" key
    (v22ze-113, a raw gain) and finally to the default (gain 0.7)."""
    s = _load_settings()
    gmax = audio_backend.FLUIDSYNTH_GAIN_MAX
    try:
        if "master_volume" in s:
            return max(0.0, min(1.0, float(s["master_volume"])))
        if "fluidsynth_gain" in s:
            return max(0.0, min(1.0, float(s["fluidsynth_gain"]) / gmax))
    except (TypeError, ValueError):
        pass
    return audio_backend.DEFAULT_MASTER_VOLUME


def _fs_audio_drivers():
    """v22ze-117: audio drivers to try, best first, for this OS.  None means
    "let FluidSynth pick its default"."""
    plat = platform.system()
    if plat == "Linux":
        # v22w: pulseaudio (also served by pipewire-pulse) is the most broadly
        # reliable on modern desktops; native pipewire, alsa, jack, oss follow.
        return ["pulseaudio", "pipewire", "alsa", "jack", "oss"]
    if plat == "Darwin":
        return ["coreaudio"]
    if plat == "Windows":
        return ["dsound", "wasapi", "waveout"]
    return [None]


def _fs_delete(synth):
    """v22ze-117: release a synth we decided not to use (never raises)."""
    try:
        synth.delete()
    except Exception:
        pass


def _init_fluidsynth():
    """Try to set up a FluidSynth soft-synth as a MIDI output backend.

    Returns True if FluidSynth is ready, False if anything is missing
    (pyfluidsynth not installed, libfluidsynth not found, no SoundFont).
    Leaves _fs_synth, _fs_sfid, _fs_active in a consistent state.
    """
    global _fs_synth, _fs_sfid, _fs_active, _fs_fail_reason, _fs_fail_detail
    global _fs_driver

    # v22ze-117: every attempt starts clean, so a retry (e.g. from the Setup
    # tab) reports ITS failure, not a stale reason from an earlier attempt.
    _fs_fail_reason, _fs_fail_detail = None, ""

    # 1 — Can we import the Python binding?
    try:
        import fluidsynth
    except ImportError as exc:
        print("[FluidSynth] pyfluidsynth not installed — skipping", file=sys.stderr)
        _fs_fail_reason, _fs_fail_detail = "no_binding", str(exc)
        return False

    # 2 — Is a SoundFont available?
    sf2 = _find_soundfont()
    if not sf2:
        print("[FluidSynth] No .sf2 SoundFont found — skipping", file=sys.stderr)
        _fs_fail_reason, _fs_fail_detail = "no_soundfont", ""
        return False

    # 3 — Initialise the synth
    # v22ze-117: pyfluidsynth's Synth.start() does NOT raise when the audio
    # driver fails to open -- it prints an error, returns 0 and leaves
    # fs.audio_driver as None.  The old loop therefore accepted the FIRST
    # driver every time ("started successfully" / "Ready") even when nothing
    # could play, never tried the fallbacks, and never showed the "No Music
    # Synthesizer Found" dialog.  Now each driver gets a fresh synth and is
    # accepted only if its audio_driver really opened.
    fs = None
    try:
        # v22ze-112: default is channels=256, which made FluidSynth register
        # 16 separate ALSA ports (one per 16-channel group). MIDI only has 16.
        # v22ze-113/115b: library default gain is 0.2 (quiet). Use the saved
        # master volume (slider position) or the default (gain 0.7).
        _gain = _saved_master_volume() * audio_backend.FLUIDSYNTH_GAIN_MAX
        _drivers_to_try = _fs_audio_drivers()
        _errors = []
        for _drv in _drivers_to_try:
            _label = _drv or "default"
            _cand = fluidsynth.Synth(channels=16, gain=_gain)
            try:
                _cand.start(driver=_drv) if _drv else _cand.start()
            except Exception as _drv_exc:
                _errors.append(f"{_label}: {_drv_exc}")
                print(f"[FluidSynth] Driver '{_label}' failed: {_drv_exc}", file=sys.stderr)
                _fs_delete(_cand)
                continue
            if _drv and _cand.get_setting("audio.driver") != _drv:
                _errors.append(f"{_label}: not supported by this FluidSynth build")
                print(f"[FluidSynth] Driver '{_label}' is not supported here", file=sys.stderr)
                _fs_delete(_cand)
                continue
            if not getattr(_cand, "audio_driver", None):
                _errors.append(f"{_label}: could not open the audio device")
                print(f"[FluidSynth] Driver '{_label}' could not open the audio device", file=sys.stderr)
                _fs_delete(_cand)
                continue
            fs = _cand
            _fs_driver = _label
            print(f"[FluidSynth] Audio driver '{_label}' opened successfully", file=sys.stderr)
            break
        if fs is None:
            _fs_fail_reason = "no_driver"
            _fs_fail_detail = "tried " + "; ".join(_errors)
            raise RuntimeError(f"No audio driver could be opened ({_fs_fail_detail})")

        # v22ze-124: optional on-demand sample decoding (opt-in, for A/B timing)
        _dyn = os.environ.get("MIDI_STUDIO_DYNAMIC_SAMPLES") == "1"
        if _dyn:
            try:
                fs.setting("synth.dynamic-sample-loading", 1)
            except Exception as _dyn_exc:
                print(f"[FluidSynth] dynamic sample loading not available: {_dyn_exc}", file=sys.stderr)
        _t_sf = time.time()
        sfid = fs.sfload(sf2)
        print(f"[FluidSynth] SoundFont loaded in {time.time() - _t_sf:.1f}s "
              f"(on-demand samples: {'on' if _dyn else 'off'})", file=sys.stderr)
        if sfid == -1:
            _fs_fail_reason, _fs_fail_detail = "load_failed", f"sfload failed for {sf2}"
            raise RuntimeError(f"sfload failed for {sf2}")

        # Map all 16 channels to the loaded SoundFont, bank 0, program 0
        for ch in range(16):
            fs.program_select(ch, sfid, 0, 0)

        _fs_synth = fs
        _fs_sfid = sfid
        _fs_active = True
        print(f"[FluidSynth] Ready — driver: {_fs_driver}, SoundFont: {sf2}", file=sys.stderr)
        return True

    except Exception as exc:
        print(f"[FluidSynth] Init failed: {exc}", file=sys.stderr)
        if _fs_fail_reason is None:  # more specific reason wasn't set upstream
            _fs_fail_reason, _fs_fail_detail = "other", str(exc)
        _fs_synth = None
        _fs_sfid = None
        _fs_active = False
        return False


def _fs_program_select(channel, program, bank=0):
    """Send a program-change to FluidSynth (safe no-op if not active)."""
    if _fs_active and _fs_synth and _fs_sfid is not None:
        try:
            _fs_synth.program_select(channel, _fs_sfid, bank, program)
        except Exception:
            pass


def _maybe_show_no_synth_dialog(root):
    """Show a one-time warning dialog if neither MIDI port nor FluidSynth
    is available.  Call from MidisoftStudio.__init__ after the window exists.
    Does nothing if any backend is working.

    v22ze-31 (setup-guidance improvement): rewritten to actually explain
    WHY FluidSynth wasn't set up (using _fs_fail_reason/_fs_fail_detail,
    populated by _init_fluidsynth) and to show ONE complete, copyable
    command block for the user's actual detected distro instead of a
    generic wall of text for every OS at once. Previously all of this
    diagnostic detail only ever went to stderr, which a user who launched
    the app by double-clicking (not from a terminal) never sees.
    """
    if MIDI_OUT_OK or _fs_active:
        return

    import tkinter as tk

    import webbrowser

    distro = _detect_linux_distro()  # 'arch' / 'debian' / 'fedora' / 'suse' / None
    is_linux = platform.system() == "Linux"
    is_mac = platform.system() == "Darwin"

    # ── Build ONE relevant, complete, copy-pasteable command block ────────
    PIP_LINE = "pip install pyfluidsynth mido python-rtmidi --break-system-packages"
    if is_linux:
        _pkgs = {
            "arch": "sudo pacman -S fluidsynth timidity++ soundfont-fluid",
            "debian": "sudo apt install fluidsynth timidity fluid-soundfont-gm",
            "fedora": "sudo dnf install fluidsynth fluidsynth-utils timidity++ fluid-soundfont-gm",
            "suse": "sudo zypper install fluidsynth timidity",
        }
        if distro in _pkgs:
            os_line = _pkgs[distro]
        else:
            os_line = (
                "# Distro not auto-detected -- install your distro's\n"
                "# 'fluidsynth' and a General MIDI soundfont package,\n"
                "# e.g. one of:\n"
                "sudo pacman -S fluidsynth soundfont-fluid   # Arch/Manjaro\n"
                "sudo apt install fluidsynth fluid-soundfont-gm   # Debian/Ubuntu\n"
                "sudo dnf install fluidsynth fluid-soundfont-gm   # Fedora"
            )
    elif is_mac:
        os_line = "brew install fluid-synth"
    else:  # Windows
        os_line = (
            "# Download and run the FluidSynth installer from\n"
            "# fluidsynth.org, then download a .sf2 SoundFont\n"
            "# (e.g. FluidR3_GM.sf2) into C:\\soundfonts\\"
        )
    full_command_block = f"{os_line}\n{PIP_LINE}"

    # ── Explain the SPECIFIC reason, if FluidSynth was actually attempted ──
    reason_text = {
        "no_binding": 'The Python package "pyfluidsynth" isn\'t installed '
        "(this is separate from the system fluidsynth program).",
        "no_soundfont": "FluidSynth itself is installed correctly, but no "
        "SoundFont (.sf2 file) could be found anywhere on "
        "this system. FluidSynth needs one to know what any "
        "instrument actually sounds like.",
        "no_driver": "FluidSynth and a SoundFont were both found, but none "
        "of the audio drivers could open your sound device (every driver "
        "FluidSynth offers on this system was tried -- see the details "
        "below). This usually means your audio server isn't running, or "
        "another program has the sound card to itself -- on Linux check "
        "that PipeWire/PulseAudio is active "
        '("systemctl --user status pipewire-pulse").',
        "load_failed": "A SoundFont file was found, but FluidSynth rejected "
        "it -- it may be corrupt or not actually a valid "
        ".sf2 file.",
        "other": "FluidSynth failed to start for an unexpected reason "
        "(see details below).",
    }.get(
        _fs_fail_reason,
        "This application does not produce sound on its own, and no "
        "synthesizer was detected.",
    )

    dlg = tk.Toplevel(root)
    dlg.title("No Music Synthesizer Found")
    dlg.resizable(False, False)
    dlg.configure(bg="#0d1117")
    dlg.grab_set()
    dlg.attributes("-topmost", True)

    BG = "#0d1117"
    FG = "#f0f6fc"
    MUTED = "#8b949e"
    WARN = "#d29922"

    tk.Label(
        dlg,
        text="⚠️  No Music Synthesizer Found",
        bg=BG,
        fg=WARN,
        font=("TkDefaultFont", 13, "bold"),
    ).pack(pady=(22, 8))

    tk.Label(
        dlg,
        text=reason_text,
        bg=BG,
        fg=FG,
        font=("TkDefaultFont", 10),
        wraplength=440,
        justify=tk.LEFT,
    ).pack(padx=28)

    if _fs_fail_detail:
        tk.Label(
            dlg,
            text=_fs_fail_detail,
            bg="#161b22",
            fg=MUTED,
            font=("TkFixedFont", 8),
            wraplength=420,
            justify=tk.LEFT,
            padx=10,
            pady=6,
        ).pack(fill=tk.X, padx=28, pady=(6, 0))

    tk.Label(
        dlg,
        text="Run this to set everything up:",
        bg=BG,
        fg=FG,
        font=("TkDefaultFont", 10, "bold"),
    ).pack(padx=28, pady=(16, 4), anchor="w")

    cmd_box = tk.Text(
        dlg,
        height=full_command_block.count("\n") + 1,
        width=56,
        bg="#161b22",
        fg="#7ee787",
        font=("TkFixedFont", 9),
        relief=tk.FLAT,
        padx=10,
        pady=8,
        wrap=tk.NONE,
    )
    cmd_box.insert("1.0", full_command_block)
    cmd_box.configure(state=tk.DISABLED)
    cmd_box.pack(padx=28, pady=(0, 4))

    def _copy_commands():
        root.clipboard_clear()
        root.clipboard_append(full_command_block)
        copy_btn.configure(text="Copied!")
        dlg.after(1500, lambda: copy_btn.configure(text="Copy Commands"))

    btn_frame = tk.Frame(dlg, bg=BG)
    btn_frame.pack(pady=(6, 12))
    bs = dict(
        relief=tk.FLAT, padx=16, pady=6, font=("TkDefaultFont", 10), cursor="hand2"
    )

    copy_btn = tk.Button(
        btn_frame,
        text="Copy Commands",
        bg="#238636",
        fg="white",
        activebackground="#2ea043",
        command=_copy_commands,
        **bs,
    )
    copy_btn.pack(side=tk.LEFT, padx=6)

    def _open_fs():
        webbrowser.open("https://www.fluidsynth.org")

    tk.Button(
        btn_frame,
        text="Open FluidSynth Website",
        bg="#21262d",
        fg=FG,
        activebackground="#30363d",
        command=_open_fs,
        **bs,
    ).pack(side=tk.LEFT, padx=6)
    tk.Button(
        btn_frame,
        text="Continue Without Sound",
        bg="#21262d",
        fg=MUTED,
        activebackground="#30363d",
        command=dlg.destroy,
        **bs,
    ).pack(side=tk.LEFT, padx=6)

    tk.Label(
        dlg,
        text="After running the commands above, just restart the app --\n"
        "it re-checks for a synthesizer every time it starts.",
        bg=BG,
        fg=MUTED,
        font=("TkDefaultFont", 8),
        justify=tk.CENTER,
    ).pack(pady=(0, 18))

    root.wait_window(dlg)


def _launch_timidity():
    """Start TiMidity in ALSA-server mode with buffer flags that prevent buzz.
    Returns True if launched successfully, False if already running or failed."""
    import re
    import shutil
    import subprocess

    global _timidity_proc

    if not shutil.which("timidity"):
        print(
            "[TiMidity] Not found on PATH — install timidity or timidity++",
            file=sys.stderr,
        )
        return False

    # Check if a TiMidity port already exists — if so, nothing to do
    try:
        existing = mido.get_output_names()
        if any("timidity" in p.lower() for p in existing):
            print("[TiMidity] Already running — skipping auto-launch", file=sys.stderr)
            return False
    except Exception:
        pass

    try:
        _timidity_proc = subprocess.Popen(
            ["timidity"] + TIMIDITY_ARGS,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        print(
            f"[TiMidity] Launched (PID {_timidity_proc.pid}): {TIMIDITY_HINT}",
            file=sys.stderr,
        )
        # Give the sequencer a moment to register its ALSA ports
        time.sleep(0.8)
        return True
    except Exception as exc:
        print(f"[TiMidity] Launch failed: {exc}", file=sys.stderr)
        return False


def _prompt_midi_output_choice(trusted_ports):
    """Show a small dialog letting the user pick among multiple detected
    trusted synth ports (e.g. TiMidity and Pianoteq both running).

    Uses a throwaway Tk root since the main app hasn't started yet — same
    pattern as the mido-import-guard dialog.

    Returns (chosen_port_name, remember_bool).  "Remember" defaults to
    UNCHECKED (v22za) — a previous version always persisted the choice
    immediately, which meant the dialog only ever appeared once and every
    later reload silently reused that first pick even if the user wanted
    to try something else.  Now the user must explicitly opt in to
    persistence; otherwise every session asks fresh.
    """
    import tkinter as tk

    _root = tk.Tk()
    _root.withdraw()
    _dlg = tk.Toplevel(_root)
    _dlg.title("Choose MIDI Output")
    _dlg.configure(bg="#0d1117")
    _dlg.resizable(False, False)
    _dlg.attributes("-topmost", True)

    tk.Label(
        _dlg,
        text="Multiple synthesizers were found",
        bg="#0d1117",
        fg="#58a6ff",
        font=("TkDefaultFont", 11, "bold"),
    ).pack(padx=20, pady=(16, 4))
    tk.Label(
        _dlg,
        text="Choose which one this app should send MIDI to.\n"
        "You can change this later in Setup \u2192 MIDI Output Device.",
        bg="#0d1117",
        fg="#8b949e",
        font=("TkDefaultFont", 9),
        justify=tk.CENTER,
    ).pack(padx=20, pady=(0, 10))

    var = tk.StringVar(master=_root, value=trusted_ports[0])  # v22ze-126
    for name in trusted_ports:
        tk.Radiobutton(
            _dlg,
            text=name,
            variable=var,
            value=name,
            bg="#0d1117",
            fg="white",
            selectcolor="#21262d",
            activebackground="#0d1117",
            activeforeground="white",
            anchor="w",
        ).pack(fill=tk.X, padx=24, pady=2)

    remember_var = tk.BooleanVar(master=_root, value=False)  # unchecked by default (v22ze-126: own root)
    tk.Checkbutton(
        _dlg,
        text="Remember this choice for next time",
        variable=remember_var,
        bg="#0d1117",
        fg="#8b949e",
        selectcolor="#21262d",
        activebackground="#0d1117",
        activeforeground="white",
    ).pack(padx=20, pady=(6, 0), anchor="w")

    result = [(trusted_ports[0], False)]

    def _confirm():
        result[0] = (var.get(), remember_var.get())
        _dlg.destroy()

    tk.Button(
        _dlg,
        text="Use This",
        command=_confirm,
        bg="#238636",
        fg="white",
        relief=tk.FLAT,
        padx=12,
        pady=4,
    ).pack(pady=(10, 16))

    _dlg.protocol("WM_DELETE_WINDOW", _confirm)
    _dlg.grab_set()
    _root.wait_window(_dlg)
    _root.destroy()
    return result[0]


def _init_midi():
    global MIDI_OUT_OK, MIDI_IN_OK, _midi_out, _midi_in
    global _unverified_out_port_name

    _SKIP_PORTS = ("midi through", "through port", "rtmidi")
    # v22w: only these names are trusted enough to skip FluidSynth entirely.
    # Any OTHER port (an unrecognized hardware MIDI port, a stray ALSA
    # sequencer client, etc.) might not actually produce audio — reported:
    # an unrelated existing port silently satisfied MIDI_OUT_OK, so
    # FluidSynth was never even attempted, and the user heard nothing.
    _TRUSTED_SYNTH_NAMES = (
        "timidity",
        "fluidsynth",
        "fluid synth",  # v22ze-110 (trusted name): pyfluidsynth's own ALSA port is "FLUID Synth ..." (with a space) --
                        # without this, a standalone FluidSynth port was never recognized
                        # as trusted and could never be offered as a choice alongside TiMidity.
        "qsynth",
        "zynaddsubfx",
        "yoshimi",
        "pianoteq",
    )

    def _port_key(name):
        import re

        m = re.search(r"(\d+):(\d+)\s*$", name)
        return (int(m.group(1)), int(m.group(2))) if m else (9999, 0)

    # ── MIDI OUT ──────────────────────────────────────────────────────────────
    try:
        outs = mido.get_output_names()
        print(f"[MIDI OUT] Available: {outs}")

        # If no TiMidity port visible yet, try to launch one.
        # v22ze-145: not when built-in FluidSynth is available (unless the
        # user's remembered choice IS a TiMidity port) -- TiMidity crashed
        # with an error pop-up on Ubuntu 26.04 and is not needed.
        _pref_saved = str(_load_settings().get("preferred_midi_port") or "")
        if not any("timidity" in o.lower() for o in outs) and (
            not _fluidsynth_importable() or "timidity" in _pref_saved.lower()
        ):
            if _launch_timidity():
                outs = mido.get_output_names()  # refresh after launch
                print(f"[MIDI OUT] Available (post-launch): {outs}")

        if outs:
            trusted = [
                o for o in outs if any(t in o.lower() for t in _TRUSTED_SYNTH_NAMES)
            ]
            if trusted:
                # v22z-2: check for a remembered choice from a previous
                # session first — if it's still available, use it directly
                # with no prompt.
                _settings = _load_settings()
                _saved_port = _settings.get("preferred_midi_port")
                # v22ze-112: built-in FluidSynth counts as one more option.
                # v22ze-146: built-in FluidSynth goes FIRST so it is the
                # pre-selected answer in the choice window.
                _options = (
                    [FLUIDSYNTH_BUILTIN] if _fluidsynth_importable() else []
                ) + trusted
                if _saved_port == FLUIDSYNTH_BUILTIN and len(_options) > len(trusted):
                    pref = FLUIDSYNTH_BUILTIN
                    print("[MIDI OUT] Using remembered choice: built-in FluidSynth")
                elif _saved_port and _saved_port in trusted:
                    pref = _saved_port
                    print(f"[MIDI OUT] Using remembered port: {pref}")
                elif len(_options) > 1:
                    # v22z-2: genuine choice among multiple trusted synths
                    # (e.g. TiMidity AND Pianoteq both running) — ask rather
                    # than silently picking whichever sorts first.  Previously
                    # this always silently took the first TiMidity port found.
                    pref, _remember = _prompt_midi_output_choice(_options)
                    if _remember:
                        _save_settings({"preferred_midi_port": pref})
                else:
                    tim_ports = [o for o in trusted if "timidity" in o.lower()]
                    pref = (
                        sorted(tim_ports, key=_port_key)[0] if tim_ports else trusted[0]
                    )
                if pref == FLUIDSYNTH_BUILTIN:
                    # v22ze-112: leave MIDI_OUT_OK False; the module-level
                    # `if not MIDI_OUT_OK: _init_fluidsynth()` below takes over.
                    print("[MIDI OUT] Built-in FluidSynth selected — no port opened")
                else:
                    _midi_out = mido.open_output(pref)
                    MIDI_OUT_OK = True
                    print(f"[MIDI OUT] Opened trusted port: {pref}")
            else:
                # No recognized synth port — don't claim success yet.
                # Remember the best candidate but let FluidSynth be tried
                # first; only fall back to this unverified port afterward
                # if FluidSynth also fails to initialise (see bottom of file).
                candidates = [
                    o for o in outs if not any(s in o.lower() for s in _SKIP_PORTS)
                ]
                _unverified_out_port_name = candidates[0] if candidates else outs[0]
                print(
                    f"[MIDI OUT] No trusted synth port found — "
                    f"'{_unverified_out_port_name}' is unverified, "
                    f"trying FluidSynth first",
                    file=sys.stderr,
                )
    except Exception as e:
        print(f"[MIDI OUT] FAILED: {e}")

    # ── MIDI IN ───────────────────────────────────────────────────────────────
    try:
        ins = mido.get_input_names()
        print(f"[MIDI IN ] Available: {ins}")
        if ins:
            hw = next(
                (p for p in ins if not any(s in p.lower() for s in _SKIP_PORTS)), None
            )
            chosen = hw if hw else ins[0]
            _midi_in = mido.open_input(chosen)
            MIDI_IN_OK = True
            print(f"[MIDI IN ] Opened: {chosen}")
    except Exception as e:
        print(f"[MIDI IN ] FAILED: {e}")


_be_src = None  # the legacy object audio_backend's active backend was built from


def _sync_backend():
    """v22ze-115a: make audio_backend's active backend match the legacy
    state (_midi_out / _fs_active / _fs_synth) that gui.py still mutates
    directly.  Cheap identity check; only rebuilds when the source changed.
    stop_previous=False: we never close/delete anything here -- the code that
    opened a port or synth (gui.py / _init_fluidsynth) still owns its lifetime,
    and FluidSynth deliberately stays alive while a port is selected."""
    global _be_src
    if _midi_out is not None:
        src = _midi_out
    elif _fs_active and _fs_synth is not None:
        src = _fs_synth
    else:
        src = None
    if src is _be_src:
        return
    _be_src = src
    if src is None:
        backend = None
    elif src is _midi_out:
        backend = MidiPortBackend(port=src)
    else:
        backend = FluidSynthBackend(src, _fs_sfid)
    audio_backend.set_active(backend, stop_previous=False)


def _send(msg):
    """Route a mido Message to the active output backend.
    Priority: hardware/virtual MIDI port → FluidSynth soft-synth.
    (v22ze-115a: routing now done by audio_backend; priority unchanged.)
    """
    _sync_backend()
    audio_backend.send(msg)


# ── v22ze-115b: public output API (gui.py uses only these) ───────────────────
def output_ready() -> bool:
    """True if some output (a MIDI port or built-in FluidSynth) can make sound."""
    _sync_backend()
    return audio_backend.ready()


def output_label() -> str:
    """'(none)', the MIDI port's name, or 'FluidSynth (built-in)'."""
    _sync_backend()
    return audio_backend.active_name()


def forget_saved_output():
    """Clear the remembered startup choice so the startup window returns."""
    s = _load_settings()
    s["preferred_midi_port"] = None
    _save_settings(s)


def _silence_active():
    b = audio_backend.get_active()
    if b is not None and b.is_ready():
        try:
            b.all_notes_off()
        except Exception:
            pass


def select_output(choice, forget_saved=True):
    """Switch output at runtime.  `choice` is a mido output-port name or
    FLUIDSYNTH_BUILTIN.  Raises on failure and leaves the current output
    untouched.  Like every in-program switch, it clears the remembered
    startup choice (see v22ze-112) unless forget_saved=False."""
    global _midi_out, MIDI_OUT_OK
    if choice == FLUIDSYNTH_BUILTIN:
        if not _fs_active and not _init_fluidsynth():
            raise RuntimeError(
                "Built-in FluidSynth could not start: "
                + (_fs_fail_detail or str(_fs_fail_reason) or "unknown reason")
            )
        new = None
    else:
        new = mido.open_output(choice)  # open first: a failure changes nothing
    _silence_active()
    old, _midi_out = _midi_out, new
    MIDI_OUT_OK = new is not None
    if old is not None and old is not new:
        try:
            old.close()
        except Exception:
            pass
    _sync_backend()
    if forget_saved:
        forget_saved_output()


def close_output():
    """Close the MIDI output port, if any (called when the app shuts down)."""
    global _midi_out, MIDI_OUT_OK
    old, _midi_out = _midi_out, None
    MIDI_OUT_OK = False
    if old is not None:
        try:
            old.close()
        except Exception:
            pass
    _sync_backend()


def get_fluidsynth_volume() -> float:
    """Built-in FluidSynth volume, 0..1 (slider position)."""
    return _saved_master_volume()


def set_fluidsynth_volume(level, save=True) -> bool:
    """Set the built-in FluidSynth volume (0..1), live if the synth exists,
    and remember it.  Returns True if a running synth was updated.  Has no
    effect on external MIDI synths (TiMidity etc.: use its own -A option)."""
    level = max(0.0, min(1.0, float(level)))
    if save:
        s = _load_settings()
        s["master_volume"] = level
        _save_settings(s)
    if _fs_synth is not None and _fs_sfid is not None:
        return FluidSynthBackend(_fs_synth, _fs_sfid).set_master_volume(level)
    return False


def _send_raw(status, d1, d2=0):
    t = status & 0xF0
    c = status & 0x0F
    try:
        if t == 0x90:
            _send(mido.Message("note_on", channel=c, note=d1, velocity=d2))
        elif t == 0x80:
            _send(mido.Message("note_off", channel=c, note=d1, velocity=0))
        elif t == 0xB0:
            _send(mido.Message("control_change", channel=c, control=d1, value=d2))
        elif t == 0xC0:
            _send(mido.Message("program_change", channel=c, program=d1))
    except:
        pass


_init_midi()

# If _init_midi() found a TRUSTED synth port, FluidSynth is not needed.
# Only initialise FluidSynth when there is no trusted hardware/virtual
# port available — this is the primary fallback for most Linux users.
if not MIDI_OUT_OK:
    _init_fluidsynth()

# v22w: last resort — if neither a trusted port NOR FluidSynth worked,
# but an unverified port candidate was seen earlier, try it now.  Better
# than silence, and it only gets used when nothing more reliable worked.
if not MIDI_OUT_OK and not _fs_active and _unverified_out_port_name:
    try:
        _midi_out = mido.open_output(_unverified_out_port_name)
        MIDI_OUT_OK = True
        print(
            f"[MIDI OUT] Last-resort fallback: opened unverified port "
            f"'{_unverified_out_port_name}'",
            file=sys.stderr,
        )
    except Exception as _fallback_exc:
        print(
            f"[MIDI OUT] Last-resort fallback also failed: {_fallback_exc}",
            file=sys.stderr,
        )
# ─────────────────────────────────────────────────────────────────────────────


# ─────────────────────────────────────────────────────────────────────────────
# MIDI input dispatch (single reader thread, multiple listeners)
# ─────────────────────────────────────────────────────────────────────────────
_midi_listeners: dict = {}          # token → callback
_midi_listener_lock = threading.Lock()
_midi_dispatch_thread: threading.Thread | None = None


def _midi_dispatch_loop():
    """Single owner of _midi_in.  Reads messages and fans out to all listeners.
    Runs as a daemon thread for the lifetime of the process."""
    while not _midi_shutdown_evt.is_set():
        if _midi_in is None:
            time.sleep(0.05)
            continue
        try:
            # iter_pending is non-blocking; sleep keeps CPU reasonable
            for msg in _midi_in.iter_pending():
                with _midi_listener_lock:
                    cbs = list(_midi_listeners.values())
                for cb in cbs:
                    try:
                        cb(msg)
                    except Exception:
                        pass
            time.sleep(0.001)   # 1 ms — lowest practical latency without busy-spin
        except Exception:
            time.sleep(0.05)


def _start_dispatch_thread():
    global _midi_dispatch_thread
    if _midi_dispatch_thread and _midi_dispatch_thread.is_alive():
        return
    _midi_dispatch_thread = threading.Thread(
        target=_midi_dispatch_loop, daemon=True, name="MidiDispatch")
    _midi_dispatch_thread.start()


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


# v22ze-110 fix (duplicate init): MIDI init (_init_midi() / _init_fluidsynth()) already ran once,
# above, right after both functions were defined -- including the v22w
# last-resort unverified-port fallback that a second init block here
# used to duplicate without that fallback. Running it a second time
# here caused _prompt_midi_output_choice()'s "pick a MIDI port" dialog
# to pop up TWICE on every startup. Removed; only _start_dispatch_thread()
# (which is idempotent and safe to call once) belongs here.
_sync_backend()   # v22ze-115a: audio_backend.ready() is accurate from startup
_start_dispatch_thread()   # start immediately so thru works before any record

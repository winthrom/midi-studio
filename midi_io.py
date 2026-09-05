#!/usr/bin/env python3
"""MIDI I/O initialization, output, and input dispatching.

Provides:
- MIDI output routing (hardware/virtual ports or FluidSynth fallback)
- MIDI input dispatching (single thread, multiple listeners)
- Settings persistence for preferred MIDI ports
- FluidSynth initialization as a software synthesizer fallback
"""

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
MIDI_OUT_OK = False
MIDI_IN_OK = False
_midi_out = None
_midi_in = None
_unverified_out_port_name = None  # v22w: candidate port, not yet trusted

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
_fs_fail_reason = None
_fs_fail_detail = ""  # the actual exception text, for the "Show details" expander


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
    """Return the first .sf2 file found on this machine, or None."""
    import glob

    for path in _SF2_SEARCH_PATHS:
        if os.path.isfile(path):
            return path
    # Fallback: glob for any .sf2 anywhere under /usr/share
    for hit in glob.glob("/usr/share/**/*.sf2", recursive=True):
        return hit
    return None


def _init_fluidsynth():
    """Try to set up a FluidSynth soft-synth as a MIDI output backend.

    Returns True if FluidSynth is ready, False if anything is missing
    (pyfluidsynth not installed, libfluidsynth not found, no SoundFont).
    Leaves _fs_synth, _fs_sfid, _fs_active in a consistent state.
    """
    global _fs_synth, _fs_sfid, _fs_active, _fs_fail_reason, _fs_fail_detail

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
    try:
        fs = fluidsynth.Synth()
        _plat = platform.system()
        if _plat == "Linux":
            # v22w: try multiple drivers in order rather than hardcoding
            # "alsa".  Many current Linux distros (Arch included) default
            # to PipeWire; its ALSA compatibility layer can let fs.start()
            # succeed with no exception while producing no audible output
            # at all — reported as "FluidSynth installed but silent".
            # pulseaudio/pipewire-pulse is the most broadly reliable choice
            # on modern desktop Linux; alsa and jack are fallbacks.
            _drivers_to_try = ["pulseaudio", "alsa", "jack", "oss"]
            _started = False
            _last_exc = None
            for _drv in _drivers_to_try:
                try:
                    fs.start(driver=_drv)
                    print(
                        f"[FluidSynth] Audio driver '{_drv}' started successfully",
                        file=sys.stderr,
                    )
                    _started = True
                    break
                except Exception as _drv_exc:
                    _last_exc = _drv_exc
                    print(
                        f"[FluidSynth] Driver '{_drv}' failed: {_drv_exc}",
                        file=sys.stderr,
                    )
                    continue
            if not _started:
                _fs_fail_reason = "no_driver"
                _fs_fail_detail = f"tried {_drivers_to_try}; last error: {_last_exc}"
                raise RuntimeError(
                    f"No audio driver succeeded (tried {_drivers_to_try}); "
                    f"last error: {_last_exc}"
                )
        elif _plat == "Darwin":
            fs.start(driver="coreaudio")
        elif _plat == "Windows":
            fs.start(driver="dsound")
        else:
            fs.start()

        sfid = fs.sfload(sf2)
        if sfid == -1:
            _fs_fail_reason, _fs_fail_detail = "load_failed", f"sfload failed for {sf2}"
            raise RuntimeError(f"sfload failed for {sf2}")

        # Map all 16 channels to the loaded SoundFont, bank 0, program 0
        for ch in range(16):
            fs.program_select(ch, sfid, 0, 0)

        _fs_synth = fs
        _fs_sfid = sfid
        _fs_active = True
        print(f"[FluidSynth] Ready — SoundFont: {sf2}", file=sys.stderr)
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
        "no_driver": "FluidSynth and a SoundFont were both found, but no "
        "audio driver could be started (tried PulseAudio, "
        "ALSA, JACK, and OSS in turn). This usually means "
        "your audio server isn't running or isn't reachable "
        "-- check that PipeWire/PulseAudio is active "
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

    var = tk.StringVar(value=trusted_ports[0])
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

    remember_var = tk.BooleanVar(value=False)  # unchecked by default
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

        # If no TiMidity port visible yet, try to launch one
        if not any("timidity" in o.lower() for o in outs):
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
                if _saved_port and _saved_port in trusted:
                    pref = _saved_port
                    print(f"[MIDI OUT] Using remembered port: {pref}")
                elif len(trusted) > 1:
                    # v22z-2: genuine choice among multiple trusted synths
                    # (e.g. TiMidity AND Pianoteq both running) — ask rather
                    # than silently picking whichever sorts first.  Previously
                    # this always silently took the first TiMidity port found.
                    pref, _remember = _prompt_midi_output_choice(trusted)
                    if _remember:
                        _save_settings({"preferred_midi_port": pref})
                else:
                    tim_ports = [o for o in trusted if "timidity" in o.lower()]
                    pref = (
                        sorted(tim_ports, key=_port_key)[0] if tim_ports else trusted[0]
                    )
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


def _send(msg):
    """Route a mido Message to the active output backend.
    Priority: hardware/virtual MIDI port → FluidSynth soft-synth.
    """
    if _midi_out:
        try:
            _midi_out.send(msg)
        except Exception:
            pass
        return
    if _fs_active and _fs_synth:
        try:
            t = msg.type
            if t == "note_on":
                if msg.velocity > 0:
                    _fs_synth.noteon(msg.channel, msg.note, msg.velocity)
                else:
                    _fs_synth.noteoff(msg.channel, msg.note)
            elif t == "note_off":
                _fs_synth.noteoff(msg.channel, msg.note)
            elif t == "control_change":
                _fs_synth.cc(msg.channel, msg.control, msg.value)
            elif t == "program_change":
                _fs_program_select(msg.channel, msg.program)
        except Exception:
            pass


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


# Initialize on module load
if mido:
    _init_midi()
    if not MIDI_OUT_OK:
        _init_fluidsynth()

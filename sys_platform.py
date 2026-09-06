#!/usr/bin/env python3
"""Platform detection and initialization utilities."""

import json as _settings_json
import os
import platform
import shutil
import subprocess
import sys
import time
from datetime import datetime

# Application identity (update APP_VERSION each release)
APP_VERSION = "22ze-73"
APP_FULL_NAME = "Midi-Studio — a Synthesizer in the Spirit of MidiSoft Studio4"
APP_TIMESTAMP = datetime.now().strftime("%Y-%m-%d  %H:%M")
APP_TITLE = f"{APP_FULL_NAME}  —  v{APP_VERSION}  {APP_TIMESTAMP}"

# Sterling Lions Club links
LIONS_DONATE_URL = "https://e-clubhouse.org/sites/sterlingva/page-10.php"
LIONS_WEBSITE_URL = "https://e-clubhouse.org/sites/sterlingva"

# Settings persistence
_SETTINGS_PATH = os.path.expanduser("~/.midistudio_settings.json")


def load_settings():
    """Load user settings from disk."""
    try:
        with open(_SETTINGS_PATH, "r") as f:
            return _settings_json.load(f)
    except Exception:
        return {}


def save_settings(d):
    """Save user settings to disk."""
    try:
        with open(_SETTINGS_PATH, "w") as f:
            _settings_json.dump(d, f)
    except Exception as e:
        print(f"[Settings] Could not save: {e}", file=sys.stderr)


# TiMidity launch flags
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


def detect_linux_distro():
    """Detect Linux distro family for setup instructions."""
    if platform.system() != "Linux":
        return None
    try:
        with open("/etc/os-release") as f:
            text = f.read().lower()
    except OSError:
        return None
    for family, needles in (
        ("arch", ("id=arch", "id_like=arch", "manjaro", "endeavouros")),
        ("debian", ("id=debian", "id=ubuntu", "id_like=debian", "mint")),
        ("fedora", ("id=fedora", "id=rhel", "id=centos")),
        ("suse", ("id=opensuse", "id_like=suse")),
    ):
        if any(n in text for n in needles):
            return family
    return None


def find_soundfont():
    """Find a SoundFont .sf2 file on the system."""
    import glob

    paths = [
        "/usr/share/soundfonts/default.sf2",
        "/usr/share/soundfonts/FluidR3_GM.sf2",
        "/usr/share/sounds/sf2/FluidR3_GM.sf2",
        "/usr/share/fluidsynth/FluidR3_GM.sf2",
        "/opt/homebrew/share/sounds/sf2/FluidR3_GM.sf2",
        "/usr/local/share/sounds/sf2/FluidR3_GM.sf2",
    ]
    for path in paths:
        if os.path.isfile(path):
            return path
    for hit in glob.glob("/usr/share/**/*.sf2", recursive=True):
        return hit
    return None

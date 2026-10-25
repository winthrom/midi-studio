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
APP_VERSION = "22ze-220"
APP_RELEASE = "0.4.0-dev"
APP_FULL_NAME = "Midi-Studio — a Synthesizer in the Spirit of MidiSoft Studio4"
APP_TIMESTAMP = "2026-10-24"  # build date (was: launch time)
APP_TITLE = f"{APP_FULL_NAME}  —  v{APP_RELEASE} (build {APP_VERSION})  {APP_TIMESTAMP}"

# v22ze-218: APP_RELEASE (above) is the number users see and tags are named after; "-dev" while the
# next release is being built; release_tag.sh insists it matches the tag.
APP_RELEASES_API = "https://api.github.com/repos/winthrom/midi-studio/releases/latest"


def release_tuple(v):
    """'v0.3.3', '0.4.0-dev', '0.10.1' -> (0, 3, 3) ... ; None when it is not a version number."""
    import re as _re
    m = _re.match(r"\s*v?(\d+)\.(\d+)\.(\d+)", str(v))
    return tuple(int(x) for x in m.groups()) if m else None


def update_is_newer(latest, current):
    """True when `latest` is a higher release number than `current` (a -dev build of the same
    number is not older than that release)."""
    a, b = release_tuple(latest), release_tuple(current)
    if not a or not b:
        return False
    return a > b


def fetch_latest_release(url=None, timeout=6):
    """Ask GitHub for the newest published (non-pre-release) release.  Returns
    {"tag": "v0.3.3", "version": "0.3.3", "url": page, "name": title}.  Raises on any problem."""
    import json as _json
    import ssl as _ssl
    import urllib.request as _rq
    req = _rq.Request(url or APP_RELEASES_API,
                      headers={"User-Agent": "MIDI-Studio-update-check", "Accept": "application/vnd.github+json"})
    ctx = None
    try:
        ctx = _ssl.create_default_context()
        if not ctx.get_ca_certs():
            raise ValueError("no CA certificates")
    except Exception:
        try:
            import certifi as _certifi
            ctx = _ssl.create_default_context(cafile=_certifi.where())
        except Exception:
            ctx = None
    with _rq.urlopen(req, timeout=timeout, context=ctx) if ctx is not None else _rq.urlopen(req, timeout=timeout) as r:
        d = _json.loads(r.read().decode("utf-8"))
    tag = str(d.get("tag_name", ""))
    if not release_tuple(tag):
        raise ValueError("unexpected release tag: " + tag)
    return {"tag": tag, "version": ".".join(str(x) for x in release_tuple(tag)),
            "url": d.get("html_url") or "https://github.com/winthrom/midi-studio/releases/latest",
            "name": d.get("name") or tag}


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

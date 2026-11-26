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
APP_VERSION = "22ze-321"
APP_RELEASE = "0.4.2-dev"
APP_FULL_NAME = "Midi-Studio — a Synthesizer in the Spirit of MidiSoft Studio4"
APP_TIMESTAMP = "2026-11-23"  # build date (was: launch time)
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


_RELEASE_PREFIX = "https://github.com/winthrom/midi-studio/"
_RELEASE_FALLBACK = "https://github.com/winthrom/midi-studio/releases/latest"


def safe_release_url(u):
    """v22ze-312: the address to open for an update, or the project's own releases page.  An address is accepted only if
    it is text, begins with the project's own GitHub address, and has no spaces or control characters."""
    if isinstance(u, str) and u.startswith(_RELEASE_PREFIX) and len(u) < 300 \
            and all(32 < ord(c) < 127 for c in u):
        return u
    return _RELEASE_FALLBACK


MAX_MIDI_BYTES = 50 * 1024 * 1024     # v22ze-321: the largest MIDI file ever opened (real ones are usually under 1 MB)
MIN_MIDI_LIMIT = 1024 * 1024           # a low memory reading never makes the limit smaller than this
MIDI_MEMORY_FACTOR = 60                # memory needed per byte of file (measured about 20 for the piece itself)
MAX_PATH_CHARS = 4096
MAX_NAME_CHARS = 255


def available_memory_bytes():
    """Free memory for a new piece, in bytes, or None when it cannot be read (then the fixed cap is used)."""
    try:
        if sys.platform.startswith("linux"):
            with open("/proc/meminfo") as f:
                for line in f:
                    if line.startswith("MemAvailable:"):
                        return int(line.split()[1]) * 1024
            return None
        if sys.platform.startswith("win"):
            import ctypes

            class _MemStatus(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
            ms = _MemStatus()
            ms.dwLength = ctypes.sizeof(ms)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(ms)):
                return int(ms.ullAvailPhys)
            return None
        if sys.platform == "darwin":
            return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") // 4    # a cautious stand-in for "free"
    except Exception:
        pass
    return None


def midi_size_limit(avail="auto"):
    """The largest MIDI file to open: the smaller of the fixed cap and free memory / 60, never below 1 MB."""
    if avail == "auto":
        avail = available_memory_bytes()
    limit = MAX_MIDI_BYTES
    if isinstance(avail, int) and not isinstance(avail, bool) and avail > 0:
        limit = min(limit, max(MIN_MIDI_LIMIT, avail // MIDI_MEMORY_FACTOR))
    return limit


def check_midi_path(path, limit=None):
    """None when the file may be opened; otherwise one plain sentence saying why not.  Nothing is read."""
    import stat as _stat
    if not isinstance(path, str) or not path:
        return "No file was chosen."
    if len(path) > MAX_PATH_CHARS or len(os.path.basename(path)) > MAX_NAME_CHARS:
        return "The file name or folder path is too long."
    if any(ord(c) < 32 or ord(c) == 127 for c in path):
        return "The file name contains characters that are not allowed (such as a line break)."
    try:
        st = os.stat(path)
    except OSError:
        return "That file could not be found or cannot be read."
    if not _stat.S_ISREG(st.st_mode):
        return "That is not an ordinary file (it may be a folder or a device)."
    if not os.access(path, os.R_OK):
        return "That file could not be found or cannot be read."
    if st.st_size == 0:
        return "That file is empty."
    if limit is None:
        limit = midi_size_limit()
    if st.st_size > limit:
        return ("That file is %.1f MB. The largest this computer can open safely right now is %.1f MB. "
                "A real MIDI file is usually under 1 MB, so this may not be a MIDI file."
                % (st.st_size / 1048576.0, limit / 1048576.0))
    return None


def fetch_latest_release(url=None, timeout=6):
    """Ask GitHub for the newest published (non-pre-release) release.  Returns
    {"tag": "v0.3.3", "version": "0.3.3", "url": page, "name": title}.  Raises on any problem."""
    import json as _json
    import ssl as _ssl
    import urllib.request as _rq

    req = _rq.Request(
        url or APP_RELEASES_API,
        headers={"User-Agent": "MIDI-Studio-update-check", "Accept": "application/vnd.github+json"},
    )
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
    with (
        _rq.urlopen(req, timeout=timeout, context=ctx)
        if ctx is not None
        else _rq.urlopen(req, timeout=timeout)
    ) as r:
        d = _json.loads(r.read().decode("utf-8"))
    tag = str(d.get("tag_name", ""))
    if not release_tuple(tag):
        raise ValueError("unexpected release tag: " + tag)
    return {
        "tag": tag,
        "version": ".".join(str(x) for x in release_tuple(tag)),
        "url": safe_release_url(d.get("html_url")),
        "name": d.get("name") or tag,
    }


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

"""v22ze-319: security review of how midi_io.py starts TiMidity (0.4.2 security work).
  1. The program that is run is the full path found once, not a second search of PATH.  A path that is not absolute (a "."
     or empty entry in PATH) or that sits in a folder anyone can write to is refused, so a planted "timidity" cannot run.
  2. TiMidity starts with a clean environment: the AppImage's own library folders are removed (as the browser start already
     does), so the system TiMidity does not load the AppImage's libraries; its input is closed (stdin = nothing).
  3. A TiMidity that MIDI Studio started itself is stopped when MIDI Studio exits.  Before, it kept running in the
     background after the program closed.  One that was already running before is never touched.
The settings are fixed strings; no file name or other user text reaches the command.  Run from the repo root:
python3 patch_v22ze319_timidity_start.py
"""
import sys, os

TEST = r'''# How midi_io.py starts TiMidity (v22ze-319): which program it runs, with what environment, and that it is stopped again.
# Uses fakes only: no real TiMidity or sound device is needed.  midi_io imports no tkinter at load time.
import os, stat, sys, tempfile, unittest
from unittest import mock


def _mi():
    try:
        import midi_io
        return midi_io
    except Exception:
        raise unittest.SkipTest("midi_io could not be imported here")


class FakeProc:
    pid = 4242
    def __init__(self): self.calls = []; self.alive = True
    def poll(self): return None if self.alive else 0
    def terminate(self): self.calls.append("terminate"); self.alive = False
    def wait(self, timeout=None): self.calls.append("wait")
    def kill(self): self.calls.append("kill")


@unittest.skipIf(sys.platform.startswith("win"), "POSIX file modes")
class TimidityLaunch(unittest.TestCase):
    def setUp(self):
        self.mi = _mi()
        self.tmp = tempfile.TemporaryDirectory()
        self.d = os.path.join(self.tmp.name, "bin"); os.mkdir(self.d); os.chmod(self.d, 0o755)
        self.exe = os.path.join(self.d, "timidity")
        open(self.exe, "w").write("#!/bin/sh\n"); os.chmod(self.exe, 0o755)
        self.mi._timidity_proc = None

    def tearDown(self):
        self.mi._timidity_proc = None
        self.tmp.cleanup()

    def _run(self, which_result, env=None, ports=()):
        mi = self.mi
        popen = mock.Mock(return_value=FakeProc())
        with mock.patch("shutil.which", return_value=which_result), \
             mock.patch("subprocess.Popen", popen), \
             mock.patch.object(mi.mido, "get_output_names", return_value=list(ports)), \
             mock.patch.object(mi.time, "sleep"), \
             mock.patch.dict(os.environ, env or {}, clear=False):
            ok = mi._launch_timidity()
        return ok, popen

    def test_runs_the_full_path_with_a_clean_environment(self):
        env = {"APPDIR": "/tmp/.mount_x", "LD_LIBRARY_PATH": "/tmp/.mount_x/usr/lib:/usr/lib/keep", "PYTHONHOME": "/tmp/.mount_x/usr"}
        ok, popen = self._run(self.exe, env)
        self.assertTrue(ok)
        args, kw = popen.call_args
        self.assertEqual(args[0][0], self.exe)                       # the full path, not a second search of PATH
        self.assertEqual(args[0][1:], self.mi.TIMIDITY_ARGS)
        self.assertEqual(kw["env"]["LD_LIBRARY_PATH"], "/usr/lib/keep")
        self.assertNotIn("PYTHONHOME", kw["env"])
        self.assertIs(kw["stdin"], __import__("subprocess").DEVNULL)

    def test_refuses_a_relative_path(self):
        ok, popen = self._run("timidity")
        self.assertFalse(ok); popen.assert_not_called()

    def test_refuses_a_folder_anyone_can_write_to(self):
        os.chmod(self.d, 0o777)
        ok, popen = self._run(self.exe)
        self.assertFalse(ok); popen.assert_not_called()

    def test_not_found_and_already_running(self):
        ok, popen = self._run(None)
        self.assertFalse(ok); popen.assert_not_called()
        ok, popen = self._run(self.exe, ports=["TiMidity port 0"])
        self.assertFalse(ok); popen.assert_not_called()

    def test_only_our_own_process_is_stopped(self):
        mi = self.mi
        mi._stop_timidity()                                          # nothing launched: must do nothing, no error
        p = FakeProc(); mi._timidity_proc = p
        mi._stop_timidity()
        self.assertEqual(p.calls[:2], ["terminate", "wait"])


if __name__ == "__main__":
    unittest.main()
'''

HELPERS = r'''_timidity_proc = None  # subprocess.Popen handle if we launched it ourselves


def _child_env():
    """The environment for a program started from here.  An AppImage must not hand its own libraries to it."""
    env = dict(os.environ)
    app = env.get("APPDIR", "")
    for k in ("LD_LIBRARY_PATH", "LD_PRELOAD", "PYTHONHOME", "PYTHONPATH", "QT_PLUGIN_PATH"):
        v = env.get(k)
        if v and app:
            keep = [p for p in v.split(os.pathsep) if p and not p.startswith(app)]
            if keep:
                env[k] = os.pathsep.join(keep)
            else:
                env.pop(k, None)
    return env


def _trusted_executable(path):
    """True for an absolute path to a runnable file whose folder is not writable by everyone (POSIX)."""
    try:
        if not path or not os.path.isabs(path) or not os.path.isfile(path) or not os.access(path, os.X_OK):
            return False
        if not sys.platform.startswith("win") and os.stat(os.path.dirname(path)).st_mode & 0o002:
            return False
        return True
    except OSError:
        return False


def _stop_timidity():
    """Stop a TiMidity that this program started (never one that was already running)."""
    p = _timidity_proc
    try:
        if p is not None and p.poll() is None:
            p.terminate()
            try:
                p.wait(timeout=2)
            except Exception:
                p.kill()
    except Exception:
        pass


atexit.register(_stop_timidity)
'''


def rd(p):
    raw = open(p, "rb").read().decode("utf-8")
    return "\r\n" in raw, raw.replace("\r\n", "\n")


def wr(p, t, crlf):
    open(p, "wb").write((t.replace("\n", "\r\n") if crlf else t).encode("utf-8"))


def refuse(msg):
    print("REFUSED: " + msg + "  Nothing changed."); sys.exit(1)


def main():
    changed = False
    crlf, t = rd("midi_io.py")
    if "def _trusted_executable(" not in t:
        pairs = [
            ("_timidity_proc = None  # subprocess.Popen handle if we launched it ourselves\n", HELPERS),
            ("import json\nimport os\n", "import atexit\nimport json\nimport os\n"),
            ('    if not shutil.which("timidity"):\n', '    exe = shutil.which("timidity")\n    if not exe:\n'),
            ("    # Check if a TiMidity port already exists — if so, nothing to do\n",
             '    if not _trusted_executable(exe):   # v22ze-319: full path only, never from "." or a folder anyone can write to\n'
             '        print(f"[TiMidity] Not started: {exe!r} is not an absolute path in a protected folder", file=sys.stderr)\n'
             '        return False\n\n'
             "    # Check if a TiMidity port already exists — if so, nothing to do\n"),
            ('        _timidity_proc = subprocess.Popen(\n            ["timidity"] + TIMIDITY_ARGS,\n            stdout=subprocess.DEVNULL,\n            stderr=subprocess.DEVNULL,\n        )\n',
             '        _timidity_proc = subprocess.Popen(\n            [exe] + TIMIDITY_ARGS,\n            env=_child_env(),\n            stdin=subprocess.DEVNULL,\n'
             '            stdout=subprocess.DEVNULL,\n            stderr=subprocess.DEVNULL,\n        )\n'),
        ]
        for old, new in pairs:
            if t.count(old) != 1:
                refuse("anchor not found exactly once in midi_io.py: %r" % old[:60])
            t = t.replace(old, new)
        wr("midi_io.py", t, crlf); changed = True
    p = os.path.join("tests", "test_timidity_launch.py")
    if not os.path.exists(p) or open(p, encoding="utf-8").read() != TEST:
        open(p, "w", encoding="utf-8", newline="\n").write(TEST); changed = True
    crlf, t = rd("docs/MAINTAINING.md")
    old = "   - Still to review: how `midi_io.py` starts TiMidity; file-path handling on open, drag-in and export; what the problem-report\n     zip contains.\n"
    new = ("   - TiMidity start reviewed (v22ze-319): runs the full path found once (refused when relative or in a folder anyone can\n"
           "     write to), with the AppImage's library settings removed, and is stopped at exit when this program started it.\n"
           "     The settings are fixed strings; no user text reaches the command.\n"
           "   - Still to review: file-path handling on open, drag-in and export; what the problem-report zip contains.\n")
    if "TiMidity start reviewed (v22ze-319)" not in t:
        if t.count(old) != 1:
            refuse("MAINTAINING.md anchor not found exactly once.")
        wr("docs/MAINTAINING.md", t.replace(old, new), crlf); changed = True
    crlf, t = rd("sys_platform.py")
    if 'APP_VERSION = "22ze-319"' not in t:
        if t.count('APP_VERSION = "22ze-318"') != 1:
            refuse("APP_VERSION anchor not found.")
        wr("sys_platform.py", t.replace('APP_VERSION = "22ze-318"', 'APP_VERSION = "22ze-319"'), crlf); changed = True
    import py_compile
    py_compile.compile("midi_io.py", doraise=True); py_compile.compile("sys_platform.py", doraise=True)
    print("Done." if changed else "Already applied. Nothing changed.")


main()

# How midi_io.py starts TiMidity (v22ze-319): which program it runs, with what environment, and that it is stopped again.
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

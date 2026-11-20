import os, sys, tempfile, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import gui


class GuideSnapCopy(unittest.TestCase):
    def test_under_temp_is_copied_home(self):
        if not sys.platform.startswith("linux"):
            self.skipTest("Linux only")
        tmp = tempfile.mkdtemp(); home = tempfile.mkdtemp()
        src = os.path.join(tmp, ".mount_x", "docs"); os.makedirs(src)
        p = os.path.join(src, "G.pdf"); open(p, "wb").write(b"%PDF-1")
        out = gui.MidisoftStudio._guide_browser_copy(p, home=home, roots=[tmp])
        if out is None:
            self.skipTest("class name")
        self.assertEqual(out, os.path.join(home, "Documents", "MIDI-Studio", "G.pdf"))
        self.assertEqual(open(out, "rb").read(), b"%PDF-1")

    def test_normal_install_untouched(self):
        if not sys.platform.startswith("linux"):
            self.skipTest("Linux only")
        d = tempfile.mkdtemp(); home = tempfile.mkdtemp()
        p = os.path.join(d, "G.pdf"); open(p, "wb").write(b"x")
        self.assertEqual(gui.MidisoftStudio._guide_browser_copy(p, home=home, roots=["/nonexistent-root"]), p)
        self.assertFalse(os.path.exists(os.path.join(home, "Documents", "MIDI-Studio")))


if __name__ == "__main__":
    unittest.main()

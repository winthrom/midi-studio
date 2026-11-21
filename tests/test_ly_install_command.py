import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import gui


class LyInstallCommand(unittest.TestCase):
    def test_distros(self):
        if os.name == "nt" or sys.platform == "darwin":
            self.skipTest("Linux only")
        f = gui._ly_install_command
        self.assertEqual(f('NAME="Kubuntu"\nID=ubuntu\nID_LIKE=debian\n'), "sudo apt install lilypond")
        self.assertEqual(f('ID=endeavouros\nID_LIKE=arch\n'), "sudo pacman -S lilypond")
        self.assertEqual(f('ID="fedora"\n'), "sudo dnf install lilypond")
        self.assertEqual(f('ID="opensuse-tumbleweed"\nID_LIKE="opensuse suse"\n'), "sudo zypper install lilypond")
        self.assertIsNone(f('ID=somethingelse\n'))
        self.assertIsNone(f(''))


if __name__ == "__main__":
    unittest.main()

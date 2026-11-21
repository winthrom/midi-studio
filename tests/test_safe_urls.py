import json, os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import sys_platform as sp
import gui

FALLBACK = "https://github.com/winthrom/midi-studio/releases/latest"


class SafeReleaseUrl(unittest.TestCase):
    def test_own_pages_pass(self):
        for u in ("https://github.com/winthrom/midi-studio/releases/tag/v0.4.1",
                  "https://github.com/winthrom/midi-studio/releases/latest"):
            self.assertEqual(sp.safe_release_url(u), u)

    def test_everything_else_becomes_the_releases_page(self):
        for u in ("https://evil.example/winthrom/midi-studio/", "http://github.com/winthrom/midi-studio/x",
                  "https://github.com.evil.com/winthrom/midi-studio/x", "https://github.com/winthrom/midi-studio-evil/x",
                  "https://github.com/winthrom/midi-studio", "file:///etc/passwd", "javascript:alert(1)", "",
                  None, 5, ["https://github.com/winthrom/midi-studio/"],
                  "https://github.com/winthrom/midi-studio/x y", "https://github.com/winthrom/midi-studio/x\n",
                  "https://github.com/winthrom/midi-studio/" + "a" * 400):
            self.assertEqual(sp.safe_release_url(u), FALLBACK, repr(u))

    def test_answer_from_github_is_checked(self):
        import io, urllib.request

        class R(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False
        real = urllib.request.urlopen
        try:
            urllib.request.urlopen = lambda *a, **k: R(json.dumps(
                {"tag_name": "v9.9.9", "html_url": "https://evil.example/download", "name": "x"}).encode())
            info = sp.fetch_latest_release()
        finally:
            urllib.request.urlopen = real
        self.assertEqual(info["url"], FALLBACK)
        self.assertEqual(info["version"], "9.9.9")


class MuseScorePaths(unittest.TestCase):
    def test_full_paths_only(self):
        found = {"mscore": "/usr/bin/mscore", "MuseScore4": "/opt/ms/MuseScore4"}
        self.assertEqual(gui._musescore_paths(which=found.get), ["/usr/bin/mscore", "/opt/ms/MuseScore4"])

    def test_nothing_found(self):
        self.assertEqual(gui._musescore_paths(which=lambda n: None), [])

    def test_same_program_listed_once(self):
        self.assertEqual(gui._musescore_paths(which=lambda n: "/usr/bin/mscore"), ["/usr/bin/mscore"])


if __name__ == "__main__":
    unittest.main()

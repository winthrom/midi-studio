import hashlib, io, os, sys, tempfile, unittest, zipfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import gui


def _zip_bytes():
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr("lilypond-x/share/readme.txt", "hello")
    return b.getvalue()


class _Resp:
    def __init__(self, data):
        self._b = io.BytesIO(data)
        self.headers = {"Content-Length": str(len(data))}

    def read(self, n=-1):
        return self._b.read(n)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class LilyPondPin(unittest.TestCase):
    def setUp(self):
        import urllib.request
        self.dir = tempfile.mkdtemp()
        self.data = _zip_bytes()
        self._d, self._u, self._pins = gui._ly_data_dir, urllib.request.urlopen, dict(gui._LY_PINS)
        gui._ly_data_dir = lambda: self.dir
        urllib.request.urlopen = lambda req, timeout=30: _Resp(self.data)
        self.url = "https://example.invalid/lilypond-test.zip"

    def tearDown(self):
        import urllib.request
        gui._ly_data_dir, urllib.request.urlopen = self._d, self._u
        gui._LY_PINS.clear(); gui._LY_PINS.update(self._pins)

    def test_real_address_is_pinned(self):
        self.assertRegex(gui._LY_PINS[gui._LY_DL_URL], r"^[0-9a-f]{64}$")

    def test_wrong_checksum_is_refused_and_nothing_unpacked(self):
        gui._LY_PINS[self.url] = "0" * 64
        exe, msg = gui._ly_download_and_setup(self.url, lambda *a: None, lambda: False)
        self.assertIsNone(exe)
        self.assertIn("does not match", msg)
        self.assertFalse(os.path.exists(os.path.join(self.dir, "unpack")))
        self.assertFalse(os.path.exists(os.path.join(self.dir, "download.part")))

    def test_address_without_a_pin_is_refused(self):
        exe, msg = gui._ly_download_and_setup(self.url, lambda *a: None, lambda: False)
        self.assertIsNone(exe)
        self.assertIn("no checksum", msg)

    def test_matching_checksum_goes_on_to_unpack(self):
        gui._LY_PINS[self.url] = hashlib.sha256(self.data).hexdigest()
        exe, msg = gui._ly_download_and_setup(self.url, lambda *a: None, lambda: False)
        self.assertIsNone(exe)                      # the test zip holds no lilypond program ...
        self.assertNotIn("checksum", msg)           # ... but it got past the checksum, to the "program not found" step
        self.assertIn("program file", msg)


if __name__ == "__main__":
    unittest.main()

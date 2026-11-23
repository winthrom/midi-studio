import os, struct, sys, tempfile, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _hdr(length=6, fmt=1, ntrk=1, div=480):
    return b"MThd" + struct.pack(">IHHH", length, fmt, ntrk, div)


_NOTE = b"\x00\x90\x3c\x40" + b"\x83\x60\x80\x3c\x40" + b"\x00\xff\x2f\x00"


def _trk(body):
    return b"MTrk" + struct.pack(">I", len(body)) + body


def _write(data):
    fd, p = tempfile.mkstemp(suffix=".mid")
    os.write(fd, data)
    os.close(fd)
    return p


class DamagedMidi(unittest.TestCase):
    def test_gigantic_header_is_refused_quickly(self):
        import gui
        p = _write(_hdr(length=0xFFFFFFFF) + _trk(_NOTE))
        try:
            with self.assertRaises(ValueError) as cm:
                gui.Song.from_mid(p)
        finally:
            os.unlink(p)
        self.assertIn("could not be opened", str(cm.exception))
        self.assertIn("damaged", str(cm.exception))

    def test_ordinary_damage_gives_the_plain_sentence(self):
        import gui
        for data in (b"", b"MThd", _hdr() + b"MTrk\x00\x00\x00\x10\x00\x90",       # cut off
                     _hdr() + _trk(b"\x00\x3c\x40"),                             # running status with nothing before it
                     _hdr() + b"XXXX" + b"\x00" * 20):                           # no track header
            p = _write(data)
            try:
                with self.assertRaises(ValueError) as cm:
                    gui.Song.from_mid(p)
            finally:
                os.unlink(p)
            self.assertIn("could not be opened", str(cm.exception), repr(data[:20]))

    def test_good_file_still_loads(self):
        import gui
        p = _write(_hdr() + _trk(_NOTE))
        try:
            song = gui.Song.from_mid(p)
        finally:
            os.unlink(p)
        self.assertEqual(sum(len(t.notes) for t in song.tracks), 1)

    def test_missing_file_keeps_its_own_message(self):
        import gui
        with self.assertRaises(FileNotFoundError):
            gui.Song.from_mid(os.path.join(tempfile.gettempdir(), "no-such-file-314.mid"))

    def test_error_text_is_short(self):
        import gui
        t = gui._load_error_text(OSError("Message length " + "9" * 500 + " exceeds maximum length 1000000"))
        self.assertLess(len(t), 300)
        self.assertIn("could not be opened", t)


if __name__ == "__main__":
    unittest.main()

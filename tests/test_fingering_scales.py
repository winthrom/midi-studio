"""Tests for scale-run fingering over two octaves (v22ze-289).  Skipped where gui cannot be imported.
Only the cases where the standard pattern is certain are fixed here: right hand both ways in C D E F G A B, left hand
going up in C D E G A, left hand going down in E.  Other keys (black-key scales, left hand down) are not claimed."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

MAJ = [0, 2, 4, 5, 7, 9, 11]
PC = dict(C=0, D=2, E=4, F=5, G=7, A=9, B=11)


def _gui():
    try:
        import gui
        return gui
    except Exception:
        raise unittest.SkipTest("gui could not be imported here")


def _scale(tonic, octs):
    out = [tonic + 12 * o + iv for o in range(octs) for iv in MAJ]
    out.append(tonic + 12 * octs)
    return out


def _fing(gui, pitches, hand):
    res = gui._fp_search([[p] for p in pitches], hand)
    return "".join(str(r[p]) for r, p in zip(res, pitches))


def _rules_off(gui, fn):
    saved = dict(gui._FP_W)
    try:
        gui._FP_W["scale_gap"] = 0.0
        gui._FP_W["scale_mono"] = 0.0
        return fn()
    finally:
        gui._FP_W.clear()
        gui._FP_W.update(saved)


class TestScaleRuns(unittest.TestCase):
    def test_right_hand_two_octaves(self):
        gui = _gui()
        for name in "C D E F G A B".split():
            p = _scale(60 + PC[name], 2)
            with self.subTest(key=name):
                self.assertEqual(_fing(gui, p, "R"), "123123412312345")
                self.assertEqual(_fing(gui, p[::-1], "R"), "543213214321321")

    def test_left_hand_two_octaves_up(self):
        gui = _gui()
        for name in "C D E G A".split():
            with self.subTest(key=name):
                self.assertEqual(_fing(gui, _scale(36 + PC[name], 2), "L"), "543213214321321")

    def test_left_hand_two_octaves_down_e_major(self):
        gui = _gui()
        self.assertEqual(_fing(gui, _scale(36 + PC["E"], 2)[::-1], "L"), "123123412312345")

    def test_thumb_gaps_add_up_to_seven_in_a_long_scale(self):
        gui = _gui()
        for hand, base in (("R", 60), ("L", 36)):
            for name in "C D E G A".split():
                f = _fing(gui, _scale(base + PC[name], 3), hand)
                th = [i for i, c in enumerate(f) if c == "1"]
                gaps = [b - a for a, b in zip(th, th[1:])]
                with self.subTest(hand=hand, key=name):
                    self.assertTrue(all(g in (3, 4) for g in gaps), f)
                    self.assertTrue(all(a + b == 7 for a, b in zip(gaps, gaps[1:])), f)

    def test_chromatic_run_is_not_touched(self):
        gui = _gui()
        p = list(range(60, 73))
        for hand in ("R", "L"):
            on = _fing(gui, p, hand)
            off = _rules_off(gui, lambda: _fing(gui, p, hand))
            self.assertEqual(on, off)

    def test_chords_are_not_touched(self):
        gui = _gui()
        ev = [[48, 52, 55], [50, 53, 57], [52, 55, 59]]
        on = gui._fp_search(ev, "R")
        off = _rules_off(gui, lambda: gui._fp_search(ev, "R"))
        self.assertEqual(on, off)


if __name__ == "__main__":
    unittest.main()

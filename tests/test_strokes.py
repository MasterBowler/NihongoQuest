import math
import random
import unittest

from nihongo_quest.core import strokes as S
from nihongo_quest.core.content import Content
from nihongo_quest.paths import CONTENT_DB


def line(x0, y0, x1, y1, n=12):
    return [(x0 + (x1 - x0) * i / (n - 1), y0 + (y1 - y0) * i / (n - 1)) for i in range(n)]


class Parsing(unittest.TestCase):
    def test_lines(self):
        self.assertEqual(S.parse_path("M10,10L20,10"), [("M", 10.0, 10.0), ("L", 20.0, 10.0)])
        self.assertEqual(S.parse_path("m10,10l5,0"), [("M", 10.0, 10.0), ("L", 15.0, 10.0)])
        self.assertEqual(S.parse_path("M0,0 10,0 10,10"), [("M", 0, 0), ("L", 10, 0), ("L", 10, 10)])
        self.assertEqual(S.parse_path("M0,0H10V5h-5v-5z"),
                         [("M", 0, 0), ("L", 10, 0), ("L", 10, 5), ("L", 5, 5), ("L", 5, 0), ("L", 0, 0)])

    def test_cubics(self):
        segs = S.parse_path("M0,0c10,0,10,10,20,10s10,10,20,10")
        self.assertEqual(segs[1], ("C", 10, 0, 10, 10, 20, 10))
        self.assertEqual(segs[2], ("C", 30, 10, 30, 20, 40, 20))      # first control point is the reflection
        absolute = S.parse_path("M0,0C10,0,10,10,20,10S30,20,40,20")
        self.assertEqual(absolute, segs)

    def test_kanjivg_compact_numbers(self):
        # no separator before a negative number, as KanjiVG writes them
        segs = S.parse_path("M35,16.5c0.25,1.75,0.25,4.25-0.88,6.8C28.91,35.01,22.37,46.02,10.5,60.29")
        self.assertEqual(len(segs), 3)
        self.assertAlmostEqual(segs[1][5], 35 - 0.88)
        self.assertAlmostEqual(segs[1][6], 16.5 + 6.8)
        self.assertEqual(segs[2][5:], (10.5, 60.29))

    def test_quadratic_becomes_cubic(self):
        segs = S.parse_path("M0,0Q10,10,20,0")
        self.assertEqual(segs[1][0], "C")
        self.assertEqual(segs[1][5:], (20, 0))
        mid = S.flatten("M0,0Q10,10,20,0", steps=2)[1]
        self.assertAlmostEqual(mid[0], 10)
        self.assertAlmostEqual(mid[1], 5)          # a quadratic's midpoint is halfway to its control point

    def test_bad_input(self):
        with self.assertRaises(ValueError):
            S.parse_path("10,10")
        with self.assertRaises(ValueError):
            S.parse_path("M10")


class Sampling(unittest.TestCase):
    def test_length_and_resample(self):
        pts = S.flatten("M0,0L30,40")
        self.assertAlmostEqual(S.length(pts), 50)
        r = S.resample(pts, 6)
        self.assertEqual(len(r), 6)
        self.assertEqual(r[0], (0, 0))
        self.assertEqual(r[-1], (30, 40))
        gaps = [math.dist(r[i], r[i + 1]) for i in range(5)]
        for g in gaps:
            self.assertAlmostEqual(g, 10, places=6)

    def test_resample_uneven_input(self):
        pts = [(0, 0), (1, 0), (2, 0), (100, 0)]
        r = S.resample(pts, 11)
        self.assertEqual([round(p[0]) for p in r], list(range(0, 101, 10)))

    def test_degenerate(self):
        self.assertEqual(S.resample([], 5), [])
        self.assertEqual(S.resample([(3, 3)], 4), [(3, 3)] * 4)
        self.assertEqual(S.resample([(3, 3), (3, 3)], 4), [(3, 3)] * 4)

    def test_stroke_points(self):
        pts = S.stroke_points("M10,10c20,0,40,0,60,0", 20)
        self.assertEqual(len(pts), 20)
        self.assertAlmostEqual(pts[0][0], 10)
        self.assertAlmostEqual(pts[-1][0], 70)


class Judging(unittest.TestCase):
    target = line(20, 50, 90, 50)

    def test_accepts_a_wobbly_copy(self):
        drawn = [(x + 5, y + 6 + 2 * math.sin(i)) for i, (x, y) in enumerate(self.target)]
        self.assertTrue(S.judge_stroke(drawn, self.target).ok)

    def test_backwards(self):
        j = S.judge_stroke(list(reversed(self.target)), self.target)
        self.assertFalse(j.ok)
        self.assertEqual(j.reason, "backwards")

    def test_wrong_place(self):
        j = S.judge_stroke(line(20, 95, 90, 95), self.target)
        self.assertFalse(j.ok)
        self.assertEqual(j.reason, "elsewhere")

    def test_too_short_or_too_long(self):
        self.assertEqual(S.judge_stroke(line(20, 50, 30, 50), self.target).reason, "short")
        self.assertEqual(S.judge_stroke([(20, 50)], self.target).reason, "short")
        scribble = line(20, 50, 90, 50) + line(90, 50, 20, 52) + line(20, 52, 90, 50)
        self.assertFalse(S.judge_stroke(scribble, self.target).ok)

    def test_wrong_shape(self):
        self.assertFalse(S.judge_stroke(line(55, 15, 55, 85), self.target).ok)

    def test_dots_only_need_to_be_in_the_right_spot(self):
        dot = line(50, 20, 55, 28, n=5)
        self.assertTrue(S.judge_stroke(line(52, 18, 58, 25, n=4), dot).ok)
        self.assertTrue(S.judge_stroke(line(56, 27, 51, 21, n=4), dot).ok)     # direction of a dot is not policed
        self.assertFalse(S.judge_stroke(line(20, 80, 25, 88, n=4), dot).ok)


@unittest.skipUnless(CONTENT_DB.exists(), "content.db has not been built")
class RealKanji(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.content = Content(CONTENT_DB)

    def strokes(self, ch):
        return [list(S.stroke_points(d)) for d in self.content.strokes(ch).paths]

    def test_every_course_kanji_parses(self):
        for k in self.content.course:
            st = self.content.strokes(k.ch)
            self.assertIsNotNone(st, k.ch)
            # the two sources count a few shapes differently (e.g. 辶), but never by much
            self.assertLessEqual(abs(len(st.paths) - k.strokes), 2, k.ch)
            for d in st.paths:
                pts = S.stroke_points(d)
                self.assertEqual(len(pts), 32)
                self.assertTrue(all(-5 <= x <= 114 and -5 <= y <= 114 for x, y in pts), k.ch)

    def test_strokes_match_themselves_not_their_neighbours(self):
        for ch in "三川十":
            st = self.strokes(ch)
            for i, a in enumerate(st):
                for j, b in enumerate(st):
                    self.assertEqual(S.judge_stroke(a, b).ok, i == j, f"{ch} stroke {i} vs {j}")
            for i, a in enumerate(st):
                self.assertEqual(S.best_match(a, st), i)

    def test_shaky_hand_is_accepted(self):
        rng = random.Random(7)
        for ch in "休語日曜あア":
            for target in self.strokes(ch):
                dx, dy = rng.uniform(-5, 5), rng.uniform(-5, 5)
                drawn = [(x * 1.05 + dx + rng.uniform(-1.5, 1.5), y * 0.96 + dy + rng.uniform(-1.5, 1.5))
                         for x, y in target[::2]]
                self.assertTrue(S.judge_stroke(drawn, target).ok, ch)

    def test_component_groups_cover_valid_strokes(self):
        for ch in "休語曜鬱":
            st = self.content.strokes(ch)
            seen = set()
            for g in st.groups:
                self.assertTrue(g["strokes"], ch)
                self.assertTrue(all(0 <= i < len(st.paths) for i in g["strokes"]))
                self.assertFalse(seen & set(g["strokes"]), f"{ch}: top-level components overlap")
                seen |= set(g["strokes"])
                for sub in g.get("sub", []):
                    self.assertTrue(set(sub["strokes"]) <= set(g["strokes"]))


if __name__ == "__main__":
    unittest.main()

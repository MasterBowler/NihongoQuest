import unittest
from datetime import datetime

from nihongo_quest.core import srs
from nihongo_quest.core.srs import AGAIN, EASY, GOOD, HARD, CardState, Scheduler

NOON = datetime(2026, 1, 15, 12, 0).timestamp()
DAY = srs.DAY


class NewCards(unittest.TestCase):
    def setUp(self):
        self.s = Scheduler()

    def test_first_good_enters_learning(self):
        c = self.s.answer(CardState(), GOOD, NOON)
        self.assertEqual(c.state, srs.LEARNING)
        self.assertAlmostEqual(c.stability, 3.7145)
        self.assertAlmostEqual(c.difficulty, 5.1618)
        self.assertAlmostEqual(c.due, NOON + 600)
        self.assertEqual(c.reps, 1)
        self.assertEqual(c.last_review, NOON)

    def test_good_good_graduates_in_four_days(self):
        c = self.s.answer(CardState(), GOOD, NOON)
        c = self.s.answer(c, GOOD, NOON + 600)
        self.assertEqual(c.state, srs.REVIEW)
        self.assertEqual(c.scheduled_days, 4)
        self.assertEqual(c.due, self.s.day_start(self.s.day_index(NOON) + 4))
        self.assertAlmostEqual(c.stability, 3.7145)

    def test_easy_skips_learning(self):
        c = self.s.answer(CardState(), EASY, NOON)
        self.assertEqual(c.state, srs.REVIEW)
        self.assertEqual(c.scheduled_days, 14)

    def test_again_starts_weak(self):
        c = self.s.answer(CardState(), AGAIN, NOON)
        self.assertEqual(c.state, srs.LEARNING)
        self.assertAlmostEqual(c.stability, 0.4872)
        self.assertAlmostEqual(c.difficulty, 5.1618 + 2 * 1.2298)
        self.assertAlmostEqual(c.due, NOON + 60)
        c = self.s.answer(c, GOOD, NOON + 60)
        self.assertEqual((c.state, c.scheduled_days), (srs.REVIEW, 1))

    def test_failing_a_learning_step_resets_stability(self):
        c = self.s.answer(CardState(), GOOD, NOON)
        c = self.s.answer(c, AGAIN, NOON + 600)
        self.assertEqual(c.state, srs.LEARNING)
        self.assertAlmostEqual(c.stability, 0.4872)
        c = self.s.answer(c, GOOD, NOON + 700)
        self.assertEqual(c.scheduled_days, 1)

    def test_hard_in_learning_repeats_without_penalty(self):
        c = self.s.answer(CardState(), GOOD, NOON)
        c = self.s.answer(c, HARD, NOON + 600)
        self.assertEqual(c.state, srs.LEARNING)
        self.assertAlmostEqual(c.stability, 3.7145)
        self.assertAlmostEqual(c.due, NOON + 600 + 300)

    def test_easy_in_learning_is_one_day_longer_than_good(self):
        c = self.s.answer(CardState(), GOOD, NOON)
        p = self.s.preview(c, NOON + 600)
        self.assertEqual(p[EASY].scheduled_days, p[GOOD].scheduled_days + 1)


class Reviews(unittest.TestCase):
    """Expected values below were worked out by hand from the FSRS-4.5 formulas."""

    def setUp(self):
        self.s = Scheduler()
        c = self.s.answer(CardState(), GOOD, NOON)
        self.card = self.s.answer(c, GOOD, NOON + 600)          # review card, S=3.7145, D=5.1618
        self.later = NOON + 4 * DAY

    def test_retrievability_on_due_day(self):
        self.assertAlmostEqual(self.s.retrievability(self.card, self.later), 0.8935, places=3)
        self.assertAlmostEqual(self.s.retrievability(self.card, NOON + 700), 1.0)
        self.assertEqual(self.s.retrievability(CardState(), NOON), 0.0)

    def test_good(self):
        c = self.s.answer(self.card, GOOD, self.later)
        self.assertEqual(c.state, srs.REVIEW)
        self.assertAlmostEqual(c.stability, 14.81, delta=0.05)
        self.assertAlmostEqual(c.difficulty, 5.1618, places=4)
        self.assertEqual(c.scheduled_days, 15)
        self.assertEqual(c.reps, 3)

    def test_hard(self):
        c = self.s.answer(self.card, HARD, self.later)
        self.assertAlmostEqual(c.stability, 6.235, delta=0.03)
        self.assertAlmostEqual(c.difficulty, 6.0315, delta=0.001)
        self.assertEqual(c.scheduled_days, 6)

    def test_easy(self):
        c = self.s.answer(self.card, EASY, self.later)
        self.assertAlmostEqual(c.stability, 35.61, delta=0.15)
        self.assertEqual(c.scheduled_days, 36)

    def test_lapse(self):
        c = self.s.answer(self.card, AGAIN, self.later)
        self.assertEqual(c.state, srs.RELEARNING)
        self.assertEqual(c.lapses, 1)
        self.assertAlmostEqual(c.stability, 1.433, delta=0.01)
        self.assertGreater(c.difficulty, self.card.difficulty)
        self.assertAlmostEqual(c.due, self.later + 600)
        back = self.s.answer(c, GOOD, self.later + 600)
        self.assertEqual((back.state, back.scheduled_days), (srs.REVIEW, 1))

    def test_ordering_of_intervals(self):
        p = self.s.preview(self.card, self.later)
        self.assertLess(p[HARD].scheduled_days, p[GOOD].scheduled_days)
        self.assertLess(p[GOOD].scheduled_days, p[EASY].scheduled_days)

    def test_lapse_never_increases_stability(self):
        young = CardState(state=srs.REVIEW, stability=0.2, difficulty=1.0, last_review=NOON, reps=2)
        c = self.s.answer(young, AGAIN, NOON + DAY)
        self.assertLessEqual(c.stability, 0.2)

    def test_many_good_reviews_keep_growing(self):
        c, t = self.card, self.later
        intervals = []
        for _ in range(8):
            c = self.s.answer(c, GOOD, t)
            intervals.append(c.scheduled_days)
            t = c.due + 3600
        self.assertEqual(intervals, sorted(intervals))
        self.assertGreater(intervals[-1], 365)

    def test_retention_setting_changes_interval(self):
        lax = Scheduler(retention=0.8)
        c = lax.answer(lax.answer(CardState(), GOOD, NOON), GOOD, NOON + 600)
        self.assertEqual(c.scheduled_days, 9)
        strict = Scheduler(retention=0.95)
        c = strict.answer(strict.answer(CardState(), GOOD, NOON), GOOD, NOON + 600)
        self.assertEqual(c.scheduled_days, 2)
        with self.assertRaises(ValueError):
            Scheduler(retention=0.5)

    def test_max_interval(self):
        s = Scheduler(max_interval=30)
        big = CardState(state=srs.REVIEW, stability=500, difficulty=5, last_review=NOON, reps=9)
        self.assertEqual(s.answer(big, EASY, NOON + 400 * DAY).scheduled_days, 30)

    def test_bad_rating(self):
        with self.assertRaises(ValueError):
            self.s.answer(self.card, 5, self.later)


class Days(unittest.TestCase):
    def test_rollover_at_four(self):
        s = Scheduler()
        before = datetime(2026, 3, 10, 3, 59).timestamp()
        after = datetime(2026, 3, 10, 4, 1).timestamp()
        self.assertEqual(s.day_index(after) - s.day_index(before), 1)
        self.assertEqual(s.day_index(datetime(2026, 3, 10, 23, 59).timestamp()), s.day_index(after))
        self.assertEqual(s.day_start(s.day_index(after)), datetime(2026, 3, 10, 4, 0).timestamp())

    def test_review_due_is_available_from_day_start(self):
        s = Scheduler()
        late = datetime(2026, 3, 10, 22, 0).timestamp()
        c = s.answer(s.answer(CardState(), GOOD, late), GOOD, late + 600)
        self.assertEqual(c.due, datetime(2026, 3, 14, 4, 0).timestamp())


class Text(unittest.TestCase):
    def test_interval_text(self):
        cases = {45: "45s", 600: "10m", 7200: "2h", 4 * DAY: "4d", 61 * DAY: "2mo", 45 * DAY: "1.5mo",
                 400 * DAY: "1.1y", 730 * DAY: "2y", -5: "0s"}
        for secs, want in cases.items():
            self.assertEqual(srs.interval_text(secs), want, secs)

    def test_due_text(self):
        s = Scheduler()
        learning = s.answer(CardState(), GOOD, NOON)
        self.assertEqual(srs.due_text(learning, NOON), "10m")
        review = s.answer(learning, GOOD, NOON + 600)
        self.assertEqual(srs.due_text(review, NOON + 600), "4d")

    def test_maturity(self):
        self.assertEqual(srs.maturity(CardState()), "new")
        self.assertEqual(srs.maturity(CardState(state=srs.LEARNING)), "learning")
        self.assertEqual(srs.maturity(CardState(state=srs.REVIEW, scheduled_days=5)), "young")
        self.assertEqual(srs.maturity(CardState(state=srs.REVIEW, scheduled_days=30)), "mature")


if __name__ == "__main__":
    unittest.main()

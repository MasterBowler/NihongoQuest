import random
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from nihongo_quest.core import progress as P
from nihongo_quest.core import srs
from nihongo_quest.core.content import Content
from nihongo_quest.core.progress import KANJI, KNOWN, SUSPENDED, VOCAB, Progress
from nihongo_quest.core.session import StudySession
from nihongo_quest.core.srs import AGAIN, EASY, GOOD, CardState
from nihongo_quest.paths import CONTENT_DB

NOON = datetime(2026, 1, 15, 12, 0).timestamp()
DAY = srs.DAY


class Clock:
    def __init__(self, t=NOON):
        self.t = t

    def __call__(self):
        return self.t

    def advance(self, seconds):
        self.t += seconds


@unittest.skipUnless(CONTENT_DB.exists(), "content.db has not been built")
class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.content = Content(CONTENT_DB)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "progress.db"
        self.p = Progress(self.path, self.content)
        self.clock = Clock()

    def tearDown(self):
        self.p.close()
        self.tmp.cleanup()

    def make_review(self, kind, item, due, stability=5.0, last=None):
        """Put a graduated card straight into the store."""
        s = CardState(state=srs.REVIEW, due=due, stability=stability, difficulty=5.0, reps=2,
                      last_review=last if last is not None else due - 5 * DAY, scheduled_days=5)
        card = P.Card(kind, item, s, created=due - 10 * DAY)
        self.p._save(card)
        return card


class Content10k(Base):
    def test_shape(self):
        c = self.content
        self.assertEqual(len(c.words), 10000)
        self.assertEqual([w.id for w in c.words[:3]], [1, 2, 3])
        self.assertEqual(len({w.key for w in c.words}), 10000)
        self.assertGreater(len(c.course), 2136)
        self.assertEqual(c.course[0].ch, "日")
        self.assertEqual(sorted(w.freq_rank for w in c.words), list(range(1, 10001)))
        for w in c.words:
            self.assertTrue(w.word and w.kana and w.romaji and w.meaning and w.senses, w.key)
            self.assertIn(w.level, (5, 4, 3, 2, 1, 0))
            self.assertIn(w.band, (5, 4, 3, 2, 1))

    def test_furigana_spells_out_the_word(self):
        for w in self.content.words:
            if w.furi:
                self.assertEqual("".join(b for b, _ in w.furi), w.word, w.key)

    def test_lookup_and_search(self):
        c = self.content
        taberu = next(w for w in c.words if w.word == "食べる")
        self.assertEqual((taberu.kana, taberu.romaji, taberu.level), ("たべる", "taberu", 5))
        self.assertEqual(taberu.kanji, ["食"])
        self.assertTrue(taberu.accepts_reading("taberu"))
        self.assertFalse(taberu.accepts_reading("nomu"))
        self.assertIs(c.word(taberu.id), taberu)
        self.assertIs(c.word_by_key(taberu.key), taberu)
        for query in ("食べる", "たべる", "taberu", "TABERU", "to eat"):
            self.assertIs(c.search(query)[0], taberu, query)
        self.assertIn(taberu, c.search("eat"))
        self.assertEqual(c.search("zzzzqq"), [])
        self.assertEqual(len(c.search("")), 10000)
        n5 = [w for w in c.words if w.level == 5]
        self.assertTrue(all(w.level == 5 for w in c.search("ka", pool=n5)))

    def test_examples_and_kanji(self):
        c = self.content
        taberu = next(w for w in c.words if w.word == "食べる")
        ex = c.examples(taberu.id)
        self.assertTrue(ex)
        self.assertIn(ex[0].form, ex[0].jp)
        self.assertEqual("".join(b for b, _ in ex[0].segments), ex[0].jp)
        k = c.kanji("休")
        self.assertEqual((k.strokes, k.jlpt, k.on), (6, 5, ("キュウ",)))
        self.assertIn("rest", k.meanings)
        self.assertEqual([g["el"] for g in c.strokes("休").groups], ["亻", "木"])
        self.assertEqual(c.strokes("休").groups[0]["name"], "person")
        words = c.words_for_kanji("休")
        self.assertIn(("休む", "やす"), [(w.word, r) for w, r in words])
        self.assertEqual(c.reading_in_word("休", words[0][0]), words[0][1])
        self.assertIsNone(c.kanji("x"))
        self.assertIsNone(c.strokes("x"))
        self.assertIn("休", [x.ch for x in c.search_kanji("rest")])
        self.assertIn("休", [x.ch for x in c.search_kanji("kyuu")])
        self.assertIn("休", [x.ch for x in c.search_kanji("やす")])
        self.assertEqual([x.ch for x in c.search_kanji("休日")], ["日", "休"])

    def test_pos_labels(self):
        c = self.content
        self.assertEqual(c.pos_labels(["v5k", "vt"]), ["godan verb", "transitive"])
        self.assertEqual(c.pos_labels(["n", "n"]), ["noun"])
        self.assertTrue(c.pos_label("adj-nari"))          # falls back to the dictionary's description


class Store(Base):
    def test_introduce_and_answer(self):
        w = self.content.words[0]
        self.assertEqual(self.p.status(VOCAB, w.key), "unseen")
        card = self.p.introduce(VOCAB, w.key, NOON)
        self.assertEqual(self.p.status(VOCAB, w.key), "new")
        self.assertEqual(card.s.due, NOON + 45)
        self.assertIs(self.p.introduce(VOCAB, w.key, NOON + 5), card)        # idempotent
        card = self.p.answer(card, GOOD, NOON + 60, 3000, "recognition")
        self.assertEqual(self.p.status(VOCAB, w.key), "learning")
        card = self.p.answer(card, GOOD, NOON + 700, 2000, "recognition")
        self.assertEqual(self.p.status(VOCAB, w.key), "young")
        row = self.p.day_row(self.p.today(NOON))
        self.assertEqual((row["reviews"], row["correct"], row["new_vocab"], row["seconds"]), (2, 2, 1, 5))
        self.assertEqual(self.p.xp, P.XP_NEW_ITEM + 2 * P.XP_FOR_RATING[GOOD])
        self.assertEqual(row["xp"], self.p.xp)
        self.assertEqual(self.p.learned_count(VOCAB), 1)

    def test_everything_survives_a_restart(self):
        w = self.content.words[0]
        card = self.p.introduce(VOCAB, w.key, NOON)
        card = self.p.answer(card, EASY, NOON + 60)
        self.p.set_setting("new_vocab_per_day", 22)
        self.p.set_note(KANJI, "休", "a person resting against a tree")
        self.p.close()
        self.p = Progress(self.path, self.content)
        self.assertEqual(self.p.card(VOCAB, w.key), card)
        self.assertEqual(self.p.setting("new_vocab_per_day"), 22)
        self.assertEqual(self.p.setting("retention"), 0.9)
        self.assertEqual(self.p.note(KANJI, "休"), "a person resting against a tree")
        self.p.set_note(KANJI, "休", "  ")
        self.assertEqual(self.p.note(KANJI, "休"), "")
        with self.assertRaises(KeyError):
            self.p.set_setting("no_such_setting", 1)

    def test_retention_setting_reaches_the_scheduler(self):
        self.assertEqual(self.p.scheduler.retention, 0.9)
        self.p.set_setting("retention", 0.85)
        self.assertEqual(self.p.scheduler.retention, 0.85)

    def test_queues(self):
        words = self.content.words
        self.assertEqual(self.p.counts(VOCAB, NOON), {"review": 0, "learning": 0, "new": 15})
        self.assertEqual(self.p.next_new(VOCAB, 3), [w.key for w in words[:3]])
        self.make_review(VOCAB, words[0].key, NOON - DAY)
        self.make_review(VOCAB, words[1].key, NOON + 3 * DAY)        # not due yet
        self.p.introduce(VOCAB, words[2].key, NOON)
        self.assertEqual(self.p.counts(VOCAB, NOON), {"review": 1, "learning": 1, "new": 14})
        self.assertEqual(self.p.next_new(VOCAB, 2), [words[3].key, words[4].key])
        self.assertEqual([c.item for c in self.p.due_reviews(VOCAB, NOON)], [words[0].key])
        self.assertEqual(self.p.forecast(5, NOON), [1, 0, 0, 1, 0])
        self.assertEqual(self.p.next_new(VOCAB, 0), [])

    def test_due_reviews_put_the_most_forgotten_first(self):
        words = self.content.words
        self.make_review(VOCAB, words[0].key, NOON - DAY, stability=50, last=NOON - 2 * DAY)
        self.make_review(VOCAB, words[1].key, NOON - DAY, stability=2, last=NOON - 20 * DAY)
        self.assertEqual([c.item for c in self.p.due_reviews(VOCAB, NOON)], [words[1].key, words[0].key])

    def test_level_filter_and_frequency_order(self):
        self.p.set_setting("levels", [3])
        first = self.p.unseen_vocab()[0]
        self.assertEqual(first.level, 3)
        self.p.set_setting("levels", [5, 4, 3, 2, 1, 0])
        self.p.set_setting("order", "frequency")
        self.assertEqual([w.freq_rank for w in self.p.unseen_vocab()[:3]], [1, 2, 3])

    def test_kanji_follow_the_vocabulary(self):
        self.assertEqual(self.p.next_new(KANJI, 2), [k.ch for k in self.content.course[:2]])
        word = next(w for w in self.content.words if w.word == "漫画")
        self.p.introduce(VOCAB, word.key, NOON)
        self.assertEqual(self.p.next_new(KANJI, 3), ["画", "漫", self.content.course[0].ch])
        self.p.set_setting("kanji_from_vocab", False)
        self.assertEqual(self.p.next_new(KANJI, 1), [self.content.course[0].ch])

    def test_flags(self):
        w = self.content.words[5]
        self.p.set_flag(VOCAB, w.key, KNOWN, NOON)
        self.assertEqual(self.p.status(VOCAB, w.key), "known")
        self.assertNotIn(w.key, self.p.next_new(VOCAB, 20))
        self.assertEqual(self.p.learned_count(VOCAB), 1)
        self.p.set_flag(VOCAB, w.key, SUSPENDED, NOON)
        self.assertEqual(self.p.status(VOCAB, w.key), "suspended")
        self.assertEqual(self.p.due_reviews(VOCAB, NOON + 99 * DAY), [])
        self.p.forget(VOCAB, w.key)
        self.assertEqual(self.p.status(VOCAB, w.key), "unseen")

    def test_mark_level_known(self):
        n5 = sum(1 for w in self.content.words if w.level == 5)
        self.p.introduce(VOCAB, next(w.key for w in self.content.words if w.level == 5), NOON)
        self.assertEqual(self.p.mark_level_known(5, NOON), n5 - 1)
        self.assertNotEqual(self.p.unseen_vocab()[0].level, 5)
        counts = self.p.status_counts(VOCAB)
        self.assertEqual(counts[5]["known"], n5 - 1)
        self.assertEqual(counts[5]["learning"], 1)
        self.assertEqual(counts[5]["total"], n5)
        self.assertEqual(sum(b["total"] for b in counts.values()), 10000)

    def test_new_allowance_counts_down(self):
        self.p.set_setting("new_vocab_per_day", 2)
        self.assertEqual(self.p.new_allowance(VOCAB, NOON), 2)
        self.p.introduce(VOCAB, self.content.words[0].key, NOON)
        self.assertEqual(self.p.new_allowance(VOCAB, NOON), 1)
        self.p.introduce(VOCAB, self.content.words[1].key, NOON)
        self.p.introduce(VOCAB, self.content.words[2].key, NOON)
        self.assertEqual(self.p.new_allowance(VOCAB, NOON), 0)
        self.assertEqual(self.p.new_allowance(VOCAB, NOON + DAY), 2)          # a new day
        self.assertEqual(self.p.new_allowance(KANJI, NOON), 5)

    def test_levels_and_ranks(self):
        self.assertEqual([P.xp_to_reach(n) for n in (1, 2, 3, 4)], [0, 100, 300, 600])
        self.assertEqual([P.level_for_xp(x) for x in (0, 99, 100, 299, 300, 4500)], [1, 1, 2, 2, 3, 10])
        self.assertEqual(P.rank_for_level(1), ("初心者", "Novice"))
        self.assertEqual(P.rank_for_level(22)[0], "侍")
        self.assertEqual(P.rank_for_level(999)[0], "伝説")
        self.p.add_xp(150, NOON)
        info = self.p.level_info()
        self.assertEqual((info["level"], info["into"], info["span"]), (2, 50, 200))

    def test_streak(self):
        self.assertEqual(self.p.streak(NOON), 0)
        for back in (3, 2, 1):
            self.p.record(NOON - back * DAY, reviews=4)
        self.assertEqual(self.p.streak(NOON), 3)             # today not studied yet: streak still alive
        self.p.record(NOON, reviews=1)
        self.assertEqual(self.p.streak(NOON), 4)
        self.assertEqual(self.p.streak(NOON + 2 * DAY), 0)   # a missed day breaks it
        self.assertEqual([d["reviews"] for d in self.p.history(5, NOON)], [0, 4, 4, 4, 1])

    def test_goal(self):
        self.p.set_setting("daily_goal", 30)
        self.p.record(NOON, reviews=12, new_vocab=3)
        self.assertEqual(self.p.goal_progress(NOON), (15, 30))

    def test_quests(self):
        quests = self.p.quests(NOON)
        self.assertEqual(len(quests), 3)
        self.assertEqual([q.id for q, _, _ in quests], [q.id for q, _, _ in self.p.quests(NOON + 3600)])
        self.assertEqual(len({q.metric for q, _, _ in quests}), 3)
        self.assertTrue(all(v == 0 and not done for _, v, done in quests))
        self.assertEqual(self.p.claim_quests(NOON), [])
        q = quests[0][0]
        amount = q.target * 60 if q.metric == "minutes" else q.target
        column = "seconds" if q.metric == "minutes" else q.metric
        if column == "best_combo":
            self.p.record_combo(amount, NOON)
        else:
            self.p.record(NOON, **{column: amount})
        before = self.p.xp
        self.assertEqual([x.id for x in self.p.claim_quests(NOON)], [q.id])
        self.assertEqual(self.p.xp, before + q.reward)
        self.assertEqual(self.p.claim_quests(NOON), [])           # rewarded once only
        self.assertTrue(self.p.quests(NOON)[0][2])
        other_days = {tuple(x.id for x, _, _ in self.p.quests(NOON + d * DAY)) for d in range(1, 15)}
        self.assertGreater(len(other_days), 5)                    # they change from day to day

    def test_retention_and_leeches(self):
        w = self.content.words[0]
        card = self.make_review(VOCAB, w.key, NOON - DAY)
        card = self.p.answer(card, AGAIN, NOON)
        card = self.p.answer(card, GOOD, NOON + 700)
        self.assertEqual(self.p.retention(30, NOON + 800), (0, 1))      # only the graduated-card review counts
        self.assertEqual([c.item for c in self.p.leeches(VOCAB)], [w.key])
        self.assertEqual(self.p.totals()["reviews"], 2)

    def test_backup_and_reset(self):
        folder = Path(self.tmp.name) / "backups"
        self.assertIsNone(self.p.backup(folder))                  # nothing to back up yet
        self.p.introduce(VOCAB, self.content.words[0].key, NOON)
        made = self.p.backup(folder)
        self.assertTrue(made.exists())
        self.assertIsNone(self.p.backup(folder))                  # once per day
        self.p.set_setting("daily_goal", 77)
        self.p.reset_all(folder)
        self.assertEqual((len(self.p.cards), self.p.xp), (0, 0))
        self.assertEqual(self.p.setting("daily_goal"), 77)        # settings are kept
        self.assertEqual(len(list(folder.glob("before-reset-*.db"))), 1)


class Sessions(Base):
    def session(self, kind=VOCAB, seed=1):
        return StudySession(self.p, kind, now=self.clock, rng=random.Random(seed))

    def test_lessons_then_quizzes_until_done(self):
        self.p.set_setting("new_vocab_per_day", 3)
        s = self.session()
        self.assertEqual((s.total, s.remaining()), (3, {"new": 3, "learning": 0, "review": 0}))
        keys = [w.key for w in self.content.words[:3]]
        for key in keys:
            prompt = s.next()
            self.assertTrue(prompt.is_lesson)
            self.assertEqual(prompt.item, key)
            self.assertEqual(s.preview(), {})
            s.finish_lesson()
            self.clock.advance(10)
        self.assertEqual(s.stats.lessons, 3)
        # nothing is due yet and nothing else is left, so the first lesson is quizzed early
        prompt = s.next()
        self.assertEqual((prompt.item, prompt.mode, prompt.is_lesson), (keys[0], "recognition", False))
        self.assertEqual(s.preview(), {1: "1m", 2: "5m", 3: "10m", 4: "14d"})
        s.answer(GOOD, 1500)
        seen = []
        while (prompt := s.next()) is not None:
            seen.append(prompt.item)
            s.answer(GOOD, 1000)
            self.clock.advance(30)
            self.assertLess(len(seen), 20, "session does not terminate")
        self.assertTrue(s.done())
        self.assertEqual(sorted(set(seen)), sorted(keys))
        self.assertEqual((s.stats.answered, s.stats.correct, s.stats.best_combo), (6, 6, 6))
        self.assertEqual(s.stats.accuracy, 1.0)
        self.assertTrue(all(self.p.status(VOCAB, k) == "young" for k in keys))
        self.assertEqual(s.xp_gained, 3 * P.XP_NEW_ITEM + 6 * P.XP_FOR_RATING[GOOD])
        self.assertEqual(self.p.counts(VOCAB, self.clock()), {"review": 0, "learning": 0, "new": 0})

    def test_lessons_do_not_pile_up(self):
        self.p.set_setting("new_vocab_per_day", 8)
        s = self.session()
        for _ in range(StudySession.WAITING_CAP):
            self.assertTrue(s.next().is_lesson)
            s.finish_lesson()
        prompt = s.next()                                   # sixth: a quiz, not another lesson
        self.assertFalse(prompt.is_lesson)
        self.assertEqual(prompt.item, self.content.words[0].key)

    def test_due_learning_card_jumps_the_queue(self):
        self.p.set_setting("new_vocab_per_day", 4)
        s = self.session()
        s.next()
        s.finish_lesson()
        self.assertTrue(s.next().is_lesson)                 # the first lesson is not due for 45 s
        self.clock.advance(60)
        prompt = s.next()
        self.assertEqual((prompt.is_lesson, prompt.item), (False, self.content.words[0].key))

    def test_new_items_are_spread_between_reviews(self):
        words = self.content.words
        for w in words[10:16]:
            self.make_review(VOCAB, w.key, NOON - DAY)
        self.p.set_setting("new_vocab_per_day", 2)
        s = self.session()
        self.assertEqual(s.remaining(), {"new": 2, "learning": 0, "review": 6})
        kinds = []
        for _ in range(8):
            prompt = s.next()
            kinds.append("L" if prompt.is_lesson else "R")
            if prompt.is_lesson:
                s.finish_lesson()
            else:
                s.answer(GOOD)
        self.assertEqual("".join(kinds), "LRRRLRRR")

    def test_again_keeps_the_card_in_the_session(self):
        w = self.content.words[20]
        self.make_review(VOCAB, w.key, NOON - DAY)
        self.p.set_setting("new_vocab_per_day", 0)
        s = self.session()
        self.assertEqual(s.next().item, w.key)
        self.assertEqual(s.preview()[1], "10m")
        card = s.answer(AGAIN)
        self.assertEqual(card.s.state, srs.RELEARNING)
        self.assertEqual((s.stats.combo, s.stats.correct), (0, 0))
        self.assertFalse(s.done())
        self.assertEqual(s.next().item, w.key)              # comes back (ahead of time: nothing else to do)
        s.answer(GOOD)
        self.assertTrue(s.done())
        self.assertIsNone(s.next())
        self.assertEqual(self.p.card(VOCAB, w.key).s.lapses, 1)

    def test_known_lesson_and_skip(self):
        self.p.set_setting("new_vocab_per_day", 2)
        s = self.session()
        first = s.next().item
        s.finish_lesson(known=True)
        self.assertEqual(self.p.status(VOCAB, first), "known")
        self.assertEqual(s.stats.lessons, 0)
        second = s.next().item
        s.skip()
        self.assertEqual(self.p.status(VOCAB, second), "unseen")
        self.assertTrue(s.done())
        with self.assertRaises(RuntimeError):
            s.answer(GOOD)
        with self.assertRaises(RuntimeError):
            s.finish_lesson()

    def test_combo_bonus(self):
        for w in self.content.words[:10]:
            self.make_review(VOCAB, w.key, NOON - DAY)
        self.p.set_setting("new_vocab_per_day", 0)
        s = self.session()
        while s.next() is not None:
            s.answer(GOOD)
        self.assertEqual(s.stats.best_combo, 10)
        self.assertEqual(s.xp_gained, 10 * P.XP_FOR_RATING[GOOD] + 20)
        self.assertEqual(self.p.day_row(self.p.today(NOON))["best_combo"], 10)

    def test_review_cap(self):
        for w in self.content.words[:9]:
            self.make_review(VOCAB, w.key, NOON - DAY)
        self.p.set_setting("review_cap", 4)
        self.p.set_setting("new_vocab_per_day", 0)
        self.assertEqual(self.session().remaining()["review"], 4)

    def test_modes(self):
        w = self.content.words[30]
        self.make_review(VOCAB, w.key, NOON - DAY)
        self.p.set_setting("new_vocab_per_day", 0)
        for mode in ("recognition", "listening", "recall"):
            self.p.set_setting("vocab_mode", mode)
            self.assertEqual(self.session().next().mode, mode)
        self.p.set_setting("vocab_mode", "mixed")
        seen = {self.session(seed=i).next().mode for i in range(30)}
        self.assertEqual(seen, {"recognition", "listening", "recall"})

    def test_kanji_session(self):
        self.p.set_setting("new_kanji_per_day", 2)
        self.p.set_setting("kanji_mode", "writing")
        s = self.session(KANJI)
        first = s.next()
        self.assertEqual((first.item, first.is_lesson), ("日", True))
        s.finish_lesson()
        self.clock.advance(60)
        quiz = s.next()
        self.assertEqual((quiz.item, quiz.mode), ("日", "recognition"))       # first quiz is always recognition
        s.answer(GOOD)
        self.clock.advance(601)
        self.assertEqual(s.next().mode, "writing")
        self.assertEqual(self.p.day_row(self.p.today(NOON))["new_kanji"], 1)
        with self.assertRaises(ValueError):
            StudySession(self.p, "grammar")


if __name__ == "__main__":
    unittest.main()

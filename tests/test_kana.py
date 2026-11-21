import unittest

from nihongo_quest.core import kana as K


class ToRomaji(unittest.TestCase):
    def test_words(self):
        cases = {
            "とうきょう": "toukyou",
            "コーヒー": "koohii",
            "がっこう": "gakkou",
            "まっちゃ": "matcha",
            "きんえん": "kin'en",
            "ほんや": "hon'ya",
            "しんぶん": "shinbun",
            "じゅう": "juu",
            "ティッシュ": "tisshu",
            "ファイル": "fairu",
            "ヴァイオリン": "vaiorin",
            "パーティー": "paatii",
            "ウィスキー": "wisukii",
            "チェック": "chekku",
            "おちゃ": "ocha",
            "りょこう": "ryokou",
            "ざっし": "zasshi",
            "みっつ": "mittsu",
            "を": "o",
            "あっ": "a",
            "つづく": "tsuzuku",
        }
        for kana, want in cases.items():
            self.assertEqual(K.to_romaji(kana), want, kana)

    def test_particle_wa(self):
        self.assertEqual(K.to_romaji("こんにちは", final_wa=True), "konnichiwa")
        self.assertEqual(K.to_romaji("こんにちは"), "konnichiha")
        self.assertEqual(K.to_romaji("は", final_wa=True), "ha")

    def test_non_kana_passthrough(self):
        self.assertEqual(K.to_romaji("アイ・ディー"), "ai dii")


class Ime(unittest.TestCase):
    def test_conversion(self):
        cases = {
            "konnichiha": "こんにちは",
            "gakkou": "がっこう",
            "matcha": "まっちゃ",
            "kin'en": "きんえn",          # the last n is still pending
            "kin'enn": "きんえん",
            "kyou": "きょう",
            "ko-hi-": "こーひー",
            "onna": "おんな",
            "konnyaku": "こんにゃく",
            "nyuusu": "にゅうす",
            "tsuduku": "つづく",
            "jisho": "じしょ",
            "jyagaimo": "じゃがいも",
            "zasshi": "ざっし",
            "kekkon": "けっこn",
            "fakkusu": "ふぁっくす",
            "xtu": "っ",
            "wo": "を",
            "たべru": "たべる",
            "shi tu": "し つ",
        }
        for typed, want in cases.items():
            self.assertEqual(K.romaji_to_kana(typed), want, typed)

    def test_pending_and_final(self):
        self.assertEqual(K.romaji_to_kana("k"), "k")
        self.assertEqual(K.romaji_to_kana("sh"), "sh")
        self.assertEqual(K.romaji_to_kana("kan"), "かn")
        self.assertEqual(K.romaji_to_kana("kan", final=True), "かん")
        self.assertEqual(K.romaji_to_kana("shinbun", final=True), "しんぶん")
        self.assertEqual(K.romaji_to_kana("konn"), "こん")

    def test_nn_modes(self):
        self.assertEqual(K.romaji_to_kana("honnya"), "ほんにゃ")
        self.assertEqual(K.romaji_to_kana("honnya", nn_eager=True), "ほんや")

    def test_reading_matches(self):
        ok = [("taberu", "たべる"), ("ko-hi-", "コーヒー"), ("koohii", "コーヒー"), ("honya", "ほんや"),
              ("honnya", "ほんや"), ("hon'ya", "ほんや"), ("kinnen", "きんえん"), ("たべる", "たべる"),
              ("タベル", "たべる"), ("  Taberu ", "たべる"), ("shinbun", "しんぶん"), ("toukyou", "とうきょう"),
              ("konnichiha", "こんにちは")]
        for typed, want in ok:
            self.assertTrue(K.reading_matches(typed, want), (typed, want))
        bad = [("taberu", "のむ"), ("", "たべる"), ("tabemasu", "たべる"), ("tokyo", "とうきょう"), ("x", "")]
        for typed, want in bad:
            self.assertFalse(K.reading_matches(typed, want), (typed, want))


class Misc(unittest.TestCase):
    def test_script(self):
        self.assertEqual(K.kata_to_hira("コーヒー"), "こーひー")
        self.assertEqual(K.hira_to_kata("ひらがな"), "ヒラガナ")
        self.assertEqual(K.kata_to_hira(K.hira_to_kata("きゃっと")), "きゃっと")
        self.assertEqual(K.kanji_in("日本語の本、時々"), ["日", "本", "語", "時"])
        self.assertTrue(K.has_kanji("食べる"))
        self.assertFalse(K.has_kanji("たべる"))

    def test_morae(self):
        self.assertEqual(K.split_morae("きょう"), ["きょ", "う"])
        self.assertEqual(K.split_morae("がっこう"), ["が", "っ", "こ", "う"])
        self.assertEqual(K.split_morae("コーヒー"), ["コ", "ー", "ヒ", "ー"])
        self.assertEqual(K.split_morae("しんぶん"), ["し", "ん", "ぶ", "ん"])

    def test_pitch(self):
        self.assertEqual(K.pitch_pattern(4, 0), [False, True, True, True, True])
        self.assertEqual(K.pitch_pattern(3, 1), [True, False, False, False])
        self.assertEqual(K.pitch_pattern(3, 2), [False, True, False, False])
        self.assertEqual(K.pitch_pattern(2, 2), [False, True, False])
        self.assertEqual(K.pitch_pattern(1, 0), [False, True])
        self.assertEqual(K.pitch_pattern(0, 0), [])
        self.assertIn("odaka", K.pitch_name(2, 2))
        self.assertIn("heiban", K.pitch_name(3, 0))
        self.assertIn("atamadaka", K.pitch_name(1, 1))
        self.assertIn("nakadaka", K.pitch_name(4, 2))

    def test_furigana(self):
        m = "ヨーロッパで[行|い]ってみたい[場所|ば|しょ]とかある？"
        self.assertEqual(K.strip_furigana(m), "ヨーロッパで行ってみたい場所とかある？")
        segs = K.parse_furigana(m)
        self.assertEqual(segs[0], ("ヨーロッパで", ""))
        self.assertIn(("行", "い"), segs)
        self.assertIn(("場", "ば"), segs)
        self.assertIn(("所", "しょ"), segs)
        self.assertEqual("".join(b for b, _ in segs), K.strip_furigana(m))
        # one reading for a multi-kanji group stays as one unit
        self.assertEqual(K.parse_furigana("[今日|きょう|]は"), [("今日", "きょう"), ("は", "")])
        self.assertEqual(K.parse_furigana("かなだけ"), [("かなだけ", "")])

    def test_chart(self):
        hira = K.chart_kana(("gojuon",))
        self.assertEqual(len(hira), 46)
        self.assertEqual(len(K.chart_kana(("gojuon", "dakuon", "yoon"))), 46 + 25 + 33)
        self.assertEqual(K.chart_kana(("gojuon",), katakana=True)[0], "ア")
        for k in K.chart_kana():
            self.assertTrue(K.to_romaji(k).isalpha(), k)


if __name__ == "__main__":
    unittest.main()

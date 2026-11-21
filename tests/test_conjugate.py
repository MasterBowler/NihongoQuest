import unittest

from nihongo_quest.core.conjugate import class_name, conjugate, stems, word_class


def forms(written, kana, pos):
    return {f.key: (f.written, f.kana) for f in conjugate(written, kana, pos)}


class Verbs(unittest.TestCase):
    def test_ichidan(self):
        f = forms("食べる", "たべる", ["v1", "vt"])
        want = {
            "dict": "食べる", "masu": "食べます", "neg": "食べない", "past": "食べた", "te": "食べて",
            "neg_past": "食べなかった", "masu_neg": "食べません", "masu_past": "食べました",
            "pot": "食べられる", "pass": "食べられる", "caus": "食べさせる", "caus_pass": "食べさせられる",
            "vol": "食べよう", "imp": "食べろ", "ba": "食べれば", "tara": "食べたら", "tai": "食べたい",
            "prog": "食べている", "proh": "食べるな",
        }
        for key, w in want.items():
            self.assertEqual(f[key][0], w, key)
        self.assertEqual(f["neg"][1], "たべない")
        self.assertEqual(forms("くれる", "くれる", ["v1-s"])["imp"][0], "くれ")

    def test_godan_kaku(self):
        f = forms("書く", "かく", ["v5k", "vt"])
        want = {
            "masu": "書きます", "neg": "書かない", "past": "書いた", "te": "書いて", "pot": "書ける",
            "pass": "書かれる", "caus": "書かせる", "caus_pass": "書かせられる", "vol": "書こう",
            "imp": "書け", "ba": "書けば", "tara": "書いたら", "tai": "書きたい", "proh": "書くな",
        }
        for key, w in want.items():
            self.assertEqual(f[key][0], w, key)
        self.assertEqual(f["te"][1], "かいて")

    def test_godan_te_forms(self):
        cases = [
            ("行く", "いく", "v5k-s", "行って", "行った"),
            ("泳ぐ", "およぐ", "v5g", "泳いで", "泳いだ"),
            ("話す", "はなす", "v5s", "話して", "話した"),
            ("待つ", "まつ", "v5t", "待って", "待った"),
            ("死ぬ", "しぬ", "v5n", "死んで", "死んだ"),
            ("遊ぶ", "あそぶ", "v5b", "遊んで", "遊んだ"),
            ("読む", "よむ", "v5m", "読んで", "読んだ"),
            ("帰る", "かえる", "v5r", "帰って", "帰った"),
            ("買う", "かう", "v5u", "買って", "買った"),
            ("問う", "とう", "v5u-s", "問うて", "問うた"),
        ]
        for written, kana, cls, te, ta in cases:
            f = forms(written, kana, [cls])
            self.assertEqual(f["te"][0], te)
            self.assertEqual(f["past"][0], ta)
        self.assertEqual(forms("買う", "かう", ["v5u"])["neg"][0], "買わない")
        self.assertEqual(forms("帰る", "かえる", ["v5r"])["neg"][0], "帰らない")

    def test_aru(self):
        f = forms("ある", "ある", ["v5r-i", "vi"])
        self.assertEqual(f["neg"], ("ない", "ない"))
        self.assertEqual(f["neg_past"], ("なかった", "なかった"))
        self.assertEqual(f["masu"][0], "あります")
        self.assertEqual(f["te"][0], "あって")
        self.assertNotIn("pot", f)
        self.assertEqual(forms("有る", "ある", ["v5r-i"])["neg"][0], "ない")

    def test_honorific(self):
        f = forms("いらっしゃる", "いらっしゃる", ["v5aru", "vi"])
        self.assertEqual(f["masu"][0], "いらっしゃいます")
        self.assertEqual(f["imp"][0], "いらっしゃい")
        self.assertEqual(f["te"][0], "いらっしゃって")

    def test_kuru(self):
        f = forms("来る", "くる", ["vk", "vi"])
        want = {
            "masu": ("来ます", "きます"), "neg": ("来ない", "こない"), "te": ("来て", "きて"),
            "past": ("来た", "きた"), "pot": ("来られる", "こられる"), "caus": ("来させる", "こさせる"),
            "vol": ("来よう", "こよう"), "imp": ("来い", "こい"), "ba": ("来れば", "くれば"),
        }
        for key, w in want.items():
            self.assertEqual(f[key], w, key)
        self.assertEqual(forms("持ってくる", "もってくる", ["vk"])["neg"], ("持ってこない", "もってこない"))

    def test_suru(self):
        f = forms("する", "する", ["vs-i"])
        self.assertEqual(f["neg"][0], "しない")
        self.assertEqual(f["masu"][0], "します")
        self.assertEqual(f["te"][0], "して")
        self.assertEqual(f["pot"][0], "できる")
        self.assertEqual(f["ba"][0], "すれば")
        g = forms("勉強", "べんきょう", ["n", "vs", "vt"])
        self.assertEqual(g["dict"], ("勉強する", "べんきょうする"))
        self.assertEqual(g["te"], ("勉強して", "べんきょうして"))
        self.assertEqual(g["pot"][0], "勉強できる")
        s = forms("愛する", "あいする", ["vs-s", "vt"])
        self.assertEqual(s["te"][0], "愛して")
        self.assertNotIn("neg", s)            # 愛さない / 接しない differ, so not guessed


class Adjectives(unittest.TestCase):
    def test_i(self):
        f = forms("高い", "たかい", ["adj-i"])
        want = {"neg": "高くない", "past": "高かった", "neg_past": "高くなかった", "te": "高くて",
                "ba": "高ければ", "adv": "高く", "noun": "高さ", "polite": "高いです", "sou": "高そう"}
        for key, w in want.items():
            self.assertEqual(f[key][0], w, key)

    def test_ii(self):
        f = forms("いい", "いい", ["adj-ix"])
        self.assertEqual(f["neg"], ("よくない", "よくない"))
        self.assertEqual(f["past"][0], "よかった")
        self.assertEqual(f["sou"][0], "よさそう")
        self.assertEqual(f["dict"][0], "いい")
        self.assertEqual(forms("良い", "いい", ["adj-ix"])["neg"], ("良くない", "よくない"))
        self.assertEqual(forms("かっこいい", "かっこいい", ["adj-ix"])["neg"][0], "かっこよくない")

    def test_na(self):
        f = forms("静か", "しずか", ["adj-na", "n"])
        want = {"dict": "静かだ", "neg": "静かじゃない", "past": "静かだった", "te": "静かで",
                "attr": "静かな", "adv": "静かに", "polite": "静かです"}
        for key, w in want.items():
            self.assertEqual(f[key][0], w, key)


class Misc(unittest.TestCase):
    def test_non_inflecting(self):
        self.assertEqual(conjugate("猫", "ねこ", ["n"]), [])
        self.assertEqual(conjugate("とても", "とても", ["adv"]), [])
        self.assertIsNone(word_class(["n", "adj-no"]))

    def test_mismatched_ending_is_rejected(self):
        self.assertEqual(conjugate("食べ", "たべる", ["v1"]), [])
        self.assertEqual(conjugate("書く", "かき", ["v5k"]), [])

    def test_class(self):
        self.assertEqual(word_class(["n", "vs", "vt"]), "vs")
        self.assertEqual(word_class(["v5k-s", "vi"]), "v5k-s")
        self.assertEqual(word_class(["adj-na", "n"]), "adj-na")
        self.assertIn("Godan", class_name("v5m"))
        self.assertEqual(class_name(None), "")

    def test_stems(self):
        self.assertEqual(stems("食べる", "たべる", ["v1"]), ["食べ"])
        self.assertEqual(stems("行く", "いく", ["v5k-s"]), ["行き", "行っ"])
        self.assertEqual(stems("高い", "たかい", ["adj-i"]), ["高く", "高かっ"])
        self.assertEqual(stems("猫", "ねこ", ["n"]), [])


if __name__ == "__main__":
    unittest.main()

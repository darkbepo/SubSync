"""Unit tests for subsync.words (run: <runtime>\\python.exe tests\\test_words.py)."""
import os
import sys
import unittest

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "app"))
sys.path.insert(0, os.path.join(_REPO, "tests"))

from subsync.subtitles import Line  # noqa: E402
from subsync import words as W  # noqa: E402


class TokenizeTests(unittest.TestCase):
    def test_tokenize_kinds(self):
        toks = W.tokenize([Line(0, 1, "Hey, i know.\n(Lock click) <i>Thanks</i>")])
        self.assertEqual([t.kind for t in toks], ["word", "word", "word", "sound", "tag", "word", "tag"])
        self.assertEqual([t.row for t in toks], [0, 0, 0, 1, 1, 1, 1])
        self.assertEqual([t.norm for t in toks if t.kind == "word"], ["hey", "i", "know", "thanks"])
        self.assertEqual([t.text for t in toks], ["Hey,", "i", "know.", "(Lock click)", "<i>", "Thanks", "</i>"])

    def test_tokenize_label_and_dash(self):
        toks = W.tokenize([Line(0, 1, "(Patrick)\n- He snuck in,")])
        self.assertEqual([t.kind for t in toks], ["label", "dash", "word", "word", "word"])

    def test_norm_curly_apostrophe(self):
        self.assertEqual(W.norm("I’m,"), "i'm")
        self.assertEqual(W.norm("—Yes!"), "yes")

    def test_sound_only_line(self):
        toks = W.tokenize([Line(0, 1, "(Engine turns off)")])
        self.assertEqual([(t.kind, t.text) for t in toks], [("sound", "(Engine turns off)")])

    def test_cue_index(self):
        toks = W.tokenize([Line(0, 1, "One two"), Line(1, 2, "three")])
        self.assertEqual([t.cue for t in toks], [0, 0, 1])


def _words(spec):
    """'Hello@1.1 there.@1.5' -> [(1.1, 1.4, 'Hello'), ...] (each word 0.3 s long)."""
    out = []
    for item in spec.split():
        w, t = item.rsplit("@", 1)
        out.append((float(t), float(t) + 0.3, w))
    return out


def _wtoks(toks):
    return [t for t in toks if t.kind == "word"]


class MatchTests(unittest.TestCase):
    def test_exact_match_times(self):
        cues = [Line(1, 2, "Hello there."), Line(3, 4, "How are you?"), Line(5, 6, "Fine.")]
        words = _words("Hello@1.1 there.@1.5 How@3.2 are@3.4 you?@3.5 Fine.@5.3")
        toks = W.tokenize(cues)
        n, match = W.match_words(toks, words, cues)
        self.assertEqual(n, 6)
        self.assertTrue(all(t.matched for t in _wtoks(toks)))
        self.assertEqual([t.start for t in _wtoks(toks)], [1.1, 1.5, 3.2, 3.4, 3.5, 5.3])
        self.assertEqual(sorted(match.values()), [0, 1, 2, 3, 4, 5])

    def test_band_blocks_far_repeat(self):
        cues = [Line(552.0, 553.0, "Come on. Move.")]
        words = _words("Come@546.7 on.@546.9 Come@551.9 on.@552.1 Move.@552.5")
        toks = W.tokenize(cues)
        W.match_words(toks, words, cues)
        self.assertEqual(_wtoks(toks)[0].start, 551.9)

    def test_fuzzy_misspelling(self):
        cues = [Line(10, 12, "Mr. degeorge likes colour")]
        words = _words("Mr.@10.0 DeGeorge,@10.3 likes@10.7 color@11.0")
        toks = W.tokenize(cues)
        n, _ = W.match_words(toks, words, cues)
        self.assertEqual(n, 4)

    def test_curly_apostrophe_matches(self):
        cues = [Line(10, 11, "I’m fine.")]
        toks = W.tokenize(cues)
        n, _ = W.match_words(toks, _words("I'm@10.2 fine.@10.5"), cues)
        self.assertEqual(n, 2)

    def test_interpolates_unmatched(self):
        cues = [Line(1, 3, "one two three")]
        toks = W.tokenize(cues)
        W.match_words(toks, _words("one@1.0 three@2.0"), cues)
        two = _wtoks(toks)[1]
        self.assertFalse(two.matched)
        self.assertTrue(1.0 < two.start < 2.0)

    def test_unmatched_stretch_keeps_rough_times(self):
        cues = [Line(5.0 * k, 5.0 * k + 2, f"alpha{k} beta{k}") for k in range(20)]
        spec = " ".join(f"alpha{k}@{5.0 * k + 0.2} beta{k}@{5.0 * k + 0.9}" for k in range(5))
        toks = W.tokenize(cues)
        W.match_words(toks, _words(spec), cues)
        late = [t for t in _wtoks(toks) if t.cue >= 5]
        for t in late:
            expected = 5.0 * t.cue + (0.0 if t.text.startswith("alpha") else 2 * len(f"alpha{t.cue} ") / len(f"alpha{t.cue} beta{t.cue}"))
            self.assertLess(abs(t.start - expected), 0.5, t.text)
        starts = [t.start for t in _wtoks(toks)]
        self.assertEqual(starts, sorted(starts))
        self.assertEqual(len(set(starts)), len(starts))

    def test_speed_large_episode(self):
        import random
        import time
        rng = random.Random(3)
        vocab = [f"w{i}" for i in range(400)]
        cues, words, t = [], [], 0.0
        for k in range(1200):
            ws = [rng.choice(vocab) for _ in range(5)]
            for q, w in enumerate(ws):
                words.append((t + q * 0.35, t + q * 0.35 + 0.3, w))
            cues.append(Line(t, t + 1.8, " ".join(ws)))
            t += 2.2
        toks = W.tokenize(cues)
        t0 = time.time()
        n, _ = W.match_words(toks, words, cues)
        self.assertLess(time.time() - t0, 1.5)
        self.assertGreater(n, 0.95 * len(words))


if __name__ == "__main__":
    unittest.main()

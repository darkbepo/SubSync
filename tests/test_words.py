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

    def test_tie_prefers_word_near_expected_time(self):
        # cue 1's first word was misheard, so its "you" could pair with cue 0's trailing "you"
        # or with its own; both give the same number of matches - the one near the cue must win
        cues = [Line(10.0, 11.0, "thank you"), Line(12.0, 13.0, "you know")]
        words = _words("thank@10.0 you@10.4 yuu@12.0 know@12.4")
        toks = W.tokenize(cues)
        W.match_words(toks, words, cues)
        w = _wtoks(toks)
        self.assertEqual(w[1].start, 10.4)   # cue 0's "you"
        self.assertNotEqual(w[2].start, 10.4)
        self.assertGreater(w[2].start, 11.0)

    def test_tie_prefers_word_near_expected_time_reverse(self):
        cues = [Line(10.0, 11.0, "thank you"), Line(12.0, 13.0, "you know")]
        words = _words("thank@10.0 yuu@10.4 you@12.0 know@12.4")
        toks = W.tokenize(cues)
        W.match_words(toks, words, cues)
        w = _wtoks(toks)
        self.assertEqual(w[2].start, 12.0)   # cue 1's own "you"
        self.assertLess(w[1].start, 11.5)

    def test_misheard_first_word_placed_before_its_own_next_word(self):
        # the previous cue's rough position is 2 s late; that error must not leak into "Nice"
        cues = [Line(110.9, 114.4, "The case is closed."), Line(113.2, 114.2, "Nice work.")]
        words = _words("The@108.9 case@109.2 is@109.6 closed.@112.06 Mice@113.09 work.@113.58")
        toks = W.tokenize(cues)
        W.match_words(toks, words, cues)
        nice = _wtoks(toks)[4]
        self.assertFalse(nice.matched)
        self.assertLess(abs(nice.start - 113.09), 0.35)

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


def _refine(cues, spec, rough=None):
    rough = rough or [Line(c.start, c.end, c.text) for c in cues]
    toks = W.tokenize(cues)
    W.match_words(toks, _words(spec), rough)
    return W.refine(cues, rough, toks)


class RefineTests(unittest.TestCase):
    def test_refine_mid_sentence_start(self):
        cues = [Line(357.86, 359.75, "The man who'd pay\nher ransom"),
                Line(359.79, 361.01, "is lying in a pool\nof his own blood.")]
        new, _, n = _refine(cues, "The@357.73 man@357.95 who'd@358.11 pay@358.33 her@358.47 ransom@358.61 "
                                  "is@358.87 lying@359.07 in@359.27 a@359.41 pool@359.49 of@359.67 his@359.79 "
                                  "own@359.93 blood.@360.11")
        self.assertAlmostEqual(new[1].start, 358.87, delta=0.01)
        self.assertAlmostEqual(new[0].start, 357.73, delta=0.01)
        self.assertEqual(n, 2)
        self.assertEqual(new[1].text, cues[1].text)

    def test_refine_short_first_sentence(self):
        cues = [Line(536.96, 540.55, "Where were you last night?"),
                Line(540.60, 543.90, "Hmm. Let me see.\nI don't rightly recall.")]
        new, _, _ = _refine(cues, "Where@538.00 were@538.18 you@538.36 last@538.48 night?@538.72 Hmm.@539.28 "
                                  "Let@540.48 me@540.72 see.@540.86 I@542.20 don't@542.68 rightly@542.88 recall.@543.06")
        self.assertAlmostEqual(new[1].start, 539.28, delta=0.01)

    def test_refine_back_to_back_end(self):
        cues = [Line(15.90, 17.28, "Hey, you're early.\nHey, agent van pelt reporting\nfor the night shift,"),
                Line(17.32, 20.67, "marshal gorman.")]
        new, speech_end, _ = _refine(cues, "Hey,@15.9 you're@16.2 early.@16.5 Hey,@16.9 agent@17.2 van@17.5 "
                                           "pelt@17.8 reporting@18.1 for@18.4 the@18.55 night@18.6 shift,@18.75 "
                                           "marshal@19.25 gorman.@19.5")
        self.assertAlmostEqual(new[1].start, 19.25, delta=0.01)
        self.assertGreaterEqual(new[0].end, 19.05)
        self.assertLessEqual(new[0].end, new[1].start - 0.084 + 1e-6)
        self.assertAlmostEqual(speech_end[0], 19.05, delta=0.01)

    def test_refine_never_reorders(self):
        # file order 0,1,2 but cue 1 starts before cue 0 (a badly shifted cue); the words for
        # cue 1 are heard before cue 0's, so a refined start would jump past its neighbour
        cues = [Line(10.0, 10.8, "alpha beta"), Line(9.5, 10.4, "gamma delta"), Line(11.0, 11.8, "epsilon zeta")]
        new, _, _ = _refine(cues, "gamma@8.0 delta@8.3 alpha@10.0 beta@10.3 epsilon@11.0 zeta@11.3")
        self.assertEqual(new[1].start, 9.5)  # kept its rough start
        self.assertGreaterEqual(new[2].start, max(new[0].start, new[1].start) + 0.05)

    def test_refine_keeps_original_overlap(self):
        cues = [Line(10.0, 14.0, "{\\an8}SIGN ON WALL"), Line(10.5, 12.0, "alpha beta gamma.")]
        new, _, _ = _refine(cues, "alpha@10.5 beta@10.8 gamma.@11.1")
        self.assertEqual((new[0].start, new[0].end), (10.0, 14.0))

    def test_refine_unmatched_keeps_rough(self):
        cues = [Line(1.0, 3.0, "Hello there."), Line(4.0, 6.0, "zzzq qqqz"), Line(7.0, 9.0, "Bye now.")]
        new, speech_end, n = _refine(cues, "Hello@1.2 there.@1.5 Bye@7.1 now.@7.4")
        self.assertEqual((new[1].start, new[1].end), (4.0, 6.0))
        self.assertNotIn(1, speech_end)
        self.assertEqual(n, 2)


class ProcessTests(unittest.TestCase):
    def test_process_timing_only(self):
        import numpy as np
        import sim
        from subsync import pipeline

        bad, truth, asr, foreign = sim.make(seed=1)
        p = pipeline.process(bad, asr, "en", sim.fake_embed(foreign), tidy=False)
        self.assertTrue(p.res.ok, p.res.reason)
        self.assertEqual(len(p.lines), len(bad))
        err = np.abs(np.array([l.start for l in p.lines]) - np.array(truth))
        self.assertGreaterEqual(float(np.mean(err < 0.3)), 0.95)
        self.assertEqual(p.stats["subtitles_before"], len(bad))
        self.assertEqual(p.stats["subtitles_after"], len(bad))
        self.assertGreater(p.stats["word_timed"], 0.5 * len(bad))
        self.assertEqual(len(p.details), len(p.lines))
        self.assertEqual(set(p.details[0]), {"n", "from_cues", "orig_start", "start", "end", "words", "matched", "changes"})

    def _tall(self, lines):
        """Make every 7th cue 3-4 rows tall and give the rest sentence punctuation."""
        out = []
        for k, l in enumerate(lines):
            ws = l.text.replace("\n", " ").split()
            if k % 7 == 0 and len(ws) >= 4:
                q = max(1, len(ws) // 4)
                text = "\n".join(" ".join(ws[a:a + q]) for a in range(0, len(ws), q))
            else:
                text = l.text
            out.append(Line(l.start, l.end, text))
        return out

    def test_process_tidy_on(self):
        import collections
        import sim
        from subsync import pipeline

        bad, truth, asr, foreign = sim.make(seed=2)
        bad = self._tall(bad)
        p = pipeline.process(bad, asr, "en", sim.fake_embed(foreign), tidy=True)
        self.assertTrue(p.res.ok)
        for l in p.lines:
            rows = l.text.split("\n")
            self.assertLessEqual(len(rows), 2, l.text)
            self.assertTrue(all(len(r) <= 42 for r in rows), l.text)
        for a, b in zip(p.lines, p.lines[1:]):
            self.assertLessEqual(a.end, b.start + 1e-6)
        self.assertNotEqual(p.stats["subtitles_after"], p.stats["subtitles_before"])
        self.assertEqual(p.stats["subtitles_after"], len(p.lines))
        words_of = lambda ls: collections.Counter(t.norm for t in W.tokenize(ls) if t.kind == "word")
        self.assertEqual(words_of(p.lines), words_of(bad))
        self.assertEqual(len(p.details), len(p.lines))
        self.assertNotIn("from_cues", p.stats)

    def test_process_tidy_foreign(self):
        import sim
        from subsync import pipeline

        bad, truth, asr, foreign = sim.make(seed=2, cross=True)
        bad = self._tall(bad)
        p = pipeline.process(bad, asr, "da", sim.fake_embed(foreign), tidy=True)
        self.assertTrue(p.res.ok)
        self.assertTrue(all(len(l.text.split("\n")) <= 2 for l in p.lines))
        out = {(l.start, l.end, l.text) for l in p.lines}
        for l in p.res.lines:
            if len(l.text.split("\n")) <= 2:
                self.assertIn((l.start, l.end, l.text), out)  # unsplit cues keep today's timing
        self.assertGreater(p.stats["split"], 0)

    def test_details_write_and_prune(self):
        import tempfile
        from subsync import details, paths

        with tempfile.TemporaryDirectory() as d:
            old = paths.LOGS
            paths.LOGS = d
            try:
                row = {"n": 1, "from_cues": [1], "orig_start": 1.0, "start": 0.5, "end": 2.0, "words": 3,
                       "matched": 3, "changes": ["start from words"]}
                for k in range(205):
                    details.write(os.path.join(d, f"Show.S01E{k:03d}.mkv"), [row])
                files = os.listdir(os.path.join(d, "details"))
                self.assertEqual(len(files), 200)
                text = open(os.path.join(d, "details", "Show.S01E204.tsv"), encoding="utf-8").read()
                self.assertIn("start from words", text)
            finally:
                paths.LOGS = old


if __name__ == "__main__":
    unittest.main()

"""Unit tests for subsync.reshape (run: <runtime>\\python.exe tests\\test_reshape.py)."""
import os
import sys
import unittest

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "app"))
sys.path.insert(0, os.path.join(_REPO, "tests"))

from subsync.subtitles import Line  # noqa: E402
from subsync import reshape as R, words as W  # noqa: E402
from test_words import _words  # noqa: E402


def timed(cues, spec=None):
    """Tokenise cues and time their words (evenly spread if no Whisper spec is given)."""
    toks = W.tokenize(cues)
    if spec is None:
        ws = []
        for c in cues:
            cw = [t for t in W.tokenize([c]) if t.kind == "word"]
            step = (c.end - c.start) / max(1, len(cw))
            ws += [(c.start + q * step, c.start + q * step + step * 0.9, t.text) for q, t in enumerate(cw)]
        words = ws
    else:
        words = _words(spec)
    W.match_words(toks, words, cues)
    return toks, words


def text_of(toks):
    return " ".join(t.text for t in toks if t.kind == "word")


class SentenceTests(unittest.TestCase):
    def test_join_caption_fragments(self):
        cues = [Line(357.86, 359.75, "The man who'd pay\nher ransom"),
                Line(359.79, 361.01, "is lying in a pool\nof his own blood.")]
        toks, _ = timed(cues)
        sents = R.sentences(toks)
        self.assertEqual(len(sents), 1)
        self.assertEqual(R.wrap(sents[0]), "The man who'd pay her ransom\nis lying in a pool of his own blood.")

    def test_split_two_sentences(self):
        toks, _ = timed([Line(540.6, 543.9, "Hmm. Let me see.\nI don't rightly recall.")])
        self.assertEqual([text_of(s) for s in R.sentences(toks)],
                         ["Hmm.", "Let me see.", "I don't rightly recall."])

    def test_abbreviation_does_not_end_sentence(self):
        toks, _ = timed([Line(1, 4, "Mr. degeorge, a year ago\nyou saw it. Right?")])
        self.assertEqual([text_of(s) for s in R.sentences(toks)],
                         ["Mr. degeorge, a year ago you saw it.", "Right?"])

    def test_split_long_at_comma(self):
        s = ("When we get back to the office tomorrow morning after the long briefing, "
             "we should look again at every single record that we have.")
        toks, _ = timed([Line(10, 16, s)])
        pieces = R.split_long(R.sentences(toks)[0])
        self.assertEqual(len(pieces), 2)
        self.assertTrue(text_of(pieces[0]).endswith("briefing,"))
        for p in pieces:
            rows = R.wrap(p).split("\n")
            self.assertLessEqual(len(rows), 2)
            self.assertTrue(all(len(r) <= 42 for r in rows), rows)

    def test_split_long_by_duration(self):
        toks, _ = timed([Line(10, 19, "Wait. Just wait for me here")])
        sents = R.sentences(toks)
        pieces = R.split_long(sents[1])  # 9 s * 5/6 > 7 s on screen: must split even though short
        self.assertEqual(len(pieces), 2)

    def test_wrap_no_stopword_row_end(self):
        toks, _ = timed([Line(1, 4, "I need assistance with my investigation of the case")])
        rows = R.wrap(R.sentences(toks)[0]).split("\n")
        self.assertEqual(len(rows), 2)
        self.assertNotIn(rows[0].split()[-1].lower(), R.STOP)

    def test_wrap_single_row(self):
        toks, _ = timed([Line(1, 2, "Where were you\nlast night?")])
        self.assertEqual(R.wrap(R.sentences(toks)[0]), "Where were you last night?")

    def test_wrap_keeps_glued_tags(self):
        toks, _ = timed([Line(1, 2, "<i>Thanks</i> a lot.")])
        self.assertEqual(R.wrap(R.sentences(toks)[0]), "<i>Thanks</i> a lot.")


if __name__ == "__main__":
    unittest.main()

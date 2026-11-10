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


if __name__ == "__main__":
    unittest.main()

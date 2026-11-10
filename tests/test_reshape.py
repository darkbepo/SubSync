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


def run(cues, spec=None):
    toks, words = timed(cues, spec)
    _, match = W.match_words(toks, words, cues)
    return R.reshape(cues, cues, toks, words, match)


class ReshapeTests(unittest.TestCase):
    def test_two_speakers_separate(self):
        cues = [Line(258.81, 263.0, "All right. Put out\nan amber alert and a b.O.L.O.\nAlready did. I've set up\n"
                                    "a perimeter and notified c.H.P.")]
        spec = ("All@258.0 right.@258.2 Put@258.6 out@258.8 an@259.0 amber@259.2 alert@259.5 and@259.8 a@259.9 "
                "BOLO.@260.0 Already@260.9 did.@261.2 I've@261.5 set@261.7 up@261.9 a@262.1 perimeter@262.3 "
                "and@262.7 notified@262.9 CHP.@263.3")
        new, _, _ = run(cues, spec)
        self.assertGreaterEqual(len(new), 2)
        self.assertTrue(all(len(l.text.split("\n")) <= 2 for l in new), [l.text for l in new])
        self.assertTrue(any(l.text.startswith("Already did.") or l.text.startswith("I've") for l in new))

    def test_short_reply_dashed(self):
        new, _, _ = run([Line(10.0, 10.9, "Thanks."), Line(11.0, 12.0, "You're welcome.")],
                        "Thanks.@10.0 You're@11.0 welcome.@11.3")
        self.assertEqual([l.text for l in new], ["- Thanks.\n- You're welcome."])

    def test_short_same_speaker_joined(self):
        new, _, _ = run([Line(10.0, 10.4, "Okay."), Line(10.4, 11.5, "Let's go.")], "Okay.@10.0 Let's@10.4 go.@10.7")
        self.assertEqual([l.text for l in new], ["Okay. Let's go."])

    def test_sound_attaches_forward(self):
        new, _, _ = run([Line(15.9, 17.3, "Hey, agent van pelt reporting\nfor the night shift,"),
                         Line(17.3, 20.7, "marshal gorman.\n(Chuckles) At ease, grace.")])
        self.assertTrue(any(l.text.startswith("(Chuckles) At ease, grace.") for l in new), [l.text for l in new])

    def test_sound_at_cue_end_attaches_back(self):
        new, _, _ = run([Line(21.7, 23.2, "We're not invading\nafghanistan.\n(Lock click)"),
                         Line(23.2, 26.4, "Yeah, i know, but you know\nwhat the rules say. Thanks.")])
        cue = next(l for l in new if "afghanistan." in l.text)
        self.assertIn("(Lock click)", cue.text)

    def test_sound_only_cues_kept(self):
        new, _, _ = run([Line(5.8, 7.5, "(Engine turns off)"), Line(15.9, 17.3, "Hey, you're early.")])
        self.assertIn(("(Engine turns off)", 5.8, 7.5), [(l.text, l.start, l.end) for l in new])

    def test_italic_across_split(self):
        new, _, _ = run([Line(1, 5, "<i>One sentence here. Another one</i>\n<i>follows.</i>")])
        self.assertGreaterEqual(len(new), 2)
        for l in new:
            self.assertEqual(l.text.count("<i>"), l.text.count("</i>"), l.text)

    def test_position_tag_copied(self):
        new, _, _ = run([Line(1, 6, "{\\an8}The first one is here.\nThe second one is there.")])
        self.assertEqual(len(new), 2)
        self.assertTrue(all(l.text.startswith("{\\an8}") for l in new), [l.text for l in new])

    def test_fast_dialogue_no_overlap(self):
        new, _, _ = run([Line(10, 11.8, "Go. Now. Run. Hide. Wait. Stop.")],
                        "Go.@10.0 Now.@10.3 Run.@10.6 Hide.@10.9 Wait.@11.2 Stop.@11.5")
        for a, b in zip(new, new[1:]):
            self.assertLessEqual(a.end, b.start - 0.084 + 1e-6, (a, b))
            self.assertLess(a.start, b.start)

    def test_stats_joined_split(self):
        _, _, st = run([Line(357.86, 359.75, "The man who'd pay\nher ransom"),
                        Line(359.79, 361.01, "is lying in a pool\nof his own blood.")])
        self.assertGreaterEqual(st["joined"], 1)
        _, _, st = run([Line(540.6, 545.9, "Hmm. Let me see now.\nI don't rightly recall.")])
        self.assertGreaterEqual(st["split"], 1)

    def test_words_never_change(self):
        cues = [Line(1, 4, "All right. Put out\nan amber alert, (Sighs) and a b.O.L.O."), Line(4, 6, "(Door closes)"),
                Line(6, 9, "- Yes.\n- <i>No, i won't.</i>")]
        new, _, _ = run(cues)
        before = [t.text.lower() for t in W.tokenize(cues) if t.kind in ("word", "sound", "label")]
        after = [t.text.lower() for t in W.tokenize(new) if t.kind in ("word", "sound", "label")]
        self.assertEqual(before, after)


def cased(cues, spec):
    toks, words = timed(cues, spec)
    _, match = W.match_words(toks, words, cues)
    n = R.fix_case(toks, words, match)
    return " ".join(t.text for t in toks if t.kind == "word"), n


class CaseTests(unittest.TestCase):
    def test_case_i(self):
        text, _ = cased([Line(1, 3, "Well, i know i'm late.")], "Well,@1.0 I@1.3 know@1.5 I'm@1.8 late.@2.1")
        self.assertEqual(text, "Well, I know I'm late.")

    def test_case_names_from_whisper(self):
        text, _ = cased([Line(1, 4, "Hey, agent van pelt is in afghanistan.")],
                        "Hey,@1.0 agent@1.3 Van@1.6 Pelt@1.9 is@2.2 in@2.4 Afghanistan.@2.6")
        self.assertEqual(text, "Hey, agent Van Pelt is in Afghanistan.")

    def test_case_sentence_start(self):
        text, _ = cased([Line(1, 3, "Done. yeah, sure.")], "Done.@1.0 yeah,@1.5 sure.@1.9")
        self.assertEqual(text, "Done. Yeah, sure.")

    def test_case_abbrev(self):
        text, _ = cased([Line(1, 4, "Put out a b.O.L.O. And call c.H.P.")],
                        "Put@1.0 out@1.2 a@1.4 BOLO.@1.6 And@2.2 call@2.4 CHP.@2.7")
        self.assertEqual(text, "Put out a B.O.L.O. And call C.H.P.")

    def test_case_sentence_initial_whisper_ignored(self):
        text, _ = cased([Line(1, 3, "I guess well enough.")], "I@1.0 guess.@1.2 Well@1.6 enough.@1.9")
        self.assertEqual(text, "I guess well enough.")

    def test_case_never_lowers(self):
        text, _ = cased([Line(1, 2, "NO WAY!")], "No@1.0 way!@1.3")
        self.assertEqual(text, "NO WAY!")

    def test_case_returns_count(self):
        _, n = cased([Line(1, 3, "Well, i know i'm late.")], "Well,@1.0 I@1.3 know@1.5 I'm@1.8 late.@2.1")
        self.assertEqual(n, 2)

    def test_reshape_fixes_case(self):
        new, _, st = run([Line(1, 3, "Well, i know.")], "Well,@1.0 I@1.3 know.@1.6")
        self.assertEqual(new[0].text, "Well, I know.")
        self.assertEqual(st["capitals_fixed"], 1)


if __name__ == "__main__":
    unittest.main()

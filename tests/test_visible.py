"""No subtitle may end up too short to be seen (1.4.1): align.keep_visible and the whole
matching step (pipeline.process) on simulated episodes. Also: SRT reading keeps a text row
that is only a number. Run: python test_visible.py"""
import os, re, sys, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.join(os.path.dirname(HERE), "app"), HERE]
from subsync.align import MIN_SHOW, keep_visible
from subsync.subtitles import Line, parse_srt


def L(a, b, t):
    return Line(a, b, t)


class KeepVisible(unittest.TestCase):
    def test_squeezed_dialogue_is_shown_with_the_next_line(self):
        out, groups, st = keep_visible([L(10.0, 10.05, "Okay."), L(10.05, 12.0, "Let's go.")])
        self.assertEqual([l.text for l in out], ["Okay.", "Let's go."])
        self.assertAlmostEqual(out[0].start, 10.0)       # starts stay exactly where they were
        self.assertAlmostEqual(out[1].start, 10.05)
        self.assertGreaterEqual(out[0].end - out[0].start, MIN_SHOW - 1e-9)
        self.assertEqual(st["overlap"], 1)

    def test_sound_right_before_dialogue_becomes_one_subtitle_at_the_dialogue(self):
        out, groups, st = keep_visible([L(20.0, 20.1, "[door slams]"), L(20.2, 22.0, "What was that?")])
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].text, "[door slams]\nWhat was that?")
        self.assertAlmostEqual(out[0].start, 20.2)
        self.assertEqual(groups, [[0, 1]])

    def test_sound_far_from_dialogue_is_not_joined(self):
        out, _, _ = keep_visible([L(20.0, 20.1, "[door slams]"), L(20.6, 22.0, "What was that?")])
        self.assertEqual(len(out), 2)
        self.assertAlmostEqual(out[0].start, 20.0)
        self.assertGreaterEqual(out[0].end - out[0].start, MIN_SHOW - 1e-9)

    def test_three_rows_are_not_joined(self):
        out, _, _ = keep_visible([L(5.0, 5.1, "[sirens]"), L(5.1, 7.0, "Get down!\nNow!")])
        self.assertEqual(len(out), 2)

    def test_nothing_shortened_or_lost(self):
        src = [L(1, 3, "a"), L(3.1, 3.12, "b"), L(3.15, 3.2, "[c]"), L(3.3, 6, "d"), L(9, 9.01, "e")]
        out, groups, _ = keep_visible(src)
        self.assertEqual(sorted(c for g in groups for c in g), list(range(len(src))))
        self.assertTrue(all(l.end - l.start >= MIN_SHOW - 1e-9 for l in out))
        for g, l in zip(groups, out):
            for c in g:
                self.assertIn(src[c].text, l.text)
                self.assertGreaterEqual(l.end, src[c].end - 1e-9)

    def test_long_enough_lines_untouched(self):
        src = [L(1, 2, "a"), L(2.1, 3, "b")]
        out, _, st = keep_visible(src)
        self.assertEqual([(l.start, l.end) for l in out], [(1, 2), (2.1, 3)])
        self.assertEqual(sum(st.values()), 0)


class SimulatedEpisodes(unittest.TestCase):
    """The whole matching step: every word kept in order, nothing shown under MIN_SHOW,
    dialogue starts as accurate as before. Fails on 1.4.0 (lines squeezed to 0.01-0.5 s)."""

    def test_episodes(self):
        import numpy as np
        import sim
        from subsync.pipeline import process
        from subsync.subtitles import speech_text

        def toks(lines):
            return [w for l in lines for w in re.findall(r"[a-z0-9']+", re.sub(r"<[^>]*>", " ", l.text).lower())]

        for seed in (1, 2):
            bad, truth, asr, foreign = sim.make(seed, False)
            for tidy in (False, True):
                p = process([Line(l.start, l.end, l.text) for l in bad], asr, "en", sim.fake_embed(foreign), tidy)
                self.assertEqual(toks(bad), toks(p.lines), "words lost or reordered")
                short = [l for l in p.lines if l.end - l.start < MIN_SHOW - 1e-6]
                self.assertEqual(short, [], f"seed {seed} tidy {tidy}: {len(short)} too short")
                if not tidy:
                    pos = {}
                    for l, d in zip(p.lines, p.details):
                        for c in d["from_cues"]:
                            pos.setdefault(c - 1, l.start)
                    dia = [i for i, l in enumerate(bad) if speech_text(l.text)]
                    acc = np.mean([abs(pos[i] - truth[i]) < 0.3 for i in dia])
                    self.assertGreater(acc, 0.95)


class Reading(unittest.TestCase):
    def test_number_row_without_numbering_is_kept(self):
        txt = "00:00:01,000 --> 00:00:02,000\nWhat year?\n1985\n00:00:03,000 --> 00:00:04,000\nRight.\n"
        self.assertEqual([l.text for l in parse_srt(txt)], ["What year?\n1985", "Right."])

    def test_normal_numbering_still_removed(self):
        txt = "1\n00:00:01,000 --> 00:00:02,000\nWhat year?\n1985\n\n2\n00:00:03,000 --> 00:00:04,000\nRight.\n"
        self.assertEqual([l.text for l in parse_srt(txt)], ["What year?\n1985", "Right."])

    def test_numbering_without_blank_rows(self):
        txt = "1\n00:00:01,000 --> 00:00:02,000\nHello\n2\n00:00:03,000 --> 00:00:04,000\nBye\n"
        self.assertEqual([l.text for l in parse_srt(txt)], ["Hello", "Bye"])


if __name__ == "__main__":
    unittest.main()

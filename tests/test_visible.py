"""No subtitle may end up too short to be seen (1.4.1): align.keep_visible and the whole
matching step (pipeline.process) on simulated episodes. Also: SRT reading keeps a text row
that is only a number. Run: python test_visible.py"""
import os, re, sys, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.join(os.path.dirname(HERE), "app"), HERE]
from subsync.align import MIN_FIT, MIN_SHOW, keep_visible
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

    def test_sound_far_from_dialogue_is_not_joined_and_fills_the_room(self):
        out, _, _ = keep_visible([L(20.0, 20.1, "[door slams]"), L(20.6, 22.0, "What was that?")])
        self.assertEqual(len(out), 2)
        self.assertAlmostEqual(out[0].start, 20.0)
        self.assertGreaterEqual(out[0].end - out[0].start, MIN_FIT)
        self.assertLessEqual(out[0].end, out[1].start)  # enough room: no overlap, so nothing jumps

    def test_joins_the_previous_line(self):
        out, groups, _ = keep_visible([L(10.0, 12.0, "Hi."), L(10.2, 10.25, "[thud]"), L(10.6, 12.0, "Bye.")])
        self.assertEqual([l.text for l in out], ["Hi.\n[thud]", "Bye."])
        self.assertAlmostEqual(out[0].start, 10.0)
        self.assertEqual(groups, [[0, 1], [2]])

    def test_two_sound_descriptions(self):
        out, _, _ = keep_visible([L(5.0, 5.05, "[sirens]"), L(5.1, 7.0, "[tires screech]")])
        self.assertEqual([l.text for l in out], ["[sirens]\n[tires screech]"])
        self.assertAlmostEqual(out[0].start, 5.0)

    def test_run_of_short_lines_never_three_on_screen(self):
        src = [L(10.0 + 0.05 * k, 10.05 + 0.05 * k, f"Line {k}.") for k in range(4)] + [L(10.2, 12.0, "Long one.")]
        for join in (True, False):
            out, groups, _ = keep_visible(src, join=join)
            if not join:
                self.assertEqual(len(out), len(src))
            self.assertEqual(sorted(c for g in groups for c in g), list(range(len(src))))
            for t in [10.005 + 0.01 * q for q in range(200)]:
                shown = sum(1 for l in out if l.start <= t < l.end)
                self.assertLessEqual(shown, 2, (join, t, out))
            for x, y in zip(out, out[1:]):
                self.assertLessEqual(x.start, y.start)

    def test_no_joins_without_tidy(self):
        out, groups, _ = keep_visible([L(20.0, 20.1, "[door slams]"), L(20.2, 22.0, "What?")], join=False)
        self.assertEqual(len(out), 2)
        self.assertGreaterEqual(out[0].end - out[0].start, MIN_SHOW - 1e-9)

    def test_three_rows_are_not_joined(self):
        out, _, _ = keep_visible([L(5.0, 5.1, "[sirens]"), L(5.1, 7.0, "Get down!\nNow!")])
        self.assertEqual(len(out), 2)

    def test_nothing_shortened_or_lost(self):
        src = [L(1, 3, "a"), L(3.1, 3.12, "b"), L(3.15, 3.2, "[c]"), L(3.3, 6, "d"), L(9, 9.01, "e")]
        out, groups, _ = keep_visible(src)
        self.assertEqual(sorted(c for g in groups for c in g), list(range(len(src))))
        self.assertTrue(all(l.end - l.start >= MIN_FIT - 1e-9 for l in out), out)
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
                short = [l for l in p.lines if l.end - l.start < MIN_FIT - 1e-6]
                self.assertEqual(short, [], f"seed {seed} tidy {tidy}: {len(short)} too short")
                if not tidy:
                    self.assertEqual(len(p.lines), len(bad))  # Tidy off: one result line per original line
                if not tidy:
                    pos = {}
                    for l, d in zip(p.lines, p.details):
                        for c in d["from_cues"]:
                            pos.setdefault(c - 1, l.start)
                    dia = [i for i, l in enumerate(bad) if speech_text(l.text)]
                    acc = np.mean([abs(pos[i] - truth[i]) < 0.3 for i in dia])
                    self.assertGreater(acc, 0.95)


class Reading(unittest.TestCase):
    T1, T2, T3 = "00:00:01,000 --> 00:00:02,000", "00:00:03,000 --> 00:00:04,000", "00:00:05,000 --> 00:00:06,000"

    def texts(self, txt):
        return [l.text for l in parse_srt(txt)]

    def test_number_row_without_numbering_is_kept(self):
        self.assertEqual(self.texts(f"{self.T1}\nWhat year?\n1985\n{self.T2}\nRight.\n"), ["What year?\n1985", "Right."])

    def test_cue_that_is_only_a_number_without_numbering(self):
        self.assertEqual(self.texts(f"{self.T1}\n1985\n\n{self.T2}\nBye\n"), ["1985", "Bye"])

    def test_normal_numbering_still_removed(self):
        txt = f"1\n{self.T1}\nWhat year?\n1985\n\n2\n{self.T2}\nRight.\n"
        self.assertEqual(self.texts(txt), ["What year?\n1985", "Right."])
        self.assertEqual(self.texts(txt.replace("\n", "\r\n")), ["What year?\n1985", "Right."])

    def test_numbering_without_blank_rows(self):
        self.assertEqual(self.texts(f"1\n{self.T1}\nHello\n2\n{self.T2}\nBye\n"), ["Hello", "Bye"])

    def test_numbered_from_zero_and_with_gaps(self):
        self.assertEqual(self.texts(f"0\n{self.T1}\nHello\n1\n{self.T2}\nBye\n2\n{self.T3}\nX\n"), ["Hello", "Bye", "X"])
        self.assertEqual(self.texts(f"1\n{self.T1}\nHello\n3\n{self.T2}\nBye\n7\n{self.T3}\nX\n"), ["Hello", "Bye", "X"])

    def test_checker_reads_the_same(self):
        sys.path.insert(0, os.path.join(os.path.dirname(HERE), "tools"))
        import check_srt
        import tempfile
        for txt in (f"0\n{self.T1}\nHello\n1\n{self.T2}\nBye\n2\n{self.T3}\nX\n",
                    f"{self.T1}\nWhat year?\n1985\n{self.T2}\nRight.\n"):
            with tempfile.NamedTemporaryFile("w", suffix=".srt", delete=False) as f:
                f.write(txt)
            try:
                self.assertEqual([c[2] for c in check_srt.cues(f.name)],
                                 [t.replace("\n", " / ") for t in self.texts(txt)])
            finally:
                os.unlink(f.name)


if __name__ == "__main__":
    unittest.main()

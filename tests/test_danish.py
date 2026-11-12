"""Danish subtitles (1.5.0): which language a subtitle is, result names, pairing per language,
and timing on simulated episodes, by an English reference subtitle and by the audio alone.
Run: python test_danish.py"""
import os, random, sys, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.join(os.path.dirname(HERE), "app"), HERE]
from subsync import language
from subsync.pairing import pair_languages
from subsync.subtitles import Line, speech_text

DA = ["Hvad laver du her?", "Jeg ved det ikke.", "Det er ikke min skyld, og det ved du godt.",
      "Hvor er han nu?", "Vi skal gå nu, ellers kommer vi for sent.", "Nej tak, jeg har det fint.",
      "Hun sagde, at hun ville komme i aften.", "Kan du hjælpe mig med det her?"]
EN = ["What are you doing here?", "I don't know.", "It's not my fault, and you know that.",
      "Where is he now?", "We have to go now, or we'll be late.", "No thanks, I'm fine.",
      "She said she would come tonight.", "Can you help me with this?"]


def lines(texts, n=40):
    return [Line(k * 3.0, k * 3.0 + 2.0, texts[k % len(texts)]) for k in range(n)]


class Language(unittest.TestCase):
    def test_names(self):
        for name, want in (("Show.S01E01.da.srt", "da"), ("Show.S01E01.dan.srt", "da"), ("Show.S01E01.Danish.srt", "da"),
                           ("Show.S01E01.dansk.srt", "da"), ("Show.S01E01 [da].srt", "da"), ("Show.S01E01.da.hi.srt", "da"),
                           ("Show.S01E01_dan.srt", "da"), ("Show.S01E01 (Danish).srt", "da"), ("Show.S01E01.da.#1.srt", "da"),
                           ("Show.S01E01.en.srt", "en"), ("Show.S01E01.eng.srt", "en"), ("Show.English.Title.da.srt", "da"),
                           ("Show.S01E01.srt", None), ("Dante.S01E01.srt", None), ("Dana.srt", None), ("Endgame.srt", None),
                           # title words, not tags (review of 1.5.0)
                           ("The.Da.Vinci.Code.2006.srt", None), ("The.Danish.Girl.2015.srt", None),
                           ("The Danish Girl (2015).srt", None), ("Leonardo.da.Vinci.srt", None), ("Steely.Dan.Live.srt", None),
                           ("Show - S02E05 - Dan.srt", None), ("Show.Dansk.Cafe.S01E01.srt", None)):
            self.assertEqual(language.from_name(name), want, name)

    def test_title_ending_in_dan_with_english_text_is_english(self):
        self.assertEqual(language.resolve("Meet.Dan.srt", lines(EN)), "en")
        self.assertEqual(language.resolve("Meet.Dan.srt", lines(DA)), "da")

    def test_text(self):
        self.assertEqual(language.resolve("x.srt", lines(DA)), "da")
        self.assertEqual(language.resolve("x.srt", lines(EN)), "en")
        self.assertEqual(language.resolve("x.srt", lines(DA, 3)), "en")  # too little to be sure: stays English
        self.assertEqual(language.resolve("x.en.srt", lines(DA)), "en")  # the name wins
        self.assertEqual(language.resolve("x.srt", lines(EN), "da"), "da")  # asked for wins

    def test_suffix(self):
        self.assertEqual([language.suffix("en", ".en"), language.suffix("en", ".eng"),
                          language.suffix("da", ".en"), language.suffix("da", ".eng")], [".en", ".eng", ".da", ".dan"])


class Pairing(unittest.TestCase):
    def test_one_subtitle_per_language(self):
        v = ["/x/Show.S01E01.mkv", "/x/Show.S01E02.mkv", "/x/Show.S01E03.mkv"]
        s = ["/x/Show.S01E01.en.srt", "/x/Show.S01E01.da.srt", "/x/Show.S01E02.dan.srt", "/x/Show S01E02 WEB.srt"]
        rows, unmatched = pair_languages(v, s)
        self.assertEqual(rows, [("/x/Show.S01E01.mkv", "/x/Show.S01E01.en.srt", None),
                                ("/x/Show.S01E01.mkv", "/x/Show.S01E01.da.srt", "/x/Show.S01E01.en.srt"),
                                ("/x/Show.S01E02.mkv", "/x/Show S01E02 WEB.srt", None),
                                ("/x/Show.S01E02.mkv", "/x/Show.S01E02.dan.srt", "/x/Show S01E02 WEB.srt")])
        self.assertEqual(unmatched, [("/x/Show.S01E03.mkv", None)])

    def test_english_only_unchanged(self):
        from subsync.pairing import pair
        for v, s in ((["/x/A.S01E01.mkv", "/x/A.S01E02.mkv"], ["/x/A.S01E02.en.srt", "/x/A.S01E01.eng.srt"]),
                     (["/x/Meet.Dan.mkv", "/x/Other.Film.mkv"], ["/x/Meet.Dan.srt", "/x/Other.Film.srt"]),
                     (["/x/The.Danish.Girl.2015.mkv"], ["/x/The.Danish.Girl.2015.en.srt"]),
                     (["/x/Leonardo.da.Vinci.mkv", "/x/Steely.Dan.Live.mkv"], ["/x/Steely.Dan.Live.srt", "/x/Leonardo.da.Vinci.srt"])):
            rows, unmatched = pair_languages(v, s)
            want = [x for x in pair(v, s) if x[0] and x[1]]
            self.assertEqual(sorted((a, b) for a, b, _ in rows), sorted(want), (v, s))
            self.assertEqual(len(rows), len(v), (v, s))
            self.assertEqual(unmatched, [])


def danish(bad, truth, foreign):
    """A "Danish" subtitle of the same episode: translated words, its own timing errors
    (constant + drift) and every 6th pair of lines as one subtitle. Truth = its first line's."""
    tr = lambda t: "\n".join(" ".join(foreign.get(w, w) for w in row.split()) for row in t.split("\n"))
    out, src, k = [], [], 0
    while k < len(bad):
        off = 2.1 + 0.0015 * truth[k]
        if (k + 1 < len(bad) and k % 6 == 0 and speech_text(bad[k].text) and speech_text(bad[k + 1].text)
                and "\n" not in bad[k].text + bad[k + 1].text):
            out.append(Line(truth[k] + off, truth[k + 1] + bad[k + 1].end - bad[k + 1].start + off,
                            tr(bad[k].text) + "\n" + tr(bad[k + 1].text)))
            src.append(k); k += 2
            continue
        out.append(Line(truth[k] + off, truth[k] + bad[k].end - bad[k].start + off, tr(bad[k].text)))
        src.append(k); k += 1
    return out, [truth[i] for i in src]


class Timing(unittest.TestCase):
    """English audio, Danish subtitle: timed by an English subtitle of the same video, by the
    audio alone, and with a wrong reference (another episode), which must fall back to the audio."""

    def run_one(self, seed, reference):
        import numpy as np
        import sim
        from subsync.pipeline import process

        bad, truth, asr, foreign = sim.make(seed, False)
        da, dtruth = danish(bad, truth, foreign)
        ref = None
        if reference == "right":
            ref = [Line(l.start, l.end, l.text) for l in bad]
        elif reference == "wrong":
            other = sim.make(seed + 10, False)[0]
            ref = [Line(l.start, l.end, l.text) for l in other]
        p = process([Line(l.start, l.end, l.text) for l in da], asr, "en", sim.fake_embed(foreign), False,
                    sub_lang="da", reference=ref)
        self.assertTrue(p.res.ok, p.res.reason)
        pos = {}
        for l, d in zip(p.lines, p.details):
            for c in d["from_cues"]:
                pos.setdefault(c - 1, l.start)
        ids = [i for i, l in enumerate(da) if speech_text(l.text)]
        err = np.array([abs(pos[i] - dtruth[i]) for i in ids])
        self.assertEqual(len(p.lines), len(da))  # Tidy off: one result line per original line
        self.assertEqual([l.text for l in p.lines], [l.text for l in da])  # words untouched
        return p, float(np.mean(err < 0.3))

    def test_by_reference(self):
        for seed in (1, 3):
            p, acc = self.run_one(seed, "right")
            self.assertEqual(p.stats["timing_from"], "reference")
            self.assertGreater(acc, 0.97, seed)

    def test_by_audio(self):
        p, acc = self.run_one(2, None)
        self.assertEqual(p.stats["timing_from"], "audio")
        self.assertGreater(acc, 0.95)

    def test_wrong_reference_falls_back_to_audio(self):
        p, acc = self.run_one(2, "wrong")
        self.assertEqual(p.stats["timing_from"], "audio")
        self.assertGreater(acc, 0.95)


if __name__ == "__main__":
    unittest.main()

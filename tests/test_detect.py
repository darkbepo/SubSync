"""Unit tests for subsync.detect (no speech model needed) and media.decode_window.
Needs ffmpeg for the seek test (skipped without it)."""
import os, shutil, subprocess, sys, tempfile, unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app"))
import numpy as np

from subsync import detect as det


class Windows(unittest.TestCase):
    def test_spread_and_bounds(self):
        dur = 45 * 60
        s = det.window_starts(dur)
        self.assertEqual(len(s), det.MAX_WINDOWS)
        self.assertTrue(all(0.05 * dur <= t <= 0.95 * dur - det.WINDOW for t in s))
        self.assertTrue(all(abs(a - b) >= det.WINDOW for i, a in enumerate(s) for b in s[i + 1:]), "windows overlap")
        first3 = sorted(s[:3])  # the first three cover the video: one in each third
        self.assertTrue(first3[0] < dur / 3 < first3[1] < 2 * dur / 3 < first3[2], first3)

    def test_short_video_has_fewer_windows(self):
        s = det.window_starts(400)
        self.assertTrue(1 <= len(s) <= 10 and all(abs(a - b) >= 30 for i, a in enumerate(s) for b in s[i + 1:]))


class Pieces(unittest.TestCase):
    def test_at_most_30s_and_nothing_lost(self):
        parts = [np.ones(int(x * 16000), np.float32) for x in (12, 25, 3.5, 40, 0.5)]
        p = det.pieces(parts)
        self.assertTrue(all(0 < len(x) <= 30 * 16000 for x in p))
        self.assertEqual(sum(map(len, p)), sum(map(len, parts)))
        self.assertEqual(len(p), 3)  # 81 s -> 30 + 30 + 21

    def test_empty(self):
        self.assertEqual(det.pieces([]), [])


class Combine(unittest.TestCase):
    def test_weighted_by_speech(self):
        r = [(30, [("en", 0.9), ("da", 0.1)]), (30, [("en", 0.8), ("da", 0.2)]), (5, [("da", 0.99), ("en", 0.01)])]
        lang, p = det.combine(r)
        self.assertEqual(lang, "en")
        self.assertAlmostEqual(p, (27 + 24 + 0.05) / 65, places=3)

    def test_one_loud_short_piece_does_not_win(self):
        self.assertEqual(det.combine([(2, [("ja", 1.0)]), (28, [("en", 0.6), ("ja", 0.1)])])[0], "en")

    def test_nothing(self):
        self.assertEqual(det.combine([]), (None, None))


@unittest.skipUnless(shutil.which("ffmpeg"), "needs ffmpeg")
class Seek(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.d = tempfile.mkdtemp()
        cls.v = {}
        # 8 minutes of pink noise: every stretch of audio is different, so an offset can't hide
        src = "anoisesrc=d=480:c=pink:r=48000:a=0.3:seed=7"
        for ext, codec in (("mkv", "aac"), ("mp4", "aac"), ("avi", "libmp3lame")):
            f = os.path.join(cls.d, "chirp." + ext)
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=black:s=32x32:r=2",
                            "-f", "lavfi", "-i", src, "-c:v", "libx264", "-preset", "ultrafast", "-c:a", codec,
                            "-shortest", f], check=True)
            cls.v[ext] = f

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.d, ignore_errors=True)

    def test_window_matches_full_decode(self):
        from subsync.media import decode, decode_window
        for ext, f in self.v.items():
            full = decode(f, 0)
            for start in (0.0, 61.3, 250.0, 449.0):
                w = decode_window(f, 0, start, 30.0)
                self.assertGreater(len(w), 16000 * 29 if start < 440 else 16000 * 20, (ext, start, len(w)))
                a = int(start * 16000)
                seg = w[8000:8000 + 16000 * 4]  # 4 s from inside the window
                lo = max(0, a + 8000 - 800)
                ref = full[lo: a + 8000 + len(seg) + 800]
                c = np.correlate(ref, seg, mode="valid")
                best = lo + int(np.argmax(c)) - (a + 8000)  # samples the window is off by
                al = full[a + 8000 + best: a + 8000 + best + len(seg)]
                corr = np.corrcoef(seg, al)[0, 1]
                # the same audio: not exactly sample-equal, because the resampler starts at another
                # sub-sample phase after a jump (which doesn't matter for recognising a language)
                self.assertGreater(corr, 0.95, (ext, start, best, corr))
                # in the right place: up to an AAC frame or so (the codec's start-up delay is handled
                # differently after a jump); detect only needs roughly the right part of the video
                self.assertLessEqual(abs(best), 1600, (ext, start, best))  # within 0.1 s


if __name__ == "__main__":
    unittest.main()

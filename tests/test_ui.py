"""Settings, command-line flag and result text for "Tidy up lines"
(run: <runtime>\\python.exe tests\\test_ui.py)."""
import os
import sys
import tempfile
import unittest

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_ROOT = tempfile.mkdtemp(prefix="subsync-ui-")
os.environ["SUBSYNC_ROOT"] = _ROOT
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.makedirs(os.path.join(_ROOT, "logs"), exist_ok=True)
sys.path.insert(0, os.path.join(_REPO, "app"))
sys.path.insert(0, os.path.join(_REPO, "tests"))

STATS = {"tidy": True, "word_timed": 747, "subtitles_before": 808, "subtitles_after": 820,
         "joined": 174, "split": 174, "capitals_fixed": 244}
DONE = {"out": "x.en.srt", "matched": 586, "total": 728, "lang": "en", "ends": (5, 1, 0), "runs": [(0, 10, 0.1)],
        "offsets": (-0.3, 0.4), "seconds": 12.0, "align_s": 1.0, "stats": {}, "dur": 2600, "tidy": STATS}


class SummaryTests(unittest.TestCase):
    def test_tidy_summary(self):
        from subsync.pipeline import tidy_summary
        self.assertEqual(tidy_summary(STATS), "808 → 820 subtitles")
        self.assertEqual(tidy_summary(dict(STATS, subtitles_after=808)), "")
        self.assertEqual(tidy_summary({}), "")

    def test_tidy_details(self):
        from subsync.pipeline import tidy_details
        text = tidy_details(STATS)
        for part in ("Subtitles: 808 → 820", "Joined: 174", "Split: 174", "Capitals fixed: 244",
                     "Timed from words: 747"):
            self.assertIn(part, text)
        self.assertIn("Tidy up lines: off", tidy_details(dict(STATS, tidy=False)))


class CliTests(unittest.TestCase):
    def test_keep_layout_flag(self):
        import cli
        self.assertTrue(cli.parse(["x", "--keep-layout"]).keep_layout)
        self.assertFalse(cli.parse(["x"]).keep_layout)

    def test_done_fields(self):
        import cli
        f = cli.done_fields(DONE)
        self.assertEqual((f["tidy"], f["subtitles_before"], f["subtitles_after"], f["joined"], f["split"],
                          f["capitals_fixed"]), (True, 808, 820, 174, 174, 244))
        self.assertEqual(f["lines_matched"], 586)


class WindowTests(unittest.TestCase):
    def test_tidy_toggle(self):
        import fake_worker
        import subsync.asr_worker
        subsync.asr_worker.worker_main = fake_worker.worker_main
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance() or QApplication([])
        from subsync.gui import MainWindow
        w = MainWindow()
        try:
            self.assertTrue(w.tidy.isChecked())          # on by default
            w.tidy.setChecked(False)
            self.assertFalse(w.settings["tidy"])
            w.tidy.setChecked(True)
            self.assertTrue(w.settings["tidy"])
        finally:
            w.engine.shutdown()
            w.close()
            del app


if __name__ == "__main__":
    unittest.main()

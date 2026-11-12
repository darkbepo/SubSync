"""The window with an English and a Danish subtitle of one video (1.5.0), with the fake speech
worker and bag-of-words matcher (as in gui_e2e). Checks the language badges, that the Danish
one is written as .da.srt and timed by the English one, and that a subtitle's language can be
changed. Prints PASS/FAIL; exits non-zero on a failure. Run with QT_QPA_PLATFORM=offscreen."""
import os, sys, shutil, time, numpy as np
os.environ["QT_QPA_PLATFORM"] = "offscreen"
ROOT = "/tmp/ssroot_gda"; shutil.rmtree(ROOT, ignore_errors=True); os.makedirs(ROOT); os.environ["SUBSYNC_ROOT"] = ROOT
_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(_REPO, "app"), os.path.join(_REPO, "tests")]
W = "/tmp/ssgda"; shutil.rmtree(W, ignore_errors=True); shutil.copytree(os.path.join(_REPO, "tests", "media"), W)
shutil.copy(W + "/Show.S01E01.en.srt", W + "/Show.S01E01.da.srt")
import subsync.asr_worker, fake_worker, subsync.embed
subsync.asr_worker.worker_main = fake_worker.worker_main
class FakeEmb:
    def __init__(self, d): pass
    def __call__(self, texts):
        out = []
        for t in texts:
            v = np.zeros(512)
            for w in t.lower().replace(".", " ").split(): v[hash(w) % 512] += 1
            out.append(v / (np.linalg.norm(v) or 1))
        return np.array(out, dtype=np.float32)
subsync.embed.Embedder = FakeEmb
if __name__ == "__main__":
    from PySide6.QtWidgets import QApplication
    from subsync.gui import MainWindow, DONE
    from subsync import theme
    app = QApplication([])
    if os.environ.get("DARK"): theme.is_dark = lambda: True
    theme.apply(app)
    w = MainWindow(); w.resize(1100, 420); w.show()
    def pump(sec, until=None):
        t = time.time()
        while time.time() - t < sec:
            app.processEvents(); time.sleep(0.02)
            if until and until(): return True
        return False
    fails = []

    def ok(c, m):
        print(("PASS " if c else "FAIL ") + m, flush=True)
        if not c:
            fails.append(m)
    pump(1)
    w.add_paths([W], None); pump(1)
    langs = {os.path.basename(j.sub): j.lang for j in w.jobs if j.sub}
    ok(langs.get("Show.S01E01.en.srt") == "en" and langs.get("Show.S01E01.da.srt") == "da"
       and langs.get("Show S01E02 WEB-DL.srt") == "en", f"languages {langs}")
    ok(sum(1 for j in w.jobs if j.video and j.video.endswith("Show.S01E01.1080p.mkv")) == 2, "one row per subtitle of S01E01")
    if len(sys.argv) > 1:
        w.grab().save(sys.argv[1] + "-before.png")
    w.btn_start.click()
    pump(90, lambda: all(j.state not in ("queued", "running") for j in w.jobs) and any(j.state == DONE for j in w.jobs))
    pump(1)
    da = next(j for j in w.jobs if j.sub and j.sub.endswith(".da.srt"))
    ok(da.state == DONE and da.out == W + "/Show.S01E01.1080p.da.srt", f"Danish written as .da.srt ({da.out})")
    ok("timed by the English subtitle" in da.detail, "Danish timed by the English subtitle")
    ok(os.path.exists(W + "/Show.S01E01.1080p.en.srt"), "English written as before")
    if len(sys.argv) > 1:
        w.grab().save(sys.argv[1] + "-after.png")
    en2 = next(j for j in w.jobs if j.sub and j.sub.endswith("WEB-DL.srt"))
    w.set_language(en2, "da")
    ok(en2.lang == "da" and en2.state == "waiting", "language can be changed")
    w.engine.shutdown()
    print(f"{len(fails)} failed")
    os._exit(1 if fails else 0)

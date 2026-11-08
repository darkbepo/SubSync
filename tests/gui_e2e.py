import os as _os, sys as _sys
_REPO = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
import os, sys, shutil, time, json, numpy as np
os.environ["QT_QPA_PLATFORM"] = "offscreen"
ROOT = "/tmp/ssroot"; shutil.rmtree(ROOT, ignore_errors=True); os.makedirs(ROOT)
os.environ["SUBSYNC_ROOT"] = ROOT
sys.path.insert(0, _os.path.join(_REPO, "app")); sys.path.insert(0, _os.path.join(_REPO, "tests"))
W = "/tmp/sswork"; shutil.rmtree(W, ignore_errors=True); shutil.copytree("media", W)
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
if __name__ == '__main__':
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import QTimer
    from subsync.gui import MainWindow, DONE
    from subsync.subtitles import load
    app = QApplication([])
    from subsync import theme
    if os.environ.get("DARK"): theme.is_dark = lambda: True
    theme.apply(app)
    w = MainWindow(); w.show()
    def pump(sec, until=None):
        t = time.time()
        while time.time() - t < sec:
            app.processEvents(); time.sleep(0.02)
            if until and until(): return True
        return False
    pump(2)
    w.add_paths([W], None)
    print("rows:", [(os.path.basename(j.video or "-"), os.path.basename(j.sub or "-"), j.state) for j in w.jobs])
    w.grab().save(f"/tmp/{os.environ.get('DARK','l')}shot_ready.png")
    w.start_stop()
    pump(3); w.grab().save(f"/tmp/{os.environ.get('DARK','l')}shot_running.png")
    ok = pump(60, lambda: not w.running)
    print("finished:", ok, [(j.state, j.text) for j in w.jobs])
    w.grab().save(f"/tmp/{os.environ.get('DARK','l')}shot_done.png")
    for name, vid in (("Show.S01E01.1080p", "mkv"), ("Show.S01E02.1080p", "mp4")):
        out = f"{W}/{name}.en.srt"
        truth = json.load(open(f"{W}/{name}.truth.json"))
        got = [l.start for l in load(out)]
        err = np.abs(np.array(got) - np.array(truth))
        print(f"{name}: lines={len(got)} max error={err.max():.2f}s mean={err.mean():.2f}s")
    # run 2: overwrite off -> .en.#1.srt ; uses transcript cache
    for j in w.jobs:
        if j.state == DONE: w.retry(j)
    pump(30, lambda: not w.running)
    print("run2 files:", sorted(f for f in os.listdir(W) if f.endswith(".srt")))
    print("run2 text:", [j.text for j in w.jobs if j.state == DONE])
    # run 3: overwrite on + .eng
    w.overwrite.setChecked(True); w.seg_group.button(1).click()
    for j in w.jobs:
        if j.state == DONE: w.retry(j)
    pump(30, lambda: not w.running)
    for j in w.jobs:
        if j.state == DONE: w.retry(j)
    pump(30, lambda: not w.running)
    print("run3 files:", sorted(f for f in os.listdir(W) if f.endswith(".srt")))
    print("settings:", open(f"{ROOT}/settings.json").read().replace("\n", " ")[:200])
    print("cache:", os.listdir(f"{ROOT}/cache/transcripts"))
    w.close(); pump(1)

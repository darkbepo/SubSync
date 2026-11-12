"""CLI end-to-end with the fake speech worker + bag-of-words matcher (as in gui_e2e)."""
import os as _os, sys as _sys
_REPO = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
import os, sys, shutil, json, subprocess
os.environ["SUBSYNC_ROOT"] = "/tmp/ssroot_cli"; os.makedirs("/tmp/ssroot_cli", exist_ok=True)
sys.path.insert(0, _os.path.join(_REPO, "app")); sys.path.insert(0, _os.path.join(_REPO, "tests"))
if __name__ == "__main__":
    import numpy as np, subsync.asr_worker, fake_worker, subsync.embed
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
    import cli
    W = "/tmp/sscli"; shutil.rmtree(W, ignore_errors=True); shutil.copytree(_os.path.join(_REPO, "tests", "media"), W)
    import random
    from subsync.subtitles import Line, to_srt
    rnd = random.Random(7); words = "alpha bravo charlie delta echo foxtrot golf hotel india juliet kilo lima".split()
    open(W + "/Wrong.Movie.srt", "w").write(to_srt([Line(5 + k * 3, 7 + k * 3, " ".join(rnd.choice(words) for _ in range(6))) for k in range(40)]))
    cases = {
        "whole folder":            [W, "--report", W + "/r1.json"],
        "explicit pair + eng":     ["--pair", W + "/Show.S01E01.1080p.mkv", W + "/Show.S01E01.en.srt", "--suffix", "eng"],
        "wrong subtitle (no match)": ["--pair", W + "/Show.S01E02.1080p.mp4", W + "/Wrong.Movie.srt", "--report", W + "/r3.json"],
        "nothing to pair":         [W + "/Other.Movie.2019.srt"],
        "missing path":            [W + "/nope.mkv"],
        "bad option":              [W, "--suffix", "de"],
        "keep layout":             [W, "--keep-layout", "--overwrite", "--report", W + "/r4.json"],
        "progress + output":       ["--pair", W + "/Show.S01E01.1080p.mkv", W + "/Show.S01E01.en.srt", "--output",
                                    W + "/out/custom.srt", "--progress", "--report", W + "/r5.json"],
        "output in place":         ["--pair", W + "/Show.S01E01.1080p.mkv", W + "/Show.S01E01.en.srt", "--output",
                                    W + "/Show.S01E01.en.srt", "--overwrite"],
        "output exists":           ["--pair", W + "/Show.S01E01.1080p.mkv", W + "/Show.S01E01.en.srt", "--output",
                                    W + "/Show.S01E01.en.srt"],
        "output with folder":      [W, "--output", W + "/x.srt"],
        "output not srt":          ["--pair", W + "/Show.S01E01.1080p.mkv", W + "/Show.S01E01.en.srt", "--output", W + "/x.txt"],
        "gpu fails at start":      [W, "--report", W + "/r6.json"],
    }
    which = sys.argv[1]
    expected = {"wrong subtitle (no match)": 4, "nothing to pair": 5, "missing path": 6, "bad option": 6,
                "output exists": 6, "output with folder": 6, "output not srt": 6}.get(which, 0)
    if which == "gpu fails at start":
        os.environ["SUBSYNC_FAKE_GPU_FATAL"] = "1"
        shutil.rmtree("/tmp/ssroot_cli/cache", ignore_errors=True)  # make it listen, not use the cache
    os.makedirs(W + "/out", exist_ok=True)
    try:
        code = cli.main(cases[which])
    except SystemExit as e:  # argparse errors ("bad option")
        code = e.code
    print(f"EXIT {code}")
    if which == "gpu fails at start":
        rep = json.load(open(W + "/r6.json"))
        if rep["speech_recognition"]["device"] != "cpu" or rep["summary"]["synced"] != 2:
            print("FAIL: expected both items synced on the CPU after the GPU failed"); code = -1
    for r in ("r1", "r3", "r4", "r5", "r6"):
        if os.path.exists(f"{W}/{r}.json"): print(open(f"{W}/{r}.json").read()[:900])
    print("PASS" if code == expected else f"FAIL: expected exit code {expected}, got {code}")
    os._exit(0 if code == expected else 1)  # this script's exit code: 0 = the case behaved as expected

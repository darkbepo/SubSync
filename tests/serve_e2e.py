"""`subsync-cli serve` end-to-end with the fake speech worker + bag-of-words matcher (as in cli_e2e).
Feeds requests on stdin with pauses, checks the JSON events on stdout. Prints PASS/FAIL lines."""
import os as _os, sys as _sys
_REPO = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
import io, json, os, shutil, sys, threading, time
os.environ["SUBSYNC_ROOT"] = "/tmp/ssroot_serve"; os.makedirs("/tmp/ssroot_serve", exist_ok=True)
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
    W = "/tmp/ssserve"; shutil.rmtree(W, ignore_errors=True); shutil.copytree(_os.path.join(_REPO, "tests", "media"), W)
    shutil.rmtree("/tmp/ssroot_serve/cache", ignore_errors=True)
    shutil.copy(W + "/Show.S01E01.en.srt", W + "/Show.S01E01.en.hi.srt")
    reqs = [
        {"id": "e1", "video": W + "/Show.S01E01.1080p.mkv", "subtitle": W + "/Show.S01E01.en.hi.srt",
         "output": W + "/Show.S01E01.en.hi.srt"},                      # in place (needs --overwrite)
        {"id": "e2", "video": W + "/Show.S01E02.1080p.mp4", "subtitle": W + "/Show S01E02 WEB-DL.srt"},
        {"id": "clash", "video": W + "/Show.S01E02.1080p.mp4", "subtitle": W + "/Show S01E02 WEB-DL.srt",
         "output": W + "/Show.S01E01.en.hi.srt"},                      # e1 is still writing that file
        {"video": W + "/nope2.mkv", "subtitle": W + "/x.srt"},          # no id: gets auto-N
        "not json",
        {"id": "bad", "video": W + "/nope.mkv", "subtitle": W + "/Show.S01E01.en.srt"},
        {"id": "e1-again", "video": W + "/Show.S01E01.1080p.mkv", "subtitle": W + "/Show.S01E01.en.srt",
         "output": W + "/again.srt"},                                   # cached transcript
    ]
    r, w = os.pipe()
    sys.stdin = io.TextIOWrapper(os.fdopen(r, "rb"), encoding="utf-8")
    out = io.StringIO()
    real_stdout, sys.stdout = sys.stdout, out
    def feed():
        with os.fdopen(w, "w", encoding="utf-8") as f:
            for k, q in enumerate(reqs):
                if isinstance(q, dict) and q.get("id") == "e1-again":  # once e1's transcript is cached
                    while '"id":"e1","video"' not in out.getvalue():
                        time.sleep(0.1)
                f.write((q if isinstance(q, str) else json.dumps(q)) + "\n"); f.flush()
                time.sleep(0.5 if k == 0 else 0.1)
            time.sleep(1.0)
    threading.Thread(target=feed, daemon=True).start()
    code = cli.serve(["--overwrite"])
    sys.stdout = real_stdout
    lines = out.getvalue().splitlines()
    ev = [json.loads(l) for l in lines]
    print("\n".join(lines[:60]))
    res = {e["id"]: e for e in ev if e["event"] == "result"}
    fails = []

    def ok(c, m):
        print(("PASS " if c else "FAIL ") + m)
        if not c:
            fails.append(m)
    ok(code == 0, f"exit code 0 (got {code})")
    ok(all(l.startswith("{") for l in lines), "every stdout line is JSON")
    ok(ev[0]["event"] == "ready" and ev[0]["subsync_version"] == cli.VERSION, "first event is ready")
    ok(any(e["event"] == "device" for e in ev), "device event")
    ok(res.get("e1", {}).get("status") == "synced" and res["e1"]["output"] == W + "/Show.S01E01.en.hi.srt", "e1 synced in place")
    ok(not os.path.exists(W + "/Show.S01E01.1080p.en.srt"), "no stray <video>.en.srt")
    ok(res.get("e2", {}).get("status") == "synced" and res["e2"]["output"] == W + "/Show.S01E02.1080p.en.srt", "e2 synced next to video")
    ok(res.get(None, {}).get("status") == "failed", "bad JSON line answered with failed")
    ok(res.get("bad", {}).get("status") == "failed" and "not found" in res["bad"]["reason"], "missing video refused")
    ok(res.get("e1-again", {}).get("timings", {}).get("from_cache") is True, "repeat comes from the cache")
    st = [e["stage"] for e in ev if e["event"] == "stage" and e["id"] == "e1"]
    ok(st[:1] == ["queued"] and "listening" in st and "matching" in st, f"e1 stages {st}")
    ok(any(e["event"] == "stage" and e["id"] == "e1" and e["stage"] == "listening" and e["percent"] for e in ev), "listening percent")
    i1 = next(i for i, e in enumerate(ev) if e["event"] == "result" and e["id"] == "e1")
    i2 = next(i for i, e in enumerate(ev) if e["event"] == "stage" and e["id"] == "e2" and e["stage"] == "reading_audio")
    ok(i2 < i1, "e2's audio is read before e1 is finished (overlap)")
    ok(res.get("clash", {}).get("status") == "failed" and "in progress" in res["clash"]["reason"],
       "a second item writing e1's file is refused")
    ok(any(str(k).startswith("auto-") for k in res), "request without id gets an auto-N id")
    print(f"{len(fails)} failed")
    os._exit(1 if fails else 0)

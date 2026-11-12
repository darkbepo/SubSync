"""Danish subtitles end-to-end (1.5.0): command line and serve, with the fake speech worker and
bag-of-words matcher (as in cli_e2e). The "Danish" subtitle has the English text (so the stand-in
matcher can match it) and a .da name, which makes it Danish. Checks result names (.da / .dan),
the report fields (subtitle_language, timing_from, reference_subtitle), that the English subtitle
of the same video is used as the reference, --sub-lang / --reference, and serve's new fields.
Prints PASS/FAIL; exits non-zero on a failure."""
import os as _os, sys as _sys
_REPO = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
import io, json, os, shutil, sys, threading, time
os.environ["SUBSYNC_ROOT"] = "/tmp/ssroot_da"; os.makedirs("/tmp/ssroot_da", exist_ok=True)
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
    W = "/tmp/ssda"; shutil.rmtree(W, ignore_errors=True); shutil.copytree(_os.path.join(_REPO, "tests", "media"), W)
    shutil.copy(W + "/Show.S01E01.en.srt", W + "/Show.S01E01.da.srt")
    fails = []

    def ok(c, m):
        print(("PASS " if c else "FAIL ") + m, flush=True)
        if not c:
            fails.append(m)

    def items(path):
        return {os.path.basename(i["subtitle"] or ""): i for i in json.load(open(path))["items"]}

    # 1. a folder: the English and the Danish subtitle of S01E01 are both synced; Danish by the English one
    code = cli.main([W, "--report", W + "/r1.json"])
    it = items(W + "/r1.json")
    da = it.get("Show.S01E01.da.srt", {})
    en = it.get("Show.S01E01.en.srt", {})
    ok(code == 0, f"folder: exit 0 (got {code})")
    ok(da.get("status") == "synced" and da.get("output") == W + "/Show.S01E01.1080p.da.srt", f"Danish result named .da.srt ({da.get('output')})")
    ok(da.get("subtitle_language") == "da" and da.get("timing_from") == "reference"
       and da.get("reference_subtitle") == W + "/Show.S01E01.en.srt", f"timed by the English subtitle ({da.get('timing_from')}, {da.get('reference_subtitle')})")
    ok(en.get("status") == "synced" and en.get("output") == W + "/Show.S01E01.1080p.en.srt"
       and en.get("subtitle_language") == "en" and en.get("timing_from") == "audio" and en.get("reference_subtitle") is None,
       "English result as before (.en.srt, from the audio)")
    ok(it.get("Show S01E02 WEB-DL.srt", {}).get("subtitle_language") == "en", "untagged English subtitle stays English")

    # 2. --pair + --sub-lang da, no reference: from the audio; overwrite off -> .da.#1.srt
    code = cli.main(["--pair", W + "/Show.S01E01.1080p.mkv", W + "/Show.S01E01.da.srt", "--sub-lang", "da", "--report", W + "/r2.json"])
    d2 = items(W + "/r2.json").get("Show.S01E01.da.srt", {})
    ok(code == 0 and d2.get("timing_from") == "audio" and d2.get("output") == W + "/Show.S01E01.1080p.da.#1.srt",
       f"--pair without reference: from the audio, .da.#1.srt ({d2.get('timing_from')}, {d2.get('output')})")

    # 3. --reference and --suffix eng -> .dan.srt
    code = cli.main(["--pair", W + "/Show.S01E01.1080p.mkv", W + "/Show.S01E01.da.srt", "--reference", W + "/Show.S01E01.en.srt",
                     "--suffix", "eng", "--report", W + "/r3.json"])
    d3 = items(W + "/r3.json").get("Show.S01E01.da.srt", {})
    ok(code == 0 and d3.get("timing_from") == "reference" and d3.get("output") == W + "/Show.S01E01.1080p.dan.srt",
       f"--reference + --suffix eng: .dan.srt ({d3.get('output')})")

    # 4. bad --reference use
    for args, what in ((["--pair", W + "/Show.S01E01.1080p.mkv", W + "/Show.S01E01.da.srt", "--reference", W + "/nope.srt"], "missing reference"),
                       ([W, "--reference", W + "/Show.S01E01.en.srt"], "reference without --pair"),
                       ([W, "--sub-lang", "de"], "unsupported --sub-lang")):
        try:
            code = cli.main(args)
        except SystemExit as e:
            code = e.code
        ok(code == 6, f"{what}: exit 6 (got {code})")

    # 5. serve: subtitle_language + reference; a bad language is refused
    reqs = [{"id": "d1", "video": W + "/Show.S01E01.1080p.mkv", "subtitle": W + "/Show.S01E01.da.srt",
             "output": W + "/serve.da.srt", "subtitle_language": "da", "reference": W + "/Show.S01E01.en.srt"},
            {"id": "bad", "video": W + "/Show.S01E01.1080p.mkv", "subtitle": W + "/Show.S01E01.da.srt", "subtitle_language": "de"},
            {"id": "badref", "video": W + "/Show.S01E01.1080p.mkv", "subtitle": W + "/Show.S01E01.da.srt", "reference": W + "/nope.srt"}]
    r, w = os.pipe()
    sys.stdin = io.TextIOWrapper(os.fdopen(r, "rb"), encoding="utf-8")
    out = io.StringIO()
    real_stdout, sys.stdout = sys.stdout, out

    def feed():
        with os.fdopen(w, "w", encoding="utf-8") as f:
            for q in reqs:
                f.write(json.dumps(q) + "\n"); f.flush(); time.sleep(0.2)
            time.sleep(1.0)
    threading.Thread(target=feed, daemon=True).start()
    code = cli.serve(["--overwrite"])
    sys.stdout = real_stdout
    res = {e["id"]: e for e in map(json.loads, out.getvalue().splitlines()) if e["event"] == "result"}
    s1 = res.get("d1", {})
    ok(code == 0 and s1.get("status") == "synced" and s1.get("subtitle_language") == "da" and s1.get("timing_from") == "reference"
       and s1.get("output") == W + "/serve.da.srt", f"serve: Danish by reference ({s1.get('timing_from')})")
    ok(res.get("bad", {}).get("status") == "failed" and "subtitle_language" in res["bad"].get("reason", ""), "serve: bad subtitle_language refused")
    ok(res.get("badref", {}).get("status") == "failed" and "reference not found" in res["badref"].get("reason", ""), "serve: missing reference refused")
    print(f"{len(fails)} failed")
    os._exit(1 if fails else 0)

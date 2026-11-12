"""`subsync-cli detect` end-to-end, as a separate process with piped stdin/stdout/stderr (like the
Jellyfin plugin), with a stand-in for Whisper (fake_detect.py: the language comes from a
<video>.lang.json sidecar). Everything else is real: track choice, seeking and decoding, voice
detection (a music-only clip must give "no speech found"), the JSON, exit codes, the GPU-to-CPU
fallback, that nothing is written next to the video or into the cache, and detect while
`serve` is running for the same folder. Needs ffmpeg and espeak-ng. Prints PASS/FAIL.

    python detect_e2e.py
"""
import os as _os, sys as _sys
_REPO = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
import json, os, shutil, subprocess, sys, tempfile, threading, time

TMP = tempfile.gettempdir()
W = os.path.join(TMP, "ssdetect")          # the "video folder"
ROOT = os.path.join(TMP, "ssroot_detect")  # the SubSync folder (cache, logs)
EN = ("Good evening. The weather has been strange all week, and nobody in the village knows why. "
      "My brother says the river will flood again before the end of the month. "
      "I told him we should move the boats up the hill tonight, while there is still time. "
      "He laughed at me, but I am not joking. Last year we lost everything.")
DA = ("God aften. Vejret har været mærkeligt hele ugen, og ingen i landsbyen ved hvorfor. "
      "Min bror siger, at åen vil gå over sine bredder igen inden udgangen af måneden. "
      "Jeg sagde til ham, at vi skulle flytte bådene op ad bakken i aften, mens der stadig er tid. "
      "Han lo af mig, men jeg mener det alvorligt. Sidste år mistede vi alt.")


def sh(*cmd):
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def ff(*args):
    sh("ffmpeg", "-y", "-loglevel", "error", *args)


def make_fixtures():
    shutil.rmtree(W, ignore_errors=True); os.makedirs(W)
    shutil.rmtree(ROOT, ignore_errors=True); os.makedirs(ROOT)
    t = os.path.join(W, "_src"); os.makedirs(t)
    sh("espeak-ng", "-v", "en", "-s", "150", "-w", f"{t}/en.wav", EN)
    sh("espeak-ng", "-v", "da", "-s", "150", "-w", f"{t}/da.wav", DA)
    vid = ["-f", "lavfi", "-i", "color=c=black:s=64x36:r=2"]
    enc = ["-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-b:a", "64k", "-shortest"]
    # English as 5.1 with the voice in the centre channel, language tag "und"
    ff(*vid, "-i", f"{t}/en.wav", "-af", "pan=5.1|FC=c0|FL=0.1*c0|FR=0.1*c0|BL=0*c0|BR=0*c0|LFE=0*c0",
       *enc, "-metadata:s:a:0", "language=und", f"{W}/english.mkv")
    # Danish, no language tag at all (mp4 without the tag)
    ff(*vid, "-i", f"{t}/da.wav", *enc, f"{W}/danish.mp4")
    # music only: chords, 40 s
    ff(*vid, "-f", "lavfi", "-i", "aevalsrc=0.15*sin(2*PI*220*t)+0.15*sin(2*PI*277*t)+0.15*sin(2*PI*330*t)"
       "*(0.6+0.4*sin(2*PI*2*t))+0.05*sin(2*PI*880*t)*sin(2*PI*0.5*t):s=44100:d=40", *enc, f"{W}/music.mkv")
    # two tracks: Danish first, English second (tagged)
    ff(*vid, "-i", f"{t}/da.wav", "-i", f"{t}/en.wav", "-map", "0:v", "-map", "1:a", "-map", "2:a",
       *enc, "-metadata:s:a:0", "language=dan", "-metadata:s:a:1", "language=eng", f"{W}/two.mkv")
    # 20 minutes: the English speech once every 100 s, silence in between
    ff("-i", f"{t}/en.wav", "-af", "apad=whole_dur=100", f"{t}/seg.wav")
    ff("-stream_loop", "11", "-i", f"{t}/seg.wav", "-c", "copy", f"{t}/long.wav")
    ff(*vid, "-i", f"{t}/long.wav", *enc, "-metadata:s:a:0", "language=und", f"{W}/long.mkv")
    ff(*vid, "-t", "5", "-c:v", "libx264", "-preset", "ultrafast", f"{W}/noaudio.mkv")
    with open(f"{W}/broken.mkv", "wb") as f:
        f.write(os.urandom(50_000))
    shutil.rmtree(t)
    for name, m in (("english.mkv", {"*": "en"}), ("danish.mp4", {"*": "da"}), ("two.mkv", {"1": "da", "2": "en"}),
                    ("long.mkv", {"*": "en"}), ("music.mkv", {"*": "en"})):
        json.dump(m, open(f"{W}/{name}.lang.json", "w"))
    # a transcript cache with one entry, which must stay untouched
    os.makedirs(f"{ROOT}/cache/transcripts"); open(f"{ROOT}/cache/transcripts/x.json.gz", "wb").write(b"x")


def child():
    """The detect process: app/cli.py's __main__ with the stand-in worker."""
    sys.path.insert(0, _os.path.join(_REPO, "app")); sys.path.insert(0, _os.path.join(_REPO, "tests"))
    import fake_detect, subsync.detect
    subsync.detect.detect_worker = fake_detect.detect_worker
    import cli
    cli.LOG = open(os.path.join(os.environ["SUBSYNC_ROOT"], "cli.log"), "a", encoding="utf-8", buffering=1)
    sys.stderr = cli.LOG
    try:
        code = cli.detect(sys.argv[2:])
    except SystemExit as e:
        code = e.code
    sys.stdout.flush()
    os._exit(code)


def run(*args, env=None, timeout=120):
    flags = 0x08000000 if sys.platform == "win32" else 0  # CREATE_NO_WINDOW
    e = dict(os.environ, SUBSYNC_ROOT=ROOT, **(env or {}))
    p = subprocess.run([sys.executable, os.path.abspath(__file__), "--child", *args], env=e, input=b"",
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=flags, timeout=timeout,
                       cwd=os.path.join(_REPO, "tests"))
    lines = p.stdout.decode("utf-8", "replace").splitlines()
    js = [json.loads(l) for l in lines if l.startswith("{")]
    return p.returncode, lines, (js[-1] if js else None), p.stderr.decode("utf-8", "replace")


def snapshot(*dirs):
    out = {}
    for d in dirs:
        for base, _, files in os.walk(d):
            for f in files:
                st = os.stat(os.path.join(base, f))
                out[os.path.join(base, f)] = (st.st_size, st.st_mtime_ns)
    return out


if __name__ == "__main__":
    if sys.argv[1:2] == ["--child"]:
        child()
    fails = []

    def ok(c, m):
        print(("PASS " if c else "FAIL ") + m, flush=True)
        if not c:
            fails.append(m)

    make_fixtures()
    before = snapshot(W, os.path.join(ROOT, "cache"))

    code, lines, j, _ = run(f"{W}/english.mkv")
    ok(code == 0 and j and j["language"] == "en" and j["probability"] == 0.95, f"English (tag und): en ({code}, {j})")
    ok(j and j["track"] == 1 and j["audio_tracks"] == 1 and j["track_language_tag"] in (None, "und"),
       "track 1 of 1, tag und or none (ffmpeg drops 'und' in MKV)")
    ok(j and 10 < j["speech_seconds"] <= 90 and j["device"] == "gpu" and j["subsync_version"], "speech seconds, device, version")
    ok(len(lines) == 1, f"stdout is exactly one JSON line (got {len(lines)})")
    keys = {"video", "track", "track_language_tag", "language", "probability", "speech_seconds", "device",
            "seconds", "subsync_version"}
    ok(j and keys <= set(j), f"all documented fields ({sorted(keys - set(j or {}))} missing)")

    code, _, j, _ = run(f"{W}/danish.mp4")
    ok(code == 0 and j and j["language"] == "da" and j["track_language_tag"] in (None, "und"),
       f"Danish (no tag; MP4 says 'und'): da ({j})")

    code, _, j, _ = run(f"{W}/music.mkv")
    ok(code == 0 and j and j["language"] is None and j["probability"] is None and j.get("reason") == "no speech found",
       f"music only: no speech found ({j})")
    ok(j and j["device"] is None, "music only: the speech model was not needed")

    sys.path.insert(0, os.path.join(_REPO, "app"))
    from subsync.media import pick_audio_stream
    code, _, j, _ = run(f"{W}/two.mkv")
    ok(code == 0 and j and j["track"] == pick_audio_stream(f"{W}/two.mkv")[0] + 1 == 2 and j["language"] == "en"
       and j["track_language_tag"] == "eng" and j["audio_tracks"] == 2, f"two tracks: default = sync's choice (2, en) ({j})")
    code, _, j, _ = run(f"{W}/two.mkv", "--track", "1")
    ok(code == 0 and j and j["track"] == 1 and j["language"] == "da" and j["track_language_tag"] == "dan", f"--track 1: da ({j})")

    t0 = time.time()
    code, lines, j, _ = run(f"{W}/long.mkv", "--progress")
    ok(code == 0 and j and j["language"] == "en" and 20 < j["speech_seconds"] <= 90, f"20-minute video: en, speech capped ({j})")
    log = open(os.path.join(ROOT, "cli.log"), encoding="utf-8").read()
    dec = [float(l.split("read ")[1].split(" s")[0]) for l in log.splitlines() if "detect: read " in l]
    ok(dec and dec[-1] <= 300, f"20-minute video: only windows decoded ({dec[-1] if dec else None} s of audio)")
    prog = [json.loads(l[9:]) for l in lines if l.startswith("PROGRESS ")]
    st = [p["stage"] for p in prog]
    ok(st and st[0] == "reading_audio" and "listening" in st and all(l.startswith(("PROGRESS ", "{")) for l in lines)
       and lines[-1].startswith("{"), f"--progress: PROGRESS lines, then the JSON ({sorted(set(st))})")
    ok(any(p["stage"] == "listening" and p["percent"] == 100 for p in prog), "listening reaches 100 %")
    code, _, j, _ = run(f"{W}/long.mkv", "--seconds", "10")
    ok(code == 0 and j and 0 < j["speech_seconds"] <= 10, f"--seconds 10 caps the speech ({j and j['speech_seconds']})")

    code, _, j, _ = run(f"{W}/english.mkv", env={"SUBSYNC_FAKE_DETECT_GPU_OOM": "1"})
    ok(code == 0 and j and j["language"] == "en" and j["device"] == "cpu" and "out of memory" in j.get("gpu_problem", ""),
       f"GPU full: falls back to the CPU ({j})")
    code, _, j, _ = run(f"{W}/english.mkv", "--cpu")
    ok(code == 0 and j and j["device"] == "cpu", "--cpu")

    for args, want, what in (([f"{W}/noaudio.mkv"], 3, "video without audio"), ([f"{W}/broken.mkv"], 3, "unreadable video"),
                             ([f"{W}/two.mkv", "--track", "3"], 6, "--track out of range"),
                             ([f"{W}/nope.mkv"], 6, "missing file"), ([f"{W}/english.mkv", "--seconds", "1"], 6, "--seconds 1"),
                             ([f"{W}/english.mkv", "--bogus"], 6, "unknown option"), ([], 6, "no video")):
        code, lines, j, err = run(*args)
        ok(code == want, f"{what}: exit {want} (got {code}, {j})")
        if want == 3:
            ok(j and j["language"] is None and j.get("reason") and len(lines) == 1, f"{what}: JSON with a reason ({j and j.get('reason')})")
            if "without audio" in what:
                ok(j and j["reason"] == "no audio track", "reason: no audio track")
        else:
            ok(not lines, f"{what}: nothing on stdout")

    # while serve runs for the same folder (and keeps the GPU busy with an item)
    flags = 0x08000000 if sys.platform == "win32" else 0
    shutil.copytree(os.path.join(_REPO, "tests", "media"), os.path.join(TMP, "ssdetect_serve"), dirs_exist_ok=True)
    shutil.rmtree(ROOT + "_serve", ignore_errors=True)  # no cached transcript: serve must really listen
    os.makedirs(ROOT + "_serve")
    srv = subprocess.Popen([sys.executable, os.path.join(_REPO, "tests", "serve_pipe_e2e.py"), "--child"],
                           env=dict(os.environ, SUBSYNC_ROOT=ROOT + "_serve"), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                           stderr=subprocess.DEVNULL, creationflags=flags, cwd=os.path.join(_REPO, "tests"))
    ev = []
    threading.Thread(target=lambda: [ev.append(json.loads(l)) for l in srv.stdout if l.startswith(b"{")], daemon=True).start()
    S = os.path.join(TMP, "ssdetect_serve")
    srv.stdin.write((json.dumps({"id": "s1", "video": f"{S}/Show.S01E01.1080p.mkv", "subtitle": f"{S}/Show.S01E01.en.srt",
                                 "output": f"{S}/out.srt"}) + "\n").encode()); srv.stdin.flush()
    end = time.time() + 60
    while time.time() < end and not any(e.get("stage") == "listening" for e in ev):
        time.sleep(0.1)
    ok(any(e.get("stage") == "listening" for e in ev), "serve is listening")
    code, _, j, _ = run(f"{W}/english.mkv")
    ok(code == 0 and j and j["language"] == "en", f"detect while serve is listening works ({code})")
    while time.time() < end + 60 and not any(e.get("event") == "result" for e in ev):
        time.sleep(0.1)
    ok(any(e.get("event") == "result" and e.get("status") == "synced" for e in ev), "serve's item still finishes")
    srv.stdin.close()
    try:
        ok(srv.wait(60) == 0, "serve exits 0")
    except subprocess.TimeoutExpired:
        srv.kill(); ok(False, "serve exits 0")

    after = snapshot(W, os.path.join(ROOT, "cache"))
    ok(after == before, "read-only: nothing created or changed next to the videos or in the cache"
       + ("" if after == before else f" ({sorted(set(after.items()) ^ set(before.items()))[:5]})"))
    print(f"{len(fails)} failed")
    sys.exit(1 if fails else 0)

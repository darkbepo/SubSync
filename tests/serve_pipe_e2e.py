"""`subsync-cli serve` as a separate process with stdin, stdout and stderr all piped, the way the
Jellyfin plugin runs it, and stdin kept OPEN while waiting for results (fake speech worker +
bag-of-words matcher, as in serve_e2e).

Guards the 1.3.1 fix: on Windows the speech worker hung in Python start-up while serve had a
read pending on the request pipe, because the worker got that pipe as its stdin. Cases:
  open stdin   two requests, each answered while stdin stays open; then stdin closes -> exit 0
  gpu crash    the worker dies on its first job; the CPU worker started meanwhile finishes it
  gpu fatal    the GPU model "fails to load"; same, through the other fallback path
On Linux the hang itself can't happen, so there the test also checks directly that no worker
has the caller's pipes as its stdin/stdout. Run it on Windows with an installed SubSync's
runtime\\python\\python.exe to check the real thing. Prints PASS/FAIL; exits non-zero on a failure.

    python serve_pipe_e2e.py            # every case
    python serve_pipe_e2e.py "gpu crash"
"""
import os as _os, sys as _sys
_REPO = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
import json, os, queue, shutil, subprocess, sys, tempfile, threading, time

TMP = tempfile.gettempdir()
LIMIT = 90  # seconds per awaited event; the fake worker needs a few


def child():
    """The serve process: like app/cli.py's __main__, with the test doubles patched in."""
    sys.path.insert(0, _os.path.join(_REPO, "app")); sys.path.insert(0, _os.path.join(_REPO, "tests"))
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
    cli.LOG = open(os.path.join(os.environ["SUBSYNC_ROOT"], "cli.log"), "a", encoding="utf-8", buffering=1)
    sys.stderr = cli.LOG
    code = cli.serve(["--overwrite"])
    sys.stdout.flush()
    os._exit(code)


def worker_pids(pid):
    """Linux: every descendant of pid."""
    kids, todo = [], [pid]
    while todo:
        p = todo.pop()
        for d in os.listdir("/proc"):
            if d.isdigit():
                try:
                    with open(f"/proc/{d}/stat") as f:
                        if int(f.read().rsplit(")", 1)[1].split()[1]) == p:
                            kids.append(int(d)); todo.append(int(d))
                except (OSError, IndexError, ValueError):
                    pass
    return kids


def run_case(name, ok):
    root = os.path.join(TMP, "ssroot_pipe_" + name.replace(" ", "_"))
    W = os.path.join(TMP, "sspipe_" + name.replace(" ", "_"))
    for d in (root, W):
        shutil.rmtree(d, ignore_errors=True)
    os.makedirs(root)
    shutil.copytree(os.path.join(_REPO, "tests", "media"), W)
    env = dict(os.environ, SUBSYNC_ROOT=root)
    env.pop("SUBSYNC_FAKE_GPU_CRASH", None); env.pop("SUBSYNC_FAKE_GPU_FATAL", None)
    if name == "gpu crash":
        env["SUBSYNC_FAKE_GPU_CRASH"] = "1"
    if name == "gpu fatal":
        env["SUBSYNC_FAKE_GPU_FATAL"] = "1"
    flags = 0x08000000 if sys.platform == "win32" else 0  # CREATE_NO_WINDOW, as the plugin does
    p = subprocess.Popen([sys.executable, os.path.abspath(__file__), "--child"], env=env,
                         stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         creationflags=flags, cwd=os.path.join(_REPO, "tests"))
    evq, events, err = queue.Queue(), [], []

    def read_out():
        for raw in p.stdout:
            line = raw.decode("utf-8", "replace").rstrip("\r\n")
            evq.put(line)
        evq.put(None)
    threading.Thread(target=read_out, daemon=True).start()
    threading.Thread(target=lambda: err.extend(p.stderr), daemon=True).start()

    def wait_for(pred, what):
        end = time.time() + LIMIT
        for e in events:
            if pred(e):
                return e
        while time.time() < end:
            try:
                line = evq.get(timeout=max(0.1, end - time.time()))
            except queue.Empty:
                break
            if line is None:
                break
            if not line.startswith("{"):
                continue
            e = json.loads(line)
            events.append(e)
            if pred(e):
                return e
        ok(False, f"[{name}] no {what} within {LIMIT} s (stdin open)")
        return None

    def send(req):
        p.stdin.write((json.dumps(req) + "\n").encode("utf-8")); p.stdin.flush()

    def is_result(i):
        return lambda e: e.get("event") == "result" and e.get("id") == i

    try:
        ok(wait_for(lambda e: e.get("event") == "ready", "ready") is not None, f"[{name}] ready")
        items = [("a", "Show.S01E01.1080p.mkv", "Show.S01E01.en.srt"),
                 ("b", "Show.S01E02.1080p.mp4", "Show S01E02 WEB-DL.srt")]
        for i, video, sub in items:
            send({"id": i, "video": os.path.join(W, video), "subtitle": os.path.join(W, sub)})
            r = wait_for(is_result(i), f"result for {i!r}")
            ok(r is not None and r.get("status") == "synced", f"[{name}] {i!r} synced while stdin is open"
               + ("" if r is None else f" (got {r.get('status')}: {r.get('reason')})"))
            st = [e["stage"] for e in events if e.get("event") == "stage" and e.get("id") == i]
            ok("reading_audio" in st and "listening" in st, f"[{name}] {i!r} stages {sorted(set(st))}")
            if sys.platform.startswith("linux"):  # the fix itself: no worker holds the caller's pipes
                mine = {os.readlink(f"/proc/{p.pid}/fd/{fd}") for fd in (0, 1)}
                checked = 0
                for k in worker_pids(p.pid):
                    try:
                        got = {fd: os.readlink(f"/proc/{k}/fd/{fd}") for fd in (0, 1)}
                    except OSError:
                        continue
                    checked += 1
                    ok(got == {0: "/dev/null", 1: "/dev/null"}, f"[{name}] worker {k} stdin/stdout are NUL (got {got})")
                ok(checked > 0, f"[{name}] found a running worker to check")
                ok(mine == {"/dev/null"}, f"[{name}] serve's own fd 0/1 point at NUL (got {mine})")
        if name != "open stdin":
            ok(any(e.get("event") == "warning" for e in events), f"[{name}] warning event about the GPU")
            dev = [e.get("device") for e in events if e.get("event") == "device"]
            ok(dev[-1:] == ["cpu"], f"[{name}] finished on the CPU (device events {dev})")
        p.stdin.close()
        try:
            code = p.wait(LIMIT)
        except subprocess.TimeoutExpired:
            code = "still running"
        ok(code == 0, f"[{name}] exit code 0 after stdin closed (got {code})")
        time.sleep(0.2)
        ok(all(e.get("event") != "result" or e.get("id") in ("a", "b") for e in events), f"[{name}] no unexpected results")
    finally:
        if p.poll() is None:
            p.kill()
        text = b"".join(err).decode("utf-8", "replace").strip()
        if text:
            print(f"--- [{name}] serve stderr:\n" + text[-2000:])


if __name__ == "__main__":
    if sys.argv[1:] == ["--child"]:
        child()
    fails = []

    def ok(c, m):
        print(("PASS " if c else "FAIL ") + m, flush=True)
        if not c:
            fails.append(m)
    for case in (sys.argv[1:] or ["open stdin", "gpu crash", "gpu fatal"]):
        run_case(case, ok)
    print(f"{len(fails)} failed")
    sys.exit(1 if fails else 0)

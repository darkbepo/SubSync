"""SubSync command line (started by subsync-cli.exe).

    subsync-cli sync <files or folders...> [--pair VIDEO SUBTITLE] [--suffix en|eng]
                     [--overwrite] [--cpu] [--report FILE.json]

Exit codes: see EXIT_* below and README-CLI.md.
"""
import argparse
import faulthandler
import json
import multiprocessing
import os
import queue
import sys
import time
import traceback

EXIT_OK = 0          # every pair was synced
EXIT_PARTIAL = 3     # some pairs synced, some failed or did not match their video
EXIT_NONE = 4        # no pair could be synced
EXIT_NOTHING = 5     # no video + subtitle pairs found
EXIT_USAGE = 6       # invalid command line
EXIT_STOPPED = 9     # stopped with Ctrl+C
EXIT_INTERNAL = 10   # unexpected error - see logs\cli.log

LOG = None


def log(msg):
    if LOG:
        LOG.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}\n")
        LOG.flush()


def out(msg=""):
    print(msg, flush=True)
    log(msg)


class Parser(argparse.ArgumentParser):
    def error(self, message):  # argparse would exit with 2; use our documented code
        self.print_usage(sys.__stderr__)
        print(f"Error: {message}\nRun \"subsync-cli help\" for all options.", file=sys.__stderr__)
        log(f"usage error: {message}")
        sys.exit(EXIT_USAGE)


def parse(argv):
    p = Parser(prog="subsync-cli sync", add_help=False)
    p.add_argument("paths", nargs="*")
    p.add_argument("--pair", nargs=2, action="append", default=[], metavar=("VIDEO", "SUBTITLE"))
    p.add_argument("--suffix", choices=["en", "eng", ".en", ".eng"], default="en")
    p.add_argument("--overwrite", action="store_true")
    p.add_argument("--cpu", action="store_true")
    p.add_argument("--report", metavar="FILE.json")
    p.add_argument("-h", "--help", action="store_true")
    return p.parse_args(argv)


def fmt_secs(s):
    s = int(s)
    return f"{s // 3600}h {s % 3600 // 60:02d}m" if s >= 3600 else f"{s // 60}m {s % 60:02d}s" if s >= 60 else f"{s}s"


def main(argv):
    from subsync.media import VIDEO_EXTS
    from subsync.pairing import expand, pair
    from subsync.subtitles import SUB_EXTS

    args = parse(argv)
    if args.help:
        print("Run \"subsync-cli help\" for usage.")
        return EXIT_OK
    suffix = "." + args.suffix.lstrip(".")

    # ---------------------------------------------------------------- pairing
    rows = []
    used = set()
    for v, s in args.pair:
        v, s = os.path.abspath(v), os.path.abspath(s)
        for f, kind, exts in ((v, "video", VIDEO_EXTS), (s, "subtitle", SUB_EXTS)):
            if not os.path.isfile(f):
                print(f"Error: --pair {kind} not found: {f}", file=sys.__stderr__)
                log(f"usage error: missing {kind} {f}")
                return EXIT_USAGE
            if os.path.splitext(f)[1].lower() not in exts:
                print(f"Error: --pair {kind} has an unsupported type: {f}", file=sys.__stderr__)
                return EXIT_USAGE
        rows.append((v, s))
        used.update((v, s))
    missing = [p for p in args.paths if not os.path.exists(p)]
    if missing:
        print("Error: not found: " + ", ".join(missing), file=sys.__stderr__)
        log("usage error: not found " + ", ".join(missing))
        return EXIT_USAGE
    videos, subs = expand([os.path.abspath(p) for p in args.paths])
    videos = [v for v in videos if v not in used]
    subs = [s for s in subs if s not in used]
    skipped = []
    for v, s in pair(videos, subs):
        if v and s:
            rows.append((v, s))
        else:
            skipped.append({"video": v, "subtitle": s, "status": "skipped",
                            "reason": "no matching subtitle" if v else "no matching video"})

    out(f"SubSync {time.strftime('%Y-%m-%d %H:%M')}: {len(rows)} pair(s) to sync"
        + (f", {len(skipped)} file(s) without a partner" if skipped else ""))
    for n, (v, s) in enumerate(rows, 1):
        out(f"  {n:>3}. {os.path.basename(v)}  <-  {os.path.basename(s)}")
    for k in skipped:
        out(f"   skip {os.path.basename(k['video'] or k['subtitle'])}  ({k['reason']})")
    if not rows:
        out("Nothing to do: no video + subtitle pairs found.")
        write_report(args.report, [], skipped, EXIT_NOTHING, 0)
        return EXIT_NOTHING

    # ---------------------------------------------------------------- run
    from subsync import settings as gui_settings
    from subsync.pipeline import Engine

    settings = {"suffix": suffix, "overwrite": args.overwrite,
                "gpu_batch": gui_settings.load().get("gpu_batch", 0)}
    events: "queue.Queue" = queue.Queue()
    engine = Engine(lambda jid, kind, data: events.put((jid, kind, data)), lambda: settings)
    engine.force_cpu = args.cpu
    jobs = {}
    for n, (v, s) in enumerate(rows, 1):
        jobs[n] = {"video": v, "subtitle": s, "status": "pending", "n": n}
    t_start = time.time()
    engine.warm_up()
    for n, j in jobs.items():
        engine.submit(n, j["video"], j["subtitle"])

    tty = sys.stdout.isatty()
    total = len(jobs)
    finished = 0
    current = {}
    last_line = ""

    def status_line():
        nonlocal last_line
        if not tty or not current:
            return
        n, text, pct = max(current.values(), key=lambda x: x[0])
        el = time.time() - t_start
        eta = f" · about {fmt_secs(el / finished * (total - finished))} left" if finished else ""
        line = f"[{finished}/{total}] {os.path.basename(jobs[n]['video'])} – {text}" + (f" {int(pct * 100)}%" if pct else "") + eta
        line = line[:118]
        if line != last_line:
            sys.stdout.write("\r" + line.ljust(120))
            sys.stdout.flush()
            last_line = line

    def clear_line():
        nonlocal last_line
        if tty and last_line:
            sys.stdout.write("\r" + " " * 120 + "\r")
            last_line = ""

    try:
        while finished < total:
            try:
                jid, kind, data = events.get(timeout=0.5)
            except queue.Empty:
                status_line()
                continue
            if jid is None:
                if kind == "device":
                    st = data.get("state")
                    if st == "ready":
                        clear_line()
                        out("Speech recognition: " + (f"GPU ({data['name']})" if data["device"] == "cuda"
                                                      else "CPU (no usable NVIDIA GPU – slower)"))
                    elif st == "error":
                        clear_line()
                        out("Warning: " + data.get("text", "speech recognition problem"))
                        if data.get("detail"):
                            log(data["detail"])
                elif kind == "batch":
                    gui_settings.update(gpu_batch=int(data))
                continue
            j = jobs.get(jid)
            if j is None:
                continue
            if kind == "stage":
                current[jid] = (jid, data, 0.0)
                if not tty and data not in ("Queued",):
                    log(f"[{jid}/{total}] {os.path.basename(j['video'])}: {data}")
            elif kind == "progress":
                n_, text, _ = current.get(jid, (jid, "", 0.0))
                current[jid] = (jid, text, float(data))
            elif kind in ("done", "warning", "error", "cancelled"):
                current.pop(jid, None)
                finished += 1
                clear_line()
                tag = f"[{finished}/{total}]"
                name = os.path.basename(j["video"])
                if kind == "done":
                    lo, hi = data["offsets"]
                    ends = sum(data["ends"][:2])
                    j.update(status="synced", output=data["out"], lines_matched=data["matched"],
                             lines_with_speech=data["total"], audio_language=data["lang"],
                             shift_min=round(lo, 3), shift_max=round(hi, 3), timing_sections=len(data["runs"]),
                             endings_extended=ends, seconds=round(data["seconds"], 1))
                    out(f"OK   {tag} {name} -> {os.path.basename(data['out'])}  ({data['matched']}/{data['total']} lines matched, "
                        f"shift {lo:+.1f}..{hi:+.1f} s, {len(data['runs'])} section(s), {ends} ending(s) extended)")
                elif kind == "warning":
                    j.update(status="no_match", reason=data["text"], audio_language=data.get("lang"))
                    out(f"SKIP {tag} {name}: {data['text']}  (no file written)")
                else:
                    reason = data["text"] if isinstance(data, dict) else str(data)
                    j.update(status="failed" if kind == "error" else "cancelled", reason=reason)
                    out(f"FAIL {tag} {name}: {reason}")
    except KeyboardInterrupt:
        clear_line()
        out("Stopped (Ctrl+C).")
        engine.shutdown()
        for j in jobs.values():
            if j["status"] == "pending":
                j["status"] = "cancelled"
        write_report(args.report, list(jobs.values()), skipped, EXIT_STOPPED, time.time() - t_start)
        return EXIT_STOPPED
    engine.shutdown()

    ok = sum(1 for j in jobs.values() if j["status"] == "synced")
    nomatch = sum(1 for j in jobs.values() if j["status"] == "no_match")
    failed = total - ok - nomatch
    code = EXIT_OK if ok == total else EXIT_NONE if ok == 0 else EXIT_PARTIAL
    out(f"Done in {fmt_secs(time.time() - t_start)}: {ok} synced"
        + (f", {nomatch} did not match their video" if nomatch else "")
        + (f", {failed} failed" if failed else "")
        + (f", {len(skipped)} without a partner" if skipped else "") + ".")
    if code != EXIT_OK:
        out("Details: " + os.path.join(os.environ.get("SUBSYNC_ROOT", "."), "logs", "cli.log"))
    write_report(args.report, list(jobs.values()), skipped, code, time.time() - t_start)
    return code


def write_report(path, items, skipped, code, seconds):
    if not path:
        return
    rep = {
        "subsync_version": "1.1.0",
        "finished": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "exit_code": code,
        "seconds": round(seconds, 1),
        "summary": {s: sum(1 for i in items if i["status"] == s)
                    for s in ("synced", "no_match", "failed", "cancelled")} | {"skipped": len(skipped)},
        "items": [{k: v for k, v in i.items() if k != "n"} for i in items] + skipped,
    }
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(rep, f, indent=2)
        out(f"Report: {os.path.abspath(path)}")
    except OSError as e:
        out(f"Could not write the report {path}: {e}")


if __name__ == "__main__":
    multiprocessing.freeze_support()
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from subsync import paths

    paths.setup_environment()
    LOG = open(os.path.join(paths.LOGS, "cli.log"), "a", encoding="utf-8", buffering=1)
    LOG.write(f"\n=== cli {time.strftime('%Y-%m-%d %H:%M:%S')}  {' '.join(sys.argv[1:])}\n")
    faulthandler.enable(file=LOG, all_threads=True)
    sys.stderr = LOG  # internal warnings/tracebacks go to the log, not the console
    log("C++ runtime: " + ", ".join(paths.preload_vc_runtime()))
    argv = sys.argv[1:]
    if argv and argv[0] == "sync":
        argv = argv[1:]
    code = EXIT_INTERNAL
    try:
        code = main(argv)
    except SystemExit as e:
        code = e.code if isinstance(e.code, int) else EXIT_USAGE
    except KeyboardInterrupt:
        code = EXIT_STOPPED
    except Exception:
        LOG.write(traceback.format_exc())
        print("Unexpected error – details in logs\\cli.log", file=sys.__stderr__)
        code = EXIT_INTERNAL
    log(f"exit code {code}")
    sys.stdout.flush()
    os._exit(code)

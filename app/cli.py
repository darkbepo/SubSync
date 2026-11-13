"""SubSync command line (started by subsync-cli.exe).

    subsync-cli sync <files or folders...> [--pair VIDEO SUBTITLE] [--suffix en|eng]
                     [--overwrite] [--keep-layout] [--cpu] [--report FILE.json]
                     [--output FILE.srt] [--progress] [--sub-lang auto|en|da] [--reference EN.srt]
    subsync-cli serve [--suffix en|eng] [--overwrite] [--keep-layout] [--cpu]

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

T_PROCESS = time.time()  # detect's "seconds" counts from here
VERSION = "1.5.1"  # also in launcher/cli.go

EXIT_OK = 0          # every pair was synced
EXIT_PARTIAL = 3     # some pairs synced, some failed or did not match their video
EXIT_NONE = 4        # no pair could be synced
EXIT_NOTHING = 5     # no video + subtitle pairs found
EXIT_USAGE = 6       # invalid command line
EXIT_STOPPED = 9     # stopped with Ctrl+C
EXIT_INTERNAL = 10   # unexpected error - see logs\cli.log
EXIT_UNREADABLE = 3  # detect only: the video can't be read or has no audio

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
    p.add_argument("--keep-layout", action="store_true")  # turn "Tidy up lines" off
    p.add_argument("--cpu", action="store_true")
    p.add_argument("--report", metavar="FILE.json")
    p.add_argument("--output", metavar="FILE.srt")  # with exactly one --pair: write the result there
    p.add_argument("--progress", action="store_true")  # machine-readable PROGRESS lines on stdout
    p.add_argument("--sub-lang", choices=["auto", "en", "da"], default="auto")  # 1.5.0: the subtitles' language
    p.add_argument("--reference", metavar="EN.srt")  # 1.5.0: with one --pair: English subtitle to time a Danish one by
    p.add_argument("-h", "--help", action="store_true")
    return p.parse_args(argv)


def done_fields(data) -> dict:
    """JSON report fields for a synced item."""
    lo, hi = data["offsets"]
    t = data.get("tidy") or {}
    return {"status": "synced", "output": data["out"], "lines_matched": data["matched"],
            "lines_with_speech": data["total"], "audio_language": data["lang"],
            "shift_min": round(lo, 3), "shift_max": round(hi, 3), "timing_sections": len(data["runs"]),
            "endings_extended": sum(data["ends"][:2]), "seconds": round(data["seconds"], 1),
            "tidy": bool(t.get("tidy", False)), "subtitles_before": t.get("subtitles_before"),
            "subtitles_after": t.get("subtitles_after"), "joined": t.get("joined", 0),
            "split": t.get("split", 0), "capitals_fixed": t.get("capitals_fixed", 0),
            "kept_visible": t.get("kept_visible", 0),
            "subtitle_language": data.get("sub_lang", "en"), "timing_from": data.get("timing_from", "audio"),
            "reference_subtitle": data.get("reference"),
            "timings": timings(data)}


def timings(data) -> dict:
    """Seconds per step of a synced item (null when the step did not run)."""
    st = data.get("stats") or {}
    r = lambda x: round(x, 1) if isinstance(x, (int, float)) else None
    return {"from_cache": bool(st.get("cached")), "read_audio": r(st.get("decode_s")),
            "listen": r(st.get("asr_s")), "match": r(data.get("align_s"))}


# --progress: stage codes for the engine's stage texts (stable; scripts depend on them)
STAGES = {"Queued": "queued", "Reading audio…": "reading_audio", "Listening…": "listening",
          "Matching lines…": "matching"}


def stage_code(text: str) -> str:
    return STAGES.get(text) or ("waiting_for_file" if text.startswith("Waiting") else "working")


def progress_line(obj: dict) -> None:
    """One machine-readable line: PROGRESS {json}. Plain ASCII, flushed at once."""
    sys.stdout.write("PROGRESS " + json.dumps(obj, ensure_ascii=True, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def fmt_secs(s):
    s = int(s)
    return f"{s // 3600}h {s % 3600 // 60:02d}m" if s >= 3600 else f"{s // 60}m {s % 60:02d}s" if s >= 60 else f"{s}s"


def main(argv):
    from subsync.media import VIDEO_EXTS
    from subsync.pairing import expand, pair_languages
    from subsync.subtitles import SUB_EXTS

    args = parse(argv)
    if args.help:
        print("Run \"subsync-cli help\" for usage.")
        return EXIT_OK
    suffix = "." + args.suffix.lstrip(".")

    # ---------------------------------------------------------------- pairing
    rows = []  # (video, subtitle, language or None, English reference or None)
    used = set()
    want = None if args.sub_lang == "auto" else args.sub_lang
    reference = os.path.abspath(args.reference) if args.reference else None
    if reference:
        problem = None
        if len(args.pair) != 1 or args.paths:
            problem = "--reference needs exactly one --pair and no other files or folders"
        elif not os.path.isfile(reference):
            problem = f"--reference not found: {reference}"
        elif os.path.splitext(reference)[1].lower() not in SUB_EXTS:
            problem = f"--reference has an unsupported type: {reference}"
        if problem:
            print(f"Error: {problem}", file=sys.__stderr__)
            log(f"usage error: {problem}")
            return EXIT_USAGE
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
        rows.append((v, s, want, reference))
        used.update((v, s))
    output = None
    if args.output:
        output = os.path.abspath(args.output)
        problem = None
        if len(args.pair) != 1 or args.paths:
            problem = "--output needs exactly one --pair and no other files or folders"
        elif os.path.splitext(output)[1].lower() != ".srt":
            problem = "--output must be a .srt file"
        elif not os.path.isdir(os.path.dirname(output)):
            problem = f"--output folder not found: {os.path.dirname(output)}"
        elif os.path.isdir(output):
            problem = f"--output is a folder: {output}"
        elif os.path.exists(output) and not args.overwrite:
            problem = f"--output exists: {output} (add --overwrite to replace it)"
        if problem:
            print(f"Error: {problem}", file=sys.__stderr__)
            log(f"usage error: {problem}")
            return EXIT_USAGE
    missing = [p for p in args.paths if not os.path.exists(p)]
    if missing:
        print("Error: not found: " + ", ".join(missing), file=sys.__stderr__)
        log("usage error: not found " + ", ".join(missing))
        return EXIT_USAGE

    # the speech and line-matching models start loading now, while the folders are scanned
    from subsync import settings as gui_settings
    from subsync.pipeline import Engine

    settings = {"suffix": suffix, "overwrite": args.overwrite, "tidy": not args.keep_layout,
                "gpu_batch": gui_settings.load().get("gpu_batch", 0)}
    events: "queue.Queue" = queue.Queue()
    engine = Engine(lambda jid, kind, data: events.put((jid, kind, data)), lambda: settings)
    engine.force_cpu = args.cpu
    t_start = time.time()
    engine.warm_up()

    videos, subs = expand([os.path.abspath(p) for p in args.paths])
    videos = [v for v in videos if v not in used]
    subs = [s for s in subs if s not in used]
    skipped = []
    found, unmatched = pair_languages(videos, subs)
    rows += [(v, s, want, ref) for v, s, ref in found]  # --sub-lang en/da wins; auto: from each name and text
    for v, s in unmatched:
        skipped.append({"video": v, "subtitle": s, "status": "skipped",
                        "reason": "no matching subtitle" if v else "no matching video"})

    out(f"SubSync {time.strftime('%Y-%m-%d %H:%M')}: {len(rows)} pair(s) to sync"
        + (f", {len(skipped)} file(s) without a partner" if skipped else ""))
    from subsync import language

    for n, (v, s, lang, ref) in enumerate(rows, 1):
        shown = lang or language.from_name(s)
        out(f"  {n:>3}. {os.path.basename(v)}  <-  {os.path.basename(s)}"
            + (f"  [{shown}" + (f", timed by {os.path.basename(ref)}" if ref else "") + "]" if shown == "da" else ""))
    for k in skipped:
        out(f"   skip {os.path.basename(k['video'] or k['subtitle'])}  ({k['reason']})")
    if not rows:
        out("Nothing to do: no video + subtitle pairs found.")
        engine.shutdown()
        write_report(args.report, [], skipped, EXIT_NOTHING, 0)
        return EXIT_NOTHING

    # ---------------------------------------------------------------- run
    jobs = {}
    for n, (v, s, lang, ref) in enumerate(rows, 1):
        jobs[n] = {"video": v, "subtitle": s, "status": "pending", "n": n, "sub_lang": lang, "reference": ref}
    speech = {}
    for n, j in jobs.items():
        engine.submit(n, j["video"], j["subtitle"], output, j["sub_lang"], j["reference"])

    tty = sys.stdout.isatty() and not args.progress  # no live status line between PROGRESS lines
    total = len(jobs)
    finished = 0
    current = {}
    last_line = ""
    shown = {}  # --progress: last (stage, percent) printed per item

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
                        speech.update(device="gpu" if data["device"] == "cuda" else "cpu", name=data.get("name") or None,
                                      model_load_seconds=data.get("load_s"))
                        log(f"speech model ready after {time.time() - t_start:.1f} s"
                            + (f" (worker {data['load_s']:.1f} s)" if data.get("load_s") is not None else ""))
                        clear_line()
                        if args.progress:
                            progress_line({"event": "device", "device": speech["device"], "name": speech["name"]})
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
                if args.progress:
                    shown[jid] = (stage_code(data), None)
                    progress_line({"event": "stage", "item": jid, "total": total, "stage": shown[jid][0],
                                   "percent": None})
            elif kind == "progress":
                n_, text, _ = current.get(jid, (jid, "", 0.0))
                current[jid] = (jid, text, float(data))
                if args.progress:
                    code = stage_code(text)
                    pct = max(0, min(100, int(float(data) * 100)))
                    if shown.get(jid) != (code, pct):
                        shown[jid] = (code, pct)
                        progress_line({"event": "stage", "item": jid, "total": total, "stage": code, "percent": pct})
            elif kind in ("done", "warning", "error", "cancelled"):
                current.pop(jid, None)
                finished += 1
                clear_line()
                tag = f"[{finished}/{total}]"
                name = os.path.basename(j["video"])
                if kind == "done":
                    from subsync.pipeline import tidy_summary

                    lo, hi = data["offsets"]
                    ends = sum(data["ends"][:2])
                    j.update(done_fields(data))
                    tm = j["timings"]
                    log(f"[{finished}/{total}] {name}: " + ("transcript from cache" if tm["from_cache"] else
                        f"read audio {tm['read_audio']} s, listen {tm['listen']} s")
                        + f", match {tm['match']} s, total {j['seconds']} s")
                    recut = tidy_summary(data.get("tidy") or {}).replace("→", "->")
                    out(f"OK   {tag} {name} -> {os.path.basename(data['out'])}  ({data['matched']}/{data['total']} lines matched, "
                        f"shift {lo:+.1f}..{hi:+.1f} s, {len(data['runs'])} section(s), {ends} ending(s) extended"
                        + (f", {recut}" if recut else "") + ")")
                elif kind == "warning":
                    j.update(status="no_match", reason=data["text"], audio_language=data.get("lang"),
                             subtitle_language=data.get("sub_lang"))
                    out(f"SKIP {tag} {name}: {data['text']}  (no file written)")
                else:
                    reason = data["text"] if isinstance(data, dict) else str(data)
                    j.update(status="failed" if kind == "error" else "cancelled", reason=reason)
                    out(f"FAIL {tag} {name}: {reason}")
                if args.progress:
                    progress_line({"event": "item_done", "item": jid, "total": total, "status": j["status"],
                                   "output": j.get("output")})
    except KeyboardInterrupt:
        clear_line()
        out("Stopped (Ctrl+C).")
        engine.shutdown()
        for j in jobs.values():
            if j["status"] == "pending":
                j["status"] = "cancelled"
        write_report(args.report, list(jobs.values()), skipped, EXIT_STOPPED, time.time() - t_start, speech)
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
    write_report(args.report, list(jobs.values()), skipped, code, time.time() - t_start, speech)
    return code


def write_report(path, items, skipped, code, seconds, speech=None):
    if not path:
        return
    rep = {
        "subsync_version": VERSION,
        "finished": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "exit_code": code,
        "seconds": round(seconds, 1),
        "summary": {s: sum(1 for i in items if i["status"] == s)
                    for s in ("synced", "no_match", "failed", "cancelled")} | {"skipped": len(skipped)},
        "speech_recognition": speech or None,
        "items": [{k: v for k, v in i.items() if k != "n"} for i in items] + skipped,
    }
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(rep, f, indent=2)
        out(f"Report: {os.path.abspath(path)}")
    except OSError as e:
        out(f"Could not write the report {path}: {e}")


# ---------------------------------------------------------------- detect
def detect(argv):
    """subsync-cli detect VIDEO: which language is spoken (README-CLI.md, "detect"). Read-only.
    Prints one JSON object on stdout (after PROGRESS lines with --progress)."""
    t_start = T_PROCESS
    p = Parser(prog="subsync-cli detect", add_help=False)
    p.add_argument("video")
    p.add_argument("--track", type=int, metavar="N")  # audio track number, 1 = first
    p.add_argument("--seconds", type=float, default=90.0)
    p.add_argument("--cpu", action="store_true")
    p.add_argument("--progress", action="store_true")
    args = p.parse_args(argv)
    if not 5 <= args.seconds <= 600:
        p.error("--seconds must be between 5 and 600")
    from subsync.media import VIDEO_EXTS

    video = os.path.abspath(args.video)
    if not os.path.isfile(video):
        p.error(f"video not found: {video}")
    if os.path.splitext(video)[1].lower() not in VIDEO_EXTS:
        p.error(f"not a supported video type: {video}")

    # the speech-model process must never get the caller's pipes (lesson 13 in CLAUDE.md)
    _, sys.stdout = _private_std_pipes()
    from subsync import detect as det

    def stage(code, frac=None):
        if args.progress:
            progress_line({"stage": code, "percent": None if frac is None else max(0, min(100, int(frac * 100)))})

    answer = {"video": video, "track": None, "audio_tracks": None, "track_language_tag": None,
              "language": None, "probability": None, "speech_seconds": 0.0, "device": None}

    def finish(code, **fields):
        answer.update(fields)
        answer.update(seconds=round(time.time() - t_start, 1), subsync_version=VERSION)
        log("detect: " + json.dumps(answer, ensure_ascii=False))
        sys.stdout.write(json.dumps(answer, ensure_ascii=True, separators=(",", ":")) + "\n")
        sys.stdout.flush()
        return code

    log(f"detect: {video} (track {args.track or 'auto'}, up to {args.seconds:g} s of speech, cpu {args.cpu})")
    try:
        import av
        from subsync.media import pick_audio_stream

        n, _, dur = pick_audio_stream(video)
        with av.open(video) as c:
            streams = list(c.streams.audio)
            if args.track is not None:
                if not 1 <= args.track <= len(streams):
                    print(f"Error: --track {args.track}: this video has {len(streams)} audio track(s)", file=sys.__stderr__)
                    log(f"usage error: --track {args.track} of {len(streams)}")
                    return EXIT_USAGE
                n = args.track - 1
                st = streams[n]
                if st.duration and st.time_base:
                    dur = dur or float(st.duration * st.time_base)
            tag = streams[n].metadata.get("language") or None
        answer.update(track=n + 1, audio_tracks=len(streams), track_language_tag=tag)
    except Exception as e:
        return finish(EXIT_UNREADABLE, reason=f"can't read the video: {e}" if "no audio" not in str(e) else "no audio track")

    # the speech model loads while the sample is read
    detector = det.Detector(args.cpu, log)
    try:
        stage("reading_audio", 0.0)
        t0 = time.time()
        try:
            pcs, speech_s, decoded = det.sample_speech(video, n, dur, args.seconds, lambda f: stage("reading_audio", f))
        except Exception as e:
            log(traceback.format_exc())
            return finish(EXIT_UNREADABLE, reason=f"can't read the audio: {e}")
        log(f"detect: read {decoded:.0f} s of audio, {speech_s:.1f} s with speech, in {time.time() - t0:.1f} s")
        answer["speech_seconds"] = speech_s
        if speech_s < det.MIN_SPEECH:
            return finish(EXIT_OK, reason="no speech found")
        stage("listening", 0.0)
        t1 = time.time()
        try:
            results = detector.run(pcs, lambda f: stage("listening", f), path=video, track=n + 1)
        except RuntimeError as e:
            log(f"detect: failed: {e}")
            print(f"Error: speech recognition failed: {e} (details in logs\\worker.log)", file=sys.__stderr__)
            return EXIT_INTERNAL
        lang, prob = det.combine(results)
        log(f"detect: language check {time.time() - t1:.1f} s")
        extra = {"gpu_problem": detector.gpu_problem} if detector.gpu_problem else {}
        return finish(EXIT_OK, language=lang, probability=prob, device=detector.device,
                      model_load_seconds=detector.load_s, **extra)
    finally:
        detector.stop()


# ---------------------------------------------------------------- serve
def _private_std_pipes():
    """Move the caller's stdin/stdout pipes off the standard handles, for `serve`. Returns the
    (requests, events) text streams to use instead of sys.stdin / sys.stdout.

    Why: on Windows every process started from here (the speech worker, at warm-up and on each
    restart) gets this process's standard handles. Python's start-up in the child queries its stdin,
    and on a synchronous pipe that call waits behind our own pending ReadFile, so the worker hung
    until the caller closed stdin. After this, fd 0/1, the Win32 STD_INPUT/OUTPUT handles and
    sys.stdin point at NUL, and only private, non-inheritable copies hold the caller's pipes.
    Streams that aren't the real fd 0/1 (tests swap sys.stdin/sys.stdout) are used as they are."""
    def real_fd(stream, fd):
        try:
            return stream is not None and stream.fileno() == fd
        except (AttributeError, OSError, ValueError):
            return False

    requests, events = sys.stdin, sys.stdout
    if real_fd(sys.stdin, 0):
        # UTF-8 as documented (the launcher runs Python with -X utf8 anyway); a bad byte must not
        # end the reader thread (that would hang serve), so it becomes U+FFFD
        requests = open(os.dup(0), "r", encoding="utf-8", errors="replace", newline=None)
        _point_std_at_nul(0, os.O_RDONLY, -10)  # STD_INPUT_HANDLE
        sys.stdin = open(os.devnull, "r", encoding="utf-8")
    if real_fd(sys.stdout, 1):
        sys.stdout.flush()
        # events are ASCII JSON; newline=None keeps the platform line ending, as sys.stdout had
        events = open(os.dup(1), "w", encoding="utf-8", newline=None)
        _point_std_at_nul(1, os.O_WRONLY, -11)  # STD_OUTPUT_HANDLE
    return requests, events


def _point_std_at_nul(fd, mode, std_handle):
    nul = os.open(os.devnull, mode)
    os.dup2(nul, fd)
    os.close(nul)
    if sys.platform == "win32":
        import ctypes
        import msvcrt

        from ctypes import wintypes

        set_std = ctypes.windll.kernel32.SetStdHandle
        set_std.argtypes, set_std.restype = (wintypes.DWORD, wintypes.HANDLE), wintypes.BOOL
        set_std(std_handle & 0xFFFFFFFF, msvcrt.get_osfhandle(fd))


def serve(argv):
    """subsync-cli serve: stay running for another program. Requests come in on stdin and
    events go out on stdout, one JSON object per line (README-CLI.md, "serve"). The models
    stay loaded between items and items overlap (the next one's audio is read while the
    current one is listened to). Ends after stdin is closed and every item is finished."""
    import threading

    from subsync import settings as gui_settings
    from subsync.media import VIDEO_EXTS
    from subsync.pipeline import Engine
    from subsync.subtitles import SUB_EXTS

    p = Parser(prog="subsync-cli serve", add_help=False)
    p.add_argument("--suffix", choices=["en", "eng", ".en", ".eng"], default="en")
    p.add_argument("--overwrite", action="store_true")
    p.add_argument("--keep-layout", action="store_true")
    p.add_argument("--cpu", action="store_true")
    args = p.parse_args(argv)

    # before any worker is started (warm-up below, and every restart later)
    requests, sys.stdout = _private_std_pipes()
    lock = threading.Lock()

    def emit(obj):
        with lock:
            sys.stdout.write(json.dumps(obj, ensure_ascii=True, separators=(",", ":")) + "\n")
            sys.stdout.flush()

    events: "queue.Queue" = queue.Queue()
    settings = {"suffix": "." + args.suffix.lstrip("."), "overwrite": args.overwrite, "tidy": not args.keep_layout,
                "gpu_batch": gui_settings.load().get("gpu_batch", 0)}
    engine = Engine(lambda jid, kind, data: events.put(("engine", jid, kind, data)), lambda: settings)
    engine.force_cpu = args.cpu
    engine.warm_up()

    def read_stdin():
        try:
            for line in requests or ():  # no stdin at all: nothing to read
                events.put(("line", line))
        except (OSError, ValueError) as e:  # a broken pipe counts as closed, or serve would wait forever
            log(f"serve: reading input failed: {e}")
        finally:
            events.put(("eof",))

    threading.Thread(target=read_stdin, daemon=True).start()
    log(f"serve: ready (suffix {settings['suffix']}, overwrite {args.overwrite}, tidy {settings['tidy']}, cpu {args.cpu})")
    emit({"event": "ready", "subsync_version": VERSION})

    pending = {}   # engine job number -> request (id, video, subtitle, output, t0)
    shown = {}     # job number -> (stage, percent) last emitted
    stage_of = {}  # job number -> current stage code
    next_n = 0
    stdin_open = True

    def result(req, **fields):
        emit({"event": "result", "id": req["id"], "video": req.get("video"), "subtitle": req.get("subtitle")} | fields)

    def check(req):
        """Reason a request can't run, or None."""
        for key, kind, exts in (("video", "video", VIDEO_EXTS), ("subtitle", "subtitle", SUB_EXTS)):
            f = req.get(key)
            if not isinstance(f, str) or not f:
                return f"missing \"{key}\""
            if not os.path.isfile(f):
                return f"{kind} not found: {f}"
            if os.path.splitext(f)[1].lower() not in exts:
                return f"{kind} has an unsupported type: {f}"
        lang = req.get("subtitle_language", "auto")
        if lang not in ("auto", "en", "da", None):
            return "\"subtitle_language\" must be \"auto\", \"en\" or \"da\""
        ref = req.get("reference")
        if ref is not None:
            if not isinstance(ref, str) or not os.path.isfile(ref):
                return f"reference not found: {ref}"
            if os.path.splitext(ref)[1].lower() not in SUB_EXTS:
                return f"reference has an unsupported type: {ref}"
        o = req.get("output")
        if o is not None:
            if not isinstance(o, str) or os.path.splitext(o)[1].lower() != ".srt":
                return "\"output\" must be a .srt file"
            if not os.path.isdir(os.path.dirname(o)):
                return f"output folder not found: {os.path.dirname(o)}"
            if os.path.exists(o) and not args.overwrite:
                return f"output exists: {o} (start serve with --overwrite to replace files)"
        if any(r["id"] == req["id"] for r in pending.values()):
            return f"id {req['id']!r} is already in progress"
        # no two items in progress may write the same file, or write another one's subtitle
        mine = target(req)
        for r in pending.values():
            theirs = target(r)
            if mine and mine in (theirs, same(r["subtitle"])):
                return f"another item in progress ({r['id']!r}) uses {mine}"
            if theirs and theirs == same(req["subtitle"]):
                return f"another item in progress ({r['id']!r}) writes this subtitle"
        return None

    def same(path):
        return os.path.normcase(os.path.abspath(path))

    def target(req):
        """The file this request will write, when it is known in advance."""
        if req.get("output"):
            return same(req["output"])
        if args.overwrite:  # otherwise a free <stem>.en.#n.srt name is picked when writing
            from subsync import language
            from subsync.pipeline import output_path

            if "sub_lang" not in req:  # the result is named after the subtitle's language
                want = req.get("subtitle_language")
                try:
                    from subsync.subtitles import load

                    req["sub_lang"] = language.resolve(req["subtitle"], [] if want in ("en", "da") else load(req["subtitle"]), want)
                except Exception:
                    req["sub_lang"] = language.resolve(req["subtitle"], [], want)
            return same(output_path(req["video"], language.suffix(req["sub_lang"], settings["suffix"]), True))
        return None

    while stdin_open or pending:
        ev = events.get()
        if ev[0] == "eof":
            stdin_open = False
            log("serve: input closed")
            continue
        if ev[0] == "line":
            line = ev[1].strip().lstrip("\ufeff")
            if not line:
                continue
            try:
                req = json.loads(line)
                if not isinstance(req, dict):
                    raise ValueError("not a JSON object")
            except ValueError as e:
                log(f"serve: bad request line: {line[:300]}")
                emit({"event": "result", "id": None, "status": "failed", "reason": f"not a valid request: {e}"})
                continue
            next_n += 1
            if req.get("id") is None:
                req["id"] = f"auto-{next_n}"
            for key in ("video", "subtitle", "output", "reference"):
                if isinstance(req.get(key), str):
                    req[key] = os.path.abspath(req[key])
            problem = check(req)
            if problem:
                log(f"serve: request {req['id']!r} refused: {problem}")
                result(req, status="failed", reason=problem)
                continue
            req["t0"] = time.time()
            pending[next_n] = req
            log(f"serve: [#{next_n}] {os.path.basename(req['video'])} <- {os.path.basename(req['subtitle'])}")
            want = req.get("subtitle_language")
            engine.submit(next_n, req["video"], req["subtitle"], req.get("output"),
                          req.get("sub_lang") or (want if want in ("en", "da") else None), req.get("reference"))
            continue

        _, jid, kind, data = ev
        if jid is None:
            if kind == "device":
                st = data.get("state")
                if st == "ready":
                    dev = "gpu" if data["device"] == "cuda" else "cpu"
                    log(f"serve: speech recognition {dev} {data.get('name') or ''}".rstrip()
                        + (f", loaded in {data['load_s']:.1f} s" if data.get("load_s") is not None else ""))
                    emit({"event": "device", "device": dev, "name": data.get("name") or None,
                          "model_load_seconds": data.get("load_s")})
                elif st == "error":
                    log("serve: " + data.get("text", "speech recognition problem"))
                    if data.get("detail"):
                        log(data["detail"])
                    emit({"event": "warning", "text": data.get("text", "speech recognition problem")})
            elif kind == "batch":
                gui_settings.update(gpu_batch=int(data))
            continue
        req = pending.get(jid)
        if req is None:
            continue
        if kind == "stage":
            stage_of[jid] = stage_code(data)
            shown[jid] = (stage_of[jid], None)
            log(f"serve: [#{jid}] {os.path.basename(req['video'])}: {data}")
            emit({"event": "stage", "id": req["id"], "stage": stage_of[jid], "percent": None})
        elif kind == "progress":
            code = stage_of.get(jid, "working")
            pct = max(0, min(100, int(float(data) * 100)))
            if shown.get(jid) != (code, pct):
                shown[jid] = (code, pct)
                emit({"event": "stage", "id": req["id"], "stage": code, "percent": pct})
        elif kind in ("done", "warning", "error", "cancelled"):
            del pending[jid]
            shown.pop(jid, None)
            stage_of.pop(jid, None)
            name = os.path.basename(req["video"])
            if kind == "done":
                f = done_fields(data)
                tm = f["timings"]
                log(f"serve: [#{jid}] {name}: synced -> {f['output']} ({f['lines_matched']}/{f['lines_with_speech']} lines; "
                    + ("transcript from cache" if tm["from_cache"] else
                       f"read audio {tm['read_audio']} s, listen {tm['listen']} s")
                    + f", match {tm['match']} s, total {f['seconds']} s)")
                result(req, **f)
            elif kind == "warning":
                log(f"serve: [#{jid}] {name}: no match: {data['text']}")
                result(req, status="no_match", reason=data["text"], audio_language=data.get("lang"),
                       subtitle_language=data.get("sub_lang"))
            else:
                reason = data["text"] if isinstance(data, dict) else str(data)
                log(f"serve: [#{jid}] {name}: {kind}: {reason}")
                result(req, status="failed" if kind == "error" else "cancelled", reason=reason)
    engine.shutdown()
    log("serve: finished")
    return EXIT_OK


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
    run = main
    if argv and argv[0] == "serve":
        run, argv = serve, argv[1:]
    elif argv and argv[0] == "detect":
        run, argv = detect, argv[1:]
    elif argv and argv[0] == "sync":
        argv = argv[1:]
    code = EXIT_INTERNAL
    try:
        code = run(argv)
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

"""Job orchestration.

  main process:   probe -> (cache?) ------------------------> match + write
  worker process:          decode+VAD (N+1)  ||  GPU transcribe (N)

Three things run at once for a season: audio of the next episode is decoded,
the current one is transcribed on the GPU, and the previous one is matched and
written.  Transcripts are cached, so re-running a file is nearly instant.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import multiprocessing as mp
import os
import queue
import sys
import threading
import time
import traceback
from dataclasses import dataclass, field

from . import paths

CACHE_VERSION = "v1-turbo"


def output_path(video: str, suffix: str, overwrite: bool) -> str:
    folder = os.path.dirname(video)
    stem = os.path.splitext(os.path.basename(video))[0]
    target = os.path.join(folder, f"{stem}{suffix}.srt")
    if overwrite or not os.path.exists(target):
        return target
    n = 1
    while os.path.exists(os.path.join(folder, f"{stem}{suffix}.#{n}.srt")):
        n += 1
    return os.path.join(folder, f"{stem}{suffix}.#{n}.srt")


@dataclass
class Processed:
    res: object                 # align.Result (rough placement; .ok / .reason as before)
    lines: list                 # what gets written
    stats: dict = field(default_factory=dict)
    details: list = field(default_factory=list)


def _from_reference(lines, reference, words, lang, embed, sub_lang, progress):
    """Time a subtitle in another language by an English subtitle of the same video (1.5.0):
    the English one is synced first (word-accurate on English audio), then each line is matched
    to the English line(s) saying the same thing (multilingual embeddings) and takes their
    timing. None if the English one can't be synced or too few lines match."""
    from .align import Phrase, align
    from .subtitles import Line, speech_text

    rp = process([Line(l.start, l.end, l.text) for l in reference], words, lang, embed, tidy=False,
                 progress=lambda f: progress(0.5 * f))
    if not rp.res.ok or len(rp.lines) != len(reference):
        return None
    phrases = [Phrase(n.start, n.end, speech_text(o.text)) for o, n in zip(reference, rp.lines) if speech_text(o.text)]
    res = align(lines, words, "en", embed, sub_lang, progress=lambda f: progress(0.5 + 0.5 * f), phrases=phrases)
    return res if res.ok else None


def process(lines, words, lang, embed, tidy: bool, progress=lambda f: None,
            sub_lang: str = "en", reference=None) -> Processed:
    """Rough alignment; then, for an English subtitle on English audio, word-accurate timing and
    (tidy) re-cutting; otherwise (tidy) only cues taller than two rows are split.
    sub_lang (1.5.0): the subtitle's language. A non-English subtitle is timed by `reference`
    (the lines of an English subtitle of the same video) when given and usable, otherwise by
    the audio (the same phrase-level matching as for English subtitles on other-language audio)."""
    from . import reshape as R
    from . import words as W
    from .align import align, keep_visible

    seen = [0.0]
    report = progress

    def progress(f):  # never backwards, also when the reference fails and the audio is used
        seen[0] = max(seen[0], f)
        report(seen[0])

    timing_from = "audio"
    res = None
    if sub_lang != "en" and reference:
        res = _from_reference(lines, reference, words, lang, embed, sub_lang, progress)
        if res is not None:
            timing_from = "reference"
    if res is None:
        res = align(lines, words, lang, embed, sub_lang, progress=progress)
    stats = {"tidy": bool(tidy), "word_timed": 0, "subtitles_before": len(lines), "subtitles_after": len(lines),
             "joined": 0, "split": 0, "capitals_fixed": 0, "sub_lang": sub_lang, "timing_from": timing_from}
    if not res.ok:
        return Processed(res, lines, stats, [])
    english = (lang or "").split("-")[0] == "en" and sub_lang == "en"  # word matching: same language
    counts: dict = {}
    timed: set = set()
    if english:
        toks = W.tokenize(lines)
        _, match = W.match_words(toks, words, res.lines)
        counts = _count_words(toks)
        if tidy:
            out, speech_end, st = R.reshape(lines, res.lines, toks, words, match)
            sources = st.pop("from_cues")
            stats.update(st)
            timed = set(speech_end)
        else:
            out, _, stats["word_timed"] = W.refine(lines, res.lines, toks)
            sources = [[k] for k in range(len(lines))]
            timed = {k for k in range(len(out)) if abs(out[k].start - res.lines[k].start) > 0.005}
    elif tidy:
        out, stats["split"] = R.split_tall(res.lines)
        sources = []
        for k, l in enumerate(res.lines):
            sources += [[k]] * max(1, (len(l.text.split("\n")) + 1) // 2)
    else:
        out, sources = res.lines, [[k] for k in range(len(lines))]
    if english and tidy:
        stats["word_timed"] = len(timed)
    # nothing may end up too short to be seen (it would look like a dropped line)
    out, groups, vis = keep_visible(out, join=tidy)  # Tidy up lines off: one result line per original line
    sources = [list(dict.fromkeys(c for g in grp for c in sources[g])) for grp in groups]
    timed = {n for n, grp in enumerate(groups) if any(g in timed for g in grp)}
    stats["kept_visible"] = sum(vis.values())
    stats["subtitles_after"] = len(out)
    used: dict = {}
    for src in sources:
        for c in src:
            used[c] = used.get(c, 0) + 1
    det = []
    for k, (n, src) in enumerate(zip(out, sources)):
        o = lines[src[0]]
        total = sum(counts.get(c, (0, 0))[0] for c in src)
        matched = sum(counts.get(c, (0, 0))[1] for c in src)
        changes = []
        if len(src) > 1:
            changes.append("joined " + "+".join(str(c + 1) for c in src))
        elif used.get(src[0], 0) > 1:
            changes.append(f"split from {src[0] + 1}")
        if k in timed:
            changes.append("start from words")
        if abs(n.start - o.start) > 0.005:
            changes.append(f"start {n.start - o.start:+.2f}")
        if len(src) == 1 and used.get(src[0], 0) == 1 and abs((n.end - n.start) - (o.end - o.start)) > 0.005:
            changes.append(f"length {(n.end - n.start) - (o.end - o.start):+.2f}")
        if n.text != o.text and len(src) == 1 and used.get(src[0], 0) == 1:
            changes.append("text re-wrapped or capitals fixed")
        det.append({"n": k + 1, "from_cues": [c + 1 for c in src], "orig_start": o.start, "start": n.start,
                    "end": n.end, "words": total, "matched": matched, "changes": changes})
    return Processed(res, out, stats, det)


def tidy_summary(stats: dict) -> str:
    """Short result text, e.g. "808 → 820 subtitles" (empty when the count did not change)."""
    a, b = stats.get("subtitles_before"), stats.get("subtitles_after")
    return f"{a} → {b} subtitles" if a is not None and b is not None and a != b else ""


def tidy_details(stats: dict) -> str:
    """Hover/detail lines about word timing and Tidy up lines."""
    if not stats:
        return ""
    lines = [f"Timed from words: {stats.get('word_timed', 0)}"]
    if not stats.get("tidy"):
        return "\n".join(lines + ["Tidy up lines: off"])
    return "\n".join(lines + [f"Subtitles: {stats.get('subtitles_before')} → {stats.get('subtitles_after')}",
                              f"Joined: {stats.get('joined', 0)}", f"Split: {stats.get('split', 0)}",
                              f"Capitals fixed: {stats.get('capitals_fixed', 0)}"])


def _count_words(toks) -> dict:
    out: dict = {}
    for t in toks:
        if t.kind == "word":
            a, b = out.get(t.cue, (0, 0))
            out[t.cue] = (a + 1, b + (1 if t.matched else 0))
    return out


def _cache_file(video: str, audio_n: int) -> str:
    st = os.stat(video)
    key = f"{os.path.abspath(video).lower()}|{st.st_size}|{st.st_mtime_ns}|{audio_n}|{CACHE_VERSION}"
    return os.path.join(paths.CACHE, "transcripts", hashlib.sha1(key.encode()).hexdigest() + ".json.gz")


class Engine:
    def __init__(self, emit, get_settings):
        """emit(job_id, kind, payload) is called from background threads."""
        self.emit = emit
        self.get_settings = get_settings
        self.ctx = mp.get_context("spawn")
        self.proc = None
        self.inflight: dict[int, dict] = {}
        self.align_q: "queue.Queue" = queue.Queue()
        self.force_cpu = False
        self.device_info = None
        self._embedder = None
        self._embed_lock = threading.Lock()
        self._lock = threading.Lock()
        self._gen = 0
        self.submit_q: "queue.Queue" = queue.Queue()
        self._dropped: set[int] = set()
        self._waiting: dict[str, list[dict]] = {}  # transcript cache file -> jobs waiting for it
        threading.Thread(target=self._align_loop, daemon=True).start()
        threading.Thread(target=self._submit_loop, daemon=True).start()

    # ------------------------------------------------------------ worker
    def warm_up(self):
        with self._lock:
            if self.proc is None or not self.proc.is_alive():
                self._spawn()
        if self._embedder is None:
            # the line-matching model loads while the speech model does, not after the first episode is heard
            threading.Thread(target=self._warm_embedder, daemon=True).start()

    def _warm_embedder(self):
        try:
            self._get_embedder()
        except Exception:
            traceback.print_exc()  # the align thread tries again and reports the error on its job

    def _get_embedder(self):
        with self._embed_lock:
            if self._embedder is None:
                from .embed import Embedder

                self._embedder = Embedder(paths.MINILM_DIR)
            return self._embedder

    def _spawn(self):
        self._gen += 1
        self.req_q = self.ctx.Queue()
        self.res_q = self.ctx.Queue()
        self.cancel_ev = self.ctx.Event()
        hint = int(self.get_settings().get("gpu_batch", 0) or 0)
        from .asr_worker import worker_main

        self.proc = self.ctx.Process(target=worker_main, daemon=True,
                                     args=(self.req_q, self.res_q, self.cancel_ev, self.force_cpu, hint))
        self.proc.start()
        threading.Thread(target=self._read_loop, args=(self._gen, self.proc, self.res_q), daemon=True).start()
        self.emit(None, "device", {"state": "loading"})

    def _read_loop(self, gen, proc, res_q):
        while True:
            try:
                msg = res_q.get(timeout=1.0)
            except queue.Empty:
                if gen != self._gen:
                    return
                if not proc.is_alive():
                    self._worker_died(gen, proc.exitcode)
                    return
                continue
            if gen != self._gen:
                return
            self._handle(msg)

    def _worker_died(self, gen, code):
        if gen != self._gen:
            return
        if not self.force_cpu:
            # GPU path crashed (driver/cuDNN issue): fall back to CPU and retry
            self.force_cpu = True
            self.emit(None, "device", {"state": "error",
                                       "text": f"GPU worker stopped (code {code}) – switched to CPU (slower)"})
            self._respawn_and_resend()
        else:
            for jid in list(self.inflight) + self._drain_waiting():
                self.emit(jid, "error", "Speech recognition stopped unexpectedly")
            self.inflight.clear()

    def _drain_waiting(self) -> list[int]:
        """Job numbers of every job waiting for another one's transcript; forgets them."""
        out = [w["id"] for ws in self._waiting.values() for w in ws]
        self._waiting.clear()
        return out

    def _respawn_and_resend(self):
        """Start a fresh (CPU) worker and hand it every job the old one had. One locked step, so a
        job submitted meanwhile can't go to a worker that is about to be replaced and be lost."""
        with self._lock:
            jobs = list(self.inflight.values())
            self.inflight.clear()
            self._spawn()
            for j in jobs:
                self._send(j)

    def _handle(self, msg):
        kind = msg[0]
        if kind == "device":
            _, device, name, batch, dll_errors, *rest = msg
            self.device_info = (device, name, batch)
            self.emit(None, "device", {"state": "ready", "device": device, "name": name, "batch": batch,
                                       "dll_errors": dll_errors, "load_s": rest[0] if rest else None})
        elif kind == "fatal":
            if not self.force_cpu:
                self.force_cpu = True
                self.emit(None, "device", {"state": "error", "text": "GPU could not start – using CPU (slower)",
                                           "detail": msg[1]})
                self._respawn_and_resend()
            else:
                self.emit(None, "device", {"state": "error", "text": "Speech recognition could not start",
                                           "detail": msg[1]})
                for jid in list(self.inflight) + self._drain_waiting():
                    self.emit(jid, "error", "Speech recognition could not start (see logs folder)")
                self.inflight.clear()
        elif kind == "batch":
            self.emit(None, "batch", msg[1])
        elif kind == "stage":
            self.emit(msg[1], "stage", msg[2])
        elif kind == "progress":
            self.emit(msg[1], "progress", msg[2])
        elif kind == "error":
            job = self.inflight.pop(msg[1], None)
            if job is not None:
                self.emit(msg[1], "cancelled" if msg[2] == "cancelled" else "error", msg[2])
                waiting = self._waiting.pop(job["cache"], [])
                if msg[2] == "cancelled":
                    for w in waiting:
                        self.emit(w["id"], "cancelled", "cancelled")
                elif waiting:  # let the next one try for itself (it may give a clearer error)
                    with self._lock:
                        self._send(waiting[0])
                        self._waiting[waiting[0]["cache"]] = waiting[1:]
        elif kind == "result":
            _, jid, words, lang, dur, stats = msg
            job = self.inflight.pop(jid, None)
            if job is None:
                return
            try:
                os.makedirs(os.path.dirname(job["cache"]), exist_ok=True)
                tmp = job["cache"] + f".{os.getpid()}.tmp"
                with gzip.open(tmp, "wt", encoding="utf-8") as f:
                    json.dump({"words": words, "lang": lang, "dur": dur}, f)
                os.replace(tmp, job["cache"])  # never a half-written cache file for another job to read
            except OSError:
                pass
            job["stats"] = stats
            self.align_q.put((job, words, lang))
            # other subtitles of the same video (an English and a Danish one) use this transcript
            for w in self._waiting.pop(job["cache"], []):
                w["stats"] = {"cached": True}
                self.align_q.put((w, [tuple(x) for x in words], lang))

    def _send(self, job):
        self.inflight[job["id"]] = job
        self.req_q.put({"id": job["id"], "path": job["video"], "audio_n": job["audio_n"], "lang": job["lang"]})

    # ------------------------------------------------------------ public
    def submit(self, jid: int, video: str, sub: str, out: str | None = None,
               sub_lang: str | None = None, reference: str | None = None):
        """out: write the result exactly there (replacing a file that exists) instead of next to the video.
        sub_lang: the subtitle's language ('en' / 'da'; None = from its name or text).
        reference: an English subtitle of the same video, to time a Danish one by (1.5.0)."""
        self.emit(jid, "stage", "Queued")
        self.submit_q.put((jid, video, sub, out, {"sub_lang": sub_lang, "reference": reference}))

    def _submit_loop(self):
        while True:
            jid, video, sub, out, opts = self.submit_q.get()
            if jid in self._dropped:
                continue
            self._submit(jid, video, sub, out, opts)

    def _submit(self, jid, video, sub, out=None, opts=None):
        try:
            from .media import pick_audio_stream

            audio_n, lang, dur = pick_audio_stream(video)
            job = {"id": jid, "video": video, "sub": sub, "out": out, "audio_n": audio_n, "lang": lang,
                   "cache": _cache_file(video, audio_n), "t0": time.time(), "dur": dur, **(opts or {})}
            if os.path.exists(job["cache"]):
                try:
                    with gzip.open(job["cache"], "rt", encoding="utf-8") as f:
                        c = json.load(f)
                    job["stats"] = {"cached": True}
                    self.align_q.put((job, [tuple(w) for w in c["words"]], c["lang"]))
                    return
                except Exception:
                    pass
            with self._lock:
                if any(j["cache"] == job["cache"] for j in self.inflight.values()):
                    # this video is being listened to for another subtitle: wait for its transcript
                    self._waiting.setdefault(job["cache"], []).append(job)
                    return
                if self.proc is None or not self.proc.is_alive():
                    self._spawn()
                self._send(job)
        except Exception as e:
            self.emit(jid, "error", f"Could not open video: {e}")

    def stop(self):
        """Cancel everything: kill the worker (frees the GPU at once) and start a fresh one."""
        jobs = list(self.inflight) + self._drain_waiting()
        self.inflight.clear()
        while True:
            try:
                jobs.append(self.submit_q.get_nowait()[0])
            except queue.Empty:
                break
        with self._lock:
            self._gen += 1
            proc, self.proc = self.proc, None
        if proc is not None and proc.is_alive():
            proc.terminate()
            proc.join(3)
            if proc.is_alive():
                proc.kill()
        while True:
            try:
                job, *_ = self.align_q.get_nowait()
                jobs.append(job["id"])
            except queue.Empty:
                break
        for jid in jobs:
            self.emit(jid, "cancelled", "Stopped")
        self.warm_up()

    def shutdown(self):
        with self._lock:
            self._gen += 1
            proc, self.proc = self.proc, None
        if proc is not None and proc.is_alive():
            proc.terminate()
            proc.join(3)
            if proc.is_alive():
                proc.kill()
                proc.join(2)

    # ------------------------------------------------------------ matching
    def _align_loop(self):
        while True:
            job, words, lang = self.align_q.get()
            jid = job["id"]
            try:
                self.emit(jid, "stage", "Matching lines…")
                embedder = self._get_embedder()
                from . import details, subtitles

                from . import language

                lines = subtitles.load(job["sub"])
                sub_lang = language.resolve(job["sub"], lines, job.get("sub_lang"))
                ref = None
                if sub_lang != "en" and job.get("reference"):
                    try:
                        ref = subtitles.load(job["reference"])
                        if language.resolve(job["reference"], ref) != "en":  # only an English one can time it
                            print(f"reference subtitle is not English, timing from the audio: {job['reference']}", file=sys.stderr)
                            ref = None
                    except Exception as e:  # time it from the audio instead
                        print(f"reference subtitle not readable, timing from the audio: {e}", file=sys.stderr)
                t0 = time.time()
                s = self.get_settings()
                p = process(lines, words, lang, embedder, bool(s.get("tidy", True)),
                            progress=lambda f: self.emit(jid, "progress", f), sub_lang=sub_lang, reference=ref)
                res = p.res
                if not res.ok:
                    self.emit(jid, "warning", {"text": res.reason, "lang": lang, "sub_lang": sub_lang})
                    continue
                out = job.get("out") or output_path(job["video"], language.suffix(sub_lang, s.get("suffix", ".en")),
                                                    bool(s.get("overwrite", False)))
                self._write(jid, out, subtitles.to_srt(p.lines))
                try:
                    details.write(job["video"], p.details, sub_lang)
                except OSError:
                    pass
                self.emit(jid, "done", {
                    "tidy": p.stats,
                    "out": out, "matched": res.matched, "total": res.total_speech, "lang": lang,
                    "sub_lang": sub_lang, "timing_from": p.stats.get("timing_from", "audio"),
                    "reference": job.get("reference") if p.stats.get("timing_from") == "reference" else None,
                    "ends": (res.ends_speech, res.ends_read, res.ends_limited),
                    "runs": res.runs, "offsets": (min(res.offsets), max(res.offsets)) if res.offsets else (0, 0),
                    "seconds": time.time() - job["t0"], "align_s": time.time() - t0,
                    "stats": job.get("stats", {}), "dur": job.get("dur", 0)})
            except Exception as e:
                traceback.print_exc()
                self.emit(jid, "error", f"{type(e).__name__}: {e}")

    def _write(self, jid, out, text):
        tmp = out + ".subsync-tmp"
        with open(tmp, "w", encoding="utf-8", newline="") as f:
            f.write(text)
        waited = 0.0
        while True:
            try:
                os.replace(tmp, out)
                return
            except PermissionError:
                # the existing file is open somewhere (player, Jellyfin scan...) – wait for it
                if waited == 0:
                    self.emit(jid, "stage", "Waiting for the existing subtitle to be released…")
                if waited > 300:
                    os.remove(tmp)
                    raise RuntimeError("Existing subtitle file stayed locked by another program for 5 minutes")
                time.sleep(1.0)
                waited += 1.0

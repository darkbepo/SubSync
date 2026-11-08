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
import threading
import time
import traceback

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
        self._lock = threading.Lock()
        self._gen = 0
        self.submit_q: "queue.Queue" = queue.Queue()
        self._dropped: set[int] = set()
        threading.Thread(target=self._align_loop, daemon=True).start()
        threading.Thread(target=self._submit_loop, daemon=True).start()

    # ------------------------------------------------------------ worker
    def warm_up(self):
        with self._lock:
            if self.proc is None or not self.proc.is_alive():
                self._spawn()

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
            jobs = list(self.inflight.values())
            self.inflight.clear()
            with self._lock:
                self._spawn()
            for j in jobs:
                self._send(j)
        else:
            for jid in list(self.inflight):
                self.emit(jid, "error", "Speech recognition stopped unexpectedly")
            self.inflight.clear()

    def _handle(self, msg):
        kind = msg[0]
        if kind == "device":
            _, device, name, batch, dll_errors = msg
            self.device_info = (device, name, batch)
            self.emit(None, "device", {"state": "ready", "device": device, "name": name, "batch": batch,
                                       "dll_errors": dll_errors})
        elif kind == "fatal":
            if not self.force_cpu:
                self.force_cpu = True
                self.emit(None, "device", {"state": "error", "text": "GPU could not start – using CPU (slower)",
                                           "detail": msg[1]})
                jobs = list(self.inflight.values())
                self.inflight.clear()
                with self._lock:
                    self._spawn()
                for j in jobs:
                    self._send(j)
            else:
                self.emit(None, "device", {"state": "error", "text": "Speech recognition could not start",
                                           "detail": msg[1]})
                for jid in list(self.inflight):
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
        elif kind == "result":
            _, jid, words, lang, dur, stats = msg
            job = self.inflight.pop(jid, None)
            if job is None:
                return
            try:
                os.makedirs(os.path.dirname(job["cache"]), exist_ok=True)
                with gzip.open(job["cache"], "wt", encoding="utf-8") as f:
                    json.dump({"words": words, "lang": lang, "dur": dur}, f)
            except OSError:
                pass
            job["stats"] = stats
            self.align_q.put((job, words, lang))

    def _send(self, job):
        self.inflight[job["id"]] = job
        self.req_q.put({"id": job["id"], "path": job["video"], "audio_n": job["audio_n"], "lang": job["lang"]})

    # ------------------------------------------------------------ public
    def submit(self, jid: int, video: str, sub: str):
        self.emit(jid, "stage", "Queued")
        self.submit_q.put((jid, video, sub))

    def _submit_loop(self):
        while True:
            jid, video, sub = self.submit_q.get()
            if jid in self._dropped:
                continue
            self._submit(jid, video, sub)

    def _submit(self, jid, video, sub):
        try:
            from .media import pick_audio_stream

            audio_n, lang, dur = pick_audio_stream(video)
            job = {"id": jid, "video": video, "sub": sub, "audio_n": audio_n, "lang": lang,
                   "cache": _cache_file(video, audio_n), "t0": time.time(), "dur": dur}
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
                if self.proc is None or not self.proc.is_alive():
                    self._spawn()
                self._send(job)
        except Exception as e:
            self.emit(jid, "error", f"Could not open video: {e}")

    def stop(self):
        """Cancel everything: kill the worker (frees the GPU at once) and start a fresh one."""
        jobs = list(self.inflight)
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
                if self._embedder is None:
                    from .embed import Embedder

                    self._embedder = Embedder(paths.MINILM_DIR)
                from . import subtitles
                from .align import align

                lines = subtitles.load(job["sub"])
                t0 = time.time()
                res = align(lines, words, lang, self._embedder, "en",
                            progress=lambda f: self.emit(jid, "progress", f))
                if not res.ok:
                    self.emit(jid, "warning", {"text": res.reason, "lang": lang})
                    continue
                s = self.get_settings()
                out = output_path(job["video"], s.get("suffix", ".en"), bool(s.get("overwrite", False)))
                self._write(jid, out, subtitles.to_srt(res.lines))
                self.emit(jid, "done", {
                    "out": out, "matched": res.matched, "total": res.total_speech, "lang": lang,
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

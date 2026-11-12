"""`subsync-cli detect`: which language is spoken in a video, from a short sample.

Read-only and quick: a few 30 s windows spread over the video are decoded (the first 5 % is
skipped for intros and logos), only the parts with voice are kept, and Whisper's language
detection runs on at most `seconds` of that speech. No transcription, no matching, nothing
written next to the video or into the transcript cache.

The speech model runs in its own process (as in sync), so a GPU/driver crash or a GPU that is
full (for example while `serve` uses it) falls back to the CPU instead of failing.
"""
from __future__ import annotations

import os
import time
import traceback

import numpy as np

SR = 16000
WINDOW = 30.0        # seconds decoded per window
MAX_WINDOWS = 10     # at most 5 minutes of audio is decoded
WHOLE_FILE = 330.0   # shorter videos are decoded completely
MIN_SPEECH = 3.0     # less speech than this is "no speech found"
PIECE = 30.0         # Whisper looks at 30 s at a time
LOAD_LIMIT = 300.0   # seconds the speech process may take to load the model ...
PIECE_LIMIT = 60.0   # ... plus this per 30 s piece, before detect gives up on it


def window_starts(dur: float, n: int = MAX_WINDOWS) -> list[float]:
    """Start times of up to n windows between 5 % and 95 % of the video, in the order they are
    read: spread out first (1/2, 1/4, 3/4, 1/8, ...), so any first few cover the whole video."""
    lo = 0.05 * dur
    span = max(0.0, 0.95 * dur - WINDOW - lo)
    order, k = [], 2
    while len(order) < n * 4 and k <= 1024:
        for j in range(1, k, 2):
            order.append(j / k)
        k *= 2
    starts = []
    for f in order:
        t = round(lo + f * span, 2)
        if all(abs(t - u) >= WINDOW for u in starts):
            starts.append(t)
        if len(starts) == n:
            break
    return starts or [round(lo, 2)]


def speech_regions(audio: np.ndarray) -> list[tuple[int, int]]:
    """(start, end) sample ranges with voice (Silero VAD, as sync uses)."""
    from faster_whisper.vad import VadOptions, get_speech_timestamps

    opts = VadOptions(max_speech_duration_s=29.5, min_silence_duration_ms=160)
    return [(s["start"], s["end"]) for s in get_speech_timestamps(audio, opts)]


def sample_speech(path: str, audio_n: int, dur: float, seconds: float, progress=lambda f: None):
    """Up to `seconds` of speech from the video, as a list of <= 30 s pieces (float32 16 kHz)
    for language detection, plus the seconds of speech found and of audio decoded."""
    from .media import SeekError, decode, decode_window

    speech: list[np.ndarray] = []
    have = 0.0
    decoded = 0.0

    def take(audio):
        nonlocal have
        for a, b in speech_regions(audio):
            if have >= seconds:
                return
            part = audio[a:b][: int((seconds - have) * SR)]
            speech.append(part)
            have += len(part) / SR

    if dur and dur <= WHOLE_FILE:
        audio = decode(path, audio_n)
        decoded = len(audio) / SR
        if dur > 60:  # skip the intro, as for long videos
            audio = audio[int(0.05 * dur * SR):]
        progress(1.0)
        take(audio)
    else:
        starts = window_starts(dur) if dur else []
        try:
            for k, t in enumerate(starts):
                audio = decode_window(path, audio_n, t, WINDOW, must_seek=True)
                decoded += len(audio) / SR
                take(audio)
                progress((k + 1) / len(starts) if have < seconds else 1.0)
                if have >= seconds:
                    break
        except SeekError:
            starts = []  # this file can't be jumped into: one read through a stretch of it instead
        if not starts:
            # unknown length, or no jumping: 5 minutes of audio in one pass (after the intro when
            # the length is known), never the whole file
            audio = decode_window(path, audio_n, 0.05 * dur if dur else 0.0, MAX_WINDOWS * WINDOW)
            decoded += len(audio) / SR
            take(audio)
            progress(1.0)
    return pieces(speech), round(have, 1), round(decoded, 1)


def pieces(speech: list[np.ndarray]) -> list[np.ndarray]:
    """Join speech regions into pieces of at most 30 s (one Whisper window each)."""
    out, cur, n = [], [], 0
    lim = int(PIECE * SR)
    for part in speech:
        while len(part):
            room = lim - n
            cur.append(part[:room])
            n += len(cur[-1])
            part = part[room:]
            if n >= lim:
                out.append(np.concatenate(cur)); cur, n = [], 0
    if n:
        out.append(np.concatenate(cur))
    return out


def combine(results: list[tuple[float, list[tuple[str, float]]]]):
    """Per piece (speech seconds, [(language, probability), ...]) -> (language, probability):
    each language's probability averaged over the pieces, weighted by their speech."""
    total = sum(w for w, _ in results)
    if not results or total <= 0:
        return None, None
    score: dict[str, float] = {}
    for w, probs in results:
        for lang, p in probs:
            score[lang] = score.get(lang, 0.0) + w * float(p)
    lang = max(score, key=score.get)
    return lang, round(score[lang] / total, 3)


# ---------------------------------------------------------------- worker process
def detect_worker(req_q, res_q, force_cpu: bool):
    """Loads Whisper (GPU unless force_cpu), then answers one request: a list of speech pieces
    -> ("result", [(seconds, [(lang, prob), ...]), ...]). Sends ("fatal", text, gpu) if the
    model can't load or run; gpu=True means the CPU may still work."""
    from .asr_worker import _exit_with_parent

    _exit_with_parent()
    from . import paths

    paths.setup_environment()
    import sys

    log = open(os.path.join(paths.LOGS, "worker.log"), "a", encoding="utf-8", buffering=1)
    sys.stdout = sys.stderr = log
    import faulthandler

    faulthandler.enable(file=log, all_threads=True)
    log.write(f"\n=== detect worker start {time.strftime('%Y-%m-%d %H:%M:%S')} ({'CPU' if force_cpu else 'GPU if available'}) ===\n")
    log.write("C++ runtime: " + ", ".join(paths.preload_vc_runtime()) + "\n")
    device = "cpu"
    t0 = time.time()
    try:
        dll_errors = [] if force_cpu else paths.preload_cuda()
        import ctranslate2
        from faster_whisper import WhisperModel

        if not force_cpu and ctranslate2.get_cuda_device_count() > 0:
            device = "cuda"
        if device == "cuda":
            from .asr_worker import _vram_info

            name = _vram_info()[0] or ""
            model = WhisperModel(paths.WHISPER_DIR, device="cuda", compute_type="int8_float16")
        else:
            name = ""
            model = WhisperModel(paths.WHISPER_DIR, device="cpu", compute_type="int8",
                                 cpu_threads=max(1, os.cpu_count() or 4))
        load_s = round(time.time() - t0, 2)
        log.write(f"detect: speech model ready on {device} in {load_s:.1f} s"
                  + (f" (CUDA libraries: {dll_errors})" if dll_errors else "") + "\n")
        res_q.put(("device", device, name, load_s))
    except Exception:
        log.write(traceback.format_exc())
        res_q.put(("fatal", traceback.format_exc(), device == "cuda" or not force_cpu))
        return
    req = req_q.get()
    if req is None:
        return
    log.write(f"detect: {req.get('path')} track {req.get('track')}: {len(req['pieces'])} piece(s)\n")
    try:
        out = []
        for k, piece in enumerate(req["pieces"]):
            _, _, probs = model.detect_language(audio=piece, language_detection_segments=1)
            out.append((round(len(piece) / SR, 2), [(lang, round(float(p), 4)) for lang, p in probs]))
            res_q.put(("progress", (k + 1) / len(req["pieces"])))
        res_q.put(("result", out))
    except Exception:
        log.write(traceback.format_exc())
        res_q.put(("fatal", traceback.format_exc(), device == "cuda"))


class Detector:
    """Runs detect_worker in a separate process; falls back to the CPU once if the GPU fails."""

    def __init__(self, force_cpu: bool, log=lambda m: None):
        import multiprocessing as mp

        self.ctx = mp.get_context("spawn")
        self.force_cpu = force_cpu
        self.log = log
        self.device = self.name = self.load_s = None
        self.gpu_problem = None
        self._start()

    def _start(self):
        self.req_q, self.res_q = self.ctx.Queue(), self.ctx.Queue()
        self.proc = self.ctx.Process(target=_worker_entry(), args=(self.req_q, self.res_q, self.force_cpu), daemon=True)
        self.proc.start()

    def run(self, speech_pieces, progress=lambda f: None, **about):
        """[(seconds, probs), ...] for the pieces. Raises RuntimeError if nothing could run it.
        about (path, track) is passed along for the worker's log."""
        import queue

        req = {"pieces": speech_pieces, **about}
        limit = LOAD_LIMIT + PIECE_LIMIT * len(speech_pieces)
        self.req_q.put(req)
        deadline = time.time() + limit
        while True:
            try:
                msg = self.res_q.get(timeout=1.0)
            except queue.Empty:
                msg = None
                if not self.proc.is_alive():
                    try:  # it may have answered just before it ended
                        msg = self.res_q.get_nowait()
                    except queue.Empty:
                        msg = ("fatal", f"speech recognition stopped unexpectedly (code {self.proc.exitcode})",
                               not self.force_cpu)
                elif time.time() > deadline:
                    msg = ("fatal", f"speech recognition did not answer within {limit:.0f} s", not self.force_cpu)
                if msg is None:
                    continue
            kind = msg[0]
            if kind == "device":
                _, dev, self.name, self.load_s = msg
                self.device = "gpu" if dev == "cuda" else "cpu"
                self.log(f"detect: speech recognition {self.device} {self.name or ''}".rstrip() + f", loaded in {self.load_s:.1f} s")
            elif kind == "progress":
                progress(msg[1])
            elif kind == "result":
                return msg[1]
            elif kind == "fatal":
                text, gpu = msg[1], msg[2]
                last = text.strip().splitlines()[-1]
                self.log("detect: speech recognition failed: " + last)
                if gpu and not self.force_cpu:
                    self.gpu_problem = last
                    self.log("detect: switching to the CPU")
                    self.stop()
                    self.force_cpu = True
                    self.device = self.name = self.load_s = None
                    self._start()
                    self.req_q.put(req)
                    deadline = time.time() + limit
                    continue
                raise RuntimeError(last)

    def stop(self):
        try:
            self.req_q.put(None)
        except Exception:
            pass
        # a worker that never read its request leaves the queue's writer thread blocked on the
        # pipe; don't let it hold up this process's exit
        self.req_q.cancel_join_thread()
        p = self.proc
        if p.is_alive():
            p.join(0.5)
            if p.is_alive():
                p.terminate()
                p.join(3)


def _worker_entry():
    """The worker function (looked up at call time, so tests can swap in a stand-in)."""
    import sys

    return sys.modules[__name__].detect_worker

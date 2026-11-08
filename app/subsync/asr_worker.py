"""Speech recognition worker.  Runs in its own process so a GPU/driver crash can
never take the window down; the main process restarts it on CPU if that happens.

Inside the worker two things overlap: while the GPU transcribes episode N, a
background thread is already decoding audio and running voice detection for
episode N+1.
"""
from __future__ import annotations

import os
import queue
import threading
import time
import traceback


def _vram_info():
    """(gpu_name, free_bytes) via NVML, which ships with every NVIDIA driver."""
    try:
        import ctypes

        nvml = ctypes.WinDLL("nvml.dll") if os.name == "nt" else ctypes.CDLL("libnvidia-ml.so.1")
        if nvml.nvmlInit_v2() != 0:
            return None, None
        h = ctypes.c_void_p()
        nvml.nvmlDeviceGetHandleByIndex_v2(0, ctypes.byref(h))
        name = ctypes.create_string_buffer(96)
        nvml.nvmlDeviceGetName(h, name, 96)

        class Mem(ctypes.Structure):
            _fields_ = [("total", ctypes.c_ulonglong), ("free", ctypes.c_ulonglong), ("used", ctypes.c_ulonglong)]

        m = Mem()
        nvml.nvmlDeviceGetMemoryInfo(h, ctypes.byref(m))
        return name.value.decode(errors="ignore"), m.free
    except Exception:
        return None, None


def _clips(speech, sr=16000, max_len=29.5):
    """Group VAD speech regions into <=30 s clips for batched decoding."""
    clips = []
    cur = None
    for s in speech:
        a, b = s["start"] / sr, s["end"] / sr
        if cur and b - cur[0] <= max_len:
            cur[1] = b
        else:
            if cur:
                clips.append(cur)
            cur = [a, b]
            while cur[1] - cur[0] > max_len:  # (VAD already caps at 30 s, belt and braces)
                clips.append([cur[0], cur[0] + max_len])
                cur[0] += max_len
    if cur:
        clips.append(cur)
    return [{"start": round(a, 3), "end": round(b, 3)} for a, b in clips if b - a > 0.2]


def _exit_with_parent():
    """Never outlive the window process, even if it crashes."""
    import multiprocessing as mp

    parent = mp.parent_process()
    if parent is None:
        return

    def watch():
        parent.join()
        os._exit(0)

    threading.Thread(target=watch, daemon=True).start()


def worker_main(req_q, res_q, cancel_ev, force_cpu: bool, batch_hint: int):
    _exit_with_parent()
    from . import paths

    paths.setup_environment()
    import sys

    log = open(os.path.join(paths.LOGS, "worker.log"), "a", encoding="utf-8", buffering=1)
    sys.stdout = sys.stderr = log
    import faulthandler

    faulthandler.enable(file=log, all_threads=True)
    log.write(f"\n=== worker start {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n")
    log.write("C++ runtime: " + ", ".join(paths.preload_vc_runtime()) + "\n")
    send = res_q.put
    try:
        dll_errors = [] if force_cpu else paths.preload_cuda()
        log.write(f"CUDA libraries: {'skipped (CPU)' if force_cpu else (dll_errors or 'ok')}\n")
        import ctranslate2
        from faster_whisper import BatchedInferencePipeline, WhisperModel
        from faster_whisper.vad import VadOptions, get_speech_timestamps

        from .media import decode

        device = "cpu"
        if not force_cpu and ctranslate2.get_cuda_device_count() > 0:
            device = "cuda"
        gpu_name, free = _vram_info() if device == "cuda" else (None, None)
        if device == "cuda":
            model = WhisperModel(paths.WHISPER_DIR, device="cuda", compute_type="int8_float16")
            if batch_hint:
                batch = batch_hint
            elif free:
                gb = free / 2**30
                batch = 16 if gb >= 6 else 8 if gb >= 3.5 else 4 if gb >= 2.2 else 2
            else:
                batch = 8
        else:
            threads = max(1, (os.cpu_count() or 4))
            model = WhisperModel(paths.WHISPER_DIR, device="cpu", compute_type="int8", cpu_threads=threads)
            batch = 4
        pipe = BatchedInferencePipeline(model)
        send(("device", device, gpu_name or "", batch, dll_errors))
    except Exception:
        send(("fatal", traceback.format_exc()))
        return

    ready: "queue.Queue" = queue.Queue(maxsize=1)  # at most one episode decoded ahead
    vad_opts = VadOptions(max_speech_duration_s=29.5, min_silence_duration_ms=160)

    def prefetch():
        while True:
            job = req_q.get()
            if job is None:
                ready.put(None)
                return
            jid = job["id"]
            try:
                send(("stage", jid, "Reading audio…"))
                t0 = time.time()
                audio = decode(job["path"], job["audio_n"], cancel_ev.is_set)
                clips = _clips(get_speech_timestamps(audio, vad_opts))
                ready.put((job, audio, clips, time.time() - t0))
            except InterruptedError:
                ready.put((job, None, "cancelled", 0))
            except Exception as e:
                ready.put((job, None, f"Could not read the audio: {e}", 0))

    threading.Thread(target=prefetch, daemon=True).start()

    while True:
        item = ready.get()
        if item is None:
            return
        job, audio, clips, t_decode = item
        jid = job["id"]
        if audio is None:
            send(("error", jid, clips))
            continue
        if cancel_ev.is_set():
            send(("error", jid, "cancelled"))
            continue
        dur = len(audio) / 16000.0
        if not clips:
            send(("result", jid, [], job.get("lang") or "en", dur, {"decode_s": t_decode}))
            continue
        send(("stage", jid, "Listening…"))
        t0 = time.time()
        while True:
            try:
                segments, info = pipe.transcribe(
                    audio, language=job.get("lang"), task="transcribe", beam_size=1, best_of=1,
                    temperature=0.0, word_timestamps=True, vad_filter=False, clip_timestamps=clips,
                    batch_size=batch, without_timestamps=True, language_detection_segments=4,
                    log_progress=False)
                words = []
                last = 0.0
                for seg in segments:
                    for w in seg.words or ():
                        words.append((round(w.start, 3), round(w.end, 3), w.word))
                    if seg.end - last > 15:
                        last = seg.end
                        send(("progress", jid, min(0.99, seg.end / dur)))
                    if cancel_ev.is_set():
                        raise InterruptedError
                break
            except InterruptedError:
                words = None
                break
            except Exception as e:
                msg = str(e).lower()
                if device == "cuda" and ("out of memory" in msg or "cublas_status_alloc" in msg) and batch > 1:
                    batch //= 2
                    send(("batch", batch))
                    continue
                send(("error", jid, f"Speech recognition failed: {e}"))
                words = None
                break
        if words is None:
            if cancel_ev.is_set():
                send(("error", jid, "cancelled"))
            continue
        words.sort()
        send(("result", jid, words, info.language, dur,
              {"decode_s": t_decode, "asr_s": time.time() - t0, "lang_prob": info.language_probability}))

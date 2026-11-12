"""Test double for the ASR worker: real audio decode + real VAD, but the
transcript comes from the fixture's sidecar file instead of Whisper."""
import os as _os, sys as _sys
_REPO = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
import json, os, time
def worker_main(req_q, res_q, cancel_ev, force_cpu, batch_hint):
    import sys; sys.path.insert(0, _os.path.join(_REPO, "app"))
    from subsync import paths; paths.setup_environment()
    from subsync.media import decode
    from subsync.asr_worker import _clips
    from faster_whisper.vad import VadOptions, get_speech_timestamps
    if os.environ.get("SUBSYNC_FAKE_GPU_FATAL") and not force_cpu:
        # like the real worker when the GPU model fails to load: its audio reader has already
        # taken the first job; the engine must resend that job to a CPU worker
        req_q.get()
        res_q.put(("fatal", "fake: GPU model could not be loaded"))
        return
    res_q.put(("device", "cpu" if force_cpu else "cuda", "" if force_cpu else "FAKE GPU", 8, [], 0.5))
    while True:
        job = req_q.get()
        if job is None: return
        if os.environ.get("SUBSYNC_FAKE_GPU_CRASH") and not force_cpu:
            os._exit(3)  # like a GPU driver crash mid-job: the engine restarts on the CPU and resends it
        res_q.put(("stage", job["id"], "Reading audio…"))
        t0 = time.time()
        a = decode(job["path"], job["audio_n"])
        clips = _clips(get_speech_timestamps(a, VadOptions(max_speech_duration_s=29.5, min_silence_duration_ms=160)))
        res_q.put(("stage", job["id"], "Listening…")); t1 = time.time()
        for k in range(4):
            time.sleep(0.3); res_q.put(("progress", job["id"], k / 4))
        words = [tuple(w) for w in json.load(open(job["path"] + ".asr.json"))]
        res_q.put(("result", job["id"], words, "en", len(a) / 16000, {"decode_s": t1 - t0, "asr_s": time.time() - t1, "clips": len(clips)}))

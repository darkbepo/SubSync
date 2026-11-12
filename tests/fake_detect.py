"""Test double for the detect worker: no Whisper. The language comes from <video>.lang.json
({"1": "da", "2": "en"} by audio track, or {"*": "en"}); default "en"."""
import json, os


def detect_worker(req_q, res_q, force_cpu):
    if os.environ.get("SUBSYNC_FAKE_DETECT_GPU_OOM") and not force_cpu:
        res_q.put(("fatal", "RuntimeError: CUDA failed with error out of memory", True))  # like a full GPU
        return
    res_q.put(("device", "cpu" if force_cpu else "cuda", "" if force_cpu else "FAKE GPU", 0.3))
    req = req_q.get()
    if req is None:
        return
    if os.environ.get("SUBSYNC_FAKE_DETECT_HANG") and not force_cpu:
        import time
        time.sleep(3600)  # like a stuck GPU driver
    try:
        m = json.load(open(req["path"] + ".lang.json"))
    except OSError:
        m = {}
    lang = m.get(str(req["track"]), m.get("*", "en"))
    other = "de" if lang != "de" else "nl"
    out = []
    for k, p in enumerate(req["pieces"]):
        assert 0 < len(p) <= 30 * 16000, len(p)
        out.append((round(len(p) / 16000, 2), [(lang, 0.95), (other, 0.04)]))
        res_q.put(("progress", (k + 1) / len(req["pieces"])))
    res_q.put(("result", out))

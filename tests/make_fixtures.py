"""Test videos with real (synthesized) speech at known times, desynced subtitles,
and the transcript the fake worker returns in place of Whisper."""
import os as _os, sys as _sys
_REPO = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
import json, random, subprocess, sys, wave, numpy as np
sys.path.insert(0, _os.path.join(_REPO, "app"))
from subsync.subtitles import Line, to_srt
WORDS = ("time people way water day thing man world life hand part child eye woman place work week case point "
         "number group problem fact house night home room mother area money story month lot right book job word "
         "business side kind head father power hour game line end member city name team minute idea kid body door "
         "face others level office health person art war history party result change morning reason research girl "
         "guy moment air teacher force education foot boy age policy music market sense nation plan college").split()
def speak(text, path):
    subprocess.run(["espeak-ng", "-s", "165", "-w", path, text], check=True, capture_output=True)
    with wave.open(path) as w:
        a = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768
        return a, w.getframerate()
for name, ext, ch, seed in (("Show.S01E01.1080p", "mkv", 6, 4), ("Show.S01E02.1080p", "mp4", 2, 5)):
    rng = random.Random(seed)
    sr = 22050; t = 3.0; chunks = []; sents = []
    for k in range(40):
        ws = [rng.choice(WORDS) for _ in range(rng.randint(3, 9))]
        a, sr = speak(" ".join(ws), "/tmp/s.wav")
        nz = np.nonzero(np.abs(a) > 0.02)[0]; a = a[nz[0]:nz[-1]]
        d = len(a) / sr
        chunks.append((t, a)); sents.append((t, t + d, ws))
        t += d + rng.choice([0.4, 0.8, 1.5, 2.5])
    dur = int(t) + 3
    sig = np.zeros(dur * sr, dtype=np.float32)
    for s, a in chunks: sig[int(s*sr):int(s*sr)+len(a)] += a
    sig += np.random.default_rng(0).standard_normal(len(sig)).astype(np.float32) * 0.003
    sig.tofile("/tmp/sig.f32")
    af = "pan=5.1|c0=0.1*c0|c1=0.1*c0|c2=c0|c3=0*c0|c4=0*c0|c5=0*c0" if ch == 6 else "pan=stereo|c0=c0|c1=c0"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"color=c=black:s=320x180:d={dur}",
                    "-f", "f32le", "-ar", str(sr), "-ac", "1", "-i", "/tmp/sig.f32", "-af", af, "-c:v", "libx264",
                    "-preset", "ultrafast", "-c:a", "aac", "-ar", "48000", "-shortest", f"media/{name}.{ext}"], check=True)
    asr = []
    for s, e, ws in sents:
        step = (e - s) / len(ws)
        asr += [(s + q*step, s + (q+1)*step*0.95, " " + w + ("." if q == len(ws)-1 else "")) for q, w in enumerate(ws)]
    json.dump(asr, open(f"media/{name}.{ext}.asr.json", "w"))
    truth = [s - 0.05 for s, e, ws in sents]
    bad = []
    for k, (s, e, ws) in enumerate(sents):
        o = 2.5 if k >= 20 else 0.0
        if k == 7: o += 1.4
        bad.append(Line(s - 0.05 - o, e + 0.5 - o, " ".join(ws).capitalize() + "."))
    json.dump(truth, open(f"media/{name}.truth.json", "w"))
    open(f"media/{'Show.S01E01.en.srt' if seed == 4 else 'Show S01E02 WEB-DL.srt'}", "w", encoding="utf-8").write(to_srt(bad))
open("media/Other.Movie.2019.srt", "w").write(to_srt(bad[:10]))
print("ok")

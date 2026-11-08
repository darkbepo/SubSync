import os as _os, sys as _sys
_REPO = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
import sys, random, numpy as np, time
sys.path.insert(0, _os.path.join(_REPO, "app"))
from subsync.align import align
from subsync.subtitles import Line

def make(seed=1, cross=False, n=650):
    rng = random.Random(seed)
    vocab = [f"w{i}" for i in range(3000)]
    foreign = {w: f"f{rng.randrange(10**6)}" for w in vocab}
    t = 5.0; sents = []
    for k in range(n):
        nw = rng.choice([1,2,2,3,4,5,6,7,8,9,10,12])
        words = [vocab[min(int(rng.paretovariate(1.1)*20), 2999)] for _ in range(nw)]
        dur = max(0.4, nw*0.28 + rng.uniform(-0.1, 0.4))
        sents.append((t, t+dur, words)); t += dur + rng.choice([0.2,0.4,0.8,1.5,3,6]) + (30 if rng.random()<0.01 else 0)
    # ASR output
    asr = []
    for (s, e, ws) in sents:
        if rng.random() < 0.06: continue               # missed speech
        out = [foreign[w] for w in ws] if cross else list(ws)
        if cross and len(out) > 2 and rng.random() < 0.5: rng.shuffle(out)  # word order differs
        out = [o if rng.random() > 0.12 else f"x{rng.randrange(9999)}" for o in out]  # recognition errors
        step = (e - s) / len(out)
        for q, o in enumerate(out):
            ws_ = s + q*step + rng.uniform(-0.12, 0.12)
            asr.append((ws_, ws_ + step*0.9, o + ("." if q == len(out)-1 else "")))
    asr.sort()
    # correct subtitle (reference truth)
    subs = []; k = 0
    while k < len(sents):
        s, e, ws = sents[k]
        if rng.random() < 0.05:
            fx = Line(max(0,s-1.5), s-0.3, "[door slams]"); fx.true_end = None; subs.append(fx)
        if len(ws) >= 8 and rng.random() < 0.3:
            h = len(ws)//2; mid = s + (e-s)*h/len(ws)
            a = Line(s, mid, " ".join(ws[:h])); a.true_end = mid; b = Line(mid, e+0.5, " ".join(ws[h:])); b.true_end = e
            subs.append(a); subs.append(b)
        elif k+1 < len(sents) and rng.random() < 0.08 and sents[k+1][0]-e < 1:
            s2, e2, w2 = sents[k+1]; m_ = Line(s, e2+0.5, " ".join(ws) + "\n- " + " ".join(w2)); m_.true_end = e2; subs.append(m_); k += 1
        else:
            l_ = Line(s - 0.1 + rng.uniform(-0.15, 0.15), e + 0.6, " ".join(ws)); l_.true_end = e
            if rng.random() < 0.15:  # badly authored: disappears long before the words are said
                l_.end = l_.start + max(0.3, (e - s) * 0.4)
            subs.append(l_)
        k += 1
    subs = [l for l in subs if l.end > l.start]
    global TRUE_END
    subs.sort(key=lambda l: l.start)
    truth = [l.start for l in subs]
    TRUE_END = [getattr(l, "true_end", None) for l in subs]
    # desync it
    bad = []
    for l in subs:
        o = 0.0
        if l.start > 22*60: o += 3.4                      # second half off
        if l.start > 35*60: o += (l.start - 35*60) * 0.002 # slow drift
        if rng.random() < 0.03: o += rng.choice([-1.3, 1.2])  # individual bad lines
        bad.append(Line(l.start - o, l.end - o, l.text))
    return bad, truth, asr, foreign

def fake_embed(foreign):
    back = {v: k for k, v in foreign.items()}
    cache = {}
    def vec(tok):
        tok = tok.strip(".,- \n").lower()
        tok = back.get(tok, tok)
        if tok not in cache:
            r = np.random.default_rng(abs(hash(tok)) % (2**32)); cache[tok] = r.standard_normal(256)
        return cache[tok]
    def embed(texts):
        out = []
        for t in texts:
            ws = t.replace("\n", " ").split()
            v = sum((vec(w) for w in ws), np.zeros(256)) + np.random.default_rng(len(t)).standard_normal(256)*0.6
            out.append(v / np.linalg.norm(v))
        return np.array(out, dtype=np.float32)
    return embed

if __name__ == '__main__':
  for cross in (False, True):
    for seed in (1, 2, 3):
        bad, truth, asr, foreign = make(seed, cross)
        t0 = time.time()
        r = align(bad, asr, "da" if cross else "en", fake_embed(foreign))
        dt = time.time() - t0
        if not r.ok: print("FAIL", r.reason); continue
        err = np.abs(np.array([l.start for l in r.lines]) - np.array(truth))
        cut_before = sum(1 for k, (b, t) in enumerate(zip(bad, TRUE_END)) if t is not None and b.end + (truth[k] - b.start) < t - 0.05)
        cut_after = sum(1 for l, t in zip(r.lines, TRUE_END) if t is not None and l.end < t - 0.05)
        overlaps = sum(1 for k in range(len(r.lines)-1) if r.lines[k].end > r.lines[k+1].start + 1e-6 and bad[k].end <= bad[k+1].start)
        too_fast = sum(1 for l in r.lines if (l.end - l.start) < 0.99)
        before = np.abs(np.array([l.start for l in bad]) - np.array(truth))
        print(f"{'cross' if cross else 'same '} seed{seed}: lines={len(bad)} matched={r.matched}/{r.total_speech} runs={len(r.runs)} "
              f"before: within0.3s={np.mean(before<0.3):.0%} | after: median={np.median(err):.2f}s p95={np.quantile(err,.95):.2f}s "
              f"within0.3s={np.mean(err<0.3):.0%} max={err.max():.1f}s | cut off before speech ends: {cut_before} -> {cut_after}"
              f" | extended speech={r.ends_speech} read={r.ends_read} limited={r.ends_limited} | <1s lines={too_fast} new overlaps={overlaps}")

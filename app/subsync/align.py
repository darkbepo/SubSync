"""Per-line subtitle alignment.

1. Whisper words are grouped into short spoken phrases.
2. Every subtitle line is compared with every phrase (and every pair of
   neighbouring phrases) by meaning (multilingual embeddings) and, when the
   audio is English, also by spelling.
3. A monotonic dynamic-programming pass picks the best in-order matching, so
   lines can never swap places.  A second pass, restricted to a window around
   the first estimate, picks up short/generic lines.
4. Matches become "anchors" with a measured offset.  Anchors are grouped into
   runs of consistent offset; a run change is a split (e.g. synced in the first
   half, off in the second).  Lone disagreeing anchors are treated as outliers.
5. Every line gets its own offset: anchors use their own measurement (lightly
   smoothed), other lines are interpolated inside their run.
"""
from __future__ import annotations

import bisect
from dataclasses import dataclass, field

import numpy as np

from .subtitles import Line, speech_text

NO_SPACE_LANGS = {"zh", "ja", "th", "lo", "km", "my", "yue", "bo"}
SENT_END = tuple(".?!。？！…")
SOFT_END = tuple(",;:，、；：")


@dataclass
class Phrase:
    start: float
    end: float
    text: str


@dataclass
class Result:
    lines: list[Line]
    matched: int
    total_speech: int
    runs: list[tuple[float, float, float]] = field(default_factory=list)  # (from_time, to_time, offset)
    offsets: list[float] = field(default_factory=list)
    ok: bool = True
    reason: str = ""
    ends_speech: int = 0   # endings extended so the line stays until its words are spoken
    ends_read: int = 0     # endings extended to a readable minimum duration
    ends_limited: int = 0  # wanted more time but the next line starts too soon


# --------------------------------------------------------------- phrases
def build_phrases(words: list[tuple[float, float, str]], lang: str) -> list[Phrase]:
    joiner = "" if lang in NO_SPACE_LANGS else " "
    out: list[Phrase] = []
    cur: list[tuple[float, float, str]] = []

    def flush():
        if cur:
            text = joiner.join(w[2].strip() for w in cur).strip()
            if text:
                out.append(Phrase(cur[0][0], cur[-1][1], text))
            cur.clear()

    for w in words:
        if cur:
            prev = cur[-1]
            gap = w[0] - prev[1]
            dur = prev[1] - cur[0][0]
            pt = prev[2].strip()
            if (gap > 0.30 or pt.endswith(SENT_END) or (pt.endswith(SOFT_END) and dur > 1.2)
                    or (dur > 4.5 and gap > 0.08) or dur > 7.0):
                flush()
        cur.append(w)
    flush()
    return out


# --------------------------------------------------------------- matching
def _dp(score: np.ndarray) -> list[tuple[int, int]]:
    """Max-weight monotonic matching (each line/phrase used at most once)."""
    L, P = score.shape
    R = np.zeros((L + 1, P + 1), dtype=np.float32)
    for i in range(L):
        prev = R[i]
        cand = np.maximum(prev[1:], prev[:-1] + score[i])
        row = np.empty(P + 1, dtype=np.float32)
        row[0] = 0.0
        row[1:] = cand
        np.maximum.accumulate(row, out=row)
        R[i + 1] = row
    pairs = []
    i, j = L, P
    while i > 0 and j > 0:
        v = R[i, j]
        if v == R[i, j - 1]:
            j -= 1
        elif v == R[i - 1, j]:
            i -= 1
        else:
            pairs.append((i - 1, j - 1))
            i -= 1
            j -= 1
    pairs.reverse()
    return pairs


def _similarity(line_texts, phrases, embed, same_lang: bool):
    """(L x P) similarity, best of single phrase / phrase+next phrase."""
    ptexts = [p.text for p in phrases]
    pair_texts = [ptexts[k] + " " + ptexts[k + 1] for k in range(len(ptexts) - 1)]
    vecs = embed(line_texts + ptexts + pair_texts)
    L, P = len(line_texts), len(ptexts)
    lv, pv, qv = vecs[:L], vecs[L:L + P], vecs[L + P:]
    S = lv @ pv.T
    S2 = np.full_like(S, -1.0)
    if len(pair_texts):
        S2[:, :-1] = lv @ qv.T
    if same_lang:
        from rapidfuzz import fuzz, process, utils

        F = process.cdist(line_texts, ptexts, scorer=fuzz.ratio, processor=utils.default_process,
                          workers=-1, dtype=np.float32) / 100.0
        if len(pair_texts):
            F2 = process.cdist(line_texts, pair_texts, scorer=fuzz.ratio, processor=utils.default_process,
                               workers=-1, dtype=np.float32) / 100.0
            F[:, :-1] = np.maximum(F[:, :-1], F2)
        F2full = np.full_like(S, -1.0)
        if len(pair_texts):
            F2full[:, :-1] = F2
        S2 = np.maximum(S2, F2full)
        S = np.maximum(S, F)
    pair_wins = S2 > S
    S = np.maximum(S, S2)
    return S.astype(np.float32), pair_wins


def _threshold(S: np.ndarray, base: float) -> float:
    """Self-calibrating match threshold: almost every (line, phrase) cell is a
    non-match, so a high quantile of the whole matrix is the noise ceiling."""
    if S.size < 50:
        return base
    noise = float(np.quantile(S, 0.995))
    return float(np.clip(max(base, noise + 0.03), 0.35, 0.80))


# --------------------------------------------------------------- runs
def _runs(anchors, tol=0.8, min_run=4):
    """Split anchors (line_idx, offset, sim) into runs of consistent offset."""
    runs: list[list] = []
    cur: list = []
    pending: list = []
    for a in anchors:
        if not cur:
            cur.append(a)
            continue
        ref = float(np.median([x[1] for x in cur[-5:]]))
        if abs(a[1] - ref) <= tol:
            cur.append(a)
            pending.clear()  # the disagreeing ones were outliers
            continue
        pending.append(a)
        while pending:
            pm = float(np.median([x[1] for x in pending]))
            if all(abs(x[1] - pm) <= tol for x in pending):
                break
            pending.pop(0)
        if len(pending) >= min_run:
            runs.append(cur)
            cur, pending = list(pending), []
    runs.append(cur)
    if pending and len(pending) >= min_run:
        runs.append(pending)
    good = [r for r in runs if len(r) >= min_run]
    # a short run sandwiched between two runs that agree with each other is
    # almost always a cluster of false matches, not a real timing change
    med = lambda r: float(np.median([x[1] for x in r]))
    changed = True
    while changed:
        changed = False
        for k in range(1, len(good) - 1):
            if len(good[k]) < 8 and abs(med(good[k - 1]) - med(good[k + 1])) <= tol:
                del good[k]
                changed = True
                break
    if not good:
        good = [max(runs, key=len)] if runs and runs[0] else []
    # merge neighbouring runs that ended up agreeing
    merged: list[list] = []
    for r in good:
        if merged and abs(np.median([x[1] for x in merged[-1][-5:]]) - np.median([x[1] for x in r[:5]])) <= tol:
            merged[-1].extend(r)
        else:
            merged.append(r)
    inrun = {id(x) for r in merged for x in r}
    return merged, [a for a in anchors if id(a) not in inrun]


def _smooth(vals: list[float], k=2) -> list[float]:
    out = []
    for i in range(len(vals)):
        out.append(float(np.median(vals[max(0, i - k): i + k + 1])))
    return out


# --------------------------------------------------------------- main entry
def align(lines: list[Line], words, lang: str, embed, sub_lang: str = "en",
          progress=lambda f: None, phrases: list[Phrase] | None = None) -> Result:
    """phrases: what to match the lines to, instead of the phrases heard in words (1.5.0: the
    lines of a synced English subtitle, to time a Danish one by)."""
    if phrases is None:
        phrases = build_phrases(words, lang)
    speech_idx = [i for i, l in enumerate(lines) if speech_text(l.text)]
    texts = [speech_text(lines[i].text) for i in speech_idx]
    n_speech = len(texts)
    if n_speech < 5 or len(phrases) < 5:
        return Result(lines, 0, n_speech, ok=False,
                      reason="Not enough speech found in the audio" if len(phrases) < 5 else "Subtitle has too few lines")

    same = (lang or "").split("-")[0] == sub_lang
    S, pair_wins = _similarity(texts, phrases, embed, same)
    progress(0.5)
    thr = _threshold(S, 0.55 if same else 0.45)

    starts = np.array([lines[i].start for i in speech_idx])
    pstarts = np.array([p.start for p in phrases])
    nchar = np.array([len(t) for t in texts])
    weight = np.clip(nchar / 20.0, 0.25, 1.0)

    # pass 1: global, no time prior, long lines count more
    score = np.maximum(S - thr, 0) * weight[:, None]
    pairs = [(i, j) for i, j in _dp(score) if score[i, j] > 0]
    anchors = [(i, float(pstarts[j] - starts[i]), float(S[i, j]), j) for i, j in pairs]
    runs, _ = _runs(anchors)
    if sum(len(r) for r in runs) >= 5:
        # pass 2: only near the first estimate, with a gentle time prior; short lines get full weight
        pred = _offset_curve(runs, starts, len(starts))
        dt = np.abs(pstarts[None, :] - (starts + pred)[:, None])
        window = dt <= 12.0
        score2 = np.where(window, np.maximum(S - thr * 0.92, 0) - 0.004 * dt, 0)
        score2 = np.maximum(score2, 0) * np.clip(nchar / 12.0, 0.5, 1.0)[:, None]
        pairs = [(i, j) for i, j in _dp(score2) if score2[i, j] > 0]
        anchors = [(i, float(pstarts[j] - starts[i]), float(S[i, j]), j) for i, j in pairs]
    runs, loners = _runs(anchors)
    progress(0.8)

    kept = sum(len(r) for r in runs)
    min_needed = max(8, int(0.08 * n_speech))
    if kept < min_needed:
        return Result(lines, kept, n_speech, ok=False,
                      reason=f"Only {kept} of {n_speech} lines matched the audio – wrong subtitle for this video?")

    off_speech = _offset_curve(runs, starts, len(starts), per_anchor=True)
    # A line that clearly matches its own spot in the audio but disagrees with
    # its neighbours was individually mistimed: trust the line itself.
    strong = thr + 0.2
    accepted_loners = []
    for i, o, sim, j in loners:
        if sim >= strong and abs(o - off_speech[i]) <= 4.0:
            ns = starts[i] + o
            lo = starts[i - 1] + off_speech[i - 1] if i > 0 else -1e9
            hi = starts[i + 1] + off_speech[i + 1] if i + 1 < len(starts) else 1e9
            if lo + 0.05 <= ns <= hi - 0.05:  # never jump past a neighbour
                off_speech[i] = o
                kept += 1
                accepted_loners.append((i, o, sim, j))
    # every line (incl. sound-effect lines) gets an offset from its neighbours
    # sound-effect / music lines take the offset of the nearest spoken line
    offsets = np.zeros(len(lines))
    sp = np.array(speech_idx)
    for i in range(len(lines)):
        k = int(np.searchsorted(sp, i))
        if k < len(sp) and sp[k] == i:
            offsets[i] = off_speech[k]
            continue
        cands = [c for c in (k - 1, k) if 0 <= c < len(sp)]
        c = min(cands, key=lambda c: abs(lines[sp[c]].start - lines[i].start))
        offsets[i] = off_speech[c]
    new = _apply(lines, offsets)
    # where the words of each matched line finish in the audio
    speech_end = {}
    for a in [x for r in runs for x in r] + accepted_loners:
        i, j = a[0], a[3]
        end = phrases[j + 1].end if (pair_wins[i, j] and j + 1 < len(phrases)) else phrases[j].end
        speech_end[speech_idx[i]] = end
    st = fix_endings(new, lines, speech_end)
    run_info = []
    for r in runs:
        a, b = speech_idx[r[0][0]], speech_idx[r[-1][0]]
        run_info.append((lines[a].start, lines[b].end, float(np.median([x[1] for x in r]))))
    return Result(new, kept, n_speech, run_info, offsets.tolist(), ends_speech=st[0], ends_read=st[1],
                  ends_limited=st[2])


def _offset_curve(runs, starts, n, per_anchor=False) -> np.ndarray:
    """Offset for every speech line, given anchor runs."""
    idx_all, off_all, run_of = [], [], []
    for rn, r in enumerate(runs):
        own = [x[1] for x in r]
        sm = _smooth(own)
        for x, s in zip(r, sm):
            idx_all.append(x[0])
            # strong own measurement keeps most of its own value (true per-line fix)
            v = (0.5 * x[1] + 0.5 * s) if (per_anchor and x[2] >= 0.75) else s
            off_all.append(v)
            run_of.append(rn)
    order = np.argsort(idx_all)
    idx_all = np.array(idx_all)[order]
    off_all = np.array(off_all)[order]
    run_of = np.array(run_of)[order]
    out = np.zeros(n)
    t_anchor = starts[idx_all]
    idx_list = idx_all.tolist()
    for i in range(n):
        k = bisect.bisect_left(idx_list, i)
        if k < len(idx_all) and idx_all[k] == i:
            out[i] = off_all[k]
            continue
        if k == 0:
            out[i] = off_all[0]
        elif k >= len(idx_all):
            out[i] = off_all[-1]
        else:
            a, b = k - 1, k
            if run_of[a] == run_of[b]:
                ta, tb = t_anchor[a], t_anchor[b]
                f = 0.0 if tb <= ta else min(1.0, max(0.0, (starts[i] - ta) / (tb - ta)))
                out[i] = off_all[a] + f * (off_all[b] - off_all[a])
            else:
                # split between two runs: cut at the largest pause between the anchors
                lo, hi = idx_all[a], idx_all[b]
                gaps = [(starts[q + 1] - starts[q], q) for q in range(lo, hi)]
                cut = max(gaps)[1] if gaps else lo
                out[i] = off_all[a] if i <= cut else off_all[b]
    return out


def _apply(lines: list[Line], offsets) -> list[Line]:
    new = [Line(max(0.0, l.start + o), max(0.0, l.end + o), l.text) for l, o in zip(lines, offsets)]
    for k in range(len(new) - 1):
        a, b = new[k], new[k + 1]
        orig_overlap = lines[k].end > lines[k + 1].start
        if not orig_overlap and a.end > b.start and b.start > a.start:
            a.end = max(a.start + 0.5, b.start - 0.042)
            if a.end > b.start:
                a.end = b.start
        if a.end <= a.start:
            a.end = a.start + 0.5
    return new


GAP = 0.084        # keep ~2 frames between consecutive lines
SPEECH_TAIL = 0.3  # linger a little after the last word
MAX_EXTEND = 4.0   # never add more than this to a line
MAX_DURATION = 7.0
MIN_DURATION = 1.0
MAX_CPS = 20.0     # reading speed: characters per second


def _visible_chars(text: str) -> int:
    import re

    t = re.sub(r"<[^>]*>|\{[^}]*\}", "", text)
    return len(re.sub(r"\s+", " ", t).strip())


def fix_endings(new: list[Line], orig: list[Line], speech_end: dict) -> tuple[int, int, int]:
    """Make sure no line disappears before it has been said or could be read.
    Lines are only ever lengthened, never into the next line, and never shortened."""
    n_speech = n_read = n_limited = 0
    for k, l in enumerate(new):
        limit = float("inf")
        if k + 1 < len(new):
            nxt = new[k + 1]
            originally_separate = orig[k].end <= orig[k + 1].start + 1e-3
            if originally_separate and nxt.start > l.start:
                limit = nxt.start - GAP
        target = l.end
        reason = None
        se = speech_end.get(k)
        if se is not None and l.start < se and se + SPEECH_TAIL > target:
            target = min(se + SPEECH_TAIL, l.start + MAX_DURATION, l.end + MAX_EXTEND)
            reason = "speech"
        need = max(MIN_DURATION, _visible_chars(l.text) / MAX_CPS)
        if l.start + need > target:
            target = min(l.start + need, l.end + MAX_EXTEND)
            reason = reason or "read"
        if target <= l.end + 1e-3:
            continue
        new_end = max(l.end, min(target, limit))
        if new_end > l.end + 0.01:
            if reason == "speech":
                n_speech += 1
            else:
                n_read += 1
            l.end = new_end
        if target > limit + 0.01:
            n_limited += 1
    return n_speech, n_read, n_limited


MIN_SHOW = 0.7     # no subtitle is shown for less than this (shorter looks like a missing line)
MIN_FIT = 0.5      # with this much room before the next line, a short line fills it instead of overlapping
JOIN_WITHIN = 0.3  # a sound description this close to its neighbour's start becomes one subtitle with it


def keep_visible(lines: list[Line], join: bool = True) -> tuple[list[Line], list[list[int]], dict]:
    """Last pass before writing: make sure every subtitle stays on screen long enough to be
    seen. Moving starts can leave a subtitle only a few hundredths of a second before the next
    one, which on screen looks as if the line was dropped. Starts are never moved, and nothing
    is removed or shortened. A subtitle shorter than MIN_SHOW:
      - with room before the next one, gets that room (up to MIN_SHOW; no overlap if at least
        MIN_FIT fits, so the next line doesn't jump when this one disappears);
      - with join (Tidy up lines on), a sound description and a neighbour that start within
        JOIN_WITHIN of each other and fit in two rows become one subtitle, at the dialogue's
        start (no dashes are invented: speaker changes can't be told);
      - otherwise stays on screen for MIN_SHOW together with the next one (players show both,
        stacked). Never three at once: if the one before is still showing then, this one gets
        what room there is (or, with join, becomes one subtitle with the next one if they start
        within JOIN_WITHIN and fit in two rows), and a last pass ends the earliest of three
        overlapping ones just before the third starts.
    Returns the lines, which input lines each one came from, and counts."""
    out = [Line(l.start, l.end, l.text) for l in lines]
    groups = [[k] for k in range(len(out))]
    base = [l.end for l in out]  # ends before this pass: the last step never cuts below them
    stats = {"joined": 0, "overlap": 0, "filled": 0}

    def rows(t):
        return len(t.split("\n"))

    def sound(t):
        return speech_text(t) is None

    def merge(lo, start):
        x, y = out[lo], out[lo + 1]
        out[lo:lo + 2] = [Line(start, max(x.end, y.end, start + MIN_SHOW), x.text + "\n" + y.text)]
        groups[lo:lo + 2] = [groups[lo] + groups[lo + 1]]
        base[lo:lo + 2] = [max(base[lo], base[lo + 1])]
        stats["joined"] += 1

    k = 0
    while k < len(out):
        a = out[k]
        if a.end - a.start >= MIN_SHOW - 1e-6:
            k += 1
            continue
        nxt = out[k + 1] if k + 1 < len(out) else None
        need = a.start + MIN_SHOW
        if nxt is None or need <= nxt.start - GAP:
            a.end = max(a.end, need)
            k += 1
            continue
        if nxt.start - GAP - a.start >= MIN_FIT:
            a.end = max(a.end, nxt.start - GAP)
            stats["filled"] += 1
            k += 1
            continue
        if join:
            done = False
            for j in (k + 1, k - 1):
                if not 0 <= j < len(out):
                    continue
                b = out[j]
                if (sound(a.text) or sound(b.text)) and rows(a.text) + rows(b.text) <= 2 and abs(b.start - a.start) <= JOIN_WITHIN:
                    talk = [x for x in (a, b) if not sound(x.text)]
                    merge(min(j, k), talk[0].start if talk else min(a.start, b.start))
                    k = max(0, min(j, k) - 1)  # look again at the one before (it may now be too short)
                    done = True
                    break
            if done:
                continue
        prev = out[k - 1] if k else None
        if prev is not None and prev.end > nxt.start + 1e-6:  # an overlap now would show three at once
            if join and rows(a.text) + rows(nxt.text) <= 2 and nxt.start - a.start <= JOIN_WITHIN:
                merge(k, a.start)
                k = max(0, k - 1)
                continue
            a.end = max(a.end, nxt.start - GAP, a.start + 0.05)
            k += 1
            continue
        a.end = max(a.end, need)
        stats["overlap"] += 1
        k += 1
    # never three on screen at once because of this pass (people talking over each other): the
    # earliest gives back the time it got here, never more
    for j in range(1, len(out)):
        active = [i for i in range(max(0, j - 8), j) if out[i].end > out[j].start + 1e-6]
        while len(active) >= 2:
            i = active.pop(0)
            if out[i].end > base[i] + 1e-9:
                out[i].end = max(base[i], out[j].start - GAP, min(out[i].start + 0.05, out[j].start))
    return out, groups, stats

"""Word-level timing.

Subtitle cues are split into tokens (spoken words, sound descriptions, speaker
labels, formatting tags, dialogue dashes).  The spoken words are matched to the
words Whisper heard, near the position the rough alignment gave each cue, so
every word gets its own time.  Cues are then timed from their first and last
spoken word.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .subtitles import Line


@dataclass
class Tok:
    cue: int            # index of the original cue
    row: int            # row inside that cue (0-based)
    text: str           # exactly as in the file
    kind: str           # "word" | "sound" | "label" | "tag" | "dash"
    norm: str = ""      # words only
    start: float | None = None
    end: float | None = None
    matched: bool = False


_APOS = str.maketrans({"’": "'", "‘": "'", "ʼ": "'", "`": "'"})


def norm(word: str) -> str:
    """Comparable form of a word: lowercase, letters/digits/inner apostrophes only."""
    w = re.sub(r"[^a-z0-9']", "", word.translate(_APOS).lower())
    return w.strip("'")


_SPEAKER = re.compile(r"[A-Z][A-Z0-9 .'\-]{1,24}:")
_DASH = re.compile(r"[-–—]+(?=\s|$)")
_PIECE = re.compile(r"(<[^>]*>|\{[^}]*\})|(\[[^\]]*\]|\([^)]*\))|([♪♫#]+)|([^\s<{\[(♪♫#]+)")
_LABEL = re.compile(r"[\(\[]([A-Z][a-zA-Z'\-]{1,20}|[A-Z][A-Z'\- ]{1,20})[\)\]]")


def _is_label(piece: str, at_row_start: bool) -> bool:
    """A speaker name in brackets at the start of a row: (Patrick), [TRINA].
    Single-word sound descriptions look the same, so verb-like words are not labels."""
    m = _LABEL.fullmatch(piece)
    if not m or not at_row_start:
        return False
    w = m.group(1).lower()
    return not (w.endswith("s") or w.endswith("ing") or w.endswith("ed"))


def tokenize(lines: list[Line]) -> list[Tok]:
    out: list[Tok] = []
    for ci, line in enumerate(lines):
        for ri, row in enumerate(line.text.split("\n")):
            pos = len(row) - len(row.lstrip())
            first = True  # no word/sound/label seen yet on this row (tags don't count)
            m = _SPEAKER.match(row, pos)
            if m:
                out.append(Tok(ci, ri, m.group(0), "label"))
                pos = m.end()
                first = False
            while pos < len(row):
                while pos < len(row) and row[pos].isspace():
                    pos += 1
                if pos >= len(row):
                    break
                if first:
                    d = _DASH.match(row, pos)
                    if d:
                        out.append(Tok(ci, ri, d.group(0), "dash"))
                        pos = d.end()
                        continue
                m = _PIECE.match(row, pos)
                if not m:  # a stray bracket or similar: take it as part of a word
                    j = pos + 1
                    while j < len(row) and not row[j].isspace():
                        j += 1
                    piece, kind = row[pos:j], "word"
                    pos = j
                else:
                    piece = m.group(0)
                    pos = m.end()
                    if m.group(1):
                        kind = "tag"
                    elif m.group(2):
                        kind = "label" if _is_label(piece, first) else "sound"
                    elif m.group(3):
                        kind = "sound"
                    else:
                        kind = "word"
                # (a "word" of only punctuation, like "--" or "...", keeps an empty norm and is never matched)
                tok = Tok(ci, ri, piece, kind, norm(piece) if kind == "word" else "")
                out.append(tok)
                if kind != "tag":
                    first = False
    return out


# ------------------------------------------------------------------ matching
def _expected(toks: list[Tok], rough: list[Line]) -> list[float]:
    """Where each word token should be heard according to the rough placement:
    spread over its cue in proportion to the characters before it."""
    exp = [0.0] * len(toks)
    by_cue: dict[int, list[int]] = {}
    for i, t in enumerate(toks):
        if t.kind == "word":
            by_cue.setdefault(t.cue, []).append(i)
    for c, idx in by_cue.items():
        lens = [len(toks[i].text) for i in idx]
        total = sum(lens) + len(lens) - 1
        r = rough[c]
        off = 0
        for i, n in zip(idx, lens):
            exp[i] = r.start + (r.end - r.start) * (off / total if total > 0 else 0.0)
            off += n + 1
    return exp


class _MaxTree:
    """Fenwick tree for prefix maxima of (value, key)."""

    def __init__(self, n):
        self.n = n
        self.t = [(-1.0, None)] * (n + 1)

    def update(self, i, item):  # i is 0-based
        i += 1
        while i <= self.n:
            if item[0] > self.t[i][0]:
                self.t[i] = item
            i += i & -i

    def query(self, i):  # max over 0-based positions < i
        best = (0.0, None)
        while i > 0:
            if self.t[i][0] > best[0]:
                best = self.t[i]
            i -= i & -i
        return best


def match_words(toks: list[Tok], words: list[tuple[float, float, str]], rough: list[Line],
                band: float = 4.0) -> tuple[int, dict[int, int]]:
    """Match subtitle word tokens to Whisper words (in order, within `band` seconds
    of the rough position) and give every word token a time.
    Returns (number matched, {token index: Whisper word index})."""
    import bisect

    from rapidfuzz import fuzz

    exp = _expected(toks, rough)
    wstart = [w[0] for w in words]
    wnorm = [norm(w[2]) for w in words]
    tree = _MaxTree(len(words))
    back: dict[tuple[int, int], tuple[int, int] | None] = {}
    word_idx = [i for i, t in enumerate(toks) if t.kind == "word"]
    for i in word_idx:
        t = toks[i]
        if not t.norm:
            continue
        lo = bisect.bisect_left(wstart, exp[i] - band)
        hi = bisect.bisect_right(wstart, exp[i] + band)
        found = []
        for j in range(lo, hi):
            wn = wnorm[j]
            if not wn:
                continue
            if wn == t.norm:
                s = 1.0
            else:
                s = fuzz.ratio(t.norm, wn) / 100.0
                if s < 0.8:
                    continue
            prev = tree.query(j)
            found.append((j, prev[0] + s, prev[1]))
        for j, v, prev in found:  # update after scoring: one token never matches two words
            back[(i, j)] = prev
            tree.update(j, (v, (i, j)))
    match: dict[int, int] = {}
    key = tree.query(len(words))[1]
    while key is not None:
        match[key[0]] = key[1]
        key = back[key]
    for i, j in match.items():
        t = toks[i]
        t.start, t.end, t.matched = words[j][0], words[j][1], True
    # unmatched words: shift by the interpolated (measured - expected) of their matched neighbours
    pos = [i for i in word_idx]
    m_pos = [k for k, i in enumerate(pos) if i in match]
    for k, i in enumerate(pos):
        if i in match:
            continue
        a = bisect.bisect_left(m_pos, k) - 1
        b = a + 1
        da = (toks[pos[m_pos[a]]].start - exp[pos[m_pos[a]]]) if a >= 0 else 0.0
        db = (toks[pos[m_pos[b]]].start - exp[pos[m_pos[b]]]) if b < len(m_pos) else 0.0
        if a >= 0 and b < len(m_pos):
            f = (k - m_pos[a]) / (m_pos[b] - m_pos[a])
            d = da + f * (db - da)
        else:
            d = 0.0
        d = max(-band, min(band, d))
        toks[i].start = exp[i] + d
    # keep word times strictly increasing; unmatched words never jump over a neighbour
    next_matched: list[float | None] = [None] * len(pos)
    nxt = None
    for k in range(len(pos) - 1, -1, -1):
        next_matched[k] = nxt
        if toks[pos[k]].matched:
            nxt = toks[pos[k]].start
    prev = None
    for k, i in enumerate(pos):
        t = toks[i]
        if not t.matched:
            if prev is not None and t.start <= prev + 1e-3:
                t.start = prev + 0.01
            nxt = next_matched[k]
            if nxt is not None and t.start >= nxt:
                t.start = (prev + nxt) / 2 if prev is not None else nxt - 0.05
            t.end = t.start + max(0.15, 0.06 * len(t.text))
            if nxt is not None:
                t.end = min(t.end, nxt)
        prev = t.start
    return len(match), match


# ------------------------------------------------------------------ retiming
def cue_words(toks: list[Tok]) -> dict[int, list[Tok]]:
    out: dict[int, list[Tok]] = {}
    for t in toks:
        if t.kind == "word" and t.start is not None:
            out.setdefault(t.cue, []).append(t)
    return out


def refine(orig: list[Line], rough: list[Line], toks: list[Tok]) -> tuple[list[Line], dict[int, float], int]:
    """Time each original cue from its first and last spoken word.
    Returns (new cues, {cue: speech end}, number of cues whose start came from words)."""
    from .align import GAP, fix_endings

    by_cue = cue_words(toks)
    new = [Line(r.start, r.end, o.text) for o, r in zip(orig, rough)]
    speech_end: dict[int, float] = {}
    n_timed = 0
    prev_start = None
    for k, r in enumerate(rough):
        ws = by_cue.get(k, [])
        start = r.start
        if ws and any(w.matched for w in ws[:2]):
            cand = ws[0].start
            lo = (prev_start + 0.05) if prev_start is not None else -1e9
            hi = (rough[k + 1].start - 0.05) if k + 1 < len(rough) else 1e9
            if lo <= cand <= hi:
                start = cand
                n_timed += 1
        if ws and any(w.matched for w in ws[-2:]):
            speech_end[k] = ws[-1].end
        dur = r.end - r.start
        new[k].start = start
        new[k].end = max(start + dur, start + 0.5)
        prev_start = start
    # moving a start must not make a cue run over the next one
    for k in range(len(new) - 1):
        a, b = new[k], new[k + 1]
        if b.start > a.start and a.end > b.start - GAP:
            a.end = max(b.start - GAP, a.start + 0.3)
            if a.end > b.start:
                a.end = b.start
    fix_endings(new, [Line(l.start, l.end, l.text) for l in new], speech_end)
    return new, speech_end, n_timed

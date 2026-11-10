"""Re-cutting subtitles ("Tidy up lines").

The timed tokens of the whole file are regrouped into new cues: one sentence (or
a natural part of a long one) per cue, at most two rows of 42 characters.
Words are never added, removed or changed - only where cues and rows break,
and (fix_case) letter case.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, replace

from .align import MAX_DURATION
from .words import Tok

MAX_ROW = 42
MAX_CHARS = 2 * MAX_ROW
# a row or cue never ends on one of these (articles, prepositions, conjunctions, possessives)
STOP = {"a", "an", "the", "of", "to", "in", "on", "at", "for", "and", "or", "but", "with",
        "my", "your", "his", "its", "our", "their"}
ABBREV = {"mr.", "mrs.", "ms.", "dr.", "st.", "jr.", "sr.", "vs.", "prof.", "sgt.", "lt.", "capt.",
          "gen.", "det.", "no.", "mt.", "ft."}
_TAG = re.compile(r"<[^>]*>|\{[^}]*\}")
_END = re.compile(r"[.?!…][\"'”’)\]]*$")
_SOFT = re.compile(r"([,;:]|--|—)[\"'”’]*$")


@dataclass
class Cue:
    toks: list[Tok]
    start: float
    end: float          # last word end (speech end), before fix_endings
    dashed: bool = False


def _bare(t: Tok) -> str:
    return _TAG.sub("", t.text)


def _ends_sentence(t: Tok, nxt: Tok | None) -> bool:
    w = _bare(t)
    if not _END.search(w):
        return False
    low = w.lower()
    if low in ABBREV:
        return False
    letters = re.sub(r"[^a-zA-Z]", "", w)
    if len(letters) == 1 and w.endswith("."):           # an initial: "J."
        return False
    if re.fullmatch(r"([a-zA-Z]\.){2,}", re.sub(r"[\"'”’)\]]+$", "", w)):  # dotted abbreviation "c.H.P."
        return nxt is None or _bare(nxt)[:1].isupper()
    return True


def _words(toks: list[Tok]) -> list[Tok]:
    return [t for t in toks if t.kind == "word"]


def sentences(toks: list[Tok]) -> list[list[Tok]]:
    """Group tokens into sentences: a break after . ? ! … and before a dialogue dash."""
    out: list[list[Tok]] = []
    cur: list[Tok] = []
    ws = [k for k, t in enumerate(toks) if t.kind == "word"]
    next_word = {}
    for a, b in zip(ws, ws[1:] + [None]):
        next_word[a] = toks[b] if b is not None else None
    k = 0
    while k < len(toks):
        t = toks[k]
        if t.kind == "dash" and any(x.kind == "word" for x in cur):
            out.append(cur)
            cur = []
        cur.append(t)
        if t.kind == "word" and _ends_sentence(t, next_word.get(k)):
            # closing tags right after the last word stay with it
            while k + 1 < len(toks) and toks[k + 1].kind == "tag" and toks[k + 1].glue:
                k += 1
                cur.append(toks[k])
            out.append(cur)
            cur = []
        k += 1
    if cur:
        out.append(cur)
    return out


def visible_len(toks: list[Tok]) -> int:
    return len(_TAG.sub("", _join(toks)))


def _join(toks: list[Tok]) -> str:
    s = ""
    for t in toks:
        if t.kind == "dash":
            s += ("" if not s else " ") + t.text
            continue
        s += (t.text if (t.glue or not s) else " " + t.text)
    return s


def _duration(toks: list[Tok]) -> float:
    ws = [t for t in _words(toks) if t.start is not None]
    if not ws:
        return 0.0
    return (ws[-1].end or ws[-1].start) - ws[0].start


def _fits(toks: list[Tok]) -> bool:
    return visible_len(toks) <= MAX_CHARS and _duration(toks) <= MAX_DURATION


def _boundaries(toks: list[Tok]) -> list[int]:
    """Indexes where a cut may go (cut before toks[i]): between two words, never inside a
    glued group, never right after a STOP word."""
    out = []
    for i in range(1, len(toks)):
        t = toks[i]
        if t.glue:
            continue
        prev_words = [x for x in toks[:i] if x.kind == "word"]
        if not prev_words or not any(x.kind == "word" for x in toks[i:]):
            continue
        out.append(i)
    return out


def _last_word(toks: list[Tok]) -> Tok | None:
    for t in reversed(toks):
        if t.kind == "word":
            return t
    return None


def _first_word(toks: list[Tok]) -> Tok | None:
    for t in toks:
        if t.kind == "word":
            return t
    return None


def split_long(sent: list[Tok]) -> list[list[Tok]]:
    """Split a sentence that does not fit one cue: after , ; : or at a pause, else between words."""
    if _fits(sent) or len(_words(sent)) < 2:
        return [sent]
    cands = _boundaries(sent)
    total = visible_len(sent)

    def klass(i):
        lw, fw = _last_word(sent[:i]), _first_word(sent[i:])
        if _SOFT.search(_bare(lw)):
            return 0
        if lw.end is not None and fw.start is not None and fw.start - lw.end >= 0.25:
            return 1
        if _bare(lw).lower().strip(".,;:!?\"'") in STOP:
            return 3
        return 2

    best = None
    for i in cands:
        key = (klass(i), abs(visible_len(sent[:i]) - total / 2))
        if best is None or key < best[0]:
            best = (key, i)
    if best is None:
        return [sent]
    i = best[1]
    return split_long(sent[:i]) + split_long(sent[i:])


_I_FORMS = {"i", "i'm", "i've", "i'll", "i'd"}
_DOTTED = re.compile(r"(?:[a-zA-Z]\.){2,}")


def _upper_at(text: str, letter_positions: set[int]) -> str:
    """Upper-case the n-th letters (counting letters only, inside text without tags)."""
    out, n, in_tag = [], 0, False
    for ch in text:
        if ch in "<{":
            in_tag = True
        if not in_tag and ch.isalpha():
            out.append(ch.upper() if n in letter_positions else ch)
            n += 1
        else:
            out.append(ch)
        if ch in ">}":
            in_tag = False
    return "".join(out)


def fix_case(toks: list[Tok], words, match: dict[int, int]) -> int:
    """Repair letter case (never lowers a letter, never changes a word). Returns tokens changed."""
    from .words import norm

    wtexts = [w[2].strip() for w in words]

    def whisper_initial(j):
        return j == 0 or bool(_END.search(wtexts[j - 1]))

    def set_text(t, new):
        assert new.lower() == t.text.lower()
        if new != t.text:
            t.text = new
            return True
        return False

    touched = set()
    for i, t in enumerate(toks):
        if t.kind != "word":
            continue
        bare = _bare(t).lower().strip(".,;:!?\"'()-–—…")
        new = t.text
        if bare in _I_FORMS:
            new = _upper_at(new, {0})
        if _DOTTED.fullmatch(re.sub(r"[^a-zA-Z.]", "", _bare(t))):
            letters = sum(ch.isalpha() for ch in _bare(t))
            new = _upper_at(new, set(range(letters)))
        j = match.get(i)
        if j is not None and not whisper_initial(j):
            wl = [ch for ch in wtexts[j] if ch.isalpha()]
            if wl and norm(wtexts[j]) == t.norm:
                new = _upper_at(new, {p for p, ch in enumerate(wl) if ch.isupper()})
            elif wl and wl[0].isupper():
                new = _upper_at(new, {0})
        if set_text(t, new):
            touched.add(i)
    # first word of every sentence
    prev = None
    word_idx = [i for i, t in enumerate(toks) if t.kind == "word"]
    for i in word_idx:
        t = toks[i]
        if prev is None or _ends_sentence(prev, t):
            if set_text(t, _upper_at(t.text, {0})):
                touched.add(i)
        prev = t
    return len(touched)


_OPEN = re.compile(r"<\s*([a-zA-Z]+)[^>]*>")
_CLOSE = re.compile(r"<\s*/\s*([a-zA-Z]+)\s*>")


def _balance_tags(pieces: list[list[Tok]]) -> list[list[Tok]]:
    """Inline tags (<i>...</i>) cut by a new cue boundary are closed at the end of the
    cue and reopened at the start of the next one."""
    out = []
    stack: list[Tok] = []  # open tags carried over from earlier pieces
    for p in pieces:
        pre = [replace(t, glue=False) for t in stack]
        body = list(p)
        if pre:
            fw = next((k for k, t in enumerate(body) if t.kind != "tag" or not _CLOSE.fullmatch(t.text)), None)
            if fw is not None:
                body[fw] = replace(body[fw], glue=True)
        for t in p:
            if t.kind != "tag":
                continue
            c = _CLOSE.fullmatch(t.text)
            o = _OPEN.fullmatch(t.text)
            if c:
                for k in range(len(stack) - 1, -1, -1):
                    if _OPEN.fullmatch(stack[k].text).group(1).lower() == c.group(1).lower():
                        del stack[k]
                        break
            elif o:
                stack.append(t)
        post = [Tok(t.cue, t.row, f"</{_OPEN.fullmatch(t.text).group(1)}>", "tag", glue=True) for t in reversed(stack)]
        out.append(pre + body + post)
    return out


def _render(toks: list[Tok], dashed_at: int | None = None) -> str:
    toks = [t for t in toks if t.kind != "dash"]
    pos = [t for t in toks if t.kind == "tag" and t.text.startswith("{")]
    rest = [t for t in toks if not (t.kind == "tag" and t.text.startswith("{"))]
    head = "".join(dict.fromkeys(t.text for t in pos))
    if dashed_at is not None:
        a = [t for t in dashed_at[0] if t.kind != "dash" and not t.text.startswith("{")]
        b = [t for t in dashed_at[1] if t.kind != "dash" and not t.text.startswith("{")]
        return head + "- " + _join(a) + "\n- " + _join(b)
    return head + wrap(rest)


def reshape(orig, rough, toks: list[Tok], words, match) -> tuple[list, dict[int, float], dict]:
    """Regroup the timed tokens of a whole file into new cues (see module docstring).
    Returns (new cues, {new cue: speech end}, stats)."""
    from .align import GAP, MIN_DURATION, SPEECH_TAIL, fix_endings
    from .subtitles import Line

    has_words = {t.cue for t in toks if t.kind == "word"}
    standalone = [k for k in range(len(orig)) if k not in has_words]
    # position tags ({\an8}) belong to the whole original cue
    pos_tags: dict[int, list[Tok]] = {}
    for t in toks:
        if t.kind == "tag" and t.text.startswith("{") and t.cue in has_words:
            pos_tags.setdefault(t.cue, []).append(t)
    capitals = fix_case(toks, words, match)  # match keys are indexes into toks
    stream = [t for t in toks if t.cue in has_words and not (t.kind == "tag" and t.text.startswith("{"))]
    # a sound description that ends its original cue belongs to the sentence before it
    last_real = {}
    for k, t in enumerate(stream):
        if t.kind != "tag":
            last_real[t.cue] = k
    back = {id(stream[k]) for k in last_real.values() if stream[k].kind == "sound"}

    sents = sentences(stream)
    fixed: list[list[Tok]] = []
    for s in sents:
        lead = []
        while s and (id(s[0]) in back or (s[0].kind == "tag" and _CLOSE.fullmatch(s[0].text))):
            lead.append(s.pop(0))
        if lead and fixed:
            fixed[-1].extend(lead)
        elif lead:
            s[:0] = lead
        if s and not any(t.kind == "word" for t in s) and fixed:
            fixed[-1].extend(s)
        elif s:
            fixed.append(s)

    pieces: list[list[Tok]] = []
    for s in fixed:
        pieces.extend(split_long(s))

    # short replies: combine with a neighbour so they don't flash by
    def span(p):
        ws = _words(p)
        return ws[0].start, ws[-1].end

    cues: list[tuple[list[Tok], tuple | None]] = []  # (tokens, (a, b) if dashed)
    k = 0
    while k < len(pieces):
        p = pieces[k]
        s, e = span(p)
        if e - s + SPEECH_TAIL < MIN_DURATION and k + 1 < len(pieces):
            q = pieces[k + 1]
            qs, qe = span(q)
            if visible_len(p) <= MAX_ROW and visible_len(q) <= MAX_ROW and qe - s <= MAX_DURATION:
                if qs - e >= 0.5:
                    cues.append((p + q, (p, q)))
                    k += 2
                    continue
                if visible_len(p + q) <= MAX_CHARS:
                    cues.append((p + q, None))
                    k += 2
                    continue
        if e - s + SPEECH_TAIL < MIN_DURATION and cues and cues[-1][1] is None:
            prev = cues[-1][0]
            ps, _ = span(prev)
            if visible_len(prev) <= MAX_ROW and visible_len(p) <= MAX_ROW and e - ps <= MAX_DURATION \
                    and s - span(prev)[1] < 0.5:
                cues[-1] = (prev + p, None)
                k += 1
                continue
        cues.append((p, None))
        k += 1

    bal = _balance_tags([c[0] for c in cues])
    built = []  # dicts: line, speech_end (None for sound-only cues), from_cues
    for (toks_c, dashed), b in zip(cues, bal):
        src = sorted({t.cue for t in toks_c if t.kind == "word"})
        tags = [t for c in src for t in pos_tags.get(c, [])]
        if dashed:
            q0 = dashed[1][0]  # first token of the reply: _balance_tags keeps it as the same object
            cut = next(i for i, t in enumerate(b) if t is q0)
            text = _render(tags + b, (b[:cut], b[cut:]))
        else:
            text = _render(tags + b)
        s, e = span(toks_c)
        built.append({"line": Line(s, e, text), "speech_end": e, "from": src})
    for k in standalone:
        built.append({"line": Line(rough[k].start, rough[k].end, orig[k].text), "speech_end": None, "from": [k]})
    # file order; a sound-only cue goes before the re-cut cue made from the cues after it
    built.sort(key=lambda b: (b["from"][0], b["speech_end"] is not None))
    new = [b["line"] for b in built]
    speech_end = {k: b["speech_end"] for k, b in enumerate(built) if b["speech_end"] is not None}
    # starts strictly increasing: word-timed cues stay put, sound-only cues give way
    for k in range(1, len(new)):
        if new[k].start >= new[k - 1].start + 0.05:
            continue
        if k not in speech_end:                       # this one is a sound-only cue: move it later
            new[k].start = new[k - 1].start + 0.05
        elif k - 1 not in speech_end:                 # the one before is sound-only: move it earlier
            floor = new[k - 2].start + 0.05 if k >= 2 else 0.0
            new[k - 1].start = max(floor, new[k].start - 0.5)
    for k in range(len(new) - 1):
        a, b = new[k], new[k + 1]
        if a.end > b.start - GAP:
            a.end = max(a.start + 0.05, b.start - GAP)
        if a.end <= a.start:
            a.end = a.start + 0.05
    fix_endings(new, [Line(l.start, l.end, l.text) for l in new], speech_end)
    from_cues = [b["from"] for b in built]
    joined = sum(1 for f in from_cues if len(f) > 1)
    seen: dict[int, int] = {}
    for f in from_cues:
        for c in f:
            seen[c] = seen.get(c, 0) + 1
    split = sum(1 for c, n in seen.items() if n > 1)
    return new, speech_end, {"joined": joined, "split": split, "capitals_fixed": capitals, "from_cues": from_cues}


def wrap(toks: list[Tok]) -> str:
    """At most two rows of MAX_ROW characters, broken at a natural, balanced point."""
    if visible_len(toks) <= MAX_ROW:
        return _join(toks)
    best = None
    for i in _boundaries(toks):
        top, bot = toks[:i], toks[i:]
        a, b = visible_len(top), visible_len(bot)
        lw = _bare(_last_word(top)).lower().strip(".,;:!?\"'")
        cost = abs(a - b) + (3 if a > b else 0)
        cost += 1000 * (max(0, a - MAX_ROW) + max(0, b - MAX_ROW))
        if lw in STOP:
            cost += 500
        if _SOFT.search(_bare(_last_word(top))) or _END.search(_bare(_last_word(top))):
            cost -= 10
        prev, nxt = top[-1], bot[0]
        if (prev.cue, prev.row) != (nxt.cue, nxt.row):
            cost -= 7  # the original captioner broke here too
        if best is None or cost < best[0]:
            best = (cost, i)
    if best is None:
        return _join(toks)
    i = best[1]
    return _join(toks[:i]) + "\n" + _join(toks[i:])

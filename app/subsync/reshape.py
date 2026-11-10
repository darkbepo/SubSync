"""Re-cutting subtitles ("Tidy up lines").

The timed tokens of the whole file are regrouped into new cues: one sentence (or
a natural part of a long one) per cue, at most two rows of 42 characters.
Words are never added, removed or changed - only where cues and rows break,
and (fix_case) letter case.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

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

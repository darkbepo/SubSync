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

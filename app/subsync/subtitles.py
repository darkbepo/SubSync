"""Subtitle reading/writing. SRT is parsed by hand so the original text and
formatting tags come back out exactly as they went in."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass

SUB_EXTS = {".srt", ".ass", ".ssa", ".vtt"}

_TIME = re.compile(
    r"(\d{1,2}):(\d{1,2}):(\d{1,2})[,.](\d{1,3})\s*-->\s*(\d{1,2}):(\d{1,2}):(\d{1,2})[,.](\d{1,3})"
)


@dataclass
class Line:
    start: float
    end: float
    text: str  # original text, lines joined with "\n"


def read_text(path: str) -> str:
    raw = open(path, "rb").read()
    for bom, enc in ((b"\xef\xbb\xbf", "utf-8-sig"), (b"\xff\xfe", "utf-16"), (b"\xfe\xff", "utf-16")):
        if raw.startswith(bom):
            return raw.decode(enc)
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("cp1252", errors="replace")


def _t(h, m, s, ms) -> float:
    ms = (ms + "00")[:3]
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0


def parse_srt(text: str) -> list[Line]:
    rows = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    marks = [(i, m) for i, r in enumerate(rows) if (m := _TIME.search(r))]
    out: list[Line] = []
    for k, (i, m) in enumerate(marks):
        stop = marks[k + 1][0] if k + 1 < len(marks) else len(rows)
        body = rows[i + 1:stop]
        # drop the next block's index number and trailing blank lines
        while body and not body[-1].strip():
            body.pop()
        if k + 1 < len(marks) and body and body[-1].strip().isdigit():
            body.pop()
            while body and not body[-1].strip():
                body.pop()
        g = m.groups()
        start, end = _t(*g[:4]), _t(*g[4:])
        if end < start:
            end = start + 1.0
        out.append(Line(start, end, "\n".join(r.rstrip() for r in body)))
    return out


def load(path: str) -> list[Line]:
    ext = os.path.splitext(path)[1].lower()
    if ext == ".srt":
        lines = parse_srt(read_text(path))
    else:
        import pysubs2

        subs = pysubs2.SSAFile.from_string(read_text(path))
        lines = parse_srt(subs.to_string("srt"))
        lines.sort(key=lambda l: l.start)
    # SRT: keep the file's own numbering order - it is the spoken order even
    # when a badly shifted section makes start times overlap
    return lines


def _fmt(t: float) -> str:
    ms = max(0, int(round(t * 1000)))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def to_srt(lines: list[Line]) -> str:
    parts = []
    for n, l in enumerate(lines, 1):
        parts.append(f"{n}\r\n{_fmt(l.start)} --> {_fmt(l.end)}\r\n{l.text.replace(chr(10), chr(13) + chr(10))}\r\n")
    return "\r\n".join(parts)


_TAGS = re.compile(r"<[^>]*>|\{[^}]*\}")
_HI = re.compile(r"\[[^\]]*\]|\([^)]*\)|[♪♫#]+")
_SPEAKER = re.compile(r"^\s*[A-Z][A-Z0-9 .'\-]{1,24}:\s*", re.M)
_DASH = re.compile(r"^\s*[-–—]\s*", re.M)


def speech_text(text: str) -> str | None:
    """The spoken words of a subtitle line, or None for sound effects / music cues."""
    t = _TAGS.sub(" ", text)
    t = t.replace("\\N", " ")
    t = _HI.sub(" ", t)
    t = _SPEAKER.sub("", t)
    t = _DASH.sub("", t)
    t = re.sub(r"\s+", " ", t).strip()
    if sum(ch.isalpha() for ch in t) < 2:
        return None
    return t

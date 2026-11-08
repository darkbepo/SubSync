"""Sort dropped files into videos and subtitles and pair them up."""
from __future__ import annotations

import os
import re

from .media import VIDEO_EXTS
from .subtitles import SUB_EXTS

_EP = re.compile(r"(?i)\bs(\d{1,2})[ ._-]?e(\d{1,3})\b|\b(\d{1,2})x(\d{2,3})\b")
_TAIL = re.compile(r"(?i)([._ -](en|eng|english|sdh|hi|cc|forced|full|default|#\d+|\d{1,2}))+$")


def expand(paths: list[str]) -> tuple[list[str], list[str]]:
    videos, subs = [], []
    for p in paths:
        if os.path.isdir(p):
            for dp, _, files in os.walk(p):
                for f in sorted(files):
                    _classify(os.path.join(dp, f), videos, subs)
        else:
            _classify(p, videos, subs)
    return videos, subs


def _classify(p, videos, subs):
    ext = os.path.splitext(p)[1].lower()
    if ext in VIDEO_EXTS:
        videos.append(os.path.normpath(p))
    elif ext in SUB_EXTS:
        subs.append(os.path.normpath(p))


def _stem(p: str) -> str:
    return os.path.splitext(os.path.basename(p))[0]


def sub_key(p: str) -> str:
    return _TAIL.sub("", _stem(p)).lower()


def episode(p: str):
    m = _EP.search(_stem(p))
    if not m:
        return None
    a, b = (m.group(1), m.group(2)) if m.group(1) else (m.group(3), m.group(4))
    return int(a), int(b)


def _english_rank(p: str) -> int:
    s = _stem(p).lower()
    if re.search(r"[._ -](en|eng|english)([._ -]|$)", s):
        return 0
    if re.search(r"[._ -][a-z]{2,3}$", s):  # some other language tag
        return 2
    return 1


def pair(videos: list[str], subs: list[str]) -> list[tuple[str | None, str | None]]:
    """Returns rows of (video, subtitle); either side may be None if unmatched."""
    from rapidfuzz import fuzz

    vids = list(dict.fromkeys(videos))
    pending = sorted(dict.fromkeys(subs), key=_english_rank)
    rows: dict[str, str] = {}

    def take(v, s):
        rows[v] = s
        pending.remove(s)

    # 1. same name (Movie.mkv <-> Movie.en.srt)
    for s in list(pending):
        k = sub_key(s)
        for v in vids:
            if v not in rows and _stem(v).lower() == k:
                take(v, s)
                break
    # 2. same episode number (S01E04 / 1x04)
    for s in list(pending):
        e = episode(s)
        if not e:
            continue
        cands = [v for v in vids if v not in rows and episode(v) == e]
        if len(cands) == 1:
            take(cands[0], s)
    # 3. one of each left -> they belong together
    free = [v for v in vids if v not in rows]
    if len(free) == 1 and len(pending) == 1:
        ev, es = episode(free[0]), episode(pending[0])
        if not (ev and es and ev != es):
            take(free[0], pending[0])
    # 4. closest names
    for s in list(pending):
        free = [v for v in vids if v not in rows]
        if not free:
            break
        e = episode(s)
        best = max(free, key=lambda v: fuzz.token_set_ratio(_stem(v).lower(), sub_key(s)))
        if fuzz.token_set_ratio(_stem(best).lower(), sub_key(s)) >= 80 and (not e or not episode(best) or episode(best) == e):
            take(best, s)

    out: list[tuple[str | None, str | None]] = [(v, rows.get(v)) for v in vids]
    out += [(None, s) for s in pending]
    return out

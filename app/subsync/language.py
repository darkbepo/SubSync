"""Which language a subtitle is in (1.5.0: English or Danish), and how results are named.

The language comes from the file name when it says so (Show.S01E01.da.srt, .dan, .danish,
.dansk / .en, .eng, .english), otherwise from the text with a cautious check: a subtitle is
only taken for Danish when common Danish words clearly outnumber common English ones. When
in doubt it stays English, so English subtitles behave exactly as before.
"""
from __future__ import annotations

import os
import re

SUPPORTED = ("en", "da")
THREE = {"en": "eng", "da": "dan"}  # 3-letter names for results (.eng.srt / .dan.srt)

_TAGS = {
    "da": re.compile(r"(?i)[._ \-\[(](da|dan|danish|dansk)(?=[._ \-\])]|$)"),
    "en": re.compile(r"(?i)[._ \-\[(](en|eng|english)(?=[._ \-\])]|$)"),
}
_DA_WORDS = set("ikke jeg og det er til med hvad hvor der ham hun mig dig skal kan være har også nej tak godt "
                "hvorfor hvordan hvem noget nogen ingen meget måske lige bare så nu her vi de jer os".split())
_EN_WORDS = set("the and you to is it that of what this have was are not with for don't i'm it's".split())


def from_name(path: str) -> str | None:
    """Language named in the file name (the part after the video name), or None."""
    stem = os.path.splitext(os.path.basename(path))[0]
    found = [(m.start(), lang) for lang, rx in _TAGS.items() for m in rx.finditer(stem)]
    return max(found)[1] if found else None  # the last tag wins: Show.English.Title.da.srt is Danish


def from_text(lines) -> str | None:
    """'da' when the text is clearly Danish, otherwise None (meaning: don't know)."""
    from .subtitles import speech_text

    da = en = 0
    for l in lines[:400]:
        t = speech_text(l.text)
        if not t:
            continue
        for w in re.findall(r"[a-zæøå']+", t.lower()):
            da += w in _DA_WORDS
            en += w in _EN_WORDS
    return "da" if da >= 30 and da > 3 * en else None


def resolve(path: str, lines, wanted: str | None = None) -> str:
    """The subtitle's language: wanted ('en' / 'da') if given, else from the name, else the text."""
    if wanted in SUPPORTED:
        return wanted
    return from_name(path) or from_text(lines) or "en"


def suffix(lang: str, style: str = ".en") -> str:
    """Result name suffix: '.en' / '.eng' style (the suffix setting) for the subtitle's language."""
    three = style.lstrip(".").lower() in ("eng", "dan")
    return "." + (THREE.get(lang, lang) if three else lang)

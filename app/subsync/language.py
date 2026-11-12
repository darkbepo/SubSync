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

# language tags at the end of a file name: Show.S01E01.da.srt, .dan.hi.srt, [da]. Danish tags must be
# set off by a dot, underscore or bracket, so a title word ("Meet Dan", "Show - Dan") isn't one
_LANG_TAG = {"da": "da", "dan": "da", "danish": "da", "dansk": "da", "en": "en", "eng": "en", "english": "en"}
_OTHER_TAG = re.compile(r"(?i)^(sdh|hi|cc|forced|full|default|#\d+|\d{1,2})$")
_PIECE = re.compile(r"([._ \-\[\]()]+)([^._ \-\[\]()]+)$")

_DA_WORDS = set("ikke jeg og det er til med hvad hvor der ham hun mig dig skal kan være har også nej tak godt "
                "hvorfor hvordan hvem noget nogen ingen meget måske lige bare så nu her vi de jer os".split())
_EN_WORDS = set("the and you to is it that of what this have was are not with for don't i'm it's".split())


def from_name(path: str) -> str | None:
    """Language tag at the end of the file name (only the trailing tags: .da.hi.srt is Danish,
    The.Danish.Girl.2015.srt has none), or None."""
    rest = os.path.splitext(os.path.basename(path))[0]
    while True:
        closed = rest.endswith((")", "]"))
        rest = rest.rstrip(")]")
        m = _PIECE.search(rest)
        if not m:
            return None
        sep, word = m.group(1), m.group(2).lower()
        lang = _LANG_TAG.get(word)
        if lang and (lang == "en" or closed or set(sep) & set("._[(")):
            return lang
        if not _OTHER_TAG.match(word):
            return None
        rest = rest[:m.start()]


def from_text(lines) -> str | None:
    """'da' when the text is clearly Danish, 'en' when clearly English, otherwise None."""
    from .subtitles import speech_text

    da = en = 0
    for l in lines[:400]:
        t = speech_text(l.text)
        if not t:
            continue
        for w in re.findall(r"[a-zæøå']+", t.lower()):
            da += w in _DA_WORDS
            en += w in _EN_WORDS
    if da >= 30 and da > 3 * en:
        return "da"
    if en >= 30 and en > 3 * da:
        return "en"
    return None


def resolve(path: str, lines, wanted: str | None = None) -> str:
    """The subtitle's language: wanted ('en' / 'da') if given, else the name's tag, else the
    text, else English. A name that says Danish on clearly English text is English."""
    if wanted in SUPPORTED:
        return wanted
    name, text = from_name(path), from_text(lines)
    if name == "da" and text == "en":
        return "en"
    return name or text or "en"


def suffix(lang: str, style: str = ".en") -> str:
    """Result name suffix: '.en' / '.eng' style (the suffix setting) for the subtitle's language."""
    three = style.lstrip(".").lower() in ("eng", "dan")
    return "." + (THREE.get(lang, lang) if three else lang)

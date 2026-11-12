"""Audio track selection and fast decoding to 16 kHz mono (what Whisper wants)."""
from __future__ import annotations

import numpy as np

VIDEO_EXTS = {".mkv", ".mp4", ".m4v", ".avi", ".mov", ".wmv", ".ts", ".m2ts", ".mts",
              ".webm", ".flv", ".mpg", ".mpeg", ".vob", ".ogm"}

# ISO 639-2 -> Whisper (639-1) codes for track-language tags
_ISO2 = {"eng": "en", "dan": "da", "ger": "de", "deu": "de", "fre": "fr", "fra": "fr", "spa": "es",
         "ita": "it", "jpn": "ja", "kor": "ko", "chi": "zh", "zho": "zh", "swe": "sv", "nor": "no",
         "nob": "no", "fin": "fi", "dut": "nl", "nld": "nl", "por": "pt", "rus": "ru", "pol": "pl",
         "tur": "tr", "hin": "hi", "ara": "ar", "vie": "vi", "tha": "th", "cze": "cs", "ces": "cs",
         "hun": "hu", "gre": "el", "ell": "el", "heb": "he", "ukr": "uk", "ind": "id", "may": "ms",
         "msa": "ms", "tgl": "tl", "fil": "tl", "rum": "ro", "ron": "ro", "ice": "is", "isl": "is"}


def lang_code(tag: str | None) -> str | None:
    if not tag:
        return None
    t = tag.lower().strip()
    if len(t) == 2:
        return t
    return _ISO2.get(t)


def pick_audio_stream(path: str):
    """Returns (stream_index, whisper_language_or_None, duration_seconds).
    Prefers an English track (matching is most precise when the audio is in the
    subtitle's language), then the default track, then the first."""
    import av

    with av.open(path) as c:
        streams = list(c.streams.audio)
        if not streams:
            raise RuntimeError("This video has no audio track")
        dur = float(c.duration / 1e6) if c.duration else 0.0

        def info(s):
            lang = lang_code(s.metadata.get("language"))
            try:
                default = bool(s.disposition & av.stream.Disposition.default)
            except Exception:
                default = False
            try:
                commentary = bool(s.disposition & av.stream.Disposition.comment)
            except Exception:
                commentary = False
            title = (s.metadata.get("title") or "").lower()
            commentary = commentary or "comment" in title or "description" in title
            return lang, default, commentary

        scored = []
        for n, s in enumerate(streams):
            lang, default, comm = info(s)
            score = (0 if comm else 4) + (2 if lang == "en" else 0) + (1 if default else 0)
            scored.append((score, -n, n, lang))
        scored.sort(reverse=True)
        _, _, n, lang = scored[0]
        if not dur and streams[n].duration and streams[n].time_base:
            dur = float(streams[n].duration * streams[n].time_base)
        return n, lang, dur


def _resampler(st):
    """(resampler, channel names, centre) for one audio stream: 16 kHz, and for 5.1/7.1 all
    channels so _mix() can weight the centre channel up, otherwise mono."""
    import av

    names = []
    try:
        names = [ch.name for ch in st.layout.channels]
    except Exception:
        pass
    centre = "FC" in names and len(names) >= 6
    try:
        res = av.AudioResampler(format="fltp", layout=st.layout if centre else "mono", rate=16000)
    except Exception:
        centre = False
        res = av.AudioResampler(format="fltp", layout="mono", rate=16000)
    return res, names, centre


def _mix(chunks, names, centre) -> np.ndarray:
    a = np.concatenate(chunks, axis=1)
    if centre:
        fc, fl, fr = names.index("FC"), names.index("FL"), names.index("FR")
        a = a[fc] + 0.35 * (a[fl] + a[fr])
        peak = float(np.max(np.abs(a))) or 1.0
        a = a / max(peak, 1e-4) * 0.9 if peak > 1.0 else a
    else:
        a = a[0]
    return np.ascontiguousarray(a, dtype=np.float32)


def decode(path: str, audio_n: int, cancelled=lambda: False) -> np.ndarray:
    """Decode one audio track to float32 16 kHz mono.  For 5.1/7.1 tracks the
    centre channel (where dialogue lives) is weighted up, which gives Whisper a
    cleaner voice signal than a plain downmix."""
    import av

    with av.open(path) as c:
        st = c.streams.audio[audio_n]
        st.thread_type = "AUTO"
        res, names, centre = _resampler(st)
        chunks = []
        n = 0
        for frame in c.decode(st):
            frame.pts = None
            for f in res.resample(frame):
                chunks.append(f.to_ndarray())
            n += 1
            if n % 2000 == 0 and cancelled():
                raise InterruptedError
        for f in res.resample(None):
            chunks.append(f.to_ndarray())
    if not chunks:
        raise RuntimeError("Could not decode any audio")
    return _mix(chunks, names, centre)


class SeekError(RuntimeError):
    """The file can't be jumped into (decode_window with must_seek)."""


def decode_window(path: str, audio_n: int, start: float, length: float, must_seek: bool = False) -> np.ndarray:
    """Decode length seconds of one audio track, from start seconds after the track's first
    sample (the same position as in decode()'s output). Jumps there when the file allows it;
    otherwise raises SeekError with must_seek, or reads up to it. May return less audio near
    the end of the file, or an empty array.

    Timestamps in a file need not start at zero (TV recordings often start at hours), so the
    track's own start time is added for the jump and taken off every frame's time."""
    import av

    with av.open(path) as c:
        st = c.streams.audio[audio_n]
        st.thread_type = "AUTO"
        res, names, centre = _resampler(st)
        if st.start_time is not None and st.time_base:
            base = float(st.start_time * st.time_base)
        elif c.start_time is not None:
            base = c.start_time / 1_000_000
        else:
            base = 0.0
        if start > 0:
            try:
                c.seek(int((base + start) * 1_000_000), any_frame=False, backward=True)  # µs, absolute
            except Exception as e:
                if must_seek:
                    raise SeekError(str(e)) from e
                # can't jump: decode from the start and skip what comes before
        chunks = []
        have = 0
        need = int(length * 16000)
        for frame in c.decode(st):
            t = None if frame.time is None else frame.time - base
            if t is not None and t + frame.samples / (frame.sample_rate or 16000) <= start:
                continue
            frame.pts = None
            for f in res.resample(frame):
                a = f.to_ndarray()
                if t is not None and t < start and not chunks:  # first frame starts before the window
                    a = a[:, min(a.shape[1], int((start - t) * 16000)):]
                chunks.append(a)
                have += a.shape[1]
            if have >= need:
                break
    if not chunks:
        return np.zeros(0, dtype=np.float32)
    return _mix(chunks, names, centre)[:need]

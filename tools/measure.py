"""Developer tool: how well do a subtitle's cues line up with the words Whisper heard?

    python tools\\measure.py TRANSCRIPT.json.gz RESULT.srt

Aligns all spoken words of the subtitle with the transcript in one global pass
(difflib; independent of SubSync's own word matching) and reports, per cue,
the distance between its start and its first spoken word, and whether it
disappears before its last word has been said.
"""
import difflib
import gzip
import json
import os
import re
import statistics
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app"))
from subsync import subtitles  # noqa: E402


def norm(w):
    return re.sub(r"[^a-z0-9']", "", w.replace("’", "'").lower()).strip("'")


def main(transcript, result):
    words = json.load(gzip.open(transcript, "rt", encoding="utf-8"))["words"]
    cues = subtitles.load(result)
    wt = [norm(w[2]) for w in words]
    st, owner = [], []
    for k, c in enumerate(cues):
        for t in (subtitles.speech_text(c.text) or "").split():
            if norm(t):
                st.append(norm(t))
                owner.append(k)
    hit = {}
    for a, b, n in difflib.SequenceMatcher(None, st, wt, autojunk=False).get_matching_blocks():
        for q in range(n):
            hit[a + q] = b + q
    per = {}
    for q, k in enumerate(owner):
        per.setdefault(k, []).append(hit.get(q))
    starts, ends, late, early, cut = [], [], 0, 0, 0
    for k, hs in per.items():
        if sum(h is not None for h in hs) < max(2, 0.6 * len(hs)):
            continue
        c = cues[k]
        if hs[0] is not None:
            d = c.start - words[hs[0]][0]
            starts.append(d)
            late += d > 0.5
            early += d < -0.5
        if hs[-1] is not None:
            e = words[hs[-1]][1]
            ends.append(c.end - e)
            nxt = cues[k + 1].start if k + 1 < len(cues) else 1e9
            if c.end < e - 0.3 and nxt >= e:
                cut += 1
    rows = [len(c.text.split("\n")) for c in cues]
    overlaps = sum(cues[k].end > cues[k + 1].start + 1e-3 for k in range(len(cues) - 1))
    a = [abs(x) for x in starts]
    print(f"cues: {len(cues)}  measured starts: {len(starts)}")
    print(f"starts within 0.3 s of first word: {sum(x <= 0.3 for x in a) / len(a):.1%}   "
          f"median {statistics.median(starts):+.2f} s   >0.5 s late: {late}   >0.5 s early: {early}")
    print(f"cues gone >0.3 s before their last word (next cue not yet started): {cut}")
    print(f"overlapping cues: {overlaps}   cues with >2 rows: {sum(r > 2 for r in rows)}   "
          f"longest row: {max(len(r) for c in cues for r in c.text.split(chr(10)))} chars")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])

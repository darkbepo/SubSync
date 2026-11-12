"""Per-line details for troubleshooting: logs\\details\\<video name>.tsv, one row per
written subtitle (where it came from, old and new time, matched words, what changed)."""
from __future__ import annotations

import os

from . import paths

KEEP = 200


def write(video_path: str, rows: list[dict], lang: str = "en") -> str:
    """lang: the subtitle's language; a non-English one gets its own file (<video>.da.tsv)."""
    folder = os.path.join(paths.LOGS, "details")
    os.makedirs(folder, exist_ok=True)
    out = os.path.join(folder, os.path.splitext(os.path.basename(video_path))[0] + ("" if lang == "en" else f".{lang}") + ".tsv")
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        f.write("new\tfrom original\torig start\tnew start\tnew end\twords\tmatched\tchanges\n")
        for r in rows:
            orig = "" if r["orig_start"] is None else f"{r['orig_start']:.3f}"
            f.write(f"{r['n']}\t{','.join(str(c) for c in r['from_cues'])}\t{orig}\t{r['start']:.3f}\t"
                    f"{r['end']:.3f}\t{r['words']}\t{r['matched']}\t{'; '.join(r['changes'])}\n")
    files = sorted((os.path.join(folder, n) for n in os.listdir(folder) if n.endswith(".tsv")),
                   key=os.path.getmtime, reverse=True)
    for old in files[KEEP:]:
        if os.path.abspath(old) != os.path.abspath(out):
            try:
                os.remove(old)
            except OSError:
                pass
    return out

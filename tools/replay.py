"""Developer tool: re-run SubSync's matching on a video whose transcript is already cached.

Run with the installed SubSync's own Python, e.g.
    D:\\Tools\\SubSync\\runtime\\python\\python.exe tools\\replay.py D:\\Tools\\SubSync VIDEO SUBTITLE OUT.srt [--keep-layout]

Uses the code from this repository (not the copy inside the installed folder),
the installed models and the transcript cache, so a change can be tried in seconds
without rebuilding the exe or running speech recognition again.
"""
import argparse
import gzip
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("root", help="installed SubSync folder (has runtime, models, cache)")
    ap.add_argument("video")
    ap.add_argument("subtitle")
    ap.add_argument("out")
    ap.add_argument("--keep-layout", action="store_true")
    a = ap.parse_args()
    os.environ["SUBSYNC_ROOT"] = os.path.abspath(a.root)
    sys.path.insert(0, os.path.join(REPO, "app"))
    from subsync import paths, pipeline, subtitles
    from subsync.embed import Embedder
    from subsync.media import pick_audio_stream

    audio_n, _, _ = pick_audio_stream(a.video)
    cache = pipeline._cache_file(a.video, audio_n)
    if not os.path.exists(cache):
        sys.exit(f"No cached transcript for this video ({cache}). Sync it once with SubSync first.")
    with gzip.open(cache, "rt", encoding="utf-8") as f:
        c = json.load(f)
    lines = subtitles.load(a.subtitle)
    p = pipeline.process(lines, [tuple(w) for w in c["words"]], c["lang"], Embedder(paths.MINILM_DIR),
                         tidy=not a.keep_layout)
    if not p.res.ok:
        sys.exit("No result: " + p.res.reason)
    with open(a.out, "w", encoding="utf-8", newline="") as f:
        f.write(subtitles.to_srt(p.lines))
    print(f"transcript: {cache}")
    print(json.dumps(p.stats))


if __name__ == "__main__":
    main()

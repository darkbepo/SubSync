"""Check a synced subtitle for lines that are hard or impossible to see.

    python check_srt.py RESULT.srt [ORIGINAL.srt]
    python check_srt.py "D:\\Shows\\The Mentalist\\Season 1"      (every .srt in the folder)

Lists subtitles shown for less than 0.7 s (they flash by and look like missing lines), ones that
end before they start, and ones that start before the previous one. With the original subtitle
as well, it also checks that every word is still there, in the same order.

Needs only Python (no SubSync files), for example an installed SubSync's
runtime\\python\\python.exe. Changes nothing.
"""
import os
import re
import sys

TIME = re.compile(r"(\d+):(\d\d):(\d\d)[,.](\d{1,3})\s*-->\s*(\d+):(\d\d):(\d\d)[,.](\d{1,3})")
SHORT = 0.7


def read(path):
    raw = open(path, "rb").read()
    for bom, enc in ((b"\xef\xbb\xbf", "utf-8-sig"), (b"\xff\xfe", "utf-16"), (b"\xfe\xff", "utf-16")):
        if raw.startswith(bom):
            return raw.decode(enc)
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("cp1252", errors="replace")


def cues(path):
    rows = read(path).replace("\r\n", "\n").replace("\r", "\n").split("\n")
    marks = [(i, m) for i, r in enumerate(rows) if (m := TIME.search(r))]
    # the same rule as SubSync (subtitles.parse_srt): a number right before a timing line is
    # that block's number only in a file where most timing lines have one
    numbered = sum(1 for i, _ in marks if i > 0 and rows[i - 1].strip().isdigit()) * 2 > len(marks) > 0
    out = []
    for k, (i, m) in enumerate(marks):
        body = rows[i + 1:(marks[k + 1][0] if k + 1 < len(marks) else len(rows))]
        if numbered and k + 1 < len(marks) and body and body[-1].strip().isdigit():
            body.pop()
        while body and not body[-1].strip():
            body.pop()
        g = m.groups()
        t = lambda h, mi, s, ms: int(h) * 3600 + int(mi) * 60 + int(s) + int(ms.ljust(3, "0")[:3]) / 1000
        out.append((t(*g[:4]), t(*g[4:]), " / ".join(r.strip() for r in body if r.strip())))
    return out


def words(cs):
    return [w for _, _, text in cs for w in re.findall(r"[^\W_]+(?:'[^\W_]+)?", re.sub(r"<[^>]*>|\{[^}]*\}", " ", text).lower())]


def stamp(t):
    return f"{int(t // 3600)}:{int(t % 3600 // 60):02d}:{t % 60:06.3f}"


def check(path, original=None):
    cs = cues(path)
    problems = []
    for n, (a, b, text) in enumerate(cs, 1):
        if b <= a:
            problems.append(f"  #{n} {stamp(a)}  ends before it starts: {text[:60]}")
        elif b - a < SHORT:
            problems.append(f"  #{n} {stamp(a)}  shown only {b - a:.2f} s: {text[:60]}")
        if n > 1 and a < cs[n - 2][0] - 0.001:
            problems.append(f"  #{n} {stamp(a)}  starts before #{n - 1}: {text[:60]}")
    if original:
        w0, w1 = words(cues(original)), words(cs)
        if w0 != w1:
            i = next((k for k, (x, y) in enumerate(zip(w0, w1)) if x != y), min(len(w0), len(w1)))
            problems.append(f"  words differ from the original ({len(w0)} -> {len(w1)} words); first difference at word {i + 1}: "
                            f"{' '.join(w0[max(0, i - 3):i + 4])!r} vs {' '.join(w1[max(0, i - 3):i + 4])!r}")
        else:
            print(f"  every word of the original is there, in order ({len(w0)} words)")
    print(f"{os.path.basename(path)}: {len(cs)} subtitles, " + (f"{len(problems)} problem(s)" if problems else "no problems"))
    for p in problems:
        print(p)
    return len(problems)


def main(args):
    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    if os.path.isdir(args[0]):
        found = 0
        for base, _, files in os.walk(args[0]):
            for f in sorted(files):
                if f.lower().endswith(".srt"):
                    found += check(os.path.join(base, f))
        return 1 if found else 0
    return 1 if check(args[0], args[1] if len(args) > 1 else None) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

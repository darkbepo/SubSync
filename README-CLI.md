# SubSync command line (`subsync-cli.exe`)

For developers and scripts. `subsync-cli.exe` does the same work as the SubSync window, without a window, so you can run it from a terminal, a scheduled task, or as a post-processing step in another program.

It sits next to `SubSync.exe` in the same folder and **shares the same installation**: models, libraries, transcript cache, logs and the GPU batch-size setting. Either program can do the first-time setup.

---

## Quick start

```bat
cd /d D:\Tools\SubSync
subsync-cli setup                         :: one-time download (≈3.2 GB), with text progress
subsync-cli sync "D:\Shows\My Show\Season 1"
```

Paths are resolved against the **current directory**, so you can also run it from anywhere:

```bat
cd /d "D:\Shows\My Show\Season 1"
D:\Tools\SubSync\subsync-cli.exe .
```

## Commands

| Command | What it does |
|---|---|
| `subsync-cli sync <files or folders…> [options]` | Pair videos with subtitles and sync them. |
| `subsync-cli <files or folders…> [options]` | Shorthand for `sync`. |
| `subsync-cli setup` | Download everything (first time) or repair missing/damaged files. |
| `subsync-cli check` | Report whether the installation is complete and intact. Downloads nothing. |
| `subsync-cli version` | Print the version. |
| `subsync-cli help` | Print usage. |

`sync` runs the same self-check as the window first, and downloads or repairs automatically if needed.

## `sync` options

| Option | Meaning |
|---|---|
| `<files or folders…>` | Any mix of videos, subtitles and folders (searched recursively). Pairing works like the window: same name (`Movie.mkv` ↔ `Movie.en.srt`), then same episode code (`S01E04` / `1x04`), then closest name. |
| `--pair VIDEO SUBTITLE` | Sync this exact pair. Repeatable. Files given here are left out of automatic pairing. |
| `--suffix en` / `--suffix eng` | Result name `<video>.en.srt` (default) or `<video>.eng.srt`. |
| `--overwrite` | Replace an existing result. Without it the existing file is kept and the result is `<video>.en.#1.srt` (`#2`, …). If the existing file is open in another program, SubSync waits up to 5 minutes for it to be released. |
| `--keep-layout` | Turn *Tidy up lines* off: keep the original line layout and capitals. The timing is still fixed line by line. (The window's setting does not affect the command line; tidying is on unless this option is given.) |
| `--cpu` | Don't use the NVIDIA GPU (slower; for testing, or if the GPU is busy). |
| `--report FILE.json` | Write a machine-readable report (format below). |

Supported inputs: videos `.mkv .mp4 .m4v .avi .mov .wmv .ts .m2ts .mts .webm .flv .mpg .mpeg .vob .ogm`; subtitles `.srt .ass .ssa .vtt` (English). Results are always `.srt` (UTF-8), written **next to the video**.

## Output

Before starting, the CLI lists every pair it will sync and every file it couldn't pair, so you see the plan up front. Then there is one line per result:

```
SubSync 2026-11-08 20:15: 3 pair(s) to sync, 1 file(s) without a partner
    1. Show.S01E01.1080p.mkv  <-  Show.S01E01.en.srt
    2. Show.S01E02.1080p.mkv  <-  Show S01E02 WEB-DL.srt
    3. Show.S01E03.1080p.mkv  <-  Show.S01E03.srt
   skip Show.S01E04.1080p.mkv  (no matching subtitle)
Speech recognition: GPU (NVIDIA GeForce RTX 3050)
OK   [1/3] Show.S01E01.1080p.mkv -> Show.S01E01.1080p.en.srt  (612/640 lines matched, shift -2.1..+0.4 s, 2 section(s), 14 ending(s) extended, 668 -> 655 subtitles)
SKIP [2/3] Show.S01E02.1080p.mkv: Only 9 of 655 lines matched the audio – wrong subtitle for this video?  (no file written)
FAIL [3/3] Show.S01E03.1080p.mkv: Could not read the audio: …
Done in 4m 12s: 1 synced, 1 did not match their video, 1 failed, 1 without a partner.
Details: D:\Tools\SubSync\logs\cli.log
```

- **OK**: synced and saved. *shift* is how far lines moved. More than one *section* means the file was partly out of sync. *Endings extended* counts lines kept on screen until their words were spoken or long enough to read. *before -> after subtitles* appears when *Tidy up lines* changed the number of subtitles.
- **SKIP**: too few lines matched the speech, almost always the wrong subtitle (another episode, cut or language). Nothing is written.
- **FAIL**: an error, with the reason. The full error is in `logs\cli.log`.

In an interactive terminal a single status line shows the current file, stage, progress and remaining time. When output is redirected to a file or pipe, only the result lines are printed.

## Exit codes

| Code | Meaning | What to do |
|---|---|---|
| `0` | Every pair was synced. | Nothing. |
| `3` | Some pairs synced; others failed or didn't match their video. | See the `SKIP`/`FAIL` lines, the report, or `logs\cli.log`. |
| `4` | No pair could be synced. | Same as 3. |
| `5` | No video + subtitle pairs were found in the given paths. | Check the paths/names, or use `--pair`. |
| `6` | Invalid command line: unknown option, file not found, unsupported file type. | The message says which. |
| `7` | SubSync's own files could not be downloaded/repaired, or repair isn't possible right now because another SubSync (window or command line) is using the folder. | Check the internet connection, or close the other SubSync, and run again. Finished downloads are kept. |
| `8` | (`check` only) The installation is incomplete or damaged. | Run `subsync-cli setup`. |
| `9` | Stopped with Ctrl+C. | |
| `10` | Unexpected error inside SubSync (a bug, or a crash in a library). | Send `logs\cli.log` (and `logs\worker.log`). |

Every error is printed with its reason, written to `logs\cli.log`, and included in the JSON report, so the exit code only tells a script *whether* to look; the details say *what* happened.

## JSON report (`--report`)

```json
{
  "subsync_version": "1.2.0",
  "finished": "2026-11-08T20:19:27",
  "exit_code": 3,
  "seconds": 252.4,
  "summary": { "synced": 1, "no_match": 1, "failed": 1, "cancelled": 0, "skipped": 1 },
  "items": [
    {
      "video": "D:\\Shows\\Show.S01E01.1080p.mkv",
      "subtitle": "D:\\Shows\\Show.S01E01.en.srt",
      "status": "synced",
      "output": "D:\\Shows\\Show.S01E01.1080p.en.srt",
      "lines_matched": 612,
      "lines_with_speech": 640,
      "audio_language": "en",
      "shift_min": -2.1,
      "shift_max": 0.4,
      "timing_sections": 2,
      "endings_extended": 14,
      "seconds": 81.3,
      "tidy": true,
      "subtitles_before": 668,
      "subtitles_after": 655,
      "joined": 120,
      "split": 107,
      "capitals_fixed": 85
    },
    { "video": "…S01E02…", "subtitle": "…", "status": "no_match",
      "reason": "Only 9 of 655 lines matched the audio – wrong subtitle for this video?", "audio_language": "en" },
    { "video": "…S01E03…", "subtitle": "…", "status": "failed", "reason": "Could not read the audio: …" },
    { "video": "…S01E04…", "subtitle": null, "status": "skipped", "reason": "no matching subtitle" }
  ]
}
```

`status` is one of `synced`, `no_match`, `failed`, `cancelled` (Ctrl+C) or `skipped` (no partner file). For synced items, `tidy` says whether *Tidy up lines* was on; `joined` counts new subtitles made from several original ones, `split` counts original subtitles spread over several new ones.

## Logs

All in the `logs` folder next to the exe:

| File | Contents |
|---|---|
| `cli.log` | Every command-line run: arguments, pairing, per-file results, errors with tracebacks, native crash stack traces, exit code. |
| `worker.log` | The speech-recognition process: GPU/CPU choice, GPU library loading, crashes. |
| `setup.log` | Downloads, self-check repairs, setup failures. |
| `app.log` | The window version. |
| `details\<video name>.tsv` | One row per written subtitle: original subtitle number(s), old and new time, words heard, what changed (window and command line; the 200 newest are kept). |

## Examples

**A whole library, results as `.eng.srt`, replacing older results:**
```bat
subsync-cli sync "D:\Media\Shows" --suffix eng --overwrite --report "D:\Media\subsync-report.json"
```

**Exact pairs from a script:**
```bat
subsync-cli sync --pair "D:\In\movie.mkv" "D:\In\movie.subs.srt" --overwrite
```

**PowerShell, acting on the result:**
```powershell
& "D:\Tools\SubSync\subsync-cli.exe" sync $folder --report "$env:TEMP\subsync.json"
switch ($LASTEXITCODE) {
  0       { "all synced" }
  { $_ -in 3,4 } { (Get-Content "$env:TEMP\subsync.json" | ConvertFrom-Json).items |
                       Where-Object status -ne "synced" | Format-Table video, status, reason }
  7       { "setup problem - check the internet connection / close SubSync" }
  default { "see D:\Tools\SubSync\logs\cli.log" }
}
```

**As a post-processing step** (e.g. a Sonarr *Custom Script* or a scheduled task): call
`subsync-cli.exe sync "<episode folder>"` and treat exit code `0` as success, `3`/`4`/`5` as "check the report", and anything else as an error.

## Running alongside the window

The window and the command line can run at the same time on the same folder; they share the transcript cache. Two things are coordinated:

- Repairs only happen when no other SubSync is using the folder (otherwise exit code `7` with an explanation).
- Leftover processes from crashes are cleaned up only when nothing else is running.

Every process a run starts belongs to it: when the run ends (normally, by Ctrl+C, by a crash, or if `subsync-cli.exe` is killed) Windows ends all of them.

---

# For developers

## How it fits together

```
SubSync.exe / subsync-cli.exe     Go, no dependencies; same code, built as GUI or console program
 ├─ self-check + setup/repair      downloads with fallbacks, SHA-256 checks, resume
 ├─ process supervision            Windows Job Object (kill-on-close), one window per folder
 └─ starts runtime\python\python(w).exe
       app\main.py                  window (PySide6)
       app\cli.py                   command line
       app\subsync\
         pipeline.py                job queue: decode → speech recognition → matching → write
         asr_worker.py              separate process: audio decode + voice detection + Whisper (GPU/CPU)
         align.py                   rough per-line alignment, timing sections, speech-aware endings
         words.py                   subtitle words ↔ Whisper words; cues timed from their first/last word
         reshape.py                 "Tidy up lines": re-cut by sentence/speaker, 2-row wrap, capitals
         details.py                 logs\details\*.tsv
         embed.py                   multilingual sentence embeddings (MiniLM, ONNX, CPU)
         media.py / subtitles.py    audio track choice + decoding / subtitle reading & writing
         pairing.py                 video ↔ subtitle pairing
```

Three things overlap in a batch: decoding the next episode, transcribing the current one on the GPU, and matching and writing the previous one. Transcripts are cached in `cache\transcripts`, keyed by path, size, modification time and audio track.

## Downloads, fallbacks and the self-check

The download list (`launcher/manifest.json`) is compiled into the exe:

| What | Primary | Fallbacks | Integrity |
|---|---|---|---|
| Python 3.12.10 | python.org embeddable zip | NuGet `python` package | HTTPS |
| 28 Python packages + 3 NVIDIA packages | exact PyPI file URL | the same file name on any PEP 503 index: pypi.org, pypi.tuna.tsinghua.edu.cn, mirrors.aliyun.com | SHA-256 from build time |
| Whisper large-v3-turbo (CTranslate2), MiniLM (ONNX) | huggingface.co | hf-mirror.com; backup repositories | exact revision + SHA-256 pinned in `runtime\models.lock.json` at first install |

If a pinned model repository disappears, SubSync drops the pin and installs from the backup repository instead. Files are verified, so a mirror can't deliver a wrong file.

**Your own sources**: a `sources.json` next to the exe is tried before the built-in ones:

```json
{
  "python_urls":  ["https://my.server/subsync/python-3.12.10-embed-amd64.zip"],
  "pypi_indexes": ["https://my.server/simple"],
  "hf_hosts":     ["https://my.server/hf"]
}
```

`pypi_indexes` entries must be PEP 503 "simple" indexes (`<index>/<project>/` listing the wheel files). Any static folder laid out that way works, as does `pip download` plus a simple index generator. `hf_hosts` entries must serve the Hugging Face URL layout (`/api/models/<repo>/revision/main`, `/api/models/<repo>/tree/<rev>`, `/<repo>/resolve/<rev>/<file>`).

**Self-check** (every start, both programs): Python's core files; every installed file of every package against the package's own `RECORD` (path + size); the NVIDIA DLLs against sizes recorded at build time; model files against the lock; the app files against the copy inside the exe. Anything missing or a different size is re-downloaded on its own; app files are restored from the exe without a download.

## Running from source

Requirements: Windows, Python 3.12 x64, an NVIDIA driver for GPU use.

```bat
py -3.12 -m venv .venv && .venv\Scripts\activate
pip install faster-whisper==1.2.1 ctranslate2==4.8.5 PySide6-Essentials onnxruntime tokenizers numpy rapidfuzz pysubs2 av
pip install nvidia-cublas-cu12 nvidia-cudnn-cu12==9.10.2.21 nvidia-cuda-nvrtc-cu12   :: GPU only
```

Put the models in `<root>\models\whisper-large-v3-turbo` (files of `mobiuslabsgmbh/faster-whisper-large-v3-turbo`) and `<root>\models\minilm` (`onnx/model_quint8_avx2.onnx` saved as `model.onnx`, plus `tokenizer.json`, from `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`), and the NVIDIA DLLs in `<root>\runtime\cuda`. Then:

```bat
set SUBSYNC_ROOT=D:\Dev\subsync-root
python app\main.py                      :: window
python app\cli.py sync D:\Shows\S01     :: command line
```

## Tests

Run from the `tests` folder (`pip install` the packages listed above plus `pyflakes` if you like; `make_fixtures.py` needs `ffmpeg` and `espeak-ng`):

```bash
cd tests
python sim.py                                  # alignment accuracy: 45-min episodes, splits, drift, bad lines,
                                               # early endings, English and other-language audio
python make_fixtures.py && python gui_e2e.py   # window end-to-end (videos with synthesized speech)
python cli_e2e.py "whole folder"               # command line end-to-end (also: "explicit pair + eng",
                                               # "wrong subtitle (no match)", "nothing to pair", "keep layout", ...)
python test_words.py && python test_reshape.py && python test_ui.py   # unit tests (word timing, re-cutting, settings)
```

**Trying a change on a real episode** without rebuilding the exe or re-running speech recognition (the episode must have been synced once, so its transcript is cached):

```bat
D:\Tools\SubSync\runtime\python\python.exe tools\replay.py D:\Tools\SubSync "D:\Shows\Ep.mkv" "D:\Shows\Ep.original.srt" out.srt [--keep-layout]
D:\Tools\SubSync\runtime\python\python.exe tools\measure.py D:\Tools\SubSync\cache\transcripts\<hash>.json.gz out.srt
```

`measure.py` reports how many subtitles start within 0.3 s of their first spoken word, how many disappear before their words are spoken, overlaps, rows per subtitle and the longest row.

The end-to-end tests replace Whisper with the known transcript of the test videos. Everything else is real: audio decoding, voice detection, the worker process, matching and file writing.

## Building

Needs Go 1.24+ (any OS: it cross-compiles, no CGO):

```bash
./build/build.sh             # → build/SubSync.exe and build/subsync-cli.exe
```

The icon and Windows manifest are pre-compiled into `launcher/rsrc_windows_amd64.syso`; to change them, edit `app.ico` / `app.manifest` and rebuild it with `x86_64-w64-mingw32-windres --preprocessor=cat app.rc -O coff -o rsrc_windows_amd64.syso`.

`tools/make_manifest.py` regenerates `launcher/manifest.json` from pip resolver reports (pinned versions, URLs, SHA-256, sizes) when dependencies are updated.

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
| `subsync-cli serve [options]` | (Since 1.3.0.) Stay running for another program: pairs come in on stdin, results go out on stdout, one JSON object per line. See [`serve`](#serve-for-programs). |
| `subsync-cli detect <video> [options]` | (Since 1.4.0.) Find out which language is spoken in a video, from a short sample. Quick and read-only; one JSON object on stdout. See [`detect`](#detect-which-language-is-spoken). |
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
| `--suffix en` / `--suffix eng` | Result name `<video>.en.srt` (default) or `<video>.eng.srt`; for Danish subtitles `<video>.da.srt` or `<video>.dan.srt`. |
| `--overwrite` | Replace an existing result. Without it the existing file is kept and the result is `<video>.en.#1.srt` (`#2`, …). If the existing file is open in another program, SubSync waits up to 5 minutes for it to be released. |
| `--keep-layout` | Turn *Tidy up lines* off: keep the original line layout and capitals. The timing is still fixed line by line. (The window's setting does not affect the command line; tidying is on unless this option is given.) |
| `--cpu` | Don't use the NVIDIA GPU (slower; for testing, or if the GPU is busy). |
| `--report FILE.json` | Write a machine-readable report (format below). |
| `--output FILE.srt` | (Since 1.3.0.) Write the result to exactly this file instead of `<video>.en.srt`. Only with exactly one `--pair` and no other files or folders; `--suffix` is then not used. If the file exists, `--overwrite` is required (otherwise exit code 6, before any work). It may be the input subtitle itself, which is then replaced in place. |
| `--sub-lang auto\|en\|da` | (Since 1.5.0.) The subtitles' language. `auto` (default): from the file name (`.da`, `.dan`, `.danish`, `.dansk` / `.en`, `.eng`, `.english`), otherwise from the text, and English when unsure. |
| `--reference EN.srt` | (Since 1.5.0.) With exactly one `--pair` of a Danish subtitle: an English subtitle of the same video to take the timing from (see [Danish subtitles](#danish-subtitles)). With folders, the English subtitle paired with the same video is used by itself. |
| `--progress` | (Since 1.3.0.) Print machine-readable progress lines on stdout, for programs that run SubSync (see [Progress lines](#progress-lines---progress)). The live status line is not shown. |

Supported inputs: videos `.mkv .mp4 .m4v .avi .mov .wmv .ts .m2ts .mts .webm .flv .mpg .mpeg .vob .ogm`; subtitles `.srt .ass .ssa .vtt` (English, or since 1.5.0 Danish). Results are always `.srt` (UTF-8), written **next to the video**.

### Danish subtitles

(Since 1.5.0.) A Danish subtitle is synced in one of two ways; the report's `timing_from` says which:

- **`reference`**: the video also has an English subtitle (paired with it in the same run, or given with `--reference`). The English one is synced first (word-accurate on English audio), then each Danish line is matched to the English line or lines that say the same thing and takes their timing. This is the more precise way. If the English subtitle can't be synced or doesn't match, SubSync falls back to the audio.
- **`audio`**: the Danish lines are matched to the spoken phrases by meaning, as for English subtitles on audio in another language.

With folders, a video can have both an English and a Danish subtitle; each is synced and written separately (`.en.srt` and `.da.srt`). *Tidy up lines* only splits Danish subtitles taller than two rows (re-cutting into sentences needs words in the subtitle's own language).

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
| `3` | Some pairs synced; others failed or didn't match their video. (`detect`: the video can't be read or has no audio track.) | See the `SKIP`/`FAIL` lines, the report, or `logs\cli.log`. |
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
  "subsync_version": "1.3.1",
  "finished": "2026-11-08T20:19:27",
  "exit_code": 3,
  "seconds": 252.4,
  "summary": { "synced": 1, "no_match": 1, "failed": 1, "cancelled": 0, "skipped": 1 },
  "speech_recognition": { "device": "gpu", "name": "NVIDIA GeForce RTX 3050", "model_load_seconds": 6.2 },
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
      "capitals_fixed": 85,
      "kept_visible": 6,
      "subtitle_language": "en",
      "timing_from": "audio",
      "reference_subtitle": null,
      "timings": { "from_cache": false, "read_audio": 9.8, "listen": 58.1, "match": 4.2 }
    },
    { "video": "…S01E02…", "subtitle": "…", "status": "no_match",
      "reason": "Only 9 of 655 lines matched the audio – wrong subtitle for this video?", "audio_language": "en" },
    { "video": "…S01E03…", "subtitle": "…", "status": "failed", "reason": "Could not read the audio: …" },
    { "video": "…S01E04…", "subtitle": null, "status": "skipped", "reason": "no matching subtitle" }
  ]
}
```

`status` is one of `synced`, `no_match`, `failed`, `cancelled` (Ctrl+C) or `skipped` (no partner file). For synced items, `tidy` says whether *Tidy up lines* was on; `joined` counts new subtitles made from several original ones, `split` counts original subtitles spread over several new ones. `kept_visible` (since 1.4.1) counts subtitles that would otherwise have flashed by too fast to see. Such a line now gets the room before the next one (at least 0.5 s), or stays up for 0.7 s together with the next one (never three at once). With *Tidy up lines* on, a sound description that starts right next to a neighbour becomes one subtitle with it. Starts are never moved for this. `subtitle_language` (since 1.5.0) is `en` or `da`; `timing_from` is `audio` or `reference` (a Danish subtitle timed by an English one, which is then named in `reference_subtitle`, otherwise `null`). A `no_match` item also has `subtitle_language`.

`speech_recognition` (since 1.3.0) says what listened: `device` is `gpu` or `cpu` (a GPU problem during the run switches to `cpu`, and the report says so), `name` is the graphics card, `model_load_seconds` how long the speech model took to load. It is `null` when nothing had to be listened to, for example when every transcript came from the cache. `timings` (since 1.3.0, synced items) gives the seconds spent reading the audio, listening and matching; `from_cache: true` means the transcript was remembered from an earlier run, so `read_audio` and `listen` are `null`.

## Progress lines (`--progress`)

Each line starts with `PROGRESS ` followed by one JSON object (plain ASCII, one line, flushed immediately). All other lines on stdout are the usual human-readable ones, so a program can pick out its lines by the prefix:

```
PROGRESS {"event":"stage","item":1,"total":1,"stage":"queued","percent":null}
PROGRESS {"event":"device","device":"gpu","name":"NVIDIA GeForce RTX 3050"}
PROGRESS {"event":"stage","item":1,"total":1,"stage":"reading_audio","percent":null}
PROGRESS {"event":"stage","item":1,"total":1,"stage":"listening","percent":37}
PROGRESS {"event":"stage","item":1,"total":1,"stage":"matching","percent":50}
PROGRESS {"event":"item_done","item":1,"total":1,"status":"synced","output":"D:\\Shows\\Show.S01E01.en.srt"}
```

| Event | Fields |
|---|---|
| `stage` | `item` (number in the listing printed at the start, 1-based), `total`, `stage`, `percent` (0–100 within that stage, or `null` when the stage has just started or has no measure). |
| `device` | Speech recognition is ready: `device` `gpu` or `cpu`, `name` the graphics card (or `null`). Comes again if a GPU problem switches to the CPU. |
| `item_done` | `item`, `total`, `status` (`synced`, `no_match`, `failed`, `cancelled`, as in the report) and `output` (the written file, or `null`). |

Stages in order: `queued`, `reading_audio`, `listening` (nearly all of the time; `percent` is how much of the soundtrack has been heard, updated every 15 seconds of audio or so), `matching`, and rarely `waiting_for_file` (the existing result is open in another program). With several items, the next item's `reading_audio` starts while the current one is still `listening`. A transcript from the cache goes straight from `queued` to `matching`. New events and fields may be added later; ignore what you don't know.

## `detect` (which language is spoken)

`subsync-cli detect` tells a program such as the Jellyfin plugin which language a video's audio is in, for files whose audio track is tagged `und` (undetermined) or not tagged at all. It listens to a short sample instead of the whole video.

```bat
subsync-cli detect "D:\Movies\Other Mommy (2026).mkv" [--track N] [--seconds 90] [--cpu] [--progress]
```

| Option | Meaning |
|---|---|
| `--track N` | Check audio track `N` (`1` = the first audio track). Default: the track `sync` would use, so the answer is about the audio a later sync listens to. |
| `--seconds S` | Listen to at most `S` seconds of speech (5–600, default 90). |
| `--cpu` | Don't use the NVIDIA GPU. |
| `--progress` | `PROGRESS {json}` lines before the answer, as in `sync`: stage `reading_audio`, then `listening`, each with `percent`. |

**What it does:** it reads 30-second pieces spread over the video (the first 5 % is skipped for intros and logos; videos under about 5½ minutes are read completely), keeps only the parts with voice, and stops once it has `--seconds` of speech, or after 10 pieces (5 minutes of audio). If the video's length isn't stored in the file, or the file can't be jumped into, it reads 5 minutes of audio in one go instead (after the intro when the length is known), never the whole video. TV recordings whose timestamps don't start at zero are handled. Whisper's language detection then runs on that speech; the answer is the language with the highest probability, averaged over the 30-second stretches of speech. Nothing is transcribed or matched.

**Read-only:** nothing is created or changed next to the video, and the transcript cache and `settings.json` are not touched. Only `logs\cli.log` and `logs\worker.log` get lines.

**Output (stdout):** exactly one JSON object on one line (after the `PROGRESS` lines with `--progress`). Setup or repair messages go to stderr.

```json
{"video":"D:\\Movies\\Other Mommy (2026).mkv","track":1,"audio_tracks":1,"track_language_tag":"und","language":"en","probability":0.97,"speech_seconds":84.2,"device":"gpu","model_load_seconds":5.9,"seconds":11.4,"subsync_version":"1.5.0"}
```

| Field | Meaning |
|---|---|
| `video` | The full path. |
| `track` | The audio track that was checked (`1` = first). |
| `audio_tracks` | How many audio tracks the video has. |
| `track_language_tag` | The track's language tag as stored in the file (`"und"`, `"eng"`, …), or `null` if it has none. |
| `language` | The spoken language as Whisper's code, two letters for nearly every language (`"en"`, `"da"`, …; a few have three, such as `"haw"`), the same codes as `audio_language` in the sync report. `null` if no speech was found or the video can't be read. |
| `probability` | How sure Whisper is, 0–1. `null` together with `language`. |
| `speech_seconds` | Seconds of speech the answer is based on. |
| `device` | `gpu` or `cpu`; `null` if the speech model wasn't needed (no speech found). If the GPU can't be used (for example it is full because `serve` is using it, or it doesn't answer within 5 minutes plus 1 minute per 30 s of speech), `detect` switches to the CPU: slower, but it still answers, and `gpu_problem` says what happened. |
| `model_load_seconds` | How long the speech model took to load. |
| `seconds` | Time from SubSync's Python start to the answer (the launcher's self-check before it is not included). |
| `reason` | Only when `language` is `null`: `"no speech found"`, `"no audio track"`, or why the video can't be read. |
| `subsync_version` | The SubSync version. |

New fields may be added later; ignore what you don't know. Music with singing counts as speech, so a video whose sample is mostly songs reports the language of the songs.

**Exit codes:** `0` answered (including "no speech found"), `3` the video can't be read or has no audio track (a JSON object with `reason` is still printed), `6` invalid command line (no JSON; the message is on stderr), `7` setup/repair not possible right now, `10` unexpected error (no JSON). `detect` can run while the window, `sync` or `serve` use the same SubSync folder.

## `serve` (for programs)

`subsync-cli serve` is for a program that syncs one item at a time and wants each result as soon as it's ready, such as the Jellyfin plugin. Compared with starting `subsync-cli sync` once per item, the self-check, Python start and model loading happen **once**, and items overlap: the next item's audio is read while the current one is listened to.

```bat
subsync-cli serve --overwrite [--suffix en|eng] [--keep-layout] [--cpu]
```

The options apply to every item and work as in `sync`. `--overwrite` is needed to write into an existing file, such as the input subtitle itself.

**Input (stdin):** one JSON object per line, UTF-8.

```json
{"id": "ep-4711", "video": "D:\\Shows\\Show.S01E01.mkv", "subtitle": "D:\\Shows\\Show.S01E01.en.hi.srt", "output": "D:\\Shows\\Show.S01E01.en.hi.srt"}
```

- `id` is any string or number, and is echoed in every event about the item. Without one, SubSync uses `"auto-N"` (N = the request's line number).
- `video` and `subtitle` are required. `output` is optional: the exact file to write (as with `--output`), otherwise `<video>.en.srt` with the usual naming rules (`<video>.da.srt` for a Danish subtitle).
- (Since 1.5.0.) `subtitle_language` is optional: `"auto"` (default, as `--sub-lang auto`), `"en"` or `"da"`. `reference` is optional: an English subtitle of the same video to time a Danish one by (as `--reference`).
- SubSync may start on an item as soon as it is received, and writes its result when that item is finished. A program that keeps a backup of the subtitle should make it before sending the request.
- Sending one item ahead of the one being worked on is enough for the overlap.
- stdin may stay open between items: each `result` comes as soon as its item is finished. (On Windows, 1.3.0 only started working once stdin was closed; fixed in 1.3.1.)
- **Close stdin** when there is nothing more to do: SubSync finishes every item it has received, then exits with `0`. To stop at once, end the process. Items not yet finished are then not written; a result already written stays.

**Output (stdout):** one JSON object per line, flushed immediately.

```
{"event":"ready","subsync_version":"1.3.1"}
{"event":"stage","id":"ep-4711","stage":"queued","percent":null}
{"event":"device","device":"gpu","name":"NVIDIA GeForce RTX 3050","model_load_seconds":6.2}
{"event":"stage","id":"ep-4711","stage":"reading_audio","percent":null}
{"event":"stage","id":"ep-4711","stage":"listening","percent":37}
{"event":"stage","id":"ep-4711","stage":"matching","percent":50}
{"event":"result","id":"ep-4711","video":"…","subtitle":"…","status":"synced","output":"…","lines_matched":612,…,"timings":{…}}
```

| Event | Meaning |
|---|---|
| `ready` | Requests are accepted (the models are still loading; requests sent now simply wait). |
| `device` | Speech recognition is ready, as in `--progress`, plus `model_load_seconds`. Comes again if a GPU problem switches to the CPU. |
| `warning` | `text`: a problem that doesn't stop the work, for example the GPU fallback. |
| `stage` | As in `--progress`, with `id` instead of `item`. |
| `result` | The item is finished. `status` and the other fields are those of a report item (`synced`, `no_match`, `failed`). A request that can't run (bad JSON, missing file, `output` exists without `--overwrite`, an `id` already in progress, or a file that an item still in progress writes or reads) gets a `result` with `status` `failed` and a `reason` straight away; its `id` is `null` if the line couldn't be read. |

Lines before `ready` can be setup or repair messages from the self-check (plain text). Ignore any line that doesn't start with `{`. New events and fields may be added later; ignore what you don't know. Exit codes: `0` (stdin closed, all done), `6` (bad option), `7` (setup/repair not possible), `9` (Ctrl+C), `10` (unexpected error). Details go to `logs\cli.log` as `serve:` lines.

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
python cli_e2e.py "whole folder"               # command line end-to-end, one case per run (also: "explicit pair + eng",
                                               # "wrong subtitle (no match)", "progress + output", "gpu fails at start", ...);
                                               # prints PASS and exits 0 when the case ends with its expected exit code
python serve_e2e.py                            # `serve` end-to-end; exits non-zero if any check fails
python serve_pipe_e2e.py                       # `serve` as a separate process with piped, open stdin (also on Windows)
python detect_e2e.py && python test_detect.py  # `detect` end-to-end (stand-in for Whisper) and its unit tests
python test_visible.py                         # no subtitle too short to be seen; every word kept
python test_danish.py && python danish_e2e.py  # Danish subtitles: language, names, pairing, timing; command line and serve
python gui_danish_e2e.py                       # Danish subtitles in the window (QT_QPA_PLATFORM=offscreen)
python test_words.py && python test_reshape.py && python test_ui.py   # unit tests (word timing, re-cutting, settings)
```

**Checking a result for lines that are hard to see:** `python tools/check_srt.py RESULT.srt [ORIGINAL.srt]` (or a folder) lists subtitles shown for less than 0.7 s, ones out of order, and, with the original, whether every word is still there. It needs only Python, for example an installed SubSync's `runtime\python\python.exe`.

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

# CLAUDE.md: context for Claude Code sessions on SubSync

This file is loaded automatically at the start of every Claude Code session in this repository. This is a **public repository**: keep this file, code, comments and commits free of personal information (names, emails, home paths, machine names, accounts).

## Working agreement with the owner

- **Plan first, then wait for approval** before multi-step work. After each major step, summarise briefly what was done and what's next. Small, clearly requested fixes can go straight ahead.
- **Ask before deleting, overwriting or renaming** existing files, and before anything hard to undo: force-pushes, history rewrites, tag/release changes.
- **Commits: no `Co-Authored-By: Claude` or `Claude-Session:` trailers**, and no other AI attribution in commit messages. The owner explicitly removed these from history. Commit as the owner's GitHub noreply identity (`darkbepo <darkbepo@users.noreply.github.com>`), not as "Claude", even if a hook asks for it; the owner confirmed (2026-11-12) that GitHub showing these commits as Unverified is fine.
- **Always pull before committing.** The owner also edits files in the GitHub web editor. Their wording in `README.md` is intentional, so don't revert it. For example, they softened "Don't delete anything" to "No need to delete the other files and folders", and removed the "start fresh" sentence.
- At the end of a task, **list the files created or modified**, with their locations.
- Deliverable files handed to the owner *outside* the repo (zips, notes) are named `DD-MM-YYYY-descriptive-name`. Files inside the repo keep conventional names.
- The owner is a capable non-developer. Explain outcomes in plain language; keep jargon for code and READMEs.

## Current status (keep this section up to date)

- **Released:** v1.4.0 (GitHub release `v1.4.0`, published 2026-11-12, marked Latest, tag on `main` at `960dcb3`, asset `SubSync-v1.4.0-windows-x64.zip`, SHA-256 `60569d0270501126cf400aa2c0a91eb5252496ce35b28507a23c0d234c779af9`, matching GitHub's digest; exes cross-compiled with Go 1.24.7 on Linux from that commit's code). Before that: v1.3.1 (`287e60acdc5b450d9224e1024dc2a39f6fa19a67d85f05d467ac0ecd4596d627`, tag at `c5af662`), v1.3.0 (`6eee6791866d803ea01f5d1f0da92a50496a8187320cd70f8a395d7e353e3fa7`, Go 1.24.7, commit `611c504`, tag at `0d333d4`), v1.2.0 (`2af27e3d74ac639cbec12150e805654911b85673f4397eeaa79fe07040671cae`, Go 1.27.4, commit `94fbeca`), v1.1.0 (`6622ccac1d935ac644ec59a084f5b3c49db5dd78bad28798ce109805e464e2dc`, commit `0d3fa2b`). History of changes: `CHANGELOG.md`.
- **v1.4.0** — `subsync-cli detect <video> [--track N] [--seconds 90] [--cpu] [--progress]` for the plugin's Check button (files tagged "und"). `app/subsync/detect.py`: 30 s windows between 5 % and 95 % (`media.decode_window`, seeks; adds the track's start time, since TV recordings' timestamps don't start at 0), Silero VAD speech up to `--seconds`, ≤ 30 s pieces, Whisper `detect_language` per piece in a separate process (`Detector`: GPU, one fallback to CPU on failure/crash/time limit), probabilities averaged weighted by speech. One JSON object on stdout (launcher sends setup messages to stderr for detect); exit 3 = unreadable / no audio, 6 = bad arguments; read-only. `media.decode` refactored into `_resampler`/`_mix` (output byte-identical to 1.3.1). Tested in a Linux sandbox with a Whisper stand-in (`tests/fake_detect.py`): `detect_e2e.py` (incl. detect while serve listens, read-only snapshot), `test_detect.py` (incl. seek accuracy for mkv/mp4/avi/ts/offset-ts; it fails without the start-time fix), serve/cli/unit tests, launcher tests under Wine 30/30. A review found and fixed: wrong audio on offset TS files, a queue thread that could block exit after the GPU fallback, no time limit, a rarely lost result, whole-file decode for unknown length. **Not tested:** real Whisper (language accuracy, probabilities) and speed; the owner chose not to run CPU tests here and released without a PC check (the release notes say speed isn't measured yet). First real check: `detect` on an "und" English film (expect `en`) and a Danish episode (expect `da`); the `seconds` field gives the timing.
- **v1.3.1** (fix only). `serve` hung on Windows while the caller kept stdin open: the spawned speech worker got the request pipe as its stdin, and Python's start-up in it blocked behind serve's pending `ReadFile`. Now `cli._private_std_pipes()` moves the caller's stdin/stdout to private, non-inheritable copies and points fd 0/1, the Win32 standard handles and `sys.stdin` at NUL before any worker starts (lesson 13). Tested in a Linux sandbox: `serve_pipe_e2e.py` (new; fails 6 checks on the 1.3.0 code), `serve_e2e.py`, every `cli_e2e.py` case, unit tests, launcher tests under Wine 29/29, `subsync-cli.exe version` under Wine; a probe under Wine with Windows Python 3.12 showed the worker's stdin is the caller's pipe in 1.3.0 and NUL with the fix (Wine doesn't reproduce the hang itself). **Not tested:** real Windows. Confirm with the plugin (serve, stdin kept open) before calling it fixed. stderr is still shared with the workers (it can't cause this hang).
- **1.2.0 exes tested on Windows** (not yet on the owner's own PC): `version`, `check`, the command line with and without `--keep-layout` on a real episode (results matched `tools/replay.py`), and the window opening. Not run: the e2e and launcher tests.
- **Confirmed by the owner on real hardware** (Windows 11, NVIDIA RTX 3050): first-time setup, the window opening, the UI, no leftover processes.
- **First real-use report (English audio, broadcast TV captions):** v1.1.0 left ~11% of lines > 0.5 s off (placed by phrase, not word) and cut endings off. Fixed in **1.2.0** (word-accurate timing + "Tidy up lines"), developed on branch `feat/word-timing-tidy`; measured on that episode: 99.5% of starts within 0.3 s, 0 cut-off endings. Owner confirmed Whisper's word timings match what they see. Still unreported: other-language audio, and how the re-cut subtitles read over a whole season.
- **Local Windows sessions:** a SubSync install with a cached test episode makes `tools/replay.py` + `tools/measure.py` the fastest way to check matching changes. Commits use the repo-local GitHub noreply identity. Check first whether Go, `gh`, `windres` and espeak-ng are installed; without them there is no exe build, no e2e fixtures and no launcher tests.
- **1.3.0 contents** (details in `CHANGELOG.md`). What's new: faster starts (first episode's audio read while the speech model loads, MiniLM at warm-up, CLI warms up before scanning folders, `.pyc` precompiled at the end of setup), timings in the logs, `speech_recognition` + per-item `timings` in the report, `--output`, `--progress`, `subsync-cli serve`, exe VERSIONINFO 1.3.0.
- **1.3.0 testing:** in a Linux sandbox: unit tests, `sim.py` (97–99% within 0.3 s), `gui_e2e.py`, every `cli_e2e.py` case (incl. the GPU failing at start), `serve_e2e.py` (15 checks), the read-while-loading order and its model-load-failure path with a stand-in model, `go vet`, the launcher tests under Wine (29/29), and `subsync-cli.exe version`/`help` under Wine. A review pass found and fixed: a lost-job race when the worker is restarted, two `serve` items writing one file, tests that couldn't fail. **Not tested:** real Whisper/GPU and real Windows. Before calling it confirmed, the owner should open the window once and run a season through the command line; the timing lines in `logs\setup.log`, `logs\app.log` and `logs\cli.log` show the real start-up saving.
- **Jellyfin plugin** (`darkbepo/Jellyfin-Subfixer`, separate repo) runs `subsync-cli sync --pair … --report …` **once per episode**, so every SubSync start-up cost is paid per episode. It reads the report (now with `speech_recognition` and `timings`) and follows `logs\cli.log` for stage lines. Keep the report fields and the `[n/m] <video>: <stage>…` log lines stable, and add new fields rather than renaming.
- **Contract with the plugin:** the `serve` and `--progress` event names, stage codes, report fields and (1.4.0) the `detect` JSON fields and exit codes (`README-CLI.md`). Add fields; don't rename or remove them.
- **Parked (owner said wait):** GitHub community files (description/topics, issue templates, `SECURITY.md`). The exact drafts are in `docs/parked/community-files.md`. `CONTRIBUTING.md` was declined.

## Handoff and access

- The repository is `darkbepo/SubSync` (public, MIT). A new Claude account needs a GitHub connection that can see it (the owner's account, or a collaborator). Pushing also needs the **Claude GitHub App** installed with access to this repository.
- **Cloud** Claude Code sessions (through the Claude GitHub App) can read the repo and push branches and `main`, but GitHub refuses (403) **creating repositories, releases and tags**. Only repository-scoped REST endpoints work; GraphQL and `gh release` don't.
- **Local** sessions on the owner's Windows PC use the owner's own git login, and can use `gh` once the owner has run `gh auth login` themselves. That's how the v1.2.0 draft release was created (`gh release create vX.Y.Z --draft --target main ...`). Only ever create a **draft**: the owner reviews it and publishes it, and publishing creates the tag.
- New sessions start from a fresh clone and know nothing beyond this file and the repo. The design history is summarised here and in `CHANGELOG.md`; the full original conversation is not available.

## What SubSync is

A Windows tool that syncs **English** subtitles to a video **line by line**, using the video's own audio. The audio may be in any language. It's built for bulk use: whole seasons of 23 × 40-minute episodes. Two front ends share one installation:

- `SubSync.exe`: a drag-and-drop window with a **Reference video | Reference subtitle | Result** table. It pairs files automatically, has `.en.srt`/`.eng.srt` and "Overwrite existing" settings, and follows Windows light/dark mode.
- `subsync-cli.exe`: the command line, documented in `README-CLI.md`, including its exit codes and JSON report.

Owner requirements that shaped the design (keep them):

- **Speed matters** (GPU, pipelining, cache), but never at the cost of quality.
- **Everything lives next to the exe.** Deleting the folder removes the tool completely: models, Python, cache, logs and settings. Nothing is written to AppData or Temp (`TMP`, `HF_HOME` and `CUDA_CACHE_PATH` are redirected into the folder).
- **Results are saved next to the video**, as `<video stem>.en.srt`. With overwrite **off**, an existing result is kept and the new one becomes `<stem>.en.#1.srt`, then `#2`, and so on. With overwrite **on**, the file is replaced once no other program has it open.
- **Nothing may keep running** after the app closes, crashes or fails to start.
- **The first install must survive dead links** (fallback sources), and missing or damaged files must self-repair.
- **Modern UI** in both the app and the setup window.

## Architecture

```
launcher/   Go, standard library only; one codebase built twice: SubSync.exe (GUI) and subsync-cli.exe (console, -X main.mode=cli)
  main.go      install/repair flow, downloads (resume, SHA-256, sources tried in order), launch + "window ready" handshake
  sources.go   fallback sources: python.org → NuGet; PyPI URL → any PEP 503 index; huggingface.co → hf-mirror.com;
               models.lock.json (pinned revision + hashes); optional sources.json (user sources tried first)
  verify.go    self-check on every start: Python core, every wheel file via its RECORD, CUDA DLL sizes, model lock, app files
  supervise.go Job Object (KILL_ON_JOB_CLOSE), per-folder mutexes ("GUI" = single window, "Any" = someone uses the folder), stray-process cleanup
  ui.go        custom-drawn setup window (GDI+ anti-aliasing, light/dark, dark title bar)
  cli.go       console commands: setup / check / sync / version / help; exit codes
  manifest.json  pinned download list (generated by tools/make_manifest.py)
app/        Python 3.12 (run by the embedded runtime\python)
  main.py        window entry: logging, faulthandler, C++ runtime preload, then subsync.gui
  cli.py         command-line entry: sync (--output, --progress, --report), serve (JSON lines on stdin/stdout), detect (1.4.0)
  subsync/
    pipeline.py  Engine: job queue; worker process (decode + VAD + Whisper) → align thread (match + write); transcript cache; overwrite / #n naming
    asr_worker.py  separate process (crash isolation): PyAV decode (5.1 → centre-channel weighted), Silero VAD → ≤30 s clips,
                   faster-whisper BatchedInferencePipeline (int8_float16, beam 1, word timestamps), VRAM-based batch size, OOM back-off,
                   exits by itself if the parent dies
    align.py     the core: phrases from word timestamps → similarity (multilingual MiniLM embeddings + fuzzy text for English audio)
                 → monotonic DP matching (2 passes) → runs of consistent offset (splits/drift) → per-line offsets
                 → strong lone matches = per-line fixes → speech-aware endings (fix_endings). Since 1.2.0 this is the ROUGH placement.
    words.py     (1.2.0) tokenise cues (word/sound/label/tag/dash) → banded (±4 s) monotonic word matching to Whisper words
                 (Fenwick-tree DP, fuzzy ≥ 80, small time prior) → refine(): cue start = first word, end via fix_endings
    reshape.py   (1.2.0) "Tidy up lines": sentences → split_long → short replies (dashes) → tags balanced → wrap (2 × 42)
                 → fix_case; split_tall() for non-English audio
    details.py   logs\details\<video>.tsv (200 newest kept)
    detect.py    (1.4.0) `subsync-cli detect`: sample windows → VAD speech → Whisper language detection in its own process
    pipeline.process()  the whole matching step as a pure function (used by the Engine, tests and tools/replay.py)
    embed.py     MiniLM ONNX (CPU) mean-pooled embeddings
    gui.py, theme.py  PySide6 window; theme follows Windows colour scheme
    pairing.py   name / episode-code (S01E04, 1x04) / fuzzy pairing
    media.py, subtitles.py, paths.py, settings.py
tests/      sim.py (accuracy simulation), gui_e2e.py / cli_e2e.py / serve_e2e.py / serve_pipe_e2e.py / detect_e2e.py (end-to-end with a fake ASR worker), make_fixtures.py (espeak-ng + ffmpeg)
            test_words.py / test_reshape.py / test_ui.py (unittest; run with an installed SubSync's runtime\python\python.exe)
tools/      replay.py (re-run process() on a cached transcript with this repo's code), measure.py (cue starts/ends vs Whisper words)
  launcher/   run.sh: 30 Wine checks of the real exes against a fake internet (fallbacks, repair, processes, CLI); see its README
build/      build.sh (cross-compiles both exes), make_icon.py
tools/      update_deps.sh + requirements-windows.txt / requirements-cuda.txt → make_manifest.py → launcher/manifest.json
docs/parked/  drafts waiting for the owner's approval
CHANGELOG.md  what changed in each version, and why
```

### What an installed SubSync folder looks like (first stop when debugging a user's install)

```
SubSync.exe, subsync-cli.exe
settings.json            suffix (.en/.eng), overwrite, gpu_batch (learned GPU batch size), window geometry
sources.json             optional: user-added download locations
app\                     Python sources, unpacked from the exe (restored if changed or missing)
runtime\python\          embedded Python 3.12 (+ Lib\site-packages); python312._pth points at app\
runtime\cuda\            cuBLAS / cuDNN / NVRTC DLLs (only on PCs with an NVIDIA driver)
runtime\install-state.json   which components are installed ("vcrt2:" = the complete C++ runtime set), app version hash
runtime\models.lock.json     model repo + exact revision + per-file size/SHA-256
runtime\downloads\       partial downloads (resumed; deleted after setup)
models\whisper-large-v3-turbo\, models\minilm\
cache\transcripts\       transcript cache (gzip JSON; key = path + size + mtime + audio track + model)
cache\tmp, cache\hf, cache\cuda, cache\window-ready.flag (launcher handshake)
logs\app.log (window: startup steps, crashes, Qt messages), worker.log (speech/GPU), setup.log (downloads, repairs),
     cli.log (command line), startup.log (raw stderr), worker-errors.log
```

## Hard-won lessons (don't regress)

1. **Never start the app with `HideWindow` / `STARTF_USESHOWWINDOW` + `SW_HIDE`.** Windows applies it to the app's *first* `ShowWindow`, which made the Qt window invisible ("the app crashes" with an empty log, and hidden `pythonw` processes piling up). `gui.run()` also force-shows the window via Win32 as a second safeguard. Wine does **not** reproduce this.
2. **One consistent MSVC C++ runtime set.** The `msvc-runtime` wheel's DLLs, including the `vcruntime140*.dll` that live under `.data/data/Scripts/`, are copied into the Python root. Python is installed *first* so its older runtime can't overwrite them. `paths.preload_vc_runtime()` loads the set before Qt or numpy load their own copies.
3. **CUDA:** ctranslate2 4.8.5 bundles a cuDNN shim (9.10.2.21) and loads `cublas64_12.dll` dynamically, so the cuDNN sub-libraries must match **exactly 9.10.2.21**. `paths.preload_cuda()` loads them by full path, in dependency order, in the worker only.
4. **The worker runs in its own process.** A GPU/driver crash falls back to CPU instead of killing the window.
5. **The self-check must not false-alarm.** It is verified against all 4,907 files of the 28 real wheels, and wheel `dist-info` names match the filename-derived names on Windows (case-insensitive). If a dependency changes, re-check this, or the app will "repair" on every start.
6. **SRT files are read in file order, not sorted by time.** A badly shifted section can overlap earlier lines, and the numbering is the true spoken order.
7. **Lone per-line corrections must land strictly between their neighbours** (`lo + 0.05 ≤ ns ≤ hi − 0.05`), otherwise lines can swap places.
8. Keep `PySide6` widget properties from shadowing Qt properties (the toggle uses `knob`, not `pos`).
9. **A misheard word is placed from matched words of its own cue** (by character count), never by interpolating across cues: a neighbouring cue's rough position can be seconds off and drags the start with it.
10. **Speaker changes can't be detected reliably.** Dashes are used only for very short sentences after a ≥ 0.5 s pause that also starts a new caption row; a pause on the same row is one speaker. Expect some false dashes where captioners broke rows for length.
11. `tests/sim.py` numbers vary slightly between runs (its fake embedder uses `hash()`); compare within-0.3 s percentages, not exact counts.
12. The installed exe restores `app\` from its embedded copy, so repo changes can't be tried by editing an install. Use `tools/replay.py` with the install's Python instead.
13. **No child process of `serve` may have the caller's pipes as its standard handles.** On Windows a spawned Python blocks in start-up querying a stdin pipe that the parent has a synchronous read pending on. `serve` reads from a private copy and points the standard handles at NUL first (`cli._private_std_pipes()`); keep that before `engine.warm_up()`.

## Building, testing, releasing

- **Build** (any OS, Go ≥ 1.24, no CGO): `./build/build.sh` produces `build/SubSync.exe` and `build/subsync-cli.exe`. The icon and manifest are pre-compiled in `launcher/rsrc_windows_amd64.syso`; rebuild that with `x86_64-w64-mingw32-windres --preprocessor=cat app.rc -O coff -o rsrc_windows_amd64.syso`.
- **Tests** (run from `tests/`): `python test_words.py`, `python test_reshape.py`, `python test_ui.py` (unit), `python sim.py`, `python make_fixtures.py && python gui_e2e.py`, `python cli_e2e.py "whole folder"` (one case per run; see its `cases`), `python serve_e2e.py`, `python serve_pipe_e2e.py` and `python detect_e2e.py` (print PASS/FAIL; `python test_detect.py` is unittest; the second runs `serve` as a separate process with piped, open stdin, so run it on Windows too). Use `QT_QPA_PLATFORM=offscreen` for headless runs.
  - Reference results: about 96–99% of lines within 0.3 s on simulated 45-minute episodes, about 80% fewer cut-off endings, zero new overlaps; on the synthesized-speech fixtures, every line is within 0.05 s.
- **Launcher tests:** `tests/launcher/run.sh` (about 5 min, 30 checks, needs wine + Xvfb + Go). Run it after any change in `launcher/`.
- **What can't be tested in a cloud/Linux session:** real Whisper or MiniLM inference (Hugging Face and python.org may be unreachable from the sandbox), NVIDIA GPU behaviour, and real Windows window behaviour (Wine ignores the "start hidden" flag from lesson 1). Be explicit with the owner about what was and wasn't tested.
- **Dependencies:** edit the pinned versions in `tools/requirements-windows.txt` / `tools/requirements-cuda.txt`, then run `tools/update_deps.sh`, which regenerates `launcher/manifest.json` (URLs, SHA-256, sizes, GPU DLL sizes). With unchanged pins it reproduces the shipped manifest exactly. Afterwards re-check lesson 3 (cuDNN must match ctranslate2's bundled shim) and lesson 5 (self-check against the real wheels), and run the launcher tests.
- **Version number:** it lives in `launcher/cli.go` (`appVersionString`), `app/cli.py` (the report's `subsync_version`) and `launcher/app.rc` (VERSIONINFO; after changing it rebuild `launcher/rsrc_windows_amd64.syso` with windres, see Build).
- **Releases:** cloud sessions **cannot** create GitHub releases or push tags (GitHub refuses with 403). A local session with `gh` signed in can create a **draft** release with the zip and notes attached (see "Handoff and access"); the owner publishes it. Prepare the release zip (`SubSync-vX.Y.Z-windows-x64.zip`: both exes, both READMEs, LICENSE), its SHA-256 and the release notes, then hand them to the owner with the web steps: Releases → Draft new release → create the tag on publish, targeting `main` → attach the zip → put the checksum in the description too (one upload of the `.sha256` file was rejected by the web form; a retry worked). The README download link points at `releases/latest`. Add the version to `CHANGELOG.md` and update "Current status" above.
- **Changing an existing release's tag:** GitHub won't delete a tag that a published release uses. The owner must delete the release first, then the tag, then recreate the release.

## Open items / ideas

- **Real-world tuning:** the match thresholds in `align.py` (`_threshold`, `strong = thr + 0.2`, run tolerance 0.8 s) were tuned on simulated data and a stand-in embedder. Check them against the owner's real episodes once results come in, especially with other-language audio.
- The exe is unsigned, so Windows SmartScreen shows "Windows protected your PC" (documented in the README).
- GitHub's Contributors box briefly showed `claude` from the original commit's trailer (since removed); it's cached and clears by itself.
- Possible future work, none of it requested yet: other subtitle languages, ASS output that keeps styling, a portable offline package for installs without internet.

# CLAUDE.md: context for Claude Code sessions on SubSync

This file is loaded automatically at the start of every Claude Code session in this repository. This is a **public repository**: keep this file, code, comments and commits free of personal information (names, emails, home paths, machine names, accounts).

## Working agreement with the owner

- **Plan first, then wait for approval** before multi-step work. After each major step, summarise briefly what was done and what's next. Small, clearly requested fixes can go straight ahead.
- **Ask before deleting, overwriting or renaming** existing files, and before anything hard to undo: force-pushes, history rewrites, tag/release changes.
- **Commits: no `Co-Authored-By: Claude` or `Claude-Session:` trailers**, and no other AI attribution in commit messages. The owner explicitly removed these from history.
- **Always pull before committing.** The owner also edits files in the GitHub web editor. Their wording in `README.md` is intentional, so don't revert it. For example, they softened "Don't delete anything" to "No need to delete the other files and folders", and removed the "start fresh" sentence.
- At the end of a task, **list the files created or modified**, with their locations.
- Deliverable files handed to the owner *outside* the repo (zips, notes) are named `DD-MM-YYYY-descriptive-name`. Files inside the repo keep conventional names.
- The owner is a capable non-developer. Explain outcomes in plain language; keep jargon for code and READMEs.

## Current status (keep this section up to date)

- **Released:** v1.2.0 (GitHub release `v1.2.0`, marked Latest, asset `SubSync-v1.2.0-windows-x64.zip`, SHA-256 `2af27e3d74ac639cbec12150e805654911b85673f4397eeaa79fe07040671cae`). The exes in that zip were built with Go 1.27.4 from the code in commit `94fbeca`, which is also what the tag points at. Before that: v1.1.0 (`6622ccac1d935ac644ec59a084f5b3c49db5dd78bad28798ce109805e464e2dc`, built from commit `0d3fa2b`). History of changes: `CHANGELOG.md`.
- **1.2.0 exes tested on Windows** (not yet on the owner's own PC): `version`, `check`, the command line with and without `--keep-layout` on a real episode (results matched `tools/replay.py`), and the window opening. Not run: the e2e and launcher tests.
- **Confirmed by the owner on real hardware** (Windows 11, NVIDIA RTX 3050): first-time setup, the window opening, the UI, no leftover processes.
- **First real-use report (English audio, broadcast TV captions):** v1.1.0 left ~11% of lines > 0.5 s off (placed by phrase, not word) and cut endings off. Fixed in **1.2.0** (word-accurate timing + "Tidy up lines"), developed on branch `feat/word-timing-tidy`; measured on that episode: 99.5% of starts within 0.3 s, 0 cut-off endings. Owner confirmed Whisper's word timings match what they see. Still unreported: other-language audio, and how the re-cut subtitles read over a whole season.
- **Local Windows sessions:** a SubSync install with a cached test episode makes `tools/replay.py` + `tools/measure.py` the fastest way to check matching changes. Commits use the repo-local GitHub noreply identity. Check first whether Go, `gh`, `windres` and espeak-ng are installed; without them there is no exe build, no e2e fixtures and no launcher tests.
- **1.3.0 in progress** (branch `claude/dazzling-cori-ltkcst`, not released): faster starts (first episode's audio read while the speech model loads, MiniLM loaded at warm-up, CLI warms up before scanning folders, `.pyc` precompiled at the end of setup), start-up and per-item timings in the logs, `speech_recognition` + per-item `timings` in the JSON report. Tested in a Linux sandbox only: unit tests, `gui_e2e.py`, all `cli_e2e.py` cases, the overlap with a stand-in model (both episodes' audio read during a 3 s model load), the Windows cross-build and `go vet`. **Not tested:** real Whisper/GPU, Windows, the launcher tests (no Wine). Measure on the owner's PC before releasing: `logs\setup.log` start line, `app.log` step times, `cli.log` per-item timings.
- **Jellyfin plugin** (`darkbepo/Jellyfin-Subfixer`, separate repo) runs `subsync-cli sync --pair … --report …` **once per episode**, so every SubSync start-up cost is paid per episode. It reads the report (now with `speech_recognition` and `timings`) and follows `logs\cli.log` for stage lines. Keep the report fields and the `[n/m] <video>: <stage>…` log lines stable, and add new fields rather than renaming.
- **Also in 1.3.0:** `--output FILE.srt` (one `--pair` only; needs `--overwrite` if the file exists) and `--progress` (`PROGRESS {json}` lines on stdout; event/stage names are a contract with the plugin, documented in `README-CLI.md`). Tested with `cli_e2e.py` (new cases) in the sandbox only.
- **Planned next (owner approved the direction):** a long-running `subsync-cli serve` mode that keeps the model loaded between episodes; measure 1.3.0's start-up saving on real hardware first.
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
  cli.py         command-line entry (sync)
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
    pipeline.process()  the whole matching step as a pure function (used by the Engine, tests and tools/replay.py)
    embed.py     MiniLM ONNX (CPU) mean-pooled embeddings
    gui.py, theme.py  PySide6 window; theme follows Windows colour scheme
    pairing.py   name / episode-code (S01E04, 1x04) / fuzzy pairing
    media.py, subtitles.py, paths.py, settings.py
tests/      sim.py (accuracy simulation), gui_e2e.py / cli_e2e.py (end-to-end with a fake ASR worker), make_fixtures.py (espeak-ng + ffmpeg)
            test_words.py / test_reshape.py / test_ui.py (unittest; run with an installed SubSync's runtime\python\python.exe)
tools/      replay.py (re-run process() on a cached transcript with this repo's code), measure.py (cue starts/ends vs Whisper words)
  launcher/   run.sh: 28 Wine checks of the real exes against a fake internet (fallbacks, repair, processes, CLI); see its README
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

## Building, testing, releasing

- **Build** (any OS, Go ≥ 1.24, no CGO): `./build/build.sh` produces `build/SubSync.exe` and `build/subsync-cli.exe`. The icon and manifest are pre-compiled in `launcher/rsrc_windows_amd64.syso`; rebuild that with `x86_64-w64-mingw32-windres --preprocessor=cat app.rc -O coff -o rsrc_windows_amd64.syso`.
- **Tests** (run from `tests/`): `python test_words.py`, `python test_reshape.py`, `python test_ui.py` (unit), `python sim.py`, `python make_fixtures.py && python gui_e2e.py`, `python cli_e2e.py "whole folder"`. Use `QT_QPA_PLATFORM=offscreen` for headless runs.
  - Reference results: about 96–99% of lines within 0.3 s on simulated 45-minute episodes, about 80% fewer cut-off endings, zero new overlaps; on the synthesized-speech fixtures, every line is within 0.05 s.
- **Launcher tests:** `tests/launcher/run.sh` (about 5 min, 28 checks, needs wine + Xvfb + Go). Run it after any change in `launcher/`.
- **What can't be tested in a cloud/Linux session:** real Whisper or MiniLM inference (Hugging Face and python.org may be unreachable from the sandbox), NVIDIA GPU behaviour, and real Windows window behaviour (Wine ignores the "start hidden" flag from lesson 1). Be explicit with the owner about what was and wasn't tested.
- **Dependencies:** edit the pinned versions in `tools/requirements-windows.txt` / `tools/requirements-cuda.txt`, then run `tools/update_deps.sh`, which regenerates `launcher/manifest.json` (URLs, SHA-256, sizes, GPU DLL sizes). With unchanged pins it reproduces the shipped manifest exactly. Afterwards re-check lesson 3 (cuDNN must match ctranslate2's bundled shim) and lesson 5 (self-check against the real wheels), and run the launcher tests.
- **Version number:** it lives in `launcher/cli.go` (`appVersionString`), `app/cli.py` (the report's `subsync_version`) and `launcher/app.rc` (VERSIONINFO, which still says 1.0.0; needs a `.syso` rebuild to change).
- **Releases:** cloud sessions **cannot** create GitHub releases or push tags (GitHub refuses with 403). A local session with `gh` signed in can create a **draft** release with the zip and notes attached (see "Handoff and access"); the owner publishes it. Prepare the release zip (`SubSync-vX.Y.Z-windows-x64.zip`: both exes, both READMEs, LICENSE), its SHA-256 and the release notes, then hand them to the owner with the web steps: Releases → Draft new release → create the tag on publish, targeting `main` → attach the zip → put the checksum in the description too (one upload of the `.sha256` file was rejected by the web form; a retry worked). The README download link points at `releases/latest`. Add the version to `CHANGELOG.md` and update "Current status" above.
- **Changing an existing release's tag:** GitHub won't delete a tag that a published release uses. The owner must delete the release first, then the tag, then recreate the release.

## Open items / ideas

- **Real-world tuning:** the match thresholds in `align.py` (`_threshold`, `strong = thr + 0.2`, run tolerance 0.8 s) were tuned on simulated data and a stand-in embedder. Check them against the owner's real episodes once results come in, especially with other-language audio.
- The `app.rc` VERSIONINFO still says 1.0.0.
- The exe is unsigned, so Windows SmartScreen shows "Windows protected your PC" (documented in the README).
- GitHub's Contributors box briefly showed `claude` from the original commit's trailer (since removed); it's cached and clears by itself.
- Possible future work, none of it requested yet: other subtitle languages, ASS output that keeps styling, a portable offline package for installs without internet.

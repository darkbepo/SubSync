# Changelog

## 1.3.0 (not released yet)

Faster starts; the results and the matching are unchanged.

- **The first episode's audio is read while the speech model loads.** Before, reading only started once the model was ready. This saves up to the model's loading time on every run (window and command line), and matters most when another program runs `subsync-cli` once per episode.
- **The line-matching model loads at start**, alongside the speech model, instead of after the first episode has been listened to.
- **The command line starts loading both models before it scans the folders.**
- **Setup prepares Python's ready-to-run files** (`.pyc`) for the libraries, so the first start after installing doesn't have to.
- **Timings in the logs.** `logs\app.log` shows each start-up step with the seconds since start; `logs\setup.log` gets one line per start ("self-check … ms, window open after … s"); `logs\worker.log` and `logs\cli.log` say how long the speech model took to load; `cli.log` gets each item's read-audio / listen / match seconds.
- **JSON report:** new `speech_recognition` (GPU or CPU, card name, model load seconds) and, per synced item, `timings`.

## 1.2.0

- **Word-accurate timing** (English audio). Every subtitle now starts when its first word is spoken and ends after its last. Before, subtitles were placed by whole spoken phrases, so lines that start mid-sentence (common in TV captions) or open with a short sentence ("Hmm. Let me see…") kept their late start. On a real broadcast-caption episode, subtitles starting within 0.3 s of their first word went from 85% to 99.5%, and lines disappearing before their words were spoken went from 9 to 0.
- **Tidy up lines** (new setting, on by default; `--keep-layout` turns it off on the command line). Subtitles are re-cut to one sentence (or a natural part of a long one) per subtitle, at most 2 lines of 42 characters; sentences that captions chopped up are joined; different speakers get their own subtitle, very short replies are paired with dashes; sound descriptions stay with their sentence; capital letters are repaired using what Whisper heard. Words are never changed. With other-language audio only subtitles taller than 2 lines are split.
- **Per-line details** in `logs\details\<video>.tsv` for troubleshooting.
- The result summary, the hover details and the command-line JSON report show how many subtitles were joined, split and re-capitalised.

## 1.1.0

- **Fallback download sources** for first install and repairs:
  - Python: python.org, then NuGet.
  - Libraries: the exact PyPI link, then any PEP 503 package index (pypi.org, mirrors).
  - Models: huggingface.co, then hf-mirror.com, then a backup repository if the original disappears.
  - Everything is checksum-verified. An optional `sources.json` can add your own locations.
- **Models are pinned** to the exact revision installed first (`runtime\models.lock.json`).
- **Self-check on every start.** Every installed file is checked, and anything missing or damaged is re-downloaded on its own; the setup window shows "Repairing SubSync".
- **Command line**: `subsync-cli.exe` with `sync`, `setup`, `check`, documented exit codes, a JSON report and `logs\cli.log`.
- The window and the command line can run at the same time on one folder.

## 1.0.3

- **Speech-aware endings.** Lines stay on screen until their words have been spoken (+0.3 s) and long enough to read (at least 1 s, at most about 20 characters per second). They are never stretched over the next line and never made shorter.
- Individual line corrections can no longer make neighbouring lines swap places.
- The result summary and its details show how many endings were extended.
- First user README.

## 1.0.2

- **Fixed: the window never appeared.** The launcher started the app with a "start hidden" flag, which Windows applied to the app's window, so it ran invisibly. The app now also forces its window visible.
- **Nothing is left running:** the launcher supervises the app through a Windows job object. Helper processes end when the app closes, crashes or fails to start, or if the launcher is killed. The speech helper also exits by itself if the window process disappears.
- One SubSync window per folder; a second start brings the open one to the front. Leftover processes from older versions are ended at start.
- A crash after the window opens is now reported with a dialog.

## 1.0.1

- One consistent Microsoft C++ runtime set, loaded before any library. This was a suspected cause of the 1.0.0 problem; the real cause was fixed in 1.0.2.
- Startup diagnostics: each startup step, native crash traces and Qt messages go to `logs\app.log`. If the app closes before its window appears, a dialog shows the reason.

## 1.0.0

- First version: per-line sync (Whisper large-v3-turbo + multilingual matching), split/drift detection, bulk processing with GPU pipelining and transcript cache, a drag-and-drop window with automatic pairing, a first-run installer that keeps everything in the program's folder, and a modern light/dark UI.

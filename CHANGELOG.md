# Changelog

## 1.5.2

- **Tidy up lines: anything in brackets at the end of a caption now goes with the next line.** 1.5.1 did this only for a description of how a line is spoken ("(Quietly)"). A name or a sound in round or square brackets ("[Dexter]", "[Phone rings]", "(sighs)") at the end of a caption, right after a finished sentence, was still joined to that sentence. It now starts the next line ("[Phone rings] Hello?"), which is where captions usually put it. Inside an unfinished sentence nothing moves, and music notes stay with their song.

## 1.5.1

- **Tidy up lines: a description of how a line is spoken stays with that line.** "(Quietly)", "(whispering)", "(in Spanish)" and the like at the end of a caption, right after a finished sentence, were joined to that sentence ("I'll call S.F.P.D for backup. (Quietly)" then "Jane!"). They now go with the line they describe ("I'll call S.F.P.D for backup." then "(Quietly) Jane!"). A sound that happens ("(sighs)", "[door slams]") still stays with its sentence.

## 1.5.0

- **Danish subtitles.** SubSync now also syncs Danish subtitles, typically on English audio. It recognises them by their name (`.da`, `.dan`, `.danish`, `.dansk`) or, cautiously, by their text, and saves the result as `<video>.da.srt` (`.dan.srt` with the three-letter setting). English subtitles are handled exactly as before.
- **Timed by the English subtitle.** When the same video also has an English subtitle, the English one is synced first and each Danish line takes the timing of the English line(s) that say the same thing. That is more precise than timing it from the audio alone, which is used otherwise (and as a fallback).
- A video can now have an English and a Danish subtitle in the same run; each is synced and saved separately.
- Window: a small `EN` / `DA` badge shows each subtitle's language; right-click → *Subtitle language* changes it.
- Command line: `--sub-lang auto|en|da` and `--reference EN.srt`; `serve` requests take `subtitle_language` and `reference`; the report gets `subtitle_language`, `timing_from` and `reference_subtitle`. Nothing was renamed or removed.

## 1.4.1

- **No more subtitles that flash by too fast to read.** When a subtitle's timing was moved, the next one could end up starting just after it, and the first one was then cut back to make room, sometimes to a few hundredths of a second. On screen that looked like a missing line. It happened to about 1–3 % of subtitles, most often sound descriptions such as "[door slams]" and short replies. No words were ever removed. Now such a subtitle gets the room before the next one if there is at least 0.5 s, and otherwise stays on screen for 0.7 s together with the next one (players show both; never three at once). With *Tidy up lines* on, a sound description that starts right next to its dialogue becomes one subtitle with it. Starts are not moved for this, so the timing accuracy is unchanged, and with *Tidy up lines* off every original subtitle is still exactly one subtitle in the result. The report counts these as `kept_visible`.
- Reading subtitles: in a file without subtitle numbers, a row that is only a number (for example "1985") is no longer taken for a subtitle number and dropped.
- New `tools/check_srt.py` lists subtitles in a result that are hard to see, and with the original also checks that every word is still there.

## 1.4.0

- **New: `subsync-cli detect <video>`** finds out which language is spoken, from a short sample, for files whose audio is tagged "und" or not tagged at all. It reads 30-second pieces spread over the video, keeps only the parts with voice (up to 90 s of speech), and runs Whisper's language detection on them, without transcribing anything. One JSON object on stdout (`language`, `probability`, which track was checked and its tag, …). It is read-only (nothing is written next to the video or into the cache), checks the same audio track `sync` would use unless `--track` says otherwise, and can run while `serve` is running; if the GPU is full it switches to the CPU. For the Jellyfin plugin's Check button.
- Internal: the audio decoding is split into small parts shared by `sync` and `detect`; `sync`'s decoded audio is byte-for-byte unchanged.

## 1.3.1

- **`serve` no longer hangs when the calling program keeps its input open (Windows).** In 1.3.0 an item stayed at "queued" until the program closed `serve`'s stdin: the speech worker got the request pipe as its own input and could not finish starting while `serve` was waiting for the next request on it. `serve` now reads requests from a private copy of the pipe, and every worker it starts (at the beginning and after a GPU-to-CPU fallback) gets an empty input and output instead.

## 1.3.0

Faster starts; the results and the matching are unchanged.

- **The first episode's audio is read while the speech model loads.** Before, reading only started once the model was ready. This saves up to the model's loading time on every run (window and command line), and matters most when another program runs `subsync-cli` once per episode.
- **The line-matching model loads at start**, alongside the speech model, instead of after the first episode has been listened to.
- **The command line starts loading both models before it scans the folders.**
- **Setup prepares Python's ready-to-run files** (`.pyc`) for the libraries, so the first start after installing doesn't have to.
- **Timings in the logs.** `logs\app.log` shows each start-up step with the seconds since start; `logs\setup.log` gets one line per start ("self-check … ms, window open after … s"); `logs\worker.log` and `logs\cli.log` say how long the speech model took to load; `cli.log` gets each item's read-audio / listen / match seconds.
- **Command line `--output FILE.srt`:** with exactly one `--pair`, write the result to that file (for example the input subtitle itself, or a name like `.en.hi.srt`).
- **Command line `--progress`:** machine-readable `PROGRESS {json}` lines on stdout (stage, percent, GPU/CPU, item finished) for programs that run SubSync, such as the Jellyfin plugin.
- **`subsync-cli serve`:** stays running for another program (pairs in on stdin, results out on stdout, one JSON object per line). Setup check, Python start and model loading happen once instead of per item, and items overlap.
- The exe's file properties now show the real version (they said 1.0.0).
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

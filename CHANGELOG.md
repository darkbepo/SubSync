# Changelog

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

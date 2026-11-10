# Launcher tests (Wine)

These tests run the **real** `SubSync.exe` and `subsync-cli.exe` under Wine, against a fake internet on `127.0.0.1:8766`. Only Python is replaced: a small stand-in program (`fake_app/`) imitates the app's visible behaviour, such as opening a window, starting a helper process or crashing. Everything else is the launcher itself: downloads, fallbacks, checksums, self-check, repair, process supervision and CLI exit codes.

```bash
tests/launcher/run.sh                 # ~5 min; prints PASS/FAIL per check, exit code 0 = all passed
WORK=/tmp/other-dir tests/launcher/run.sh
```

Needs Linux with `wine` (64-bit), `Xvfb`, Go ≥ 1.24 and `python3`. It creates its own Wine prefix in the work folder, and installs a dummy `nvcuda.dll` there so the GPU path is exercised.

## What it covers (28 checks)

| | Scenario |
|---|---|
| A | First install with **every primary link dead**: Python comes from the NuGet layout (no `pythonw.exe`), libraries from the package index, models from the HF host. Also checks the C++ runtime set, GPU DLL extraction and model pinning. |
| B | An intact install starts without downloading anything. |
| C | A deleted library file, a truncated GPU DLL, a deleted model file and a deleted app file are each repaired. Nothing intact is downloaded again. |
| D | The pinned model repository disappears, so the model is re-installed from the backup repository and the lock is updated. |
| E | Processes: app + helper running; a second start only focuses the open window; killing the launcher ends everything; a crash before the window leaves nothing running; stray processes from older versions are cleaned up. |
| F | CLI: `help`, `check` (intact → 0, damaged → 8), `sync` repairs first and passes exit codes through with the arguments and working folder intact, an app crash gives 10, an unknown command gives 6, nothing is left running. |

## Files

| File | Role |
|---|---|
| `run.sh` | Builds everything, starts the fake server, runs the scenarios. |
| `make_fixtures.py` | Fake downloads (Python, wheels with real `RECORD` files, a GPU wheel, three model repos), a test manifest whose primary links are all dead, and `sources.json`. |
| `fake_server.py` | Python host, PEP 503 index and Hugging Face API, with HTTP Range support. Logs every request to `<work>/requests.log`. Repositories listed in `<work>/gone.txt` answer 404. |
| `fake_app/` | Stand-in for `python(w).exe`. Its behaviour is chosen by `<root>/mode.txt`: `normal`, `stay`, `crash` or `exitN`. |

## Limits

Wine does **not** reproduce everything Windows does. In particular, it ignores the "start hidden" flag that once made SubSync's window invisible on real Windows (CLAUDE.md, lesson 1). Window behaviour, real Python and Qt, and the NVIDIA GPU must still be checked on a real Windows PC.

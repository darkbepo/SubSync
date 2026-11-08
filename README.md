# SubSync

SubSync fixes English subtitles that are out of sync with a video, **line by line**. It listens to the video's own audio and moves every subtitle line to where it is actually spoken, so a file that is fine in the first half and off in the second half is fixed as well. So are single lines that are badly timed.

It works in bulk: drop in a whole season and walk away.

**[⬇ Download the latest version](https://github.com/darkbepo/SubSync/releases/latest)**

---

## Requirements

- Windows 10 or 11, 64-bit
- About **6 GB of free disk space** in the folder you put SubSync in
- An **NVIDIA graphics card** is strongly recommended (it is many times faster). Without one SubSync still works, using the processor instead.
- An internet connection for the **first start only**

## Installing

1. Create an empty folder you own, for example `D:\Tools\SubSync`. Avoid `Program Files`, because SubSync needs to write into its own folder.
2. Download the zip from **[Releases](https://github.com/darkbepo/SubSync/releases/latest)**, put `SubSync.exe` (and `subsync-cli.exe` if you want the command line) in that folder, and double-click `SubSync.exe`.
3. Windows may say *"Windows protected your PC"* because the program is not signed. Click **More info → Run anyway**.
4. The first start shows a setup window and downloads what SubSync needs (about 3.2 GB: Python, libraries, the NVIDIA GPU libraries if you have an NVIDIA card, and two AI models). If the download is interrupted, it continues where it left off next time.
5. When setup is done, SubSync opens. Later starts open straight away.

Everything is stored **inside that folder**. Nothing is installed anywhere else on your PC.

## Using it

1. **Drop files onto the window**: videos (`.mkv`, `.mp4`, `.avi`, …) and subtitles (`.srt`, `.ass`, `.ssa`, `.vtt`). You can also drop whole folders, such as a season folder.
2. SubSync pairs each subtitle with its video by name or episode number (`S01E04`, `1x04`), shown as **Reference video | Reference subtitle | Result**.
   - If a row is missing its video or subtitle, drop the right file **onto that row**.
   - Right-click a row to remove it, run it again, or open its folder.
3. Choose how results are saved (see *Settings*) and press **Start**.
4. Each finished row shows **Synced** plus a short summary. **Hover** over a result to see the details. **Double-click** it to show the new file in Explorer.

The new subtitle is saved **next to the video**, named after the video, for example `Show.S01E04.1080p.en.srt`, so media servers such as Jellyfin and Plex pick it up automatically.

You can keep adding files while it is running; they join the queue. **Stop** cancels everything that hasn't finished.

## Settings

| Setting | What it does |
|---|---|
| **Save as `.en.srt` / `.eng.srt`** | The language tag in the file name. |
| **Overwrite existing** (on) | If a subtitle with that name already exists, it is replaced. If another program (a player, a Jellyfin scan) has it open, SubSync waits until it is released. |
| **Overwrite existing** (off) | The existing file is kept and the new one is saved as `name.en.#1.srt` (then `#2`, …). |

## What SubSync fixes

- **Constant offsets**: everything is a few seconds early or late.
- **Partial offsets**: synced in one part, off in another (different cut, ad breaks, recaps).
- **Drift**: gets slowly worse over the episode.
- **Single bad lines**: one line far off while its neighbours are fine.
- **Lines that vanish too early**: a line is kept on screen until its words have been spoken, and every line stays up long enough to read (at least 1 second, at most ~20 characters per second). Lines are never stretched over the next line and never made shorter.

The audio may be in any language. The subtitle must be **English**. When a video has several audio tracks, SubSync prefers the English one, because matching is most precise when audio and subtitle share a language.

## Reading the result

- **Synced**: done. The summary shows how many lines were matched to speech, how far lines were moved, how many timing sections were found (more than one means the file was partly out of sync), and how many endings were extended.
- **Check**: SubSync could match only a few lines to the audio, usually because the subtitle belongs to a different video or episode. **No file is written** in this case.
- **Failed**: something went wrong. Hover for the reason.

Lines that are not speech (`[door slams]`, `♪ music ♪`) are moved along with the lines around them.

## Speed

On an RTX 3050, expect roughly **1–2 minutes per 45-minute episode**. While one episode is being listened to, the next one is already being read and the previous one is being matched and saved. Running a file a second time is nearly instant, because SubSync remembers what it heard. Without an NVIDIA card, expect it to be several times slower.

## Your privacy

Everything happens on your PC. The only internet access is the one-time setup download from `python.org`, `pypi.org` / `files.pythonhosted.org` and `huggingface.co`. Your videos and subtitles never leave your computer.

## Updating

Replace `SubSync.exe` (and `subsync-cli.exe`) with the new version and start it. **No need to delete the other files and folders.** It downloads only what changed, if anything.

## Missing or damaged files repair themselves

Every time SubSync starts it checks that all of its files are present and intact (this takes well under a second). If something was deleted or damaged, for example a model file or a library, the setup window appears as **"Repairing SubSync"** and downloads **only that piece** again. You never need to delete anything to "start fresh".

The downloads have **backup sources**. If a link stops working (python.org, the Python package site, or the AI model site), SubSync automatically tries official mirrors and backup copies. Every file is checked against a known fingerprint, so a backup source can't give you a wrong or tampered file. The AI models are locked to the exact version that was first installed.

## Troubleshooting

- **The status chip in the top-right says "CPU mode"**: no usable NVIDIA card was found, or its driver is too old. Updating the NVIDIA driver usually fixes this.
- **An error window appears at start**: it shows what went wrong. The full details are in the `logs` folder (`app.log`, `worker.log`, `startup.log`). Send those if you report a problem.
- **Setup or repair keeps failing**: check the internet connection and start again. Finished downloads are kept. Details are in `logs\setup.log`.
- **Starting SubSync twice** just brings the open window to the front.
- **Nothing is left running** after SubSync closes, crashes or fails to start, so the folder can always be deleted.

## Folder contents

| Folder / file | Contents |
|---|---|
| `SubSync.exe` | The program you start |
| `subsync-cli.exe` | The command-line version (see `README-CLI.md`) |
| `runtime\` | Python, libraries, NVIDIA GPU libraries |
| `models\` | The speech recognition and matching models |
| `app\` | SubSync's own program files |
| `cache\` | Remembered transcripts (safe to delete; files are just processed again) |
| `logs\` | Log files for troubleshooting |
| `settings.json` | Your settings |
| `sources.json` | *Optional*: extra download locations (see `README-CLI.md`) |

## Command line

`subsync-cli.exe` does the same as the window, from a terminal or a script, for example `subsync-cli "D:\Shows\Season 1"`. See **`README-CLI.md`**.

## Uninstalling

Close SubSync and delete the folder. That's all.

## License and credits

SubSync is released under the [MIT License](LICENSE). It builds on open-source work, which it downloads during setup: [faster-whisper](https://github.com/SYSTRAN/faster-whisper) / [CTranslate2](https://github.com/OpenNMT/CTranslate2), OpenAI's Whisper model ([large-v3-turbo](https://huggingface.co/mobiuslabsgmbh/faster-whisper-large-v3-turbo)), [paraphrase-multilingual-MiniLM-L12-v2](https://huggingface.co/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2), [PySide6 / Qt](https://www.qt.io/qt-for-python), [PyAV](https://github.com/PyAV-Org/PyAV) / FFmpeg, [ONNX Runtime](https://onnxruntime.ai/), [RapidFuzz](https://github.com/rapidfuzz/RapidFuzz), [pysubs2](https://github.com/tkarabela/pysubs2) and NVIDIA cuBLAS/cuDNN. Each keeps its own license.

For developers: see [README-CLI.md](README-CLI.md) for the command line, architecture, tests and building.

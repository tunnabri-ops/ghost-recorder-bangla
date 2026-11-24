# Ghost Recorder Bangla — Python Desktop App

Screen recorder + screenshot tool with a dark Bangla UI (PySide6).

## Features

- 📷 Full-screen screenshot (PNG)
- 📷 Region screenshot — set X, Y, width, height and capture
- ● Screen recording to MP4 (15 fps) — Start / Pause / Resume / Stop
- ⏱ Live recording timer
- 📁 Choose your save folder
- 📜 History list — double-click any recording or screenshot to open it

## Install & Run

```bash
pip install -r requirements.txt
python app.py
```

Requires Python 3.9+ and a display (Windows / macOS / Linux desktop).
Recording uses `mss` for capture and `imageio` + `imageio-ffmpeg` for MP4.

## Files

- `app.py` — PySide6 GUI (dark Bangla UI)
- `recorder.py` — recording / screenshot engine (no GUI imports, headless-testable)
- `requirements.txt` — dependencies

## Notes

- Default save folder: `~/Videos/GhostRecorderBangla`
- Recordings are saved as `recording-YYYYMMDD-HHMMSS.mp4`,
  screenshots as `screenshot-YYYYMMDD-HHMMSS.png`.
- On a headless machine (no display) screenshots/recording fail with a
  clear Bangla/English message instead of crashing.

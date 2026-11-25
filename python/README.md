# Ghost Recorder Bangla — Python Desktop App

Screen recorder + screenshot tool with a dark Bangla UI (PySide6).

## Features

- 📷 Full-screen screenshot (PNG)
- 📷 Region screenshot — set X, Y, width, height and capture
- ● Screen recording to MP4 (15 fps) — Start / Pause / Resume / Stop
- ⏱ Live recording timer
- 📁 Choose your save folder
- 📜 History list — double-click any recording or screenshot to open it

## 🆕 What's new in v1.1.0

- **📷 Webcam overlay** — tick the checkbox and the camera picture is
  composited into a corner of the recording (corner selectable, OpenCV).
  Needs `opencv-python` and a camera: if either is missing, the checkbox
  is disabled with a clear message — nothing is faked. If the camera is
  requested but unavailable, recording refuses with a clear error instead
  of silently recording without the overlay.
- **✏️ Screenshot annotate** — after every screenshot an editor opens:
  pen, arrow, click-to-place text, colour picker, line width, Undo.
  Saving writes the edited PNG; cancelling discards the screenshot.
- **🎞 GIF export** — "শেষ রেকর্ডিং GIF করুন" converts the last recording
  (or a picked video) to an animated GIF via PIL, or ffmpeg for video
  files when imageio can't read them.
- **⏰ Scheduled recording** — set a time + duration (0 = stop manually);
  the schedule is saved to `schedule.json` in the save folder and the app
  starts recording automatically when due, stopping after the duration.

## Install & Run

```bash
pip install -r requirements.txt
python app.py
```

Requires Python 3.9+ and a display (Windows / macOS / Linux desktop).
Recording uses `mss` for capture and `imageio` + `imageio-ffmpeg` for MP4.
`opencv-python` is optional — webcam overlay only.

## Files

- `app.py` — PySide6 GUI (dark Bangla UI), version 1.1.0
- `recorder.py` — recording / screenshot engine (no GUI imports, headless-testable)
- `scheduler.py` — scheduled recording: time parsing, next-run maths, JSON persistence
- `test_v11.py` — headless tests for the v1.1.0 engine features (`python3 test_v11.py`)
- `requirements.txt` — dependencies

## Notes

- Default save folder: `~/Videos/GhostRecorderBangla`
- Recordings are saved as `recording-YYYYMMDD-HHMMSS.mp4`,
  screenshots as `screenshot-YYYYMMDD-HHMMSS.png`.
- On a headless machine (no display) screenshots/recording fail with a
  clear Bangla/English message instead of crashing.

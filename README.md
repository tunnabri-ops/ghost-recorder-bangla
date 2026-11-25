# 👻 Ghost Recorder Bangla

[![Screen Recorder](https://img.shields.io/badge/type-screen%20recorder-blue)](https://github.com/tunnabri-ops/ghost-recorder-bangla)
[![Platforms](https://img.shields.io/badge/platforms-Web%20%7C%20Python%20%7C%20Electron-green)](https://github.com/tunnabri-ops/ghost-recorder-bangla)
[![Language](https://img.shields.io/badge/UI-Bangla%20%2B%20English-orange)](https://github.com/tunnabri-ops/ghost-recorder-bangla)

**A Bangla-first screen recorder and screenshot tool for everyone — web, Python desktop, and Electron desktop in one project.**

**Record your screen or take a screenshot — with a Bangla-first interface and three ways to run it.**

> বাংলা সংস্করণ নিচে আছে। / Bangla version below.

## 🆕 What's new in v1.1.0

- **📷 Webcam overlay** — a small face-cam in a corner of the recording (corner selectable). Web + Electron composite the camera onto the recorded video; Python overlays with OpenCV when a camera is available — and says so plainly (option disabled) when OpenCV or a camera is missing, instead of faking it.
- **✏️ Screenshot annotate** — draw with a pen, add arrows and text, pick a colour, undo, then save the edited PNG. Available in all three versions.
- **🎞 GIF export** — turn a recording into an animated GIF. Web uses a built-in GIF encoder (no library); Python exports with PIL (or ffmpeg for video files); Electron converts with ffmpeg.
- **⏰ Scheduled recording** — set a time and the recording starts automatically. Python + Electron persist the schedule and check it while the app runs; the web version works while the page stays open (and says so in the UI).

## ✨ Features

- **Record screen / window / tab** — pick what to record, the browser or desktop app captures it
- **Pause / Resume** — pause mid-recording and continue from where you stopped
- **Live timer** — see exactly how long you have been recording
- **Preview before saving** — watch the recording, then download or save it
- **Screenshot** — capture the current frame as a PNG, full screen or a region (Python desktop)
- **Recording quality** — high / medium / low bitrate (web)
- **Recording history** — finished recordings and screenshots are listed; search your history on desktop
- **Webcam overlay** — small face-cam in a corner of the recording (v1.1.0)
- **Screenshot annotate** — pen, arrows, text before saving (v1.1.0)
- **GIF export** — turn a recording into an animated GIF (v1.1.0)
- **Scheduled recording** — starts automatically at a set time (v1.1.0)
- **Minimize to tray** (Electron desktop) — closing the window hides it in the system tray
- **Update check** (Electron desktop) — checks GitHub releases and tells you when a newer version is out

## 🚀 Three versions

| Version | Folder | Run it |
|---|---|---|
| 🌐 Web app | `web/` | Open `index.html` in a browser — nothing to install |
| 🐍 Python desktop | `python/` | `pip install -r requirements.txt` → `python app.py` |
| 🖥️ Desktop app | `desktop/` | `npm install` → `npm start` (Windows `.exe` is built by GitHub Actions) |

### Web app

Open `web/index.html` in any modern browser. Click **Record**, pick a screen, window or tab, and the recording starts. Pause and resume any time; Stop ends it and shows a preview with a Download button (`.webm`). The **Screenshot** button saves the current frame as a PNG. History is kept in the browser (max 50 entries) and can be cleared.

### Python desktop

```bash
cd python
pip install -r requirements.txt
python app.py
```

Full-screen screenshot or region screenshot (enter X / Y / width / height), screen recording to **MP4** (15 fps, pause/resume, live timer), save folder picker (default `~/Videos/GhostRecorderBangla`), and a history list — double-click any entry to open the file.

### Electron desktop

```bash
cd desktop
npm install
npm start
```

Pick a screen or window from the thumbnail list, record to **WebM**, take screenshots, save with the system save dialog. Closing the window minimizes to the tray. The Windows installer (`.exe`) is built automatically by GitHub Actions on every push to `main`.

## ⚠️ Honest limits

- The browser asks for screen permission **every time** — nothing records without you picking a screen.
- **System audio capture depends on the browser and OS** — on some setups the recording may be silent. The app tells you if no audio track arrives.
- Web and Electron record **WebM** video; Python desktop records **MP4**.
- **Webcam overlay needs a camera + permission.** Python also needs OpenCV (`pip install opencv-python`); without it the option is disabled with a clear message. If the camera is denied mid-setup, the recording still happens — without the overlay, and the app says so.
- **Scheduled recording needs the app/page running.** Python + Electron keep the schedule saved and check it while the app runs (even minimized to the tray); the web version only works while the page stays open. A missed time (app closed) does not fire late.
- **GIF export needs something to convert with.** Web encodes in the browser; Python uses PIL/ffmpeg; Electron uses ffmpeg (bundled via `ffmpeg-static`, or the system `ffmpeg` on PATH) — if ffmpeg is missing, Electron reports a clear error instead of a fake GIF.
- If you stop sharing (or close the shared window), the recording stops — what was captured up to that point is still saved.
- The Python app needs a real display to capture the screen; it refuses cleanly with a clear message when there is none.

## 🇧🇩 বাংলা

**Ghost Recorder বাংলা — সবার জন্য বাংলা স্ক্রিন রেকর্ডার ও স্ক্রিনশট টুল।**

- স্ক্রিন / উইন্ডো / ট্যাব রেকর্ড — যা রেকর্ড করবে নিজে বেছে নাও
- Pause / Resume, লাইভ টাইমার, প্রিভিউ দেখে তারপর সেভ
- স্ক্রিনশট — পুরো স্ক্রিন বা নির্দিষ্ট অংশ, PNG ফাইল
- বাংলা ইন্টারফেস, ডার্ক ডিজাইন, রেকর্ডিং হিস্ট্রি
- ওয়েব, Python ডেস্কটপ আর Electron ডেস্কটপ — তিনভাবে চলে

## 📄 License

MIT — use it however you like; credit is appreciated.

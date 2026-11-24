# Ghost Recorder Bangla — Desktop (Electron)

Bangla screen recorder + screenshot tool. Pick a screen or window, record it
to WebM, or capture the current frame as a PNG. Dark Bangla UI, history with
search, minimize-to-tray, and an update check against GitHub releases.

## Install

```bash
cd desktop
npm install
```

Requires Node.js 18+ (Electron 33). Windows build needs Windows; macOS/Linux
builds use the same commands with their own targets.

## Run

```bash
npm start
```

## Build a Windows installer

```bash
npm run build:win
```

Produces an NSIS installer (choose install folder) + a portable exe in
`dist/`. The installer is one-click-off (`oneClick: false`,
`allowToChangeInstallationDirectory: true`).

## How it works

1. **সোর্স বেছে নিন** — screen / window list with thumbnails
   (`desktopCapturer` via main, thumbnails as data URLs).
2. **প্রিভিউ** — `navigator.mediaDevices.getUserMedia` with
   `chromeMediaSource: 'desktop'` + the chosen `chromeMediaSourceId`.
3. **রেকর্ড** — `MediaRecorder` (WebM, VP9 → VP8 → plain WebM fallback),
   chunks collected, on Stop the Blob is saved via the `save-file` IPC
   (Save dialog → file written by main). Pause / Resume supported.
4. **স্ক্রিনশট** — current preview frame drawn to a canvas → PNG blob →
   same `save-file` IPC.
5. **হিস্টোরি** — recordings + screenshots saved in this session, with a
   live filename search box. History is session-only; files stay on disk.
6. **ট্রে** — closing the window hides it to the tray (Show / Check for
   update / Quit). The tray icon is an embedded PNG — no download.
7. **আপডেট** — checks `api.github.com/repos/tunnabri-ops/ghost-recorder-bangla/releases/latest`,
   compares the tag with the app version, shows a banner only when a newer
   version exists. Silent on failure, never auto-downloads; the Download
   button only opens the releases page (allow-listed in main).

## Files

- `main.js` — window, tray, IPC handlers (`get-sources`, `save-file`,
  `check-for-update`, `open-external`, `get-app-version`,
  `minimize-to-tray`, `quit-app`)
- `preload.js` — `contextBridge` exposing only `window.ghostRecorder`
- `renderer/` — Bangla dark UI (`index.html`, `style.css`, `renderer.js`)

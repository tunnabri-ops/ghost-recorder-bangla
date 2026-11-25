'use strict';

const { app, BrowserWindow, ipcMain, dialog, shell, Tray, Menu, nativeImage, desktopCapturer } = require('electron');
const path = require('path');
const fs = require('fs');
const os = require('os');
const { spawn } = require('child_process');

const REPO = 'tunnabri-ops/ghost-recorder-bangla';
const RELEASES_URL = `https://github.com/${REPO}/releases`;
const LATEST_API_URL = `https://api.github.com/repos/${REPO}/releases/latest`;

// 32x32 white ghost on transparent background (embedded, no download).
const TRAY_ICON_BASE64 =
  'iVBORw0KGgoAAAANSUhEUgAAACAAAAAgCAYAAABzenr0AAAAvElEQVR4nO2XwQ2DMAxFE9QJuHUD9p+GDXpjhfSCqsiKjf+vQ4vIO2E5tj/BJkpKdyczQaWUoibMGcoJLbYKs0KmHsWR9S4BaHEk7lAAW9wbbwr4trgnj7sHeqEKiHr7o3z/uwNn8UAD5ufyed5eq9unAe1AXUDali9MQA+GAEiAbKzatnwW6pEZ/SNKqX1Ew2NYw4ydhO4BduzCBERBC2CbTvLzJrzuJxgCugvQLhZ5h/FBAlpBtc36BpI31ItTQaFzSPkAAAAASUVORK5CYII=';

let mainWindow = null;
let tray = null;
let isQuitting = false;

function trayIcon() {
  return nativeImage.createFromDataURL(`data:image/png;base64,${TRAY_ICON_BASE64}`);
}

function compareVersions(a, b) {
  const pa = String(a).split('.').map((n) => parseInt(n, 10) || 0);
  const pb = String(b).split('.').map((n) => parseInt(n, 10) || 0);
  const len = Math.max(pa.length, pb.length);
  for (let i = 0; i < len; i++) {
    const x = pa[i] || 0;
    const y = pb[i] || 0;
    if (x !== y) return x > y ? 1 : -1;
  }
  return 0;
}

async function checkForUpdate() {
  const currentVersion = app.getVersion();
  try {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 10000);
    const res = await fetch(LATEST_API_URL, {
      signal: controller.signal,
      headers: { Accept: 'application/vnd.github+json', 'User-Agent': 'ghost-recorder-bangla' },
    });
    clearTimeout(timer);
    if (!res.ok) return { updateAvailable: false, version: null, url: null, currentVersion };
    const data = await res.json();
    const tag = String(data.tag_name || '').replace(/^v/, '');
    const url = data.html_url || RELEASES_URL;
    if (!tag) return { updateAvailable: false, version: null, url: null, currentVersion };
    return {
      updateAvailable: compareVersions(tag, currentVersion) > 0,
      version: tag,
      url,
      currentVersion,
    };
  } catch (_err) {
    // Silent on failure: offline / GitHub unreachable is not an error for the user.
    return { updateAvailable: false, version: null, url: null, currentVersion };
  }
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1000,
    height: 680,
    backgroundColor: '#0f172a',
    title: 'Ghost Recorder Bangla',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  mainWindow.loadFile(path.join(__dirname, 'renderer', 'index.html'));

  // Close hides to tray instead of quitting (Quit comes from the tray menu / app button).
  mainWindow.on('close', (event) => {
    if (!isQuitting) {
      event.preventDefault();
      mainWindow.hide();
    }
  });

  mainWindow.on('closed', () => {
    mainWindow = null;
  });
}

function createTray() {
  tray = new Tray(trayIcon());
  tray.setToolTip('Ghost Recorder Bangla');
  const menu = Menu.buildFromTemplate([
    {
      label: 'Show / দেখান',
      click: () => {
        if (mainWindow) {
          mainWindow.show();
          mainWindow.focus();
        }
      },
    },
    {
      label: 'Check for update / আপডেট দেখুন',
      click: async () => {
        const result = await checkForUpdate();
        if (mainWindow) mainWindow.webContents.send('update-result', result);
      },
    },
    { type: 'separator' },
    {
      label: 'Quit / বন্ধ করুন',
      click: () => {
        isQuitting = true;
        app.quit();
      },
    },
  ]);
  tray.setContextMenu(menu);
  tray.on('click', () => {
    if (mainWindow) {
      if (mainWindow.isVisible()) mainWindow.hide();
      else {
        mainWindow.show();
        mainWindow.focus();
      }
    }
  });
}

app.whenReady().then(() => {
  createWindow();
  createTray();
  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
    else if (mainWindow) mainWindow.show();
  });
});

app.on('window-all-closed', () => {
  // Keep running in the tray on Windows/Linux; quit on macOS like a normal app.
  if (process.platform === 'darwin') app.quit();
});

// ---- IPC: sources ---------------------------------------------------------
ipcMain.handle('get-sources', async () => {
  const sources = await desktopCapturer.getSources({
    types: ['screen', 'window'],
    thumbnailSize: { width: 320, height: 180 },
  });
  return sources.map((s) => ({
    id: s.id,
    name: s.name,
    thumbnail: s.thumbnail.toDataURL(),
  }));
});

// ---- IPC: save file -------------------------------------------------------
// Renderer passes { defaultName, data, kind } where data is an ArrayBuffer
// (from a MediaRecorder Blob or a canvas PNG blob) and kind is 'webm' | 'png'.
ipcMain.handle('save-file', async (_event, payload) => {
  const { defaultName, data, kind } = payload || {};
  if (!defaultName || !data) return { cancelled: true, path: null, error: 'missing-name-or-data' };
  const filters =
    kind === 'png'
      ? [{ name: 'PNG Image', extensions: ['png'] }]
      : kind === 'gif'
        ? [{ name: 'GIF Image', extensions: ['gif'] }]
        : [{ name: 'WebM Video', extensions: ['webm'] }];
  const { canceled, filePath } = await dialog.showSaveDialog({
    defaultPath: defaultName,
    filters,
  });
  if (canceled || !filePath) return { cancelled: true, path: null };
  try {
    const buffer = Buffer.from(new Uint8Array(data));
    fs.writeFileSync(filePath, buffer);
    return { cancelled: false, path: filePath };
  } catch (err) {
    return { cancelled: true, path: null, error: String(err && err.message ? err.message : err) };
  }
});

// ---- IPC: update check ----------------------------------------------------
ipcMain.handle('check-for-update', async () => checkForUpdate());

// ---- IPC: GIF export (v1.1.0) ---------------------------------------------
// Converts a saved WebM recording to an animated GIF with ffmpeg
// (two-pass palettegen/paletteuse, 10 fps, 480px wide).
// ffmpeg comes from the bundled ffmpeg-static binary when installed;
// otherwise the system `ffmpeg` on PATH is used. A missing ffmpeg is
// reported as a clear error — no fake GIF is ever produced.
function findFfmpeg() {
  try {
    // eslint-disable-next-line global-require
    const bundled = require('ffmpeg-static');
    if (bundled && fs.existsSync(bundled)) return bundled;
  } catch (_err) { /* not installed: fall through to PATH */ }
  return 'ffmpeg';
}

ipcMain.handle('export-gif', async (_event, payload) => {
  const { inputPath, defaultName } = payload || {};
  if (!inputPath || !fs.existsSync(inputPath)) {
    return { cancelled: true, path: null, error: 'input-not-found' };
  }
  const { canceled, filePath } = await dialog.showSaveDialog({
    defaultPath: defaultName || 'ghost-recorder.gif',
    filters: [{ name: 'GIF Image', extensions: ['gif'] }],
  });
  if (canceled || !filePath) return { cancelled: true, path: null };
  const ffmpeg = findFfmpeg();
  const palettePath = path.join(os.tmpdir(), `ghost-recorder-palette-${process.pid}.png`);
  const vf = 'fps=10,scale=480:-1:flags=lanczos';
  const run = (args) => new Promise((resolve, reject) => {
    const proc = spawn(ffmpeg, args);
    let stderr = '';
    proc.stderr.on('data', (d) => { stderr += d.toString(); });
    proc.on('error', reject);
    proc.on('close', (code) => {
      if (code === 0) resolve();
      else reject(new Error(stderr.slice(-300) || `ffmpeg exited with code ${code}`));
    });
  });
  try {
    await run(['-y', '-i', inputPath, '-vf', `${vf},palettegen`, palettePath]);
    await run(['-y', '-i', inputPath, '-i', palettePath, '-lavfi',
      `${vf}[x];[x][1:v]paletteuse`, filePath]);
  } catch (err) {
    return {
      cancelled: true,
      path: null,
      error: String(err && err.message ? err.message : err),
    };
  } finally {
    try { fs.unlinkSync(palettePath); } catch (_err) { /* palette is temp */ }
  }
  return { cancelled: false, path: filePath };
});

// ---- IPC: scheduled recording (v1.1.0) ------------------------------------
// The schedule lives in a JSON file under the app's userData folder, so it
// survives restarts. The renderer checks it on an interval and starts the
// recording when due; main only stores it.
function scheduleFilePath() {
  return path.join(app.getPath('userData'), 'schedule.json');
}

function readSchedule() {
  const fallback = { time: '09:00', durationMinutes: 5, enabled: false, lastFiredDate: null };
  try {
    const raw = fs.readFileSync(scheduleFilePath(), 'utf8');
    const parsed = JSON.parse(raw);
    if (parsed && typeof parsed === 'object') return { ...fallback, ...parsed };
  } catch (_err) { /* missing/corrupt file: defaults */ }
  return fallback;
}

ipcMain.handle('get-schedule', () => readSchedule());

ipcMain.handle('save-schedule', async (_event, schedule) => {
  const s = schedule || {};
  const time = String(s.time || '');
  if (!/^(?:[01]\d|2[0-3]):[0-5]\d$/.test(time)) {
    return { ok: false, error: 'bad-time' };
  }
  const durationMinutes = Math.max(0, Math.min(480, parseInt(s.durationMinutes, 10) || 0));
  const out = {
    time,
    durationMinutes,
    enabled: !!s.enabled,
    lastFiredDate: typeof s.lastFiredDate === 'string' ? s.lastFiredDate : null,
  };
  try {
    fs.mkdirSync(path.dirname(scheduleFilePath()), { recursive: true });
    fs.writeFileSync(scheduleFilePath(), JSON.stringify(out, null, 2));
    return { ok: true, schedule: out };
  } catch (err) {
    return { ok: false, error: String(err && err.message ? err.message : err) };
  }
});

ipcMain.handle('clear-schedule', async () => {
  try { fs.unlinkSync(scheduleFilePath()); } catch (_err) { /* already gone */ }
  return { ok: true };
});

// ---- IPC: app version -----------------------------------------------------
ipcMain.handle('get-app-version', () => app.getVersion());

// ---- IPC: open external (allow-listed to this repo's releases only) -------
ipcMain.handle('open-external', async (_event, url) => {
  const allowedPrefix = `${RELEASES_URL}/`;
  if (typeof url !== 'string' || (!url.startsWith(allowedPrefix) && url !== RELEASES_URL)) {
    return { ok: false, error: 'url-not-allowed' };
  }
  await shell.openExternal(url);
  return { ok: true };
});

// ---- IPC: tray / quit -----------------------------------------------------
ipcMain.on('minimize-to-tray', () => {
  if (mainWindow) mainWindow.hide();
});

ipcMain.on('quit-app', () => {
  isQuitting = true;
  app.quit();
});

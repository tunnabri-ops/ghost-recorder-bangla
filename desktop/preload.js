'use strict';

const { contextBridge, ipcRenderer } = require('electron');

// The ONLY bridge the renderer gets. No Node, no ipcRenderer, no desktopCapturer
// is exposed directly — the renderer captures via navigator.mediaDevices and
// talks to main only through these methods.
contextBridge.exposeInMainWorld('ghostRecorder', {
  // Returns [{ id, name, thumbnail }] for screens + windows.
  getSources: () => ipcRenderer.invoke('get-sources'),

  // Saves a recording/screenshot. Args: { defaultName, data (ArrayBuffer), kind: 'webm'|'png' }
  // Returns { cancelled, path, error? }.
  saveFile: (payload) => ipcRenderer.invoke('save-file', payload),

  // Returns { updateAvailable, version, url, currentVersion }. Never downloads.
  checkForUpdate: () => ipcRenderer.invoke('check-for-update'),

  // Opens a URL — main only allows this repo's releases page. Returns { ok, error? }.
  openExternal: (url) => ipcRenderer.invoke('open-external', url),

  // Current app version string, e.g. "1.0.0".
  getAppVersion: () => ipcRenderer.invoke('get-app-version'),

  // Hide the window to the tray (tray menu: Show / Check for update / Quit).
  minimizeToTray: () => ipcRenderer.send('minimize-to-tray'),

  // Quit the app for real (bypasses the close-to-tray behaviour).
  quitApp: () => ipcRenderer.send('quit-app'),

  // Fired when the tray menu's "Check for update" runs. Returns an unsubscribe fn.
  onUpdateResult: (callback) => {
    const listener = (_event, result) => callback(result);
    ipcRenderer.on('update-result', listener);
    return () => ipcRenderer.removeListener('update-result', listener);
  },
});

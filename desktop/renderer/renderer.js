'use strict';

/* Ghost Recorder Bangla — renderer.
 * Flow: pick source -> getUserMedia(desktop, chromeMediaSourceId) -> preview
 * -> MediaRecorder (video/webm) -> chunks -> Stop -> Blob -> arrayBuffer
 * -> ghostRecorder.saveFile() -> history entry.
 * Screenshot: draw preview video frame to canvas -> PNG blob -> saveFile().
 * All main-process work goes through window.ghostRecorder (preload bridge).
 */

const $ = (id) => document.getElementById(id);

const preview = $('preview');
const previewEmpty = $('previewEmpty');
const sourceListEl = $('sourceList');
const historyListEl = $('historyList');
const historySearchEl = $('historySearch');
const historyCountEl = $('historyCount');
const statusText = $('statusText');
const timerEl = $('timer');
const timerBigEl = $('timerBig');
const recBadge = $('recBadge');
const updateBanner = $('updateBanner');
const updateStatusEl = $('updateStatus');

const state = {
  sources: [],
  selectedSourceId: null,
  stream: null, // live desktop capture stream (preview + recording source)
  recorder: null,
  chunks: [],
  recording: false,
  paused: false,
  timerId: null,
  startedAt: 0, // Date.now() when (re)started, adjusted for pauses
  elapsedBeforePause: 0,
  history: [], // { kind: 'video'|'image', name, path, time }
  pendingUpdateUrl: null,
};

function fmt(ms) {
  const total = Math.max(0, Math.floor(ms / 1000));
  const m = String(Math.floor(total / 60)).padStart(2, '0');
  const s = String(total % 60).padStart(2, '0');
  return `${m}:${s}`;
}

function stamp() {
  const d = new Date();
  const p = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}-${p(d.getHours())}${p(d.getMinutes())}${p(d.getSeconds())}`;
}

function setStatus(text, recording) {
  statusText.textContent = text;
  statusText.classList.toggle('recording', !!recording);
}

function updateButtons() {
  const hasStream = !!state.stream;
  $('btnRecord').disabled = !hasStream || state.recording;
  $('btnPause').disabled = !state.recording || state.paused;
  $('btnResume').disabled = !state.recording || !state.paused;
  $('btnResume').classList.toggle('hidden', !state.paused);
  $('btnPause').classList.toggle('hidden', state.paused);
  $('btnStop').disabled = !state.recording;
  $('btnScreenshot').disabled = !hasStream || !preview.videoWidth;
}

function startTimer() {
  stopTimer();
  state.startedAt = Date.now();
  state.elapsedBeforePause = 0;
  const tick = () => {
    const elapsed = Date.now() - state.startedAt + state.elapsedBeforePause;
    timerEl.textContent = fmt(elapsed);
    timerBigEl.textContent = fmt(elapsed);
  };
  tick();
  state.timerId = setInterval(tick, 250);
}

function stopTimer() {
  if (state.timerId) {
    clearInterval(state.timerId);
    state.timerId = null;
  }
}

function stopStream() {
  if (state.stream) {
    state.stream.getTracks().forEach((t) => t.stop());
    state.stream = null;
    preview.srcObject = null;
  }
  previewEmpty.classList.remove('hidden');
  updateButtons();
}

// ---- Sources --------------------------------------------------------------
async function loadSources() {
  sourceListEl.innerHTML = '<p class="empty">সোর্স লোড হচ্ছে…</p>';
  try {
    state.sources = await window.ghostRecorder.getSources();
  } catch (err) {
    sourceListEl.innerHTML = `<p class="empty">সোর্স লোড করা যায়নি: ${err.message || err}</p>`;
    return;
  }
  if (!state.sources.length) {
    sourceListEl.innerHTML = '<p class="empty">কোনো স্ক্রিন বা উইন্ডো পাওয়া যায়নি।</p>';
    return;
  }
  sourceListEl.innerHTML = '';
  state.sources.forEach((src) => {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'source-item' + (src.id === state.selectedSourceId ? ' selected' : '');
    const img = document.createElement('img');
    img.src = src.thumbnail;
    img.alt = '';
    const span = document.createElement('span');
    span.className = 'name';
    span.textContent = src.name;
    btn.appendChild(img);
    btn.appendChild(span);
    btn.addEventListener('click', () => selectSource(src.id));
    sourceListEl.appendChild(btn);
  });
}

async function selectSource(id) {
  if (state.recording) {
    alert('রেকর্ড চলাকালীন সোর্স বদলানো যাবে না — আগে থামান।');
    return;
  }
  state.selectedSourceId = id;
  document.querySelectorAll('.source-item').forEach((el) => el.classList.remove('selected'));
  // Mark the clicked card (re-render is cheap and keeps state consistent).
  await loadSources();
  stopStream();
  setStatus('প্রিভিউ চালু হচ্ছে…', false);
  try {
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: false,
      video: {
        mandatory: {
          chromeMediaSource: 'desktop',
          chromeMediaSourceId: id,
          minWidth: 1280,
          maxWidth: 1920,
          minHeight: 720,
          maxHeight: 1080,
        },
      },
    });
    state.stream = stream;
    preview.srcObject = stream;
    previewEmpty.classList.add('hidden');
    setStatus('প্রস্তুত — রেকর্ড শুরু করুন', false);
    // If the user closes the shared window/screen, the track ends: clear preview.
    stream.getVideoTracks()[0].addEventListener('ended', () => {
      if (!state.recording) {
        stopStream();
        setStatus('সোর্স বন্ধ হয়ে গেছে — আবার বেছে নিন', false);
      }
    });
  } catch (err) {
    setStatus('প্রিভিউ চালু হয়নি — সোর্সটি আবার বেছে নিন', false);
    alert(`প্রিভিউ চালু হয়নি: ${err && err.message ? err.message : err}`);
  }
  updateButtons();
}

// ---- Recording ------------------------------------------------------------
function pickMimeType() {
  const candidates = [
    'video/webm;codecs=vp9',
    'video/webm;codecs=vp8',
    'video/webm',
  ];
  for (const type of candidates) {
    if (window.MediaRecorder && MediaRecorder.isTypeSupported(type)) return type;
  }
  return '';
}

function startRecording() {
  if (!state.stream || state.recording) return;
  const mimeType = pickMimeType();
  try {
    state.recorder = mimeType
      ? new MediaRecorder(state.stream, { mimeType })
      : new MediaRecorder(state.stream);
  } catch (err) {
    alert(`রেকর্ড শুরু হয়নি: ${err && err.message ? err.message : err}`);
    return;
  }
  state.chunks = [];
  state.recorder.ondataavailable = (e) => {
    if (e.data && e.data.size > 0) state.chunks.push(e.data);
  };
  state.recorder.onstop = onRecordingStopped;
  state.recorder.onerror = (e) => {
    setStatus('রেকর্ডে সমস্যা হয়েছে', false);
    alert(`রেকর্ডে সমস্যা: ${(e && e.error && e.error.message) || 'অজানা ত্রুটি'}`);
  };
  state.recorder.start(250);
  state.recording = true;
  state.paused = false;
  startTimer();
  recBadge.classList.remove('hidden');
  setStatus('রেকর্ড হচ্ছে…', true);
  updateButtons();
}

function pauseRecording() {
  if (state.recorder && state.recording && !state.paused) {
    state.recorder.pause();
    state.paused = true;
    state.elapsedBeforePause += Date.now() - state.startedAt;
    stopTimer();
    setStatus('বিরতি — আবার শুরু করতে চাপুন', false);
    updateButtons();
  }
}

function resumeRecording() {
  if (state.recorder && state.recording && state.paused) {
    state.recorder.resume();
    state.paused = false;
    state.startedAt = Date.now();
    const tick = () => {
      const elapsed = Date.now() - state.startedAt + state.elapsedBeforePause;
      timerEl.textContent = fmt(elapsed);
      timerBigEl.textContent = fmt(elapsed);
    };
    tick();
    state.timerId = setInterval(tick, 250);
    setStatus('রেকর্ড হচ্ছে…', true);
    updateButtons();
  }
}

function stopRecording() {
  if (state.recorder && state.recording) {
    state.recorder.stop();
    // onRecordingStopped() runs next, saves the file and resets state.
  }
}

async function onRecordingStopped() {
  state.recording = false;
  state.paused = false;
  stopTimer();
  recBadge.classList.add('hidden');
  timerEl.textContent = '00:00';
  timerBigEl.textContent = '00:00';
  setStatus('ফাইল সেভ হচ্ছে…', false);
  updateButtons();
  const blob = new Blob(state.chunks, { type: 'video/webm' });
  state.chunks = [];
  if (blob.size === 0) {
    setStatus('খালি রেকর্ডিং — কিছু সেভ হয়নি', false);
    return;
  }
  const name = `ghost-recorder-${stamp()}.webm`;
  try {
    const data = await blob.arrayBuffer();
    const result = await window.ghostRecorder.saveFile({ defaultName: name, data, kind: 'webm' });
    if (result && !result.cancelled && result.path) {
      addHistory('video', name, result.path);
      setStatus('রেকর্ডিং সেভ হয়েছে ✓', false);
    } else {
      setStatus('সেভ বাতিল করা হয়েছে', false);
    }
  } catch (err) {
    setStatus('সেভ করতে সমস্যা হয়েছে', false);
    alert(`সেভ হয়নি: ${err && err.message ? err.message : err}`);
  }
  updateButtons();
}

// ---- Screenshot -----------------------------------------------------------
async function takeScreenshot() {
  if (!state.stream || !preview.videoWidth) {
    alert('প্রথমে একটি সোর্স বেছে নিন।');
    return;
  }
  const canvas = document.createElement('canvas');
  canvas.width = preview.videoWidth;
  canvas.height = preview.videoHeight;
  const ctx = canvas.getContext('2d');
  ctx.drawImage(preview, 0, 0, canvas.width, canvas.height);
  const blob = await new Promise((resolve) => canvas.toBlob(resolve, 'image/png'));
  if (!blob) {
    alert('স্ক্রিনশট নেওয়া যায়নি।');
    return;
  }
  const name = `ghost-screenshot-${stamp()}.png`;
  try {
    const data = await blob.arrayBuffer();
    const result = await window.ghostRecorder.saveFile({ defaultName: name, data, kind: 'png' });
    if (result && !result.cancelled && result.path) {
      addHistory('image', name, result.path);
      setStatus('স্ক্রিনশট সেভ হয়েছে ✓', false);
    }
  } catch (err) {
    alert(`স্ক্রিনশট সেভ হয়নি: ${err && err.message ? err.message : err}`);
  }
}

// ---- History --------------------------------------------------------------
function addHistory(kind, name, path) {
  state.history.unshift({
    kind,
    name,
    path,
    time: new Date().toLocaleString('bn-BD'),
  });
  renderHistory();
}

function renderHistory() {
  const q = (historySearchEl.value || '').trim().toLowerCase();
  const shown = state.history.filter((h) => !q || h.name.toLowerCase().includes(q));
  historyCountEl.textContent = `${state.history.length}টি`;
  if (!shown.length) {
    historyListEl.innerHTML = state.history.length
      ? '<li class="empty">খুঁজে কিছু পাওয়া যায়নি।</li>'
      : '<li class="empty">এখনো কিছু সেভ হয়নি — এই সেশনে সেভ করা রেকর্ডিং ও স্ক্রিনশট এখানে দেখা যাবে।</li>';
    return;
  }
  historyListEl.innerHTML = '';
  shown.forEach((h) => {
    const li = document.createElement('li');
    const badge = document.createElement('span');
    badge.className = 'badge ' + (h.kind === 'video' ? 'video' : 'image');
    badge.textContent = h.kind === 'video' ? 'ভিডিও' : 'ছবি';
    const nameEl = document.createElement('div');
    nameEl.className = 'file-name';
    nameEl.appendChild(badge);
    nameEl.appendChild(document.createTextNode(h.name));
    const pathEl = document.createElement('div');
    pathEl.className = 'file-path';
    pathEl.textContent = h.path;
    const metaEl = document.createElement('div');
    metaEl.className = 'file-meta';
    metaEl.textContent = h.time;
    li.appendChild(nameEl);
    li.appendChild(pathEl);
    li.appendChild(metaEl);
    historyListEl.appendChild(li);
  });
}

// ---- Update check ---------------------------------------------------------
function showUpdate(result) {
  if (!result) return;
  if (result.updateAvailable && result.version) {
    $('updateVersion').textContent = `v${result.version}`;
    $('currentVersion').textContent = `v${result.currentVersion || ''}`;
    state.pendingUpdateUrl = result.url;
    updateBanner.classList.remove('hidden');
    updateStatusEl.textContent = `নতুন ভার্সন v${result.version} এসেছে`;
  } else {
    updateStatusEl.textContent = 'আপনি সর্বশেষ ভার্সন ব্যবহার করছেন ✓';
  }
}

async function runUpdateCheck() {
  updateStatusEl.textContent = 'আপডেট দেখা হচ্ছে…';
  try {
    const result = await window.ghostRecorder.checkForUpdate();
    showUpdate(result);
  } catch (_err) {
    updateStatusEl.textContent = '';
  }
}

// ---- Wire up --------------------------------------------------------------
$('btnRefreshSources').addEventListener('click', loadSources);
$('btnRecord').addEventListener('click', startRecording);
$('btnPause').addEventListener('click', pauseRecording);
$('btnResume').addEventListener('click', resumeRecording);
$('btnStop').addEventListener('click', stopRecording);
$('btnScreenshot').addEventListener('click', takeScreenshot);
$('btnUpdate').addEventListener('click', runUpdateCheck);
$('btnTray').addEventListener('click', () => window.ghostRecorder.minimizeToTray());
$('btnQuit').addEventListener('click', () => window.ghostRecorder.quitApp());
$('btnDismissUpdate').addEventListener('click', () => updateBanner.classList.add('hidden'));
$('btnDownloadUpdate').addEventListener('click', () => {
  if (state.pendingUpdateUrl) window.ghostRecorder.openExternal(state.pendingUpdateUrl);
});
historySearchEl.addEventListener('input', renderHistory);

// Tray menu's "Check for update" sends its result back through this event.
window.ghostRecorder.onUpdateResult((result) => showUpdate(result));

// Init
(async () => {
  try {
    const v = await window.ghostRecorder.getAppVersion();
    if (v) $('appVersion').textContent = `v${v}`;
  } catch (_err) { /* keep default label */ }
  updateButtons();
  renderHistory();
  await loadSources();
  runUpdateCheck();
})();

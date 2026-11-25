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
  history: [], // { kind: 'video'|'image'|'gif', name, path, time }
  pendingUpdateUrl: null,
  // v1.1.0 — webcam overlay
  camStream: null,
  camVideo: null,
  compositeCanvas: null,
  compositeCtx: null,
  compositeRAF: 0,
  compositeStream: null,
  lastVideoPath: null,
  // v1.1.0 — scheduled recording (persisted in main)
  schedule: { time: '09:00', durationMinutes: 5, enabled: false, lastFiredDate: null },
  schedTimerId: null,
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
  $('btnGif').disabled = !state.lastVideoPath;
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
  stopComposite();
  if (state.stream) {
    state.stream.getTracks().forEach((t) => t.stop());
    state.stream = null;
    preview.srcObject = null;
  }
  previewEmpty.classList.remove('hidden');
  updateButtons();
}

// ---- Webcam overlay (v1.1.0) ----------------------------------------------
function camCornerXY(w, h, cw, ch) {
  const m = 12;
  const corner = $('camCorner').value;
  if (corner === 'top-left') return [m, m];
  if (corner === 'top-right') return [w - cw - m, m];
  if (corner === 'bottom-left') return [m, h - ch - m];
  return [w - cw - m, h - ch - m]; // bottom-right
}

function drawComposite() {
  if (!preview.videoWidth || !state.compositeCanvas) return;
  const canvas = state.compositeCanvas;
  if (canvas.width !== preview.videoWidth || canvas.height !== preview.videoHeight) {
    canvas.width = preview.videoWidth;
    canvas.height = preview.videoHeight;
  }
  const ctx = state.compositeCtx;
  const w = canvas.width;
  const h = canvas.height;
  ctx.drawImage(preview, 0, 0, w, h);
  if (state.camVideo && state.camVideo.videoWidth > 0) {
    let cw = Math.round(w * 0.25);
    let ch = Math.round((cw * state.camVideo.videoHeight) / state.camVideo.videoWidth);
    if (ch > Math.round(h * 0.5)) {
      ch = Math.round(h * 0.5);
      cw = Math.round((ch * state.camVideo.videoWidth) / state.camVideo.videoHeight);
    }
    const xy = camCornerXY(w, h, cw, ch);
    ctx.drawImage(state.camVideo, xy[0], xy[1], cw, ch);
    ctx.strokeStyle = '#fff';
    ctx.lineWidth = 3;
    ctx.strokeRect(xy[0] - 2, xy[1] - 2, cw + 4, ch + 4);
  }
}

function compositeLoop() {
  drawComposite();
  state.compositeRAF = requestAnimationFrame(compositeLoop);
}

function startComposite() {
  state.compositeCanvas = $('compositePreview');
  state.compositeCtx = state.compositeCanvas.getContext('2d');
  state.compositeCanvas.classList.remove('hidden');
  preview.classList.add('hidden');
  state.compositeStream = state.compositeCanvas.captureStream(30);
  compositeLoop();
}

function stopComposite() {
  if (state.compositeRAF) cancelAnimationFrame(state.compositeRAF);
  state.compositeRAF = 0;
  if (state.compositeCanvas) state.compositeCanvas.classList.add('hidden');
  preview.classList.remove('hidden');
  if (state.camStream) {
    state.camStream.getTracks().forEach((t) => t.stop());
    state.camStream = null;
  }
  state.camVideo = null;
  state.compositeStream = null;
  state.compositeCanvas = null;
  state.compositeCtx = null;
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

async function startRecording() {
  if (!state.stream || state.recording) return;
  // v1.1.0: webcam overlay — camera track composited onto the recorded
  // canvas. If the camera is denied/unavailable, record without it and
  // say so plainly instead of faking the overlay.
  if ($('camChk').checked && !state.compositeStream) {
    try {
      const camStream = await navigator.mediaDevices.getUserMedia({
        video: { width: 320 },
        audio: false,
      });
      state.camStream = camStream;
      state.camVideo = document.createElement('video');
      state.camVideo.muted = true;
      state.camVideo.srcObject = camStream;
      await state.camVideo.play();
      startComposite();
    } catch (err) {
      setStatus('ক্যামেরা চালু হয়নি — ওভারলে ছাড়াই রেকর্ড হচ্ছে', false);
      $('camNote').textContent = `ক্যামেরা চালু হয়নি (${err && err.message ? err.message : err}) — ওভারলে ছাড়াই রেকর্ড হচ্ছে।`;
    }
  }
  const recStream = state.compositeStream || state.stream;
  const mimeType = pickMimeType();
  try {
    state.recorder = mimeType
      ? new MediaRecorder(recStream, { mimeType })
      : new MediaRecorder(recStream);
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
  setStatus(state.compositeStream ? 'রেকর্ড হচ্ছে… (ওয়েবক্যাম ওভারলেসহ)' : 'রেকর্ড হচ্ছে…', true);
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
      state.lastVideoPath = result.path;
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

// ---- Screenshot + annotation (v1.1.0) -------------------------------------
// Screenshot draws the current frame (or the composited canvas when the
// webcam overlay is on) into the annotation editor; saving from the
// editor writes the edited PNG.
let annCtx = null;
let annTool = 'pen';
let annDrawing = false;
let annPoints = [];
let annUndoStack = [];
let annSnapshot = null;

function annSetTool(tool) {
  annTool = tool;
  ['toolPen', 'toolArrow', 'toolText'].forEach((id) => $(id).classList.remove('active'));
  $('toolPen').classList.toggle('active', tool === 'pen');
  $('toolArrow').classList.toggle('active', tool === 'arrow');
  $('toolText').classList.toggle('active', tool === 'text');
}

function annPos(ev) {
  const canvas = $('annotateCanvas');
  const rect = canvas.getBoundingClientRect();
  const scale = canvas.width / rect.width;
  return [(ev.clientX - rect.left) * scale, (ev.clientY - rect.top) * scale];
}

function annPushUndo() {
  const canvas = $('annotateCanvas');
  annUndoStack.push(canvas.toDataURL('image/png'));
  if (annUndoStack.length > 20) annUndoStack.shift();
}

function annDrawStroke(pts, previewOnly) {
  const canvas = $('annotateCanvas');
  const ctx = annCtx;
  if (!previewOnly) annPushUndo();
  ctx.strokeStyle = $('annColor').value;
  ctx.fillStyle = $('annColor').value;
  ctx.lineWidth = +$('annWidth').value;
  ctx.lineCap = 'round';
  ctx.lineJoin = 'round';
  if (annTool === 'pen' && pts.length >= 2) {
    ctx.beginPath();
    ctx.moveTo(pts[0][0], pts[0][1]);
    for (let i = 1; i < pts.length; i++) ctx.lineTo(pts[i][0], pts[i][1]);
    ctx.stroke();
  } else if (annTool === 'arrow' && pts.length >= 2) {
    const x1 = pts[0][0];
    const y1 = pts[0][1];
    const x2 = pts[pts.length - 1][0];
    const y2 = pts[pts.length - 1][1];
    ctx.beginPath();
    ctx.moveTo(x1, y1);
    ctx.lineTo(x2, y2);
    ctx.stroke();
    const angle = Math.atan2(y2 - y1, x2 - x1);
    const head = Math.max(10, ctx.lineWidth * 4);
    [Math.PI - 0.45, Math.PI + 0.45].forEach((delta) => {
      const a = angle + delta;
      ctx.beginPath();
      ctx.moveTo(x2, y2);
      ctx.lineTo(x2 + head * Math.cos(a), y2 + head * Math.sin(a));
      ctx.stroke();
    });
  }
}

function annRedrawFrom(dataUrl, done) {
  const img = new Image();
  img.onload = () => {
    const canvas = $('annotateCanvas');
    annCtx.clearRect(0, 0, canvas.width, canvas.height);
    annCtx.drawImage(img, 0, 0);
    if (done) done();
  };
  img.src = dataUrl;
}

function openAnnotate(sourceCanvas) {
  const canvas = $('annotateCanvas');
  canvas.width = sourceCanvas.width;
  canvas.height = sourceCanvas.height;
  annCtx = canvas.getContext('2d');
  annCtx.drawImage(sourceCanvas, 0, 0);
  annUndoStack = [];
  $('annotatePanel').classList.remove('hidden');
  $('annotatePanel').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

async function saveAnnotatedShot() {
  const canvas = $('annotateCanvas');
  const blob = await new Promise((resolve) => canvas.toBlob(resolve, 'image/png'));
  if (!blob) {
    alert('এডিট করা ছবি বানানো যায়নি।');
    return;
  }
  const name = `ghost-screenshot-annotated-${stamp()}.png`;
  try {
    const data = await blob.arrayBuffer();
    const result = await window.ghostRecorder.saveFile({ defaultName: name, data, kind: 'png' });
    if (result && !result.cancelled && result.path) {
      addHistory('image', name, result.path);
      setStatus('এডিট করা স্ক্রিনশট সেভ হয়েছে ✓', false);
      $('annotatePanel').classList.add('hidden');
    }
  } catch (err) {
    alert(`স্ক্রিনশট সেভ হয়নি: ${err && err.message ? err.message : err}`);
  }
}

async function takeScreenshot() {
  if (!state.stream || !preview.videoWidth) {
    alert('প্রথমে একটি সোর্স বেছে নিন।');
    return;
  }
  const canvas = document.createElement('canvas');
  if (state.compositeCanvas && state.compositeCanvas.width > 0) {
    // Webcam overlay is on: capture the composited frame, face-cam included.
    canvas.width = state.compositeCanvas.width;
    canvas.height = state.compositeCanvas.height;
    canvas.getContext('2d').drawImage(state.compositeCanvas, 0, 0);
  } else {
    canvas.width = preview.videoWidth;
    canvas.height = preview.videoHeight;
    const ctx = canvas.getContext('2d');
    ctx.drawImage(preview, 0, 0, canvas.width, canvas.height);
  }
  openAnnotate(canvas);
}

// ---- GIF export (v1.1.0) ---------------------------------------------------
async function exportGif() {
  if (!state.lastVideoPath) {
    alert('আগে একটি রেকর্ডিং সেভ করুন, তারপর GIF বানান।');
    return;
  }
  const btn = $('btnGif');
  btn.disabled = true;
  setStatus('GIF বানানো হচ্ছে…', false);
  try {
    const name = state.lastVideoPath.split(/[\\/]/).pop().replace(/\.webm$/i, '') + '-clip.gif';
    const result = await window.ghostRecorder.exportGif({
      inputPath: state.lastVideoPath,
      defaultName: name,
    });
    if (result && !result.cancelled && result.path) {
      addHistory('gif', name, result.path);
      setStatus('GIF সেভ হয়েছে ✓', false);
    } else if (result && result.error) {
      setStatus('GIF হয়নি', false);
      alert(`GIF বানানো যায়নি: ${result.error}`);
    } else {
      setStatus('GIF সেভ বাতিল করা হয়েছে', false);
    }
  } catch (err) {
    setStatus('GIF হয়নি', false);
    alert(`GIF বানানো যায়নি: ${err && err.message ? err.message : err}`);
  }
  updateButtons();
}

// ---- Scheduled recording (v1.1.0) -----------------------------------------
function refreshSchedStatus() {
  const s = state.schedule;
  const el = $('schedStatus');
  if (!s.enabled) {
    el.textContent = 'নির্ধারিত রেকর্ডিং বন্ধ আছে।';
    return;
  }
  const now = new Date();
  const [hh, mm] = s.time.split(':').map(Number);
  const target = new Date(now);
  target.setHours(hh, mm, 0, 0);
  if (target <= now) target.setDate(target.getDate() + 1);
  const diff = Math.max(0, Math.round((target - now) / 1000));
  const h = Math.floor(diff / 3600);
  const m = Math.floor((diff % 3600) / 60);
  const sec = diff % 60;
  el.textContent = `পরের রেকর্ডিং: ${s.time} — আর ${h} ঘণ্টা ${m} মিনিট ${sec} সেকেন্ড বাকি`
    + (s.durationMinutes > 0 ? ` (সময়কাল ${s.durationMinutes} মিনিট)` : ' (নিজে থামাতে হবে)')
    + ' — অ্যাপ চালু থাকলেই চলবে।';
}

async function persistSchedule(patch) {
  const next = { ...state.schedule, ...patch };
  try {
    const result = await window.ghostRecorder.saveSchedule(next);
    if (result && result.ok && result.schedule) state.schedule = result.schedule;
    else if (result && result.error) alert(`সময়সূচি সংরক্ষণ হয়নি: ${result.error}`);
  } catch (err) {
    alert(`সময়সূচি সংরক্ষণ হয়নি: ${err && err.message ? err.message : err}`);
  }
  refreshSchedStatus();
}

async function checkSchedule() {
  refreshSchedStatus();
  if (state.recording || !state.schedule.enabled) return;
  const now = new Date();
  const today = now.toISOString().slice(0, 10);
  if (state.schedule.lastFiredDate === today) return;
  const [hh, mm] = state.schedule.time.split(':').map(Number);
  const target = new Date(now);
  target.setHours(hh, mm, 0, 0);
  if (target <= now && now - target < 90000) {
    await persistSchedule({ lastFiredDate: today });
    // Use the already-selected source, or the first one available.
    if (!state.stream) {
      const id = state.selectedSourceId || (state.sources[0] && state.sources[0].id);
      if (!id) {
        setStatus('নির্ধারিত সময় হয়েছে, কিন্তু কোনো সোর্স পাওয়া যায়নি', false);
        return;
      }
      await selectSource(id);
    }
    if (!state.stream) return;
    setStatus('⏰ নির্ধারিত সময় — রেকর্ডিং শুরু হচ্ছে…', true);
    await startRecording();
    if (state.schedule.durationMinutes > 0 && state.recording) {
      setTimeout(() => { if (state.recording) stopRecording(); }, state.schedule.durationMinutes * 60000);
    }
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
    badge.className = 'badge ' + (h.kind === 'video' ? 'video' : h.kind === 'gif' ? 'gif' : 'image');
    badge.textContent = h.kind === 'video' ? 'ভিডিও' : h.kind === 'gif' ? 'GIF' : 'ছবি';
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
$('btnGif').addEventListener('click', exportGif);
$('toolPen').addEventListener('click', () => annSetTool('pen'));
$('toolArrow').addEventListener('click', () => annSetTool('arrow'));
$('toolText').addEventListener('click', () => annSetTool('text'));
$('annUndo').addEventListener('click', () => {
  const prev = annUndoStack.pop();
  if (prev) annRedrawFrom(prev);
});
$('annSave').addEventListener('click', saveAnnotatedShot);
$('annCancel').addEventListener('click', () => $('annotatePanel').classList.add('hidden'));
(function () {
  const canvas = $('annotateCanvas');
  function redrawWithPreview(pts) {
    if (annSnapshot) annRedrawFrom(annSnapshot, () => annDrawStroke(pts, true));
  }
  canvas.addEventListener('pointerdown', (ev) => {
    ev.preventDefault();
    canvas.setPointerCapture(ev.pointerId);
    const pos = annPos(ev);
    if (annTool === 'text') {
      const text = window.prompt('ছবিতে বসানোর টেক্সট লিখুন:');
      if (text) {
        annPushUndo();
        annCtx.fillStyle = $('annColor').value;
        annCtx.font = `bold ${Math.max(14, +$('annWidth').value * 8)}px sans-serif`;
        annCtx.fillText(text, pos[0], pos[1]);
      }
      return;
    }
    annDrawing = true;
    annPoints = [pos];
    annSnapshot = canvas.toDataURL('image/png');
  });
  canvas.addEventListener('pointermove', (ev) => {
    if (!annDrawing) return;
    annPoints.push(annPos(ev));
    redrawWithPreview(annPoints);
  });
  function endStroke(ev) {
    if (!annDrawing) return;
    annDrawing = false;
    annPoints.push(annPos(ev));
    if (annSnapshot) annRedrawFrom(annSnapshot, () => annDrawStroke(annPoints, false));
    annPoints = [];
    annSnapshot = null;
  }
  canvas.addEventListener('pointerup', endStroke);
  canvas.addEventListener('pointercancel', () => {
    annDrawing = false;
    annPoints = [];
    annSnapshot = null;
  });
})();
// v1.1.0 — scheduled recording controls
$('schedSaveBtn').addEventListener('click', () => {
  const time = $('schedTime').value;
  const durationMinutes = +$('schedDur').value;
  if (!/^(?:[01]\d|2[0-3]):[0-5]\d$/.test(time)) {
    alert('সময় সঠিক নয় — HH:MM ফরম্যাটে লিখুন (যেমন 09:00)।');
    return;
  }
  if (Number.isNaN(durationMinutes) || durationMinutes < 0 || durationMinutes > 480) {
    alert('সময়কাল ০–৪৮০ মিনিটের মধ্যে হতে হবে।');
    return;
  }
  persistSchedule({
    time,
    durationMinutes,
    enabled: $('schedEnable').checked,
  });
  setStatus('⏰ সময়সূচি সংরক্ষিত হয়েছে', false);
});
$('schedEnable').addEventListener('change', () => {
  persistSchedule({ enabled: $('schedEnable').checked });
});
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
  // v1.1.0 — load the persisted schedule, then check it every 5s.
  try {
    const saved = await window.ghostRecorder.getSchedule();
    if (saved && typeof saved === 'object') {
      state.schedule = { ...state.schedule, ...saved };
      $('schedTime').value = state.schedule.time;
      $('schedDur').value = state.schedule.durationMinutes;
      $('schedEnable').checked = state.schedule.enabled;
    }
  } catch (_err) { /* schedule stays at defaults */ }
  refreshSchedStatus();
  state.schedTimerId = setInterval(checkSchedule, 5000);
  updateButtons();
  renderHistory();
  await loadSources();
  runUpdateCheck();
})();

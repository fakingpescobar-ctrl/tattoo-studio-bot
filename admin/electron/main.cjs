// PRIZMA Admin — Electron main process.
// Обязанности: окно, автозапуск FastAPI-сервера (admin_api.py), прокидка токена.
const { app, BrowserWindow, ipcMain } = require('electron');
const { spawn } = require('node:child_process');
const path = require('node:path');
const fs = require('node:fs');

const IS_DEV = !!process.env.VITE_DEV;
const VITE_URL = 'http://127.0.0.1:5173';

let apiProc = null;
let win = null;

// Корень проекта (tattoo_bot/) — на уровень выше папки admin/.
const projectRoot = path.join(__dirname, '..', '..');
const pythonCandidates = [
  process.env.PRIZMA_PYTHON,
  path.join(process.env.USERPROFILE || '', 'anaconda3', 'python.exe'),
  'python',
].filter(Boolean);
function findToken() {
  try {
    const t = fs.readFileSync(path.join(projectRoot, '.api-token'), 'utf8').trim();
    if (t) return t;
  } catch { /* нет файла — API его создаст при старте */ }
  return null;
}

function startApiServer() {
  // В dev-режиме можно поднять API снаружи и не плодить второй процесс.
  if (process.env.PRIZMA_API_EXTERNAL === '1') return;

  // Первый кандидат, который реально стартанул, и живёт — тот и работаем.
  const tryNext = (i) => {
    if (i >= pythonCandidates.length || apiProc) return;
    apiProc = spawn(pythonCandidates[i], [path.join(projectRoot, 'admin_api.py')], {
      cwd: projectRoot,
      stdio: 'ignore',
      windowsHide: true,
    });
    apiProc.once('error', () => { apiProc = null; tryNext(i + 1); });
  };
  tryNext(0);
}

function stopApiServer() {
  if (apiProc && !apiProc.killed) {
    try { apiProc.kill(); } catch { /* уже мёртв */ }
  }
}

function createWindow() {
  win = new BrowserWindow({
    width: 1440,
    height: 900,
    minWidth: 1100,
    minHeight: 700,
    backgroundColor: '#0a0a0c',
    title: 'PRIZMA · Админ-панель',
    webPreferences: {
      preload: path.join(__dirname, 'preload.cjs'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  if (IS_DEV) {
    // Ждём Vite до 30с, затем всё равно грузим прод-сборку как fallback.
    const t0 = Date.now();
    (async function load() {
      while (Date.now() - t0 < 30000) {
        try {
          await fetch(VITE_URL);
          await win.loadURL(VITE_URL);
          return;
        } catch { await new Promise(r => setTimeout(r, 400)); }
      }
      win.loadFile(path.join(__dirname, '..', 'dist', 'index.html'));
    })();
  } else {
    win.loadFile(path.join(__dirname, '..', 'dist', 'index.html'));
  }

  win.on('closed', () => { win = null; });
}

app.whenReady().then(() => {
  ipcMain.on('prizma:get-token', (e) => { e.returnValue = findToken(); });
  startApiServer();
  createWindow();
  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on('window-all-closed', () => {
  stopApiServer();
  app.quit();
});
app.on('before-quit', stopApiServer);

// PRIZMA Admin — Electron main process.
// Обязанности: окно + супервизор всех бэкендов проекта:
//   admin_api.py (панель), main.py (Telegram-бот), max_main.py (MAX-бот).
// Закрытие окна гасит все три процесса. Повторный запуск exe фокусирует окно.
const { app, BrowserWindow, ipcMain, dialog } = require('electron');
const { spawn } = require('node:child_process');
const path = require('node:path');
const fs = require('node:fs');

const IS_DEV = !!process.env.VITE_DEV;
const VITE_URL = 'http://127.0.0.1:5173';

// Корень проекта: в dev — на уровень выше admin/, в собранном exe (asar) —
// фиксированный путь установки (переопределяется env PRIZMA_PROJECT_ROOT).
const isPackagedPath = __dirname.includes('app.asar');
const projectRoot = process.env.PRIZMA_PROJECT_ROOT
  || (isPackagedPath ? 'C:\\Projects\\tattoo_bot' : path.join(__dirname, '..', '..'));

const pythonCandidates = [
  process.env.PRIZMA_PYTHON,
  path.join(process.env.USERPROFILE || '', 'anaconda3', 'python.exe'),
  'python',
].filter(Boolean);

// Бэкенды, которыми управляет панель. Порядок = порядок запуска.
const services = [
  { key: 'api', script: 'admin_api.py', args: ['-X', 'utf8'], logFile: 'logs/admin_api_stdout.log', proc: null },
  { key: 'tg', script: 'main.py', args: [], logFile: 'logs/tg_bot_stdout.log', proc: null },
  { key: 'max', script: 'max_main.py', args: ['-X', 'utf8'], logFile: 'logs/max_bot_stdout.log', proc: null },
];

let win = null;
let stopping = false;

function findToken() {
  try {
    const t = fs.readFileSync(path.join(projectRoot, '.api-token'), 'utf8').trim();
    if (t) return t;
  } catch { /* нет файла — ждём, API создаст его при первом старте */ }
  return null;
}

// Первый запуск: .api-token появляется через 1-3с после старта API.
// Окно открываем только когда токен готов — иначе рендер навсегда останется с 401.
async function waitForToken(timeoutMs) {
  const t0 = Date.now();
  while (Date.now() - t0 < timeoutMs) {
    const t = findToken();
    if (t) return t;
    await new Promise(r => setTimeout(r, 300));
  }
  return findToken();
}

function logFd(rel) {
  try {
    const p = path.join(projectRoot, rel);
    fs.mkdirSync(path.dirname(p), { recursive: true });
    return fs.openSync(p, 'a');
  } catch { return 'ignore'; }
}

// Перед стартом прибиваем свои же прошлые экземпляры (иначе второй poller
// Telegram ловит 409 Conflict, а API — занятый порт 8765).
// Матчим и полные пути, и короткие cmdline вида `python.exe -X utf8 max_main.py`.
function preflightKill(done) {
  let fired = false;
  const finish = () => { if (!fired) { fired = true; done(); } };
  const ps =
    `Get-CimInstance Win32_Process -Filter "Name like 'python%'" | ` +
    `Where-Object { $_.ProcessId -ne ${process.pid} -and $_.CommandLine -match ` +
    `'admin_api\\.py|max_main\\.py|anaconda3.{0,60}\\\\main\\.py' } | ` +
    `ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }`;
  const psProc = spawn('powershell.exe', ['-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', ps], { windowsHide: true });
  psProc.once('exit', finish);
  psProc.once('error', finish);
  // Зависший powershell не должен оставить приложение без окна
  setTimeout(finish, 6000);
}

function startService(svc) {
  const tryNext = (i) => {
    if (stopping || svc.proc || i >= pythonCandidates.length) return;
    svc.curFd = logFd(svc.logFile);
    svc.proc = spawn(pythonCandidates[i], [...svc.args, path.join(projectRoot, svc.script)], {
      cwd: projectRoot,
      stdio: ['ignore', svc.curFd, svc.curFd],
      windowsHide: true,
      env: { ...process.env, PYTHONIOENCODING: 'utf-8', PYTHONUTF8: '1' },
    });
    // Умерший кандидат -> пробуем следующий (ошибка запуска, а не краш рантайма).
    svc.proc.once('error', () => {
      if (stopping) return;
      svc.proc = null;
      try { if (typeof svc.curFd === 'number') fs.closeSync(svc.curFd); } catch { /* уже закрыт */ }
      tryNext(i + 1);
    });
  };
  tryNext(0);
}

// Порт API занят -> считаем его внешним (ручной запуск) и не плодим второй.
function portInUse(port) {
  return new Promise((resolve) => {
    const net = require('node:net');
    const sock = net.connect({ host: '127.0.0.1', port, timeout: 800 });
    sock.once('connect', () => { sock.destroy(); resolve(true); });
    sock.once('timeout', () => { sock.destroy(); resolve(false); });
    sock.once('error', () => resolve(false));
  });
}

// После preflight TerminateProcess доходит до сокетов с задержкой: даём порту
// освободиться (до ~3с). Так и занят — значит API поднят снаружи, свой не спавним.
async function startAllBackends() {
  if (process.env.PRIZMA_API_EXTERNAL === '1') {
    // Dev-режим с внешним API; ботов панель всё равно поднимает сама.
    for (const svc of services.filter(s => s.key !== 'api')) startService(svc);
    return;
  }
  for (let i = 0; i < 8 && !stopping; i++) {
    if (!(await portInUse(8765))) { startService(services[0]); break; }
    await new Promise(r => setTimeout(r, 400));
    if (i === 7) console.log('[prizma] :8765 так и занят — используем внешний admin_api');
  }
  for (const svc of services.slice(1)) startService(svc);
}

function stopAllBackends() {
  stopping = true;
  for (const svc of services) {
    if (svc.proc && !svc.proc.killed) {
      try { svc.proc.kill(); } catch { /* уже мёртв */ }
      svc.proc = null;
    }
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
      while (Date.now() - t0 < 30000 && win && !win.isDestroyed()) {
        try {
          await fetch(VITE_URL);
          if (!win || win.isDestroyed()) return;
          await win.loadURL(VITE_URL);
          return;
        } catch { await new Promise(r => setTimeout(r, 400)); }
      }
      if (win && !win.isDestroyed()) win.loadFile(path.join(__dirname, '..', 'dist', 'index.html'));
    })();
  } else {
    win.loadFile(path.join(__dirname, '..', 'dist', 'index.html'));
  }

  win.on('closed', () => { win = null; });
}

const gotLock = app.requestSingleInstanceLock();
if (!gotLock) {
  // Второй экземпляр просто будит первый.
  app.quit();
} else {
  app.on('second-instance', () => {
    if (win) {
      if (win.isMinimized()) win.restore();
      win.show();
      win.focus();
    }
  });

  app.whenReady().then(() => {
    ipcMain.on('prizma:get-token', (e) => { e.returnValue = findToken(); });
    // Собранный exe может быть запущен на машине без проекта — не молчим, а кричим.
    if (!fs.existsSync(path.join(projectRoot, 'admin_api.py'))) {
      dialog.showErrorBox(
        'PRIZMA Admin',
        `Не найден проект ботов:\n${projectRoot}\n\n` +
        'Положите exe рядом с папкой tattoo_bot или задайте переменную окружения PRIZMA_PROJECT_ROOT.'
      );
      app.quit();
      return;
    }
    preflightKill(() => {
      (async () => {
        await startAllBackends();
        await waitForToken(12000);
        createWindow();
      })();
    });
    app.on('activate', () => {
      if (BrowserWindow.getAllWindows().length === 0) createWindow();
    });
  });

  app.on('window-all-closed', () => {
    stopAllBackends();
    app.quit();
  });
  app.on('before-quit', stopAllBackends);
}

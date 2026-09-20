// PRIZMA Admin — Electron main process.
// Окно + супервизор всех бэкендов проекта:
//   admin_api.py (панель), main.py (Telegram-бот), max_main.py (MAX-бот).
// Первый запуск: авторазвёртывание рантайма (Python + зависимости + .env + БД),
// прогресс — в окне приветствия (splash). Закрытие окна гасит все процессы.
const { app, BrowserWindow, ipcMain, dialog } = require('electron');
const { spawn } = require('node:child_process');
const net = require('node:net');
const path = require('node:path');
const fs = require('node:fs');

const runtime = require('./runtime.cjs');

const IS_DEV = !!process.env.VITE_DEV;
const VITE_URL = 'http://127.0.0.1:5173';

let projectRoot = null;
let win = null;
let stopping = false;

// Python, которым запускаем сервисы. Заполняется ensureRuntime().
let pythonExe = null;
const fallbackCandidates = [
  process.env.PRIZMA_PYTHON,
  path.join(process.env.USERPROFILE || '', 'anaconda3', 'python.exe'),
  'python',
].filter(Boolean);

// Бэкенды, которыми управляет панель. Порядок = порядок запуска.
const services = [
  { key: 'api', script: 'admin_api.py', args: [], logFile: 'logs/admin_api_stdout.log', proc: null, curFd: null },
  { key: 'tg', script: 'main.py', args: [], logFile: 'logs/tg_bot_stdout.log', proc: null, curFd: null },
  { key: 'max', script: 'max_main.py', args: [], logFile: 'logs/max_bot_stdout.log', proc: null, curFd: null },
];

function deployBundleIfNeeded() {
  // Собранный exe несёт код ботов в ресурсах; при первом запуске разворачиваем.
  if (!process.resourcesPath) return null;
  const bundle = path.join(process.resourcesPath, 'project');
  if (!fs.existsSync(path.join(bundle, 'admin_api.py'))) return null;
  const dest = path.join(path.dirname(runtime.RUNTIME_DIR), 'project');
  if (!fs.existsSync(path.join(dest, 'admin_api.py'))) {
    try {
      fs.cpSync(bundle, dest, { recursive: true });
      return dest;
    } catch (e) {
      console.log('[prizma] deploy bundle failed: ' + e.message);
      return null;
    }
  }
  return dest;
}

function resolveProjectRoot() {
  if (process.env.PRIZMA_PROJECT_ROOT) return process.env.PRIZMA_PROJECT_ROOT;
  if (IS_DEV) {
    const dev = path.join(__dirname, '..', '..');
    return fs.existsSync(path.join(dev, 'admin_api.py')) ? dev : null;
  }
  const bundled = deployBundleIfNeeded();
  if (bundled) return bundled;
  // Родная машина разработчика: собранный exe умеет работать с нашим проектом напрямую.
  const home = 'C:\\Projects\\tattoo_bot';
  return fs.existsSync(path.join(home, 'admin_api.py')) ? home : null;
}

function findToken() {
  try {
    const t = fs.readFileSync(path.join(projectRoot, '.api-token'), 'utf8').trim();
    if (t) return t;
  } catch { /* нет файла — ждём, API создаст его при первом старте */ }
  return null;
}

async function waitForToken(timeoutMs) {
  const t0 = Date.now();
  while (Date.now() - t0 < timeoutMs) {
    const t = findToken();
    if (t) return t;
    await new Promise(r => setTimeout(r, 300));
  }
  return findToken();
}

function hasValidTokens() {
  const env = runtime.readEnvFile(projectRoot);
  return !!env.BOT_TOKEN && !!env.ADMIN_ID;
}

// Минимальные токены для панели: TG обязателен, MAX — опционально.
function needConfig() {
  return !hasValidTokens();
}

function logFd(rel) {
  try {
    const p = path.join(projectRoot, rel);
    fs.mkdirSync(path.dirname(p), { recursive: true });
    return fs.openSync(p, 'a');
  } catch { return 'ignore'; }
}

function preflightKill(done) {
  let fired = false;
  const finish = () => { if (!fired) { fired = true; done(); } };
  const esc = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  // Матчим только наши сценарии: prizma_run.py (панель) и любые python-процессы
  // из папки проекта (запуски из .bat/руками). Чужие скрипты не трогаем.
  const ps =
    `Get-CimInstance Win32_Process -Filter "Name like 'python%'" | ` +
    `Where-Object { $_.ProcessId -ne ${process.pid} -and $_.CommandLine -match ` +
    `'prizma_run\\.py|${esc(projectRoot)}' } | ` +
    `ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }`;
  const psProc = spawn('powershell.exe', ['-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', ps], { windowsHide: true });
  psProc.once('exit', finish);
  psProc.once('error', finish);
  setTimeout(finish, 6000);
}

function startService(svc) {
  const candidates = pythonExe ? [pythonExe] : fallbackCandidates;
  const tryNext = (i) => {
    if (stopping || svc.proc || i >= candidates.length) return;
    svc.spawned = false;
    svc.curFd = logFd(svc.logFile);
    const runner = path.join(projectRoot, 'prizma_run.py');
    svc.proc = spawn(candidates[i], [runner, svc.script, ...svc.args], {
      cwd: projectRoot,
      stdio: ['ignore', svc.curFd, svc.curFd],
      windowsHide: true,
      env: { ...process.env, PYTHONIOENCODING: 'utf-8', PYTHONUTF8: '1' },
    });
    svc.proc.once('spawn', () => { svc.spawned = true; });
    svc.proc.once('exit', () => {
      // Сервис умер сам: освобождаем proc и fd, чтобы не копить утечки.
      svc.proc = null;
      try { if (typeof svc.curFd === 'number') fs.closeSync(svc.curFd); } catch { /* уже закрыт */ }
      svc.curFd = null;
    });
    svc.proc.once('error', () => {
      if (stopping) return;
      svc.proc = null;
      try { if (typeof svc.curFd === 'number') fs.closeSync(svc.curFd); } catch { /* уже закрыт */ }
      // 'error' у spawn бывает только когда процесс не стартовал вовсе;
      // после успешного 'spawn' ошибки приходят через 'exit' — не ретраим.
      if (!svc.spawned) tryNext(i + 1);
    });
  };
  tryNext(0);
}

function portInUse(port) {
  return new Promise((resolve) => {
    const sock = net.connect({ host: '127.0.0.1', port, timeout: 800 });
    sock.once('connect', () => { sock.destroy(); resolve(true); });
    sock.once('timeout', () => { sock.destroy(); resolve(false); });
    sock.once('error', () => resolve(false));
  });
}

async function startAllBackends() {
  if (process.env.PRIZMA_API_EXTERNAL === '1') {
    for (const svc of services.filter(s => s.key !== 'api')) startService(svc);
    return;
  }
  // Первый запуск может стартовать api дольше (после установки deps), даём 10 с.
  // apiStarted защищает от повторных спавнов, даже если api мгновенно упал.
  let apiStarted = false;
  for (let i = 0; i < 25 && !stopping; i++) {
    if (!apiStarted && !(await portInUse(8765))) {
      apiStarted = true;
      startService(services[0]);
      break;
    }
    await new Promise(r => setTimeout(r, 400));
    if (i === 24) console.log('[prizma] :8765 всё ещё занят — используем внешний admin_api');
  }
  for (const svc of services.slice(1)) startService(svc);
}

function stopAllBackends() {
  if (stopping) return; // идемпотентно: before-quit и window-all-closed зовут дважды
  stopping = true;
  for (const svc of services) {
    // Дочерние процессы тоже гасим (taskkill /T), иначе сироты держат порт 8765 и БД.
    // Синхронно: при выходе Electron не успевает дождаться async-киллов.
    if (svc.proc && !svc.proc.killed) {
      const pid = svc.proc.pid;
      svc.proc = null;
      try {
        require('node:child_process').execFileSync('taskkill.exe', ['/PID', String(pid), '/T', '/F'], { windowsHide: true, stdio: 'ignore' });
      } catch { /* процесс мог уже завершиться */ }
    }
    try { if (typeof svc.curFd === 'number') fs.closeSync(svc.curFd); } catch { /* уже закрыт */ }
    svc.curFd = null;
  }
}

function loadSplash() {
  win.loadFile(path.join(__dirname, 'splash.html'));
}

function loadSpa() {
  if (IS_DEV) {
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
  win.on('closed', () => { win = null; });
}

function send(msg) {
  if (win && !win.isDestroyed()) win.webContents.send('prizma:' + msg.channel, msg.payload);
}

const gotLock = app.requestSingleInstanceLock();
if (!gotLock) {
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
    ipcMain.handle('prizma:save-env', (e, payload) => {
      if (!projectRoot) return { ok: false, error: 'project is not ready yet' };
      if (!payload || typeof payload !== 'object') return { ok: false, error: 'bad payload' };
      return runtime.saveEnv(projectRoot, payload);
    });
    ipcMain.handle('prizma:go-spa', () => { if (win && !win.isDestroyed()) loadSpa(); });

    projectRoot = resolveProjectRoot();
    if (!projectRoot) {
      dialog.showErrorBox(
        'PRIZMA Admin',
        'Не найден проект ботов (admin_api.py).\n\n' +
        'Задайте переменную окружения PRIZMA_PROJECT_ROOT с путём к папке проекта.'
      );
      app.quit();
      return;
    }

    // Окно приветствия показываем сразу: установка может занять несколько минут.
    createWindow();
    loadSplash();

    preflightKill(() => {
      (async () => {
        try {
          const st = await runtime.ensureRuntime(projectRoot, (s) => send({ channel: 'runtime-status', payload: s }));
          pythonExe = st.pythonExe;
          await startAllBackends();
          await waitForToken(15000);
          const cfg = needConfig();
          send({ channel: 'setup-done', payload: { needConfig: cfg, portable: st.portable } });
          if (!cfg) loadSpa();
        } catch (e) {
          dialog.showErrorBox(
            'PRIZMA Admin — не удалось подготовить рантайм',
            String((e && e.message) || e) +
            '\n\nПроверьте подключение к интернету и повторите запуск.'
          );
          app.quit();
        }
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
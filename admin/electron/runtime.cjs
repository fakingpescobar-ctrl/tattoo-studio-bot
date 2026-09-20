// PRIZMA Admin — авторазвёртывание рантайма.
// Скачал exe -> запустил -> всё настроилось:
//   1) Python 3.10+ (системный ИЛИ portable embeddable в %LOCALAPPDATA%\PRIZMA\runtime)
//   2) pip-зависимости из requirements.txt (изолированно, систему не трогаем)
//   3) .env из .env.example, если отсутствует
//   4) БД: init_db() + идемпотентные демо-данные, если нет tattoo_bot.db
// Без сторонних npm-зависимостей: https.get + Expand-Archive (системный PS).
const { spawn } = require('node:child_process');
const https = require('node:https');
const path = require('node:path');
const fs = require('node:fs');
const os = require('node:os');

const PY_VERSION = '3.12.10'; // проверено на python.org (embeddable amd64, ~10.6 МБ)
const PY_URL = `https://www.python.org/ftp/python/${PY_VERSION}/python-${PY_VERSION}-embed-amd64.zip`;
const GET_PIP_URL = 'https://bootstrap.pypa.io/get-pip.py';

const RUNTIME_DIR = path.join(
  process.env.LOCALAPPDATA || path.join(os.homedir(), 'AppData', 'Local'),
  'PRIZMA', 'runtime',
);

// Быстрый признак «зависимости стоят», без полного pip list.
const DEPS_PROBE = 'import telebot, fastapi, dotenv, rich; print("ok")';

function status(onStatus, stage, msg, pct) {
  if (onStatus) onStatus({ stage, msg, pct: pct == null ? undefined : pct });
}

// ---------- команды ----------
function run(exe, args, opts = {}) {
  return new Promise((resolve) => {
    const p = spawn(exe, args, {
      cwd: opts.cwd,
      windowsHide: true,
      stdio: ['ignore', 'pipe', 'pipe'],
      env: { ...process.env, PYTHONIOENCODING: 'utf-8', PYTHONUTF8: '1' },
    });
    let out = '';
    p.stdout.on('data', (d) => { out += d; });
    p.stderr.on('data', (d) => { out += d; });
    p.on('error', (e) => resolve({ code: -1, out: String(e) }));
    p.on('close', (code) => resolve({ code, out }));
  });
}

// ---------- скачивание ----------
// Явная state-machine: единственный распорядитель — событие 'close' потока.
//  - успех: finish -> (autoClose) -> close -> rename -> resolve
//  - redirect: 3xx -> res.resume(), file.close(), redirectTo=url -> close -> рекурсивный download
//  - HTTP-ошибка: failErr=... -> file.close() -> close -> rm + reject
//  - сеть упала: failErr=e -> file.close() -> close -> rm + reject
// Рекурсия стартует ТОЛЬКО после 'close' старого файла — гонки .part нет.
function download(url, dest, label, onStatus, depth = 0) {
  if (depth > 5) return Promise.reject(new Error(`redirect loop: ${label}`));
  return new Promise((resolve, reject) => {
    fs.mkdirSync(path.dirname(dest), { recursive: true });
    const tmp = dest + '.part';
    const file = fs.createWriteStream(tmp);
    let finished = false;
    let redirectTo = null;
    let failErr = null;
    let settled = false;

    file.on('error', (e) => { failErr = e; });
    file.on('finish', () => { finished = true; file.close(); });
    file.once('close', () => {
      if (settled) return;
      settled = true;
      if (redirectTo) {
        download(redirectTo, dest, label, onStatus, depth + 1).then(resolve, reject);
      } else if (finished) {
        try { fs.renameSync(tmp, dest); resolve(); } catch (e) { reject(e); }
      } else {
        fs.rmSync(tmp, { force: true });
        reject(failErr || new Error(`download aborted: ${label}`));
      }
    });

    const req = https.get(url, { headers: { 'User-Agent': 'PRIZMA-Admin/1.0' } }, (res) => {
      // Обрыв соединения в середине тела (reset/hangup) эмитит 'error' на response,
      // а не на request — без слушателя это уронило бы main-процесс.
      res.on('error', (e) => { failErr = e; file.close(); });
      if (res.statusCode >= 300 && res.statusCode < 400 && res.headers.location) {
        res.resume(); // освобождаем сокет редиректа
        redirectTo = res.headers.location;
        file.close();
        return;
      }
      if (res.statusCode !== 200) {
        res.resume();
        failErr = new Error(`HTTP ${res.statusCode} для ${label}`);
        file.close();
        return;
      }
      const total = parseInt(res.headers['content-length'] || '0', 10);
      let done = 0;
      res.on('data', (chunk) => {
        done += chunk.length;
        if (total) status(onStatus, 'download', `${label}: ${(done / 1048576).toFixed(1)} / ${(total / 1048576).toFixed(1)} МБ`, Math.round((done / total) * 92));
      });
      res.pipe(file);
    });
    req.on('error', (e) => { failErr = e; file.close(); });
  });
}

function extractZip(zipPath, destDir) {
  return new Promise((resolve, reject) => {
    fs.mkdirSync(destDir, { recursive: true });
    // Пути в PS-литералы: экранируем одинарные кавычки.
    const q = (s) => s.replace(/'/g, "''");
    const args = ['-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command',
      `$ErrorActionPreference='Stop'; Expand-Archive -LiteralPath '${q(zipPath)}' -DestinationPath '${q(destDir)}' -Force`];
    const p = spawn('powershell.exe', args, { windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'] });
    let out = '';
    p.stdout.on('data', (d) => { out += d; });
    p.stderr.on('data', (d) => { out += d; });
    p.on('error', reject);
    p.on('close', (code) => code === 0 ? resolve() : reject(new Error(`unzip: ${out.slice(0, 400)}`)));
  });
}

// ---------- поиск системного Python ----------
function findPyVersion(pyExe) {
  return new Promise((resolve) => {
    const p = spawn(pyExe, ['--version'], { windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'] });
    let out = '';
    p.stdout.on('data', (d) => { out += d; });
    p.stderr.on('data', (d) => { out += d; });
    p.on('error', () => resolve(null));
    p.on('close', () => {
      const m = /Python (\d+)\.(\d+)/.exec(out);
      resolve(m ? { major: +m[1], minor: +m[2] } : null);
    });
  });
}

function candidates() {
  const c = [];
  if (process.env.PRIZMA_PYTHON) c.push(process.env.PRIZMA_PYTHON);
  c.push(path.join(process.env.USERPROFILE || '', 'anaconda3', 'python.exe'));
  c.push('python');
  return c.filter(Boolean);
}

async function detectSystemPython(onStatus) {
  for (const exe of candidates()) {
    status(onStatus, 'python', `Проверяю Python: ${exe}`);
    const v = await findPyVersion(exe);
    if (v && (v.major > 3 || (v.major === 3 && v.minor >= 10))) {
      return { pythonExe: exe, portable: false, version: `${v.major}.${v.minor}` };
    }
  }
  return null;
}

// ---------- portable Python ----------
function enableSitePackages(embedDir, mp) {
  // python312._pth задаёт sys.path для embeddable; без site-packages pip-модули
  // невидны интерпретатору.
  const pth = path.join(embedDir, `python${mp}._pth`);
  if (!fs.existsSync(pth)) throw new Error(`python${mp}._pth не найден в ${embedDir}`);
  fs.writeFileSync(pth, `python${mp}.zip\n.\nLib\\site-packages\nimport site\n`, 'utf8');
}

async function ensurePortablePython(onStatus) {
  const pyDir = path.join(RUNTIME_DIR, 'python');
  const pyExe = path.join(pyDir, 'python.exe');
  if (fs.existsSync(pyExe)) {
    const v = await findPyVersion(pyExe);
    if (v && (v.major > 3 || (v.major === 3 && v.minor >= 10))) {
      status(onStatus, 'python', `Portable Python ${v.major}.${v.minor} уже установлен`);
      return { pythonExe: pyExe, portable: true, version: `${v.major}.${v.minor}` };
    }
  }

  status(onStatus, 'python', `Python в системе не найден — скачиваю portable Python ${PY_VERSION} (~11 МБ)`);
  const zipPath = path.join(RUNTIME_DIR, `python-${PY_VERSION}-embed-amd64.zip`);
  if (!fs.existsSync(zipPath)) await download(PY_URL, zipPath, 'Python runtime', onStatus);
  status(onStatus, 'python', 'Распаковываю portable Python…');
  fs.rmSync(pyDir, { recursive: true, force: true }); // чистый распак (защита от битых остатков)
  await extractZip(zipPath, pyDir);
  enableSitePackages(pyDir, PY_VERSION.split('.').slice(0, 2).join(''));

  const getPip = path.join(RUNTIME_DIR, 'get-pip.py');
  if (!fs.existsSync(getPip)) {
    status(onStatus, 'pip', 'Скачиваю get-pip.py…');
    await download(GET_PIP_URL, getPip, 'get-pip.py', onStatus);
  }
  status(onStatus, 'pip', 'Устанавливаю pip…');
  const r = await run(pyExe, [getPip, '--no-warn-script-location', '--disable-pip-version-check']);
  if (r.code !== 0) throw new Error(`pip install failed:\n${r.out.slice(0, 600)}`);
  status(onStatus, 'python', `Portable Python ${PY_VERSION} готов`);
  return { pythonExe: pyExe, portable: true, version: PY_VERSION };
}

// ---------- зависимости проекта ----------
// Метка-хэш requirements.txt: если список изменился между версиями exe — переустановка.
function reqHash(projectRoot) {
  try {
    const crypto = require('node:crypto');
    return crypto.createHash('md5').update(fs.readFileSync(path.join(projectRoot, 'requirements.txt'))).digest('hex');
  } catch { return ''; }
}

async function installDeps(pythonExe, projectRoot, onStatus) {
  const reqPath = path.join(projectRoot, 'requirements.txt');
  const probe = await run(pythonExe, ['-c', DEPS_PROBE], { cwd: projectRoot });
  // Нет requirements.txt — полагаемся на probe (голая установка без пип-листа).
  if (!fs.existsSync(reqPath)) {
    if (probe.code === 0) status(onStatus, 'deps', 'Зависимости уже установлены');
    else throw new Error('requirements.txt не найден, а зависимости не установлены');
    return;
  }
  const hash = reqHash(projectRoot);
  const markPath = path.join(RUNTIME_DIR, 'requirements.md5');
  let markOk = false;
  try { markOk = hash && fs.readFileSync(markPath, 'utf8') === hash; } catch { /* нет метки */ }
  if (probe.code === 0 && markOk) {
    status(onStatus, 'deps', 'Зависимости уже установлены');
    return;
  }

  status(onStatus, 'deps', 'Устанавливаю зависимости (pip install -r requirements.txt)…');
  const args = ['-m', 'pip', 'install', '--disable-pip-version-check', '--no-warn-script-location'];
  if (process.env.PIP_INDEX_URL) args.push('--index-url', process.env.PIP_INDEX_URL);
  args.push('-r', 'requirements.txt');
  const r = await run(pythonExe, args, { cwd: projectRoot });
  if (r.code !== 0) throw new Error(`pip install -r failed:\n${r.out.slice(0, 800)}`);
  if (hash) fs.writeFileSync(markPath, hash, 'utf8');
  status(onStatus, 'deps', 'Зависимости установлены');
}

// ---------- .env ----------
function ensureEnv(projectRoot) {
  const envPath = path.join(projectRoot, '.env');
  if (fs.existsSync(envPath)) return false;
  const examplePath = path.join(projectRoot, '.env.example');
  if (!fs.existsSync(examplePath)) return false; // нет примера — .env оставляем вопросом формы
  fs.copyFileSync(examplePath, envPath);
  return true;
}

// ---------- база данных ----------
async function ensureDb(pythonExe, projectRoot, onStatus) {
  const dbPath = path.join(projectRoot, 'tattoo_bot.db');
  if (fs.existsSync(dbPath)) {
    status(onStatus, 'db', 'База данных уже есть');
    return false;
  }
  status(onStatus, 'db', 'Создаю базу данных и наполняю её демо-данными…');
  const dbCode =
    'import sys\n' +
    `sys.path.insert(0, ${JSON.stringify(projectRoot)})\n` +
    'from database import init_db, add_sample_data; init_db(); add_sample_data()';
  const r = await run(pythonExe, ['-c', dbCode], { cwd: projectRoot });
  if (r.code !== 0) throw new Error(`init_db failed:\n${r.out.slice(0, 800)}`);
  return true;
}

/**
 * Полный цикл первого запуска. Возвращает:
 *   { pythonExe, portable, dbCreated }
 * onStatus({stage, msg, pct}) — прогресс для окна приветствия.
 */
async function ensureRuntime(projectRoot, onStatus) {
  let py = await detectSystemPython(onStatus);
  if (py) {
    status(onStatus, 'python', `Найден системный Python ${py.version} — делаю изолированный venv`);
    // В системный Python пакеты не ставим: свой venv в runtime-песочнице.
    const venvDir = path.join(RUNTIME_DIR, 'venv');
    const venvPy = path.join(venvDir, 'Scripts', 'python.exe');
    if (!fs.existsSync(venvPy)) {
      status(onStatus, 'venv', 'Создаю изолированное окружение (venv)…');
      const v = await run(py.pythonExe, ['-m', 'venv', venvDir]);
      if (v.code !== 0) throw new Error(`venv create failed:\n${v.out.slice(0, 600)}`);
    }
    py.pythonExe = venvPy;
    py.portable = true;
  } else {
    py = await ensurePortablePython(onStatus);
  }
  await installDeps(py.pythonExe, projectRoot, onStatus);
  const envCreated = ensureEnv(projectRoot);
  if (envCreated) status(onStatus, 'env', 'Создан .env из шаблона (заполни токены)');
  const dbCreated = await ensureDb(py.pythonExe, projectRoot, onStatus);
  return { pythonExe: py.pythonExe, portable: py.portable, dbCreated, envCreated };
}

// ---------- токены в .env (форма первого запуска) ----------
function readEnvFile(projectRoot) {
  try {
    const txt = fs.readFileSync(path.join(projectRoot, '.env'), 'utf8');
    return txt.split(/\r?\n/).reduce((acc, line) => {
      const m = /^\s*([A-Z0-9_]+)\s*=\s*(.*)\s*$/.exec(line);
      if (m) acc[m[1]] = m[2];
      return acc;
    }, {});
  } catch { return {}; }
}

function saveEnv(projectRoot, updates) {
  const envPath = path.join(projectRoot, '.env');
  const raw = readEnvFileRaw(projectRoot); // [[key|null, value|null, text]] — сохраняем комментарии и порядок
  let changed = false;
  for (const [k, v] of Object.entries(updates)) {
    const val = String(v == null ? '' : v).trim();
    const ent = raw.find((r) => r[0] === k);
    if (ent) {
      if (ent[1] !== val) { ent[1] = val; ent[2] = `${k}=${val}`; changed = true; }
    } else {
      raw.push([k, val, `${k}=${val}`]);
      changed = true;
    }
  }
  if (!changed) return { ok: true, changed: false };
  fs.writeFileSync(envPath, raw.map((r) => r[2]).join('\n') + '\n', 'utf8');
  return { ok: true, changed: true };
}

function readEnvFileRaw(projectRoot) {
  try {
    const txt = fs.readFileSync(path.join(projectRoot, '.env'), 'utf8');
    return txt.split(/\r?\n/).map((line) => {
      const m = /^\s*([A-Z0-9_]+)\s*=\s*(.*)\s*$/.exec(line);
      return m ? [m[1], m[2], line] : [null, null, line];
    });
  } catch { return []; }
}

module.exports = { ensureRuntime, ensureEnv, ensureDb, installDeps, ensurePortablePython, saveEnv, readEnvFile, DEPS_PROBE, RUNTIME_DIR };
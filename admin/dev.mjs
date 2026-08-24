import { spawn } from 'node:child_process';

// dev.mjs — поднимает Vite dev-server, ждёт порт 5173, потом запускает Electron.
// Без лишних зависимостей (concurrently и т.п.) — голый node.

const VITE_PORT = 5173;

// Poll через fetch — просто и без лишних зависимостей.
async function waitForServer(url, timeoutMs = 30000) {
  const t0 = Date.now();
  while (Date.now() - t0 < timeoutMs) {
    try {
      const res = await fetch(url);
      if (res.ok || res.status < 500) return true;
    } catch { /* ещё не поднялся */ }
    await new Promise(r => setTimeout(r, 400));
  }
  throw new Error(`Vite not ready after ${timeoutMs}ms`);
}

const vite = spawn('npx', ['vite'], {
  cwd: import.meta.dirname,
  shell: true,
  stdio: 'inherit',
});

try {
  await waitForServer(`http://127.0.0.1:${VITE_PORT}`);
} catch (e) {
  console.error('[dev] ' + e.message);
  vite.kill();
  process.exit(1);
}

console.log('[dev] Vite up -> launching Electron');
const electron = spawn('npx', ['electron', '.'], {
  cwd: import.meta.dirname,
  shell: true,
  stdio: 'inherit',
  env: { ...process.env, VITE_DEV: '1' },
});

electron.on('exit', () => {
  vite.kill();
  process.exit(0);
});
process.on('SIGINT', () => { vite.kill(); electron.kill(); process.exit(0); });

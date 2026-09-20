// Мост между sandbox-рендерером (splash и SPA) и main-процессом.
// Токен читается в main (есть fs), наружу отдаётся только значение.
const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('prizma', {
  getToken: () => ipcRenderer.sendSync('prizma:get-token'),

  // Прогресс установки рантайма: onRuntimeStatus({stage, msg, pct})
  onRuntimeStatus: (cb) => {
    ipcRenderer.on('prizma:runtime-status', (_e, m) => cb && cb(m));
  },

  // Установка завершена: onSetupDone({needConfig, portable})
  onSetupDone: (cb) => {
    ipcRenderer.on('prizma:setup-done', (_e, m) => cb && cb(m));
  },

  // Запись токенов в .env из формы первого запуска.
  saveEnv: (env) => ipcRenderer.invoke('prizma:save-env', env),

  // Переключить окно на основное приложение.
  goSpa: () => ipcRenderer.invoke('prizma:go-spa'),
});
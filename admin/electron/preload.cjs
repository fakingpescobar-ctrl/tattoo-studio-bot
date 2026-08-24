// Мост между sandbox-рендерером и токеном API.
// Токен читается в main-контексте (есть fs), наружу отдаётся только значение.
const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('prizma', {
  getToken: () => ipcRenderer.sendSync('prizma:get-token'),
});

const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('alpha', {
  command: (cmd, payload = {}) => ipcRenderer.send('alpha-command', { cmd, payload }),
  saveParams: (params) => ipcRenderer.invoke('save-params', params),
  loadParams: () => ipcRenderer.invoke('load-params'),
  saveDefaultParams: (params) => ipcRenderer.invoke('save-default-params', params),
  loadDefaultParams: () => ipcRenderer.invoke('load-default-params'),
  loadSnapshot: () => ipcRenderer.invoke('load-snapshot'),
  onStatus: (cb) => ipcRenderer.on('status-update', (_, data) => cb(data)),
  onTrades: (cb) => ipcRenderer.on('trades-update', (_, data) => cb(data)),
  onCalendarData: (cb) => ipcRenderer.on('calendar-data-update', (_, data) => cb(data)),
  onLog: (cb) => ipcRenderer.on('log-update', (_, data) => cb(data)),
  minimize: () => ipcRenderer.send('window-minimize'),
  maximize: () => ipcRenderer.send('window-maximize'),
  close: () => ipcRenderer.send('window-close'),
  openExternal:       (url) => ipcRenderer.send('open-external', url),
  onUpdateAvailable:  (cb)  => ipcRenderer.on('update-available',  (_, d) => cb(d)),
  onUpdateProgress:   (cb)  => ipcRenderer.on('update-progress',   (_, d) => cb(d)),
  onUpdateDownloaded: (cb)  => ipcRenderer.on('update-downloaded', (_, d) => cb(d)),
  downloadUpdate: () => ipcRenderer.send('update-download'),
  installUpdate:  () => ipcRenderer.send('update-install'),
});

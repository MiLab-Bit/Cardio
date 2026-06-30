// electron/preload.js
// 安全的 IPC 桥接层 — 仅暴露必要的 API 给渲染进程

const { contextBridge, ipcRenderer } = require('electron')

contextBridge.exposeInMainWorld('byou', {
  // 检查后端状态
  backendStatus: () => ipcRenderer.invoke('backend-status'),

  // 重启后端
  restartBackend: () => ipcRenderer.invoke('restart-backend'),

  // 通用 invoke
  invoke: (channel, ...args) => ipcRenderer.invoke(channel, ...args),

  // 监听后端事件（SSE 等）
  on: (channel, callback) => {
    ipcRenderer.on(channel, (_, ...args) => callback(...args))
  },

  // 移除监听
  removeListener: (channel, callback) => {
    ipcRenderer.removeListener(channel, callback)
  },
})

// electron/main.js
// Byou Windows 桌面版 — Electron 主进程
//
// 职责：
//  1. 检测后端是否运行（http://localhost:8000/health）
//  2. 未运行 → 用 child_process 启动 uvicorn
//  3. 等待 /health 返回 200
//  4. 创建 BrowserWindow
//     - 开发模式：加载 http://localhost:3000（Vite dev server）
//     - 生产模式：加载本地 dist/index.html + 用 loadURL 代理 API 请求
//  5. 窗口关闭时自动关闭后端

const { app, BrowserWindow, ipcMain, Menu } = require('electron')
const path = require('path')
const http = require('http')
const { spawn } = require('child_process')

const IS_DEV = !app.isPackaged
const PORT = 8000
const HEALTH_URL = `http://localhost:${PORT}/health`
let backendProcess = null
let mainWindow = null

// ── 健康检查 ─────────────────────────────────────────────────
function checkHealth() {
  return new Promise((resolve) => {
    http.get(HEALTH_URL, (res) => {
      resolve(res.statusCode === 200)
    }).on('error', () => resolve(false))
  })
}

async function waitForBackend(timeoutMs = 30000) {
  const start = Date.now()
  while (Date.now() - start < timeoutMs) {
    if (await checkHealth()) return true
    await new Promise(r => setTimeout(r, 1000))
  }
  return false
}

// ── 启动后端 ─────────────────────────────────────────────────
function startBackend() {
  const pythonCmd = IS_DEV ? 'python' : path.join(process.resourcesPath, 'backend', 'python', 'python.exe')
  const backendScript = IS_DEV
    ? path.join(__dirname, '..', 'main.py')
    : path.join(process.resourcesPath, 'backend', 'main.py')

  const env = { ...process.env }
  if (!IS_DEV) {
    // 生产环境：使用打包进来的 Python 和依赖
    env.PYTHONHOME = path.join(process.resourcesPath, 'backend', 'python')
  }

  backendProcess = spawn(pythonCmd, [
    '-m', 'uvicorn',
    'byou.api:app',
    '--host', '127.0.0.1',
    '--port', String(PORT),
    '--reload', String(IS_DEV),
  ], {
    cwd: IS_DEV ? path.join(__dirname, '..') : path.join(process.resourcesPath, 'backend'),
    env,
    stdio: IS_DEV ? 'inherit' : 'ignore',
  })

  backendProcess.on('error', (err) => {
    console.error('Backend failed to start:', err)
  })

  backendProcess.on('exit', (code) => {
    console.log(`Backend exited with code ${code}`)
  })
}

// ── 创建窗口 ─────────────────────────────────────────────────
function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1400,
    height: 900,
    minWidth: 1000,
    minHeight: 700,
    icon: path.join(__dirname, 'icon.png'),  // 如果 icon.png 不存在，Electron 会用默认图标
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
    show: false,
    titleBarStyle: 'default',
    autoHideMenuBar: !IS_DEV,
  })

  if (IS_DEV) {
    // 开发模式：加载 Vite dev server
    mainWindow.loadURL('http://localhost:3000')
  } else {
    // 生产模式：加载本地构建的 index.html
    const frontendDist = path.join(__dirname, '..', 'frontend', 'dist', 'index.html')
    mainWindow.loadFile(frontendDist)
  }

  mainWindow.once('ready-to-show', () => {
    mainWindow.show()
    if (IS_DEV) mainWindow.webContents.openDevTools()
  })

  mainWindow.on('closed', () => {
    mainWindow = null
  })
}

// ── App 生命周期 ─────────────────────────────────────────────
app.whenReady().then(async () => {
  // 移除默认菜单（Windows 版）
  if (!IS_DEV) Menu.setApplicationMenu(null)

  // 检查后端是否已运行
  const isRunning = await checkHealth()
  if (!isRunning) {
    console.log('Starting backend...')
    startBackend()
    console.log('Waiting for backend...')
    const ok = await waitForBackend()
    if (!ok) {
      console.error('Backend failed to start within timeout')
      app.quit()
      return
    }
    console.log('Backend ready')
  } else {
    console.log('Backend already running')
  }

  createWindow()
})

app.on('window-all-closed', () => {
  if (backendProcess) {
    console.log('Shutting down backend...')
    backendProcess.kill('SIGTERM')
    backendProcess = null
  }
  if (process.platform !== 'darwin') app.quit()
})

app.on('activate', () => {
  if (BrowserWindow.getAllWindows().length === 0) createWindow()
})

// ── IPC：前端可调用 ─────────────────────────────────────────
ipcMain.handle('backend-status', async () => {
  return { running: await checkHealth(), port: PORT }
})

ipcMain.handle('restart-backend', async () => {
  if (backendProcess) backendProcess.kill('SIGTERM')
  startBackend()
  return { ok: await waitForBackend(15000) }
})

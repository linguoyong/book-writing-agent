import { app, BrowserWindow, dialog, ipcMain, session, shell } from 'electron'
import { join, resolve, sep } from 'node:path'
import { pathToFileURL } from 'node:url'
import { getBackendInfo, startBackend, stopBackend } from './backend'

let mainWindow: BrowserWindow | null = null
let quitting = false
// 渲染层是否有未保存的编辑；有的话关窗要先问一句
let hasUnsaved = false
let allowClose = false

const RENDERER_URL = process.env['ELECTRON_RENDERER_URL']
const RENDERER_INDEX = join(__dirname, '../renderer/index.html')
const RENDERER_FILE_URL = pathToFileURL(RENDERER_INDEX).href

// 只给开发调试用；打包后即使环境变量泄漏也不开 CDP
if (RENDERER_URL && !app.isPackaged) {
  app.commandLine.appendSwitch('remote-debugging-port', '9222')
}

/**
 * 只有本应用自己的页面才可信。
 *
 * 窗口一旦被导航到别的页面，preload 会重新执行、`backendInfo()` 会把令牌交给
 * 那个页面；所以导航必须拦死，IPC 也要认来源。
 */
function matchesBase(url: string, base: string): boolean {
  if (!url.startsWith(base)) return false
  const rest = url.slice(base.length)
  // 防止 `http://localhost:5173.evil.com` 这类前缀伪装
  return rest === '' || rest.startsWith('/') || rest.startsWith('?') || rest.startsWith('#')
}

function isTrustedUrl(url: string): boolean {
  if (!url) return false
  if (RENDERER_URL && matchesBase(url, RENDERER_URL)) return true
  return matchesBase(url, RENDERER_FILE_URL)
}

function isTrustedSender(event: Electron.IpcMainEvent | Electron.IpcMainInvokeEvent): boolean {
  // 页面销毁的瞬间 senderFrame 可能是 null，退回 webContents 自己的 URL
  const url = event.senderFrame?.url || event.sender.getURL()
  return isTrustedUrl(url)
}

function handle(
  channel: string,
  handler: (event: Electron.IpcMainInvokeEvent, ...args: unknown[]) => unknown
): void {
  ipcMain.handle(channel, (event, ...args) => {
    if (!isTrustedSender(event)) throw new Error('拒绝来自非应用页面的调用')
    return handler(event, ...args)
  })
}

function on(channel: string, handler: () => void): void {
  ipcMain.on(channel, (event) => {
    if (!isTrustedSender(event)) return
    handler()
  })
}

/**
 * 令牌只留在主进程：渲染层的每个 `/api/*` 请求由这里补上请求头。
 *
 * 这样页面里拿不到令牌原值，即使将来出现导航绕过，也无法把令牌带走复用。
 */
function isBackendRequest(url: string, port: number): boolean {
  if (!port) return false
  try {
    const parsed = new URL(url)
    if (parsed.hostname !== '127.0.0.1' && parsed.hostname !== 'localhost') return false
    return parsed.port === String(port) && parsed.pathname.startsWith('/api/')
  } catch {
    return false
  }
}

function installTokenInjector(): void {
  session.defaultSession.webRequest.onBeforeSendHeaders(
    { urls: ['<all_urls>'] },
    (details, callback) => {
      const current = getBackendInfo()
      if (current.token && isBackendRequest(details.url, current.port)) {
        details.requestHeaders['X-Book-Agent-Token'] = current.token
      }
      callback({ requestHeaders: details.requestHeaders })
    }
  )
}

function createWindow(): void {
  mainWindow = new BrowserWindow({
    width: 1480,
    height: 940,
    minWidth: 1080,
    minHeight: 680,
    show: false,
    frame: false,
    backgroundColor: '#f5f5f2',
    webPreferences: {
      preload: join(__dirname, '../preload/index.js'),
      // preload 只用到 contextBridge 与 ipcRenderer，开沙箱不影响它
      sandbox: true,
      contextIsolation: true,
      nodeIntegration: false,
      webviewTag: false
    }
  })

  mainWindow.on('ready-to-show', () => mainWindow?.show())

  mainWindow.on('close', (event) => {
    // 退出流程里不再打断，否则 before-quit 之后会关不掉
    if (quitting || allowClose || !hasUnsaved) return
    event.preventDefault()
    mainWindow?.webContents.send('app:before-close')
  })

  const contents = mainWindow.webContents
  // 任何跳转都拦下：应用是单页的，除了自身入口没有「合法目的地」
  contents.on('will-navigate', (event, url) => {
    if (!isTrustedUrl(url)) event.preventDefault()
  })
  contents.on('will-redirect', (event, url) => {
    if (!isTrustedUrl(url)) event.preventDefault()
  })
  contents.on('will-frame-navigate', (event) => {
    if (!isTrustedUrl(event.url)) event.preventDefault()
  })
  // 拖入 .html / 中键点链接都走这里：一律不开新窗，http(s) 交给系统浏览器
  contents.setWindowOpenHandler(({ url }) => {
    if (/^https?:\/\//i.test(url)) void shell.openExternal(url)
    return { action: 'deny' }
  })
  contents.on('will-attach-webview', (event) => event.preventDefault())

  if (RENDERER_URL) {
    void mainWindow.loadURL(RENDERER_URL)
  } else {
    void mainWindow.loadFile(RENDERER_INDEX)
  }
}

on('window:minimize', () => mainWindow?.minimize())
on('window:toggle-maximize', () => {
  if (!mainWindow) return
  if (mainWindow.isMaximized()) mainWindow.unmaximize()
  else mainWindow.maximize()
})
on('window:close', () => mainWindow?.close())

// 用户在渲染层确认「放弃未保存修改」后，主进程才真正关窗
on('window:force-close', () => {
  allowClose = true
  mainWindow?.close()
})

// 渲染层每次切换/编辑文件都会同步一次，省去关窗时的往返
ipcMain.on('app:set-dirty', (event, dirty) => {
  if (!isTrustedSender(event)) return
  hasUnsaved = Boolean(dirty)
})

handle('dialog:pick-directory', async (_event, defaultPath: unknown) => {
  const result = await dialog.showOpenDialog({
    // 默认停在当前目录，省得每次从系统默认位置翻起
    defaultPath: typeof defaultPath === 'string' && defaultPath ? defaultPath : undefined,
    properties: ['openDirectory', 'createDirectory'],
    title: '选择书稿空间目录'
  })
  return result.canceled ? null : result.filePaths[0]
})

handle('dialog:save-text-file', async (_event, defaultName: unknown) => {
  const result = await dialog.showSaveDialog({
    title: '导出成稿',
    defaultPath: typeof defaultName === 'string' ? defaultName : '成稿.txt',
    filters: [{ name: '文本文件', extensions: ['txt'] }]
  })
  return result.canceled ? null : result.filePath
})

handle('dialog:pick-text-file', async () => {
  const result = await dialog.showOpenDialog({
    properties: ['openFile'],
    title: '选择要提炼的作品文件',
    filters: [
      { name: '文本文件', extensions: ['txt', 'md'] },
      { name: '所有文件', extensions: ['*'] }
    ]
  })
  return result.canceled ? null : result.filePaths[0]
})

handle('shell:open-external', async (_event, url: unknown) => {
  if (typeof url === 'string' && /^https?:\/\//i.test(url)) {
    await shell.openExternal(url)
    return true
  }
  return false
})

handle('shell:show-item', async (_event, root: unknown, relative: unknown) => {
  if (typeof root !== 'string' || typeof relative !== 'string') return false
  const base = resolve(root)
  const target = resolve(base, relative)
  // `../` 能把「在文件夹中显示」带到书稿目录之外
  if (target !== base && !target.startsWith(base + sep)) return false
  shell.showItemInFolder(target)
  return true
})

handle('backend:info', async () => {
  // 等后端真正 ready 再返回，渲染层首次请求就不会打到还没监听的端口。
  // 只回端口与状态，令牌留在主进程，由请求注入器补头。
  const deadline = Date.now() + 15000
  while (Date.now() < deadline) {
    const current = getBackendInfo()
    if (current.ready || current.error) {
      return { port: current.port, ready: current.ready, error: current.error }
    }
    await new Promise((resolve) => setTimeout(resolve, 150))
  }
  const final = getBackendInfo()
  return { port: final.port, ready: final.ready, error: final.error }
})

// 重复双击图标时，第二实例退出并把已有窗口叫到前面，避免它 taskkill 掉
// 第一实例的后端（正在跑的 Agent 会被硬杀，可能留下半写入的章节）。
if (!app.requestSingleInstanceLock()) {
  // 用 exit 而不是 quit：quit 会触发 before-quit，把第一实例的后端 taskkill 掉
  app.exit(0)
} else {
  app.on('second-instance', () => {
    if (!mainWindow) return
    if (mainWindow.isMinimized()) mainWindow.restore()
    mainWindow.show()
    mainWindow.focus()
  })

  void app.whenReady().then(() => {
    installTokenInjector()
    void startBackend()
    createWindow()
    app.on('activate', () => {
      if (BrowserWindow.getAllWindows().length === 0) createWindow()
    })
  })
}

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit()
})

app.on('before-quit', (event) => {
  if (quitting) return
  quitting = true
  event.preventDefault()
  void stopBackend().finally(() => app.quit())
})

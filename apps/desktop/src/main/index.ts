import { app, BrowserWindow, dialog, ipcMain, shell } from 'electron'
import { join } from 'node:path'
import { getBackendInfo, startBackend, stopBackend } from './backend'

let mainWindow: BrowserWindow | null = null
let quitting = false

if (process.env['ELECTRON_RENDERER_URL']) {
  app.commandLine.appendSwitch('remote-debugging-port', '9222')
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
      sandbox: false,
      contextIsolation: true
    }
  })

  mainWindow.on('ready-to-show', () => mainWindow?.show())

  if (process.env['ELECTRON_RENDERER_URL']) {
    mainWindow.loadURL(process.env['ELECTRON_RENDERER_URL'])
  } else {
    mainWindow.loadFile(join(__dirname, '../renderer/index.html'))
  }
}

ipcMain.on('window:minimize', () => mainWindow?.minimize())
ipcMain.on('window:toggle-maximize', () => {
  if (!mainWindow) return
  if (mainWindow.isMaximized()) mainWindow.unmaximize()
  else mainWindow.maximize()
})
ipcMain.on('window:close', () => mainWindow?.close())

ipcMain.handle('dialog:pick-directory', async () => {
  const result = await dialog.showOpenDialog({
    properties: ['openDirectory', 'createDirectory'],
    title: '选择书稿空间目录'
  })
  return result.canceled ? null : result.filePaths[0]
})

ipcMain.handle('dialog:save-text-file', async (_event, defaultName: unknown) => {
  const result = await dialog.showSaveDialog({
    title: '导出成稿',
    defaultPath: typeof defaultName === 'string' ? defaultName : '成稿.txt',
    filters: [{ name: '文本文件', extensions: ['txt'] }]
  })
  return result.canceled ? null : result.filePath
})

ipcMain.handle('dialog:pick-text-file', async () => {
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

ipcMain.handle('shell:open-external', async (_event, url: unknown) => {
  if (typeof url === 'string' && /^https?:\/\//i.test(url)) {
    await shell.openExternal(url)
    return true
  }
  return false
})

ipcMain.handle('shell:show-item', async (_event, root: unknown, relative: unknown) => {
  if (typeof root !== 'string' || typeof relative !== 'string') return false
  shell.showItemInFolder(join(root, relative))
  return true
})

ipcMain.handle('backend:info', async () => {
  // 等后端真正 ready 再返回，渲染层首次请求就不会打到还没监听的端口
  const deadline = Date.now() + 15000
  while (Date.now() < deadline) {
    const current = getBackendInfo()
    if (current.ready || current.error) return current
    await new Promise((resolve) => setTimeout(resolve, 150))
  }
  return getBackendInfo()
})

app.whenReady().then(() => {
  void startBackend()
  createWindow()
  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow()
  })
})

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit()
})

app.on('before-quit', (event) => {
  if (quitting) return
  quitting = true
  event.preventDefault()
  void stopBackend().finally(() => app.quit())
})

import { contextBridge, ipcRenderer } from 'electron'

contextBridge.exposeInMainWorld('desktop', {
  minimize: (): void => ipcRenderer.send('window:minimize'),
  toggleMaximize: (): void => ipcRenderer.send('window:toggle-maximize'),
  close: (): void => ipcRenderer.send('window:close'),
  pickDirectory: (): Promise<string | null> => ipcRenderer.invoke('dialog:pick-directory'),
  openExternal: (url: string): Promise<boolean> =>
    ipcRenderer.invoke('shell:open-external', url),
  showItemInFolder: (root: string, relative: string): Promise<boolean> =>
    ipcRenderer.invoke('shell:show-item', root, relative),
  backendInfo: (): Promise<{
    port: number
    ready: boolean
    token?: string
    error?: string
  }> => ipcRenderer.invoke('backend:info')
})

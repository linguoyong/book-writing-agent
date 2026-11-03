import { contextBridge, ipcRenderer } from 'electron'

contextBridge.exposeInMainWorld('desktop', {
  minimize: (): void => ipcRenderer.send('window:minimize'),
  toggleMaximize: (): void => ipcRenderer.send('window:toggle-maximize'),
  close: (): void => ipcRenderer.send('window:close'),
  pickDirectory: (): Promise<string | null> => ipcRenderer.invoke('dialog:pick-directory'),
  pickTextFile: (): Promise<string | null> => ipcRenderer.invoke('dialog:pick-text-file'),
  saveTextFile: (defaultName: string): Promise<string | null> =>
    ipcRenderer.invoke('dialog:save-text-file', defaultName),
  openExternal: (url: string): Promise<boolean> =>
    ipcRenderer.invoke('shell:open-external', url),
  showItemInFolder: (root: string, relative: string): Promise<boolean> =>
    ipcRenderer.invoke('shell:show-item', root, relative),
  backendInfo: (): Promise<{
    port: number
    ready: boolean
    error?: string
  }> => ipcRenderer.invoke('backend:info'),
  setDirty: (dirty: boolean): void => ipcRenderer.send('app:set-dirty', dirty),
  forceClose: (): void => ipcRenderer.send('window:force-close'),
  onBeforeClose: (handler: () => void): (() => void) => {
    const listener = (): void => handler()
    ipcRenderer.on('app:before-close', listener)
    return () => {
      ipcRenderer.removeListener('app:before-close', listener)
    }
  }
})

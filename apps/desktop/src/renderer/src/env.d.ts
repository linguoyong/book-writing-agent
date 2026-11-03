/// <reference types="vite/client" />

interface Window {
  desktop?: {
    minimize: () => void
    toggleMaximize: () => void
    close: () => void
    pickDirectory: (defaultPath?: string) => Promise<string | null>
    pickTextFile: () => Promise<string | null>
    saveTextFile: (defaultName: string) => Promise<string | null>
    openExternal: (url: string) => Promise<boolean>
    showItemInFolder: (root: string, relative: string) => Promise<boolean>
    backendInfo: () => Promise<{
      port: number
      ready: boolean
      error?: string
    }>
    setDirty: (dirty: boolean) => void
    forceClose: () => void
    onBeforeClose: (handler: () => void) => () => void
  }
}

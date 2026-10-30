/// <reference types="vite/client" />

interface Window {
  desktop?: {
    minimize: () => void
    toggleMaximize: () => void
    close: () => void
    pickDirectory: () => Promise<string | null>
    pickTextFile: () => Promise<string | null>
    openExternal: (url: string) => Promise<boolean>
    showItemInFolder: (root: string, relative: string) => Promise<boolean>
    backendInfo: () => Promise<{
      port: number
      ready: boolean
      token?: string
      error?: string
    }>
  }
}

/// <reference types="vite/client" />

interface Window {
  desktop?: {
    minimize: () => void
    toggleMaximize: () => void
    close: () => void
    pickDirectory: () => Promise<string | null>
    openExternal: (url: string) => Promise<boolean>
    backendInfo: () => Promise<{ port: number; ready: boolean; error?: string }>
  }
}

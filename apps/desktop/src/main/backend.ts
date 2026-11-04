import { app } from 'electron'
import { execFile, spawn, type ChildProcess } from 'node:child_process'
import { randomBytes } from 'node:crypto'
import { existsSync, readFileSync, unlinkSync, writeFileSync } from 'node:fs'
import http from 'node:http'
import net from 'node:net'
import { homedir } from 'node:os'
import { dirname, join } from 'node:path'

export interface BackendInfo {
  port: number
  ready: boolean
  /** 本地 API 访问令牌：只经 IPC 下发给渲染进程，不落盘、不暴露给网页 */
  token: string
  error?: string
}

const PREFERRED_PORT = 8787
// 每次启动生成新令牌；后端重启沿用同一个（spawn 的 env 不变）
const TOKEN = randomBytes(24).toString('hex')
let child: ChildProcess | null = null
let info: BackendInfo = { port: 0, ready: false, token: TOKEN }
let quitting = false
let starting = false
let restarts = 0

function serverDir(): string | null {
  const candidates = [
    process.env['BOOK_AGENT_SERVER_DIR'],
    join(app.getAppPath(), '..', '..', 'server'),
    process.resourcesPath ? join(process.resourcesPath, 'server') : '',
    join(process.cwd(), 'server')
  ].filter((item): item is string => Boolean(item))
  return candidates.find((dir) => existsSync(join(dir, 'app', 'main.py'))) ?? null
}

/** 安装包里带的冻结后端（PyInstaller 产物）；没有就回落到本机 Python。 */
function serverBinary(): string | null {
  const name = process.platform === 'win32' ? 'book-server.exe' : 'book-server'
  const candidates = [
    process.env['BOOK_AGENT_SERVER_BIN'],
    process.resourcesPath ? join(process.resourcesPath, 'server-bin', name) : '',
    join(app.getAppPath(), '..', '..', 'server', 'dist', 'book-server', name)
  ].filter((item): item is string => Boolean(item))
  return candidates.find((item) => existsSync(item)) ?? null
}

function pythonPath(dir: string): string {
  const custom = process.env['BOOK_AGENT_PYTHON']
  if (custom) return custom
  const names =
    process.platform === 'win32'
      ? [join(dir, '.venv', 'Scripts', 'python.exe')]
      : [join(dir, '.venv', 'bin', 'python')]
  for (const candidate of names) {
    if (existsSync(candidate)) return candidate
  }
  return process.platform === 'win32' ? 'python' : 'python3'
}

function pidFile(): string {
  return join(homedir(), '.book-agent', 'backend.pid')
}

async function killStale(): Promise<void> {
  try {
    const file = pidFile()
    if (!existsSync(file)) return
    const pid = Number(readFileSync(file, 'utf8').trim())
    if (!pid) return
    process.kill(pid, 0)
    if (process.platform === 'win32') {
      await new Promise<void>((resolve) => {
        execFile('taskkill', ['/pid', String(pid), '/T', '/F'], () => resolve())
      })
    } else {
      process.kill(pid, 'SIGKILL')
    }
  } catch {
    /* 进程已不存在或无权访问 */
  } finally {
    try {
      unlinkSync(pidFile())
    } catch {
      /* ignore */
    }
  }
}

function canListen(port: number): Promise<boolean> {
  return new Promise((resolve) => {
    const server = net.createServer()
    server.once('error', () => resolve(false))
    server.once('listening', () => server.close(() => resolve(true)))
    server.listen(port, '127.0.0.1')
  })
}

function freePort(): Promise<number> {
  return new Promise((resolve, reject) => {
    const server = net.createServer()
    server.once('error', reject)
    server.listen(0, '127.0.0.1', () => {
      const address = server.address()
      const port = typeof address === 'object' && address ? address.port : 0
      server.close(() => resolve(port))
    })
  })
}

function health(port: number): Promise<boolean> {
  return new Promise((resolve) => {
    const request = http.get(
      { host: '127.0.0.1', port, path: '/api/health', timeout: 1200 },
      (response) => {
        response.resume()
        resolve(response.statusCode === 200)
      }
    )
    request.on('timeout', () => {
      request.destroy()
      resolve(false)
    })
    request.on('error', () => resolve(false))
  })
}

async function waitHealthy(port: number, timeoutMs = 40000): Promise<boolean> {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    if (await health(port)) return true
    await new Promise((resolve) => setTimeout(resolve, 500))
  }
  return false
}

export function getBackendInfo(): BackendInfo {
  return info
}

export async function startBackend(): Promise<BackendInfo> {
  if (starting) return info
  starting = true
  try {
    await killStale()
    // 优先用随包冻结的后端（安装包形态），没有才回落到本机 Python（开发态）
    const binary = serverBinary()
    const dir = binary ? null : serverDir()
    if (!binary && !dir) {
      info = {
        port: 0,
        ready: false,
        token: TOKEN,
        error: '找不到后端：既没有 resources/server-bin，也没有 server/app/main.py'
      }
      return info
    }
    const port = (await canListen(PREFERRED_PORT)) ? PREFERRED_PORT : await freePort()
    info = { port, ready: false, token: TOKEN }
    const command = binary ?? pythonPath(dir as string)
    const args = binary
      ? []
      : ['-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', String(port)]
    child = spawn(command, args, {
      cwd: binary ? dirname(binary) : (dir as string),
      env: {
        ...process.env,
        PYTHONUNBUFFERED: '1',
        BOOK_AGENT_PORT: String(port),
        BOOK_AGENT_TOKEN: TOKEN
      },
      windowsHide: true,
      stdio: ['ignore', 'pipe', 'pipe']
    })
    child.stdout?.on('data', (data) => console.log('[backend]', String(data).trim()))
    child.stderr?.on('data', (data) => console.error('[backend]', String(data).trim()))
    if (child.pid) {
      try {
        writeFileSync(pidFile(), String(child.pid), 'utf8')
      } catch {
        /* 忽略 pid 文件写入失败 */
      }
    }
    child.on('error', (error) => {
      info = { port, ready: false, token: TOKEN, error: `后端启动失败：${error.message}` }
    })
    child.on('exit', (code) => {
      child = null
      try {
        unlinkSync(pidFile())
      } catch {
        /* ignore */
      }
      if (quitting) return
      if (restarts < 3) {
        restarts += 1
        info = {
          port,
          ready: false,
          token: TOKEN,
          error: `后端退出，正在重启（${restarts}/3）`
        }
        setTimeout(() => void startBackend(), 1000)
      } else {
        info = { port, ready: false, token: TOKEN, error: `后端已退出（code ${code ?? '-'}）` }
      }
    })

    const ok = await waitHealthy(port)
    info = ok
      ? { port, ready: true, token: TOKEN }
      : { port, ready: false, token: TOKEN, error: '后端启动超时，请检查 Python 依赖' }
    return info
  } finally {
    starting = false
  }
}

export async function stopBackend(): Promise<void> {
  quitting = true
  const current = child
  child = null
  if (current?.pid) {
    if (process.platform === 'win32') {
      await new Promise<void>((resolve) => {
        execFile('taskkill', ['/pid', String(current.pid), '/T', '/F'], () => resolve())
      })
    } else {
      current.kill('SIGTERM')
    }
  }
  try {
    unlinkSync(pidFile())
  } catch {
    /* ignore */
  }
}

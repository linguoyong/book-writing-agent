import { app } from 'electron'
import { execFile, spawn, type ChildProcess } from 'node:child_process'
import { randomBytes } from 'node:crypto'
import { existsSync, mkdirSync, readFileSync, unlinkSync, writeFileSync } from 'node:fs'
import http from 'node:http'
import net from 'node:net'
import { homedir } from 'node:os'
import { dirname, join } from 'node:path'

export interface BackendInfo {
  port: number
  ready: boolean
  /** 本地 API 访问令牌：只留在主进程，不落盘、不下发给页面 */
  token: string
  error?: string
}

const PREFERRED_PORT = 8787
// 每次启动生成新令牌；后端重启沿用同一个（spawn 的 env 不变）
const TOKEN = randomBytes(24).toString('hex')
let child: ChildProcess | null = null
let info: BackendInfo = { port: 0, ready: false, token: TOKEN }
let quitting = false
let starting: Promise<BackendInfo> | null = null
let restarts = 0
let restartTimer: ReturnType<typeof setTimeout> | undefined

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
  // 开发时使用源码，避免历史打包产物遮蔽刚修改的后端。
  if (!app.isPackaged && !process.env['BOOK_AGENT_SERVER_BIN']) return null
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
  return join(process.env['BOOK_AGENT_HOME'] || join(homedir(), '.book-agent'), 'backend.pid')
}

/** 启动时间 + 命令行用于识别同一个进程，防止 PID 被其它程序复用。 */
function processIdentity(pid: number): Promise<string> {
  return new Promise((resolve) => {
    const windows = process.platform === 'win32'
    const args = windows
      ? ['-NoProfile', '-NonInteractive', '-Command',
          `$targetProcess = Get-CimInstance Win32_Process -Filter 'ProcessId = ${pid}'; ` +
          'if ($targetProcess) { [ordered]@{Started=$targetProcess.CreationDate.ToUniversalTime().Ticks.ToString();Command=$targetProcess.CommandLine} | ConvertTo-Json -Compress }']
      : ['-p', String(pid), '-o', 'lstart=', '-o', 'args=']
    execFile(windows ? 'powershell.exe' : 'ps', args, { windowsHide: true, timeout: 5000 },
      (error, stdout) => resolve(error ? '' : stdout.trim()))
  })
}

async function killStale(): Promise<void> {
  try {
    const file = pidFile()
    if (!existsSync(file)) return
    const record = JSON.parse(readFileSync(file, 'utf8'))
    // 旧版的纯数字文件没有可核验的身份，直接清理文件，不结束未知进程。
    if (!record || !Number.isSafeInteger(record.pid) || record.pid <= 0 ||
        record.pid === process.pid || typeof record.identity !== 'string' || !record.identity) return
    const pid: number = record.pid
    if (await processIdentity(pid) !== record.identity) return
    if (process.platform === 'win32') {
      await new Promise<void>((resolve) => {
        execFile(
          'taskkill',
          ['/pid', String(pid), '/T', '/F'],
          // windowsHide：主进程虽然没有控制台，但 execFile 默认仍可能闪一个窗口
          { windowsHide: true },
          () => resolve()
        )
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

async function waitHealthy(port: number, current: ChildProcess, timeoutMs = 40000): Promise<boolean> {
  const deadline = Date.now() + timeoutMs
  while (!quitting && child === current && Date.now() < deadline) {
    if (await health(port)) return !quitting && child === current
    await new Promise((resolve) => setTimeout(resolve, 500))
  }
  return false
}

export function getBackendInfo(): BackendInfo {
  return info
}

export function startBackend(): Promise<BackendInfo> {
  if (quitting) return Promise.resolve(info)
  if (starting) return starting
  if (child) return Promise.resolve(info)
  starting = launchBackend().finally(() => { starting = null })
  return starting
}

async function launchBackend(): Promise<BackendInfo> {
  await killStale()
  if (quitting) return info
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
  while (!quitting) {
    const port = (await canListen(PREFERRED_PORT)) ? PREFERRED_PORT : await freePort()
    if (quitting) return info
    info = { port, ready: false, token: TOKEN }
    const command = binary ?? pythonPath(dir as string)
    const args = binary
      ? []
      : ['-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', String(port)]
    const current = spawn(command, args, {
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
    child = current
    current.stdout?.on('data', (data) => console.log('[backend]', String(data).trim()))
    current.stderr?.on('data', (data) => console.error('[backend]', String(data).trim()))
    current.on('error', (error) => {
      if (quitting || child !== current) return
      child = null
      info = { port, ready: false, token: TOKEN, error: `后端启动失败：${error.message}` }
    })
    current.on('exit', (code) => {
      if (child !== current) return
      child = null
      try {
        unlinkSync(pidFile())
      } catch {
        /* ignore */
      }
      if (quitting) return
      info = { port, ready: false, token: TOKEN, error: `后端已退出（code ${code ?? '-'}）` }
      // 首次健康检查期间由下面的循环重试，正常运行后的退出才安排定时重启。
      if (!starting && restarts < 3) {
        restarts += 1
        restartTimer = setTimeout(() => { void startBackend() }, 1000)
      }
    })

    if (current.pid) {
      const identity = await processIdentity(current.pid)
      if (identity && child === current && !quitting) {
        try {
          mkdirSync(dirname(pidFile()), { recursive: true })
          writeFileSync(pidFile(), JSON.stringify({ pid: current.pid, identity }), 'utf8')
        } catch {
          /* 忽略 pid 文件写入失败 */
        }
      }
    }
    const ok = await waitHealthy(port, current)
    if (quitting) return info
    if (child !== current) {
      if (restarts >= 3) return info
      restarts += 1
      await new Promise((resolve) => setTimeout(resolve, 1000))
      continue
    }
    info = ok
      ? { port, ready: true, token: TOKEN }
      : { port, ready: false, token: TOKEN, error: '后端启动超时，请检查 Python 依赖' }
    return info
  }
  return info
}

export async function stopBackend(): Promise<void> {
  quitting = true
  clearTimeout(restartTimer)
  info = { ...info, ready: false }
  const current = child
  child = null
  if (current?.pid) {
    if (process.platform === 'win32') {
      await new Promise<void>((resolve) => {
        execFile(
          'taskkill',
          ['/pid', String(current.pid), '/T', '/F'],
          { windowsHide: true },
          () => resolve()
        )
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

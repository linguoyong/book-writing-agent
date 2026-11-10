import { EventEmitter } from 'node:events'
import { join } from 'node:path'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({
  spawn: vi.fn(), execFile: vi.fn(), existsSync: vi.fn(), readFileSync: vi.fn(),
  writeFileSync: vi.fn(), unlinkSync: vi.fn(), mkdirSync: vi.fn(), healthy: true,
  packaged: false
}))
vi.mock('electron', () => ({ app: { getAppPath: () => 'D:/repo/apps/desktop', get isPackaged() { return mocks.packaged } } }))
vi.mock('node:child_process', () => ({ spawn: mocks.spawn, execFile: mocks.execFile }))
vi.mock('node:fs', () => ({ existsSync: mocks.existsSync, readFileSync: mocks.readFileSync,
  writeFileSync: mocks.writeFileSync, unlinkSync: mocks.unlinkSync, mkdirSync: mocks.mkdirSync }))
vi.mock('node:http', () => ({ default: {
  get: (_options: unknown, callback: (response: unknown) => void) => {
    const request = new EventEmitter()
    queueMicrotask(() => callback({ statusCode: mocks.healthy ? 200 : 503, resume() {} }))
    return request
  }
} }))
vi.mock('node:net', () => ({ default: {
  createServer: () => {
    const server = new EventEmitter() as EventEmitter & { listen: () => void; close: (callback: () => void) => void }
    server.listen = () => queueMicrotask(() => server.emit('listening'))
    server.close = (callback) => callback()
    return server
  }
} }))

function processChild(pid = 7654) {
  return Object.assign(new EventEmitter(), { pid, stdout: new EventEmitter(), stderr: new EventEmitter(), kill: vi.fn() })
}

beforeEach(() => {
  vi.resetModules()
  vi.useFakeTimers()
  vi.stubEnv('BOOK_AGENT_HOME', 'D:/isolated-test-home')
  vi.stubEnv('BOOK_AGENT_SERVER_DIR', 'D:/repo/server')
  vi.stubEnv('BOOK_AGENT_SERVER_BIN', '')
  mocks.healthy = true
  mocks.packaged = false
  vi.spyOn(process, 'kill').mockReturnValue(true)
  mocks.existsSync.mockImplementation((file: string) => !file.endsWith('backend.pid'))
  mocks.spawn.mockImplementation(() => processChild())
  mocks.execFile.mockImplementation((_command: string, _args: string[], _options: unknown, callback: (error: null, stdout: string) => void) => callback(null, 'process-identity-123'))
})

afterEach(async () => {
  const backend = await import('./backend')
  await backend.stopBackend()
  vi.clearAllTimers()
  vi.useRealTimers()
  vi.unstubAllEnvs()
  vi.resetAllMocks()
  vi.restoreAllMocks()
})

it('stores lifecycle files in BOOK_AGENT_HOME, creating its parent on first launch', async () => {
  const backend = await import('./backend')
  expect((await backend.startBackend()).ready).toBe(true)
  expect(mocks.mkdirSync).toHaveBeenCalledWith(join('D:/isolated-test-home'), { recursive: true })
  expect(mocks.writeFileSync).toHaveBeenCalledWith(join('D:/isolated-test-home', 'backend.pid'), expect.any(String), 'utf8')
})

it('uses current source during development even when old build artifacts exist', async () => {
  const backend = await import('./backend')
  await backend.startBackend()
  expect(mocks.spawn.mock.calls[0][1]).toContain('app.main:app')
})

it('does not kill a process referenced only by a legacy numeric PID', async () => {
  mocks.existsSync.mockReturnValue(true)
  mocks.readFileSync.mockReturnValue('1234')
  const backend = await import('./backend')
  await backend.startBackend()
  expect(mocks.execFile.mock.calls.filter(([command]) => command === 'taskkill')).toHaveLength(0)
  expect(process.kill).not.toHaveBeenCalledWith(1234, expect.anything())
})

it('does not kill a reused PID whose process identity has changed', async () => {
  mocks.existsSync.mockReturnValue(true)
  mocks.readFileSync.mockReturnValue(JSON.stringify({ pid: 1234, identity: 'different-process' }))
  const backend = await import('./backend')
  await backend.startBackend()
  expect(mocks.execFile.mock.calls.filter(([command]) => command === 'taskkill')).toHaveLength(0)
  expect(process.kill).not.toHaveBeenCalledWith(1234, expect.anything())
})

it('cleans an orphan only after its saved process identity matches', async () => {
  mocks.existsSync.mockReturnValue(true)
  mocks.readFileSync.mockReturnValue(JSON.stringify({ pid: 1234, identity: 'process-identity-123' }))
  const backend = await import('./backend')
  await backend.startBackend()
  if (process.platform === 'win32') {
    expect(mocks.execFile).toHaveBeenCalledWith('taskkill', ['/pid', '1234', '/T', '/F'], { windowsHide: true }, expect.any(Function))
  } else {
    expect(process.kill).toHaveBeenCalledWith(1234, 'SIGKILL')
  }
})

it('recovers from a crash during the initial health wait', async () => {
  mocks.healthy = false
  mocks.spawn.mockImplementationOnce(() => processChild()).mockImplementationOnce(() => {
    mocks.healthy = true
    return processChild(7655)
  })
  const backend = await import('./backend')
  const starting = backend.startBackend()
  await vi.advanceTimersByTimeAsync(0)
  mocks.spawn.mock.results[0].value.emit('exit', 1)
  await vi.advanceTimersByTimeAsync(2500)
  expect(mocks.spawn).toHaveBeenCalledTimes(2)
  expect((await starting).ready).toBe(true)
})

it('cancels a scheduled restart when the application quits', async () => {
  const backend = await import('./backend')
  await backend.startBackend()
  mocks.spawn.mock.results[0].value.emit('exit', 1)
  await backend.stopBackend()
  await vi.advanceTimersByTimeAsync(2000)
  expect(mocks.spawn).toHaveBeenCalledTimes(1)
})

it('does not report ready or spawn another child when quit occurs during startup', async () => {
  mocks.healthy = false
  const backend = await import('./backend')
  const starting = backend.startBackend()
  await vi.advanceTimersByTimeAsync(0)
  await backend.stopBackend()
  mocks.healthy = true
  await vi.advanceTimersByTimeAsync(1500)
  expect((await starting).ready).toBe(false)
  expect(mocks.spawn).toHaveBeenCalledTimes(1)
})

it('shares the same startup promise without spawning duplicate children', async () => {
  const backend = await import('./backend')
  const first = backend.startBackend()
  expect(backend.startBackend()).toBe(first)
  await first
  await backend.startBackend()
  expect(mocks.spawn).toHaveBeenCalledTimes(1)
})

it('limits repeated startup crashes to three restarts', async () => {
  mocks.healthy = false
  mocks.spawn.mockImplementation(() => {
    const current = processChild()
    setTimeout(() => current.emit('exit', 1), 100)
    return current
  })
  const backend = await import('./backend')
  const starting = backend.startBackend()
  await vi.advanceTimersByTimeAsync(6000)
  expect((await starting).ready).toBe(false)
  expect(mocks.spawn).toHaveBeenCalledTimes(4)
})

it('reports spawn failure without a 40-second health timeout', async () => {
  mocks.spawn.mockImplementation(() => {
    const current = processChild()
    setTimeout(() => current.emit('error', new Error('missing executable')), 100)
    return current
  })
  mocks.healthy = false
  const backend = await import('./backend')
  const starting = backend.startBackend()
  await vi.advanceTimersByTimeAsync(6000)
  expect((await starting).error).toContain('missing executable')
  expect(mocks.spawn).toHaveBeenCalledTimes(4)
})

it('uses the bundled binary in a packaged app', async () => {
  mocks.packaged = true
  const backend = await import('./backend')
  await backend.startBackend()
  expect(mocks.spawn.mock.calls[0][1]).toEqual([])
})

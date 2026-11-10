import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Message, RunSnapshot } from './types'

const mocks = vi.hoisted(() => ({ messages: vi.fn(), sessionRun: vi.fn(), stopRun: vi.fn(), steer: vi.fn() }))
vi.mock('./api', () => ({ api: mocks, ApiError: class extends Error {}, streamChat: vi.fn(), approveChat: vi.fn(), regenerateChat: vi.fn() }))
import { useAppStore } from './store'

const initial = useAppStore.getState()
const messages: Message[] = [
  { id: 1, session_id: 's', role: 'user', content: 'old question', created_at: '' },
  { id: 2, session_id: 's', role: 'assistant', content: 'old answer', created_at: '' },
  { id: 3, session_id: 's', role: 'user', content: 'write a chapter', created_at: '' }
]
const snapshot: RunSnapshot = {
  session_id: 's', running: true, after_message_id: 2, started_at: 100, elapsed_ms: 100,
  text: '', error: '', items: [{ type: 'tool', name: 'read_file', input: '{}', output: '', status: 'running' }]
}

beforeEach(() => {
  vi.useFakeTimers()
  vi.stubGlobal('window', { setInterval, clearInterval })
  mocks.stopRun.mockResolvedValue({ ok: true })
  mocks.steer.mockResolvedValue({ ok: true, queued: 1 })
  mocks.messages.mockResolvedValue(messages)
  mocks.sessionRun.mockResolvedValue(snapshot)
  useAppStore.setState({ ...initial, activeSessionId: 's',
    refreshContext: vi.fn(), refreshPending: vi.fn(), refreshSessions: vi.fn(), refreshAllSessions: vi.fn(), refreshDiff: vi.fn()
  }, true)
})
afterEach(() => {
  useAppStore.getState().stopStreaming()
  vi.clearAllTimers()
  vi.useRealTimers()
  vi.unstubAllGlobals()
  vi.resetAllMocks()
})

describe('returning to an executing conversation', () => {
  it('keeps a newly sent steering message across subsequent snapshot polls', async () => {
    useAppStore.getState().resumeRun('s')
    await vi.advanceTimersByTimeAsync(0)
    mocks.messages.mockResolvedValue([...messages, { id: 4, session_id: 's', role: 'user', content: 'keep the new direction', created_at: '', meta: { steering: true } }])
    await useAppStore.getState().steerMessage('keep the new direction')
    await vi.advanceTimersByTimeAsync(1600)
    expect(useAppStore.getState().timeline.filter((item) => item.type === 'user' && item.content === 'keep the new direction')).toHaveLength(1)
  })

  it('keeps user messages and history after visiting approvals and across repeated polls', async () => {
    await useAppStore.getState().selectSession('s')
    await vi.advanceTimersByTimeAsync(0)
    useAppStore.getState().setView('approvals')
    useAppStore.getState().setView('chat')
    await useAppStore.getState().selectSession('s')
    await vi.advanceTimersByTimeAsync(2400)
    const state = useAppStore.getState()
    expect(state.streaming).toBe(true)
    expect(state.timeline.filter((item) => item.type === 'user').map((item) => item.content)).toEqual(['old question', 'write a chapter'])
    expect(state.timeline.filter((item) => item.type === 'assistant')).toHaveLength(1)
    expect(state.timeline.filter((item) => item.type === 'tool')).toHaveLength(1)
  })

  it('ignores late results from an older watcher for the same session', async () => {
    let resolveOld!: (value: RunSnapshot) => void
    mocks.sessionRun.mockImplementationOnce(() => new Promise<RunSnapshot>((resolve) => { resolveOld = resolve }))
    useAppStore.getState().resumeRun('s')
    useAppStore.getState().resumeRun('s')
    await vi.advanceTimersByTimeAsync(0)
    resolveOld({ ...snapshot, items: [{ type: 'text', content: 'stale output' }] })
    await vi.advanceTimersByTimeAsync(0)
    expect(useAppStore.getState().timeline.some((item) => item.type === 'assistant' && item.content === 'stale output')).toBe(false)
    await vi.advanceTimersByTimeAsync(800)
    expect(mocks.sessionRun).toHaveBeenCalledTimes(3)
  })

  it('does not overlap slow polling requests', async () => {
    let finish!: (value: RunSnapshot) => void
    mocks.sessionRun.mockImplementationOnce(() => new Promise<RunSnapshot>((resolve) => { finish = resolve }))
    useAppStore.getState().resumeRun('s')
    await vi.advanceTimersByTimeAsync(1600)
    expect(mocks.sessionRun).toHaveBeenCalledTimes(1)
    finish(snapshot)
    await vi.advanceTimersByTimeAsync(0)
    await vi.advanceTimersByTimeAsync(800)
    expect(mocks.sessionRun).toHaveBeenCalledTimes(2)
  })

  it('loads the final saved answer when generation completes', async () => {
    useAppStore.getState().resumeRun('s')
    await vi.advanceTimersByTimeAsync(0)
    mocks.sessionRun.mockResolvedValue({ ...snapshot, running: false })
    mocks.messages.mockResolvedValue([...messages, { id: 4, session_id: 's', role: 'assistant', content: 'finished chapter', created_at: '' }])
    await vi.advanceTimersByTimeAsync(800)
    expect(useAppStore.getState().streaming).toBe(false)
    expect(useAppStore.getState().timeline.at(-1)).toMatchObject({ type: 'assistant', content: 'finished chapter' })
  })

  it('recovers from a polling failure without removing the user request', async () => {
    await useAppStore.getState().selectSession('s')
    await vi.advanceTimersByTimeAsync(0)
    mocks.sessionRun.mockRejectedValueOnce(new Error('temporary failure'))
    await vi.advanceTimersByTimeAsync(800)
    expect(useAppStore.getState().timeline.some((item) => item.type === 'user' && item.content === 'write a chapter')).toBe(true)
    await vi.advanceTimersByTimeAsync(800)
    expect(useAppStore.getState().streaming).toBe(true)
  })
})

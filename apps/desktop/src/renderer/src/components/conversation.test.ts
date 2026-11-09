import { describe, expect, it } from 'vitest'
import type { Message, RunSnapshot, TimelineItem } from '../types'
import { groupTurns, timelineFromMessages, timelineWithRun } from './conversation'

describe('shared main and side conversation timeline', () => {
  it('keeps narration in process while the last tool is running', () => {
    const items: TimelineItem[] = [
      { id: 'u', type: 'user', content: 'review' },
      { id: 'a', type: 'assistant', content: 'checking' },
      { id: 't', type: 'tool', name: 'chapter_review', input: '{}', status: 'running' }
    ]
    const [turn] = groupTurns(items)
    expect(turn.conclusion).toBeUndefined()
    expect(turn.process.map((item) => item.id)).toEqual(['a', 't'])
    expect(items).toHaveLength(3)
  })

  it('restores text/tool/text order and final answer after reopening history', () => {
    const messages: Message[] = [
      { id: 1, session_id: 's', role: 'user', content: 'review', created_at: '' },
      { id: 2, session_id: 's', role: 'assistant', content: 'result', created_at: '', meta: {
        timeline: [
          { type: 'text', content: 'checking' },
          { type: 'tool', name: 'chapter_review', input: '{}', status: 'done', output: 'complete' },
          { type: 'text', content: 'result' }
        ],
        turn: { elapsed_ms: 1000, changes: { files: [], diff: '' } }
      } }
    ]
    const [turn] = groupTurns(timelineFromMessages(messages))
    expect(turn.process.map((item) => item.type)).toEqual(['assistant', 'tool'])
    expect(turn.conclusion?.content).toBe('result')
    expect(turn.meta?.elapsed_ms).toBe(1000)
  })

  it('supports older histories and settles interrupted tools', () => {
    const messages: Message[] = [
      { id: 1, session_id: 's', role: 'assistant', content: 'legacy', created_at: '', meta: { tool_calls: [{ name: 'read_file', input: 'a.md' }] } },
      { id: 2, session_id: 's', role: 'user', content: 'next', created_at: '' },
      { id: 3, session_id: 's', role: 'assistant', content: '', created_at: '', meta: { interrupted: true, timeline: [{ type: 'tool', name: 'read_file', input: 'b.md', output: '', status: 'running' }] } }
    ]
    const turns = groupTurns(timelineFromMessages(messages))
    expect(turns[0].conclusion?.content).toBe('legacy')
    expect(turns[1].conclusion).toBeUndefined()
    expect(turns[1].process[0]).toMatchObject({ type: 'tool', status: 'cancelled' })
  })
})

describe('running conversation restoration', () => {
  const messages: Message[] = [
    { id: 1, session_id: 's', role: 'user', content: 'earlier question', created_at: '' },
    { id: 2, session_id: 's', role: 'assistant', content: 'earlier answer', created_at: '' },
    { id: 3, session_id: 's', role: 'user', content: 'current request', created_at: '', meta: { references: [] } },
    { id: 4, session_id: 's', role: 'assistant', content: 'already persisted part', created_at: '' }
  ]
  const snapshot: RunSnapshot = {
    session_id: 's', running: true, after_message_id: 2, started_at: 100, elapsed_ms: 10, text: '', error: '',
    items: [{ type: 'tool', name: 'kb_write', input: '{}', output: '', status: 'running' }]
  }

  it('keeps previous history and the current user message while polling', () => {
    const items = timelineWithRun(messages, snapshot)
    expect(items.map((item) => 'content' in item ? item.content : item.type)).toEqual([
      'earlier question', 'earlier answer', 'current request', 'tool'
    ])
    const turns = groupTurns(items)
    expect(turns).toHaveLength(2)
    expect(turns[1].user?.content).toBe('current request')
    expect(timelineWithRun(messages, snapshot)).toEqual(items)
  })

  it('keeps the approval report from before the resumed run', () => {
    const items = timelineWithRun(messages, { ...snapshot, after_message_id: 4 })
    expect(items.filter((item) => item.type === 'assistant').map((item) => item.content)).toEqual([
      'earlier answer', 'already persisted part'
    ])
    expect(items.filter((item) => item.type === 'tool')).toHaveLength(1)
  })

  it('preserves the user message even before the model produces its first event', () => {
    const items = timelineWithRun(messages.slice(0, 3), { ...snapshot, items: [] })
    expect(items[items.length - 1]).toMatchObject({ type: 'user', content: 'current request' })
  })
})

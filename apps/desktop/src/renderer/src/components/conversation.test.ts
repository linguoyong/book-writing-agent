import { describe, expect, it } from 'vitest'
import type { Message, TimelineItem } from '../types'
import { groupTurns, timelineFromMessages } from './conversation'

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

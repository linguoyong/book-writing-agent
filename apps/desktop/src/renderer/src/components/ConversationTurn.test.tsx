import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it, vi } from 'vitest'
import type { TurnView } from './conversation'

vi.mock('../store', () => ({ useAppStore: (selector: (state: unknown) => unknown) => selector({
  regenerate: vi.fn(), retryLastTurn: vi.fn(), setPendingComposer: vi.fn(), showToast: vi.fn(), streaming: false
}) }))
vi.mock('./Markdown', () => ({ default: ({ content }: { content: string }) => <span>{content}</span> }))

import { ConversationTurn } from './ConversationTurn'

const turn: TurnView = {
  id: 'turn', user: { id: 'u', type: 'user', content: '问题' },
  process: [{ id: 't', type: 'tool', name: 'chapter_review', input: '{}', status: 'running' }],
  conclusion: { id: 'a', type: 'assistant', content: '正文回答' }
}

describe.each([false, true])('shared conversation presentation side=%s', (side) => {
  it('keeps user steering visible outside folded process during generation and in history', () => {
    const guided: TurnView = { ...turn, process: [
      { id: 'steer', type: 'user', content: '保留桥上钟声', steering: true }, ...turn.process
    ] }
    for (const live of [true, false]) {
      const html = renderToStaticMarkup(<ConversationTurn turn={guided} side={side} live={live} isLast startedAt={null} />)
      expect(html.indexOf('保留桥上钟声')).toBeGreaterThan(0)
      expect(html.indexOf('保留桥上钟声')).toBeLessThan(html.indexOf('<details'))
      expect(html.match(/保留桥上钟声/g)).toHaveLength(1)
    }
  })

  it('folds tool steps and hides actions during generation', () => {
    // 审批恢复时同一轮仍带有上一次暂停的摘要，运行状态应以实时流为准。
    for (const meta of [undefined, { elapsed_ms: 1000, changes: { files: [], diff: '' } }]) {
      const html = renderToStaticMarkup(<ConversationTurn turn={{ ...turn, meta }} side={side} live isLast startedAt={Date.now()} />)
      expect(html).toContain('turn-live-running')
      expect(html).toContain('正在审阅章节')
      expect(html).not.toContain('<details open')
      expect(html).not.toContain('title="复制"')
      expect(html).not.toContain('title="编辑后重发"')
      expect(html).not.toContain('title="重试')
    }
  })

  it('shows copy/edit/retry after completion and keeps the process folded', () => {
    const html = renderToStaticMarkup(<ConversationTurn turn={{ ...turn, meta: { elapsed_ms: 1000, changes: { files: [], diff: '' } } }} side={side} live={false} isLast startedAt={null} />)
    expect(html).toContain('turn-fold')
    expect(html).toContain('正文回答')
    expect(html).toContain('title="复制"')
    expect(html).toContain('title="编辑后重发"')
    expect(html).toContain('title="重试')
  })
})

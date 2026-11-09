import { describe, expect, it } from 'vitest'
import type { TimelineItem } from '../types'
import { executionProgress, toolProgress } from './progress'

describe('visible execution progress', () => {
  it('describes the action and target in plain language', () => {
    expect(toolProgress({ type: 'tool', id: 't', name: 'kb_write', input: '{"kind":"characters","entity_id":"lin-zhao"}', status: 'running' }))
      .toBe('正在保存角色设定 · lin-zhao')
    expect(toolProgress({ type: 'tool', id: 't', name: 'read_file', input: '{"file_path":"/manuscript/ch-001.md"}', status: 'running' }))
      .toBe('正在阅读文件 · ch-001.md')
  })

  it('shows completed work while the next operation runs', () => {
    const items: TimelineItem[] = [
      { id: '1', type: 'tool', name: 'read_file', input: '{}', status: 'done', output: 'text' },
      { id: '2', type: 'tool', name: 'kb_write', input: '{"kind":"characters"}', status: 'done', output: '已写入' },
      { id: '3', type: 'tool', name: 'manuscript_write', input: '{"path":"ch-001.md"}', status: 'running' }
    ]
    expect(executionProgress(items, false)).toEqual({ current: '正在保存正文 · ch-001.md', recent: '已保存角色设定 · 已完成 2 步' })
  })

  it('handles truncated inputs and tool failures without inventing success', () => {
    expect(toolProgress({ id: '1', type: 'tool', name: 'write_file', input: '{truncated', status: 'done', output: 'Error: permission denied' }))
      .not.toContain('已保存')
    expect(toolProgress({ id: '2', type: 'tool', name: 'unknown', input: '{truncated', status: 'running' })).toBe('正在处理相关资料')
    expect(executionProgress([], true).current).toBe('正在组织回复')
  })
})

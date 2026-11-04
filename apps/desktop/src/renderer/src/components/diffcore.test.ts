import { describe, expect, it } from 'vitest'
import { FOLD_KEEP, parseDiff, splitSegments, type DiffHunk, type DiffLine } from './diffcore'

const sample = [
  'diff --git a/chapters/0001.md b/chapters/0001.md',
  'index 1111111..2222222 100644',
  '--- a/chapters/0001.md',
  '+++ b/chapters/0001.md',
  '@@ -1,3 +1,3 @@',
  ' 第一行',
  '-他拔出剑。',
  '+他举起剑。',
  ' 第三行',
  ''
].join('\n')

describe('parseDiff', () => {
  it('多文件各自成块并统计增删行', () => {
    const text = `${sample}diff --git a/kb/x.md b/kb/x.md
--- a/kb/x.md
+++ b/kb/x.md
@@ -1,1 +1,2 @@
 原有
+新增
`
    const blocks = parseDiff(text)

    expect(blocks.map((block) => block.path)).toEqual(['chapters/0001.md', 'kb/x.md'])
    expect(blocks[0].additions).toBe(1)
    expect(blocks[0].deletions).toBe(1)
    expect(blocks[1].additions).toBe(1)
    expect(blocks[1].deletions).toBe(0)
  })

  it('行号按 hunk 头正确编号', () => {
    const [block] = parseDiff(sample)
    const lines = block.hunks[0].lines

    expect(lines.map((line) => [line.type, line.oldNo, line.newNo])).toEqual([
      ['ctx', 1, 1],
      ['del', 2, null],
      ['add', null, 2],
      ['ctx', 3, 3]
    ])
  })

  it('成对增删标出词级变化区间', () => {
    const [block] = parseDiff(sample)
    const deleted = block.hunks[0].lines[1]
    const added = block.hunks[0].lines[2]

    expect(deleted.content.slice(deleted.wordStart, deleted.wordEnd)).toBe('拔出')
    expect(added.content.slice(added.wordStart, added.wordEnd)).toBe('举起')
  })

  it('emoji 换字时不把代理对劈成两半', () => {
    // 😀 与 😁 的高位代理都是 0xD83D，逐位比较会从低位代理开始算差异
    const text = `diff --git a/a.md b/a.md
--- a/a.md
+++ b/a.md
@@ -1,1 +1,1 @@
-😀 你好
+😁 你好
`
    const [block] = parseDiff(text)
    const deleted = block.hunks[0].lines[0]
    const added = block.hunks[0].lines[1]

    expect(deleted.wordStart).toBe(0)
    expect(deleted.wordEnd).toBe(2)
    // 切出来的片段本身是完整的代理对，不会出现孤立低位代理
    const marked = deleted.content.slice(deleted.wordStart, deleted.wordEnd)
    expect(marked).toBe('😀')
    expect(added.content.slice(added.wordStart, added.wordEnd)).toBe('😁')
  })

  it('没有改动的相同行不给词级区间', () => {
    const text = `diff --git a/a.md b/a.md
--- a/a.md
+++ b/a.md
@@ -1,1 +1,1 @@
-同一行
+同一行
`
    const [block] = parseDiff(text)

    expect(block.hunks[0].lines.every((line) => line.wordStart === undefined)).toBe(true)
  })
})

describe('splitSegments', () => {
  const hunk = (count: number, tail = '结尾'): DiffHunk => {
    const lines: DiffLine[] = Array.from({ length: count }, (_, index) => ({
      type: 'ctx',
      oldNo: index + 1,
      newNo: index + 1,
      content: `第 ${index + 1} 行`
    }))
    lines.push({ type: 'add', oldNo: null, newNo: count + 1, content: tail })
    return { lines }
  }

  it('连续未修改行超阈值时折叠中段', () => {
    const segments = splitSegments(hunk(20), 'p')
    const fold = segments.find((segment) => segment.kind === 'fold')

    expect(fold).toBeDefined()
    expect(fold?.count).toBe(20 - FOLD_KEEP * 2)
  })

  it('未修改行不足阈值时不折叠', () => {
    const segments = splitSegments(hunk(3), 'p')

    expect(segments.some((segment) => segment.kind === 'fold')).toBe(false)
  })
})

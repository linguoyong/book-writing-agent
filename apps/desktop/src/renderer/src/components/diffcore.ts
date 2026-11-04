/** unified diff 解析与折叠切分（纯函数，无 UI 依赖，便于单测） */

export interface DiffLine {
  type: 'ctx' | 'add' | 'del'
  oldNo: number | null
  newNo: number | null
  content: string
  /** 词级变化区间 [start, end)，成对增删行才有 */
  wordStart?: number
  wordEnd?: number
}

export interface DiffHunk {
  lines: DiffLine[]
}

export interface FileBlock {
  path: string
  additions: number
  deletions: number
  hunks: DiffHunk[]
}

export type Segment =
  | { kind: 'lines'; key: string; lines: DiffLine[] }
  | { kind: 'fold'; key: string; lines: DiffLine[]; count: number }

export const FOLD_THRESHOLD = 8
export const FOLD_KEEP = 3

/** 解析 unified diff（git 输出），多文件各自成块 */
export function parseDiff(text: string): FileBlock[] {
  const blocks: FileBlock[] = []
  let current: FileBlock | null = null
  let hunk: DiffHunk | null = null
  let oldNo = 0
  let newNo = 0

  for (const raw of text.split('\n')) {
    if (raw.startsWith('diff --git')) {
      const match = /^diff --git a\/(.+?) b\/(.+)$/.exec(raw)
      current = {
        path: match?.[2] ?? '',
        additions: 0,
        deletions: 0,
        hunks: []
      }
      blocks.push(current)
      hunk = null
      continue
    }
    if (!current) continue
    if (raw.startsWith('@@')) {
      const match = /^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/.exec(raw)
      if (!match) continue
      oldNo = Number(match[1])
      newNo = Number(match[2])
      hunk = { lines: [] }
      current.hunks.push(hunk)
      continue
    }
    if (!hunk) continue
    if (raw.startsWith('+')) {
      hunk.lines.push({ type: 'add', oldNo: null, newNo: newNo++, content: raw.slice(1) })
      current.additions += 1
    } else if (raw.startsWith('-')) {
      hunk.lines.push({ type: 'del', oldNo: oldNo++, newNo: null, content: raw.slice(1) })
      current.deletions += 1
    } else if (raw.startsWith(' ')) {
      hunk.lines.push({ type: 'ctx', oldNo: oldNo++, newNo: newNo++, content: raw.slice(1) })
    }
    // 其余（index/---/+++/new file mode/\ No newline）忽略
  }
  for (const block of blocks) annotateWordDiff(block)
  return blocks
}

/** 相邻且数量相等的增删块逐行配对，标出词级变化区间 */
function annotateWordDiff(block: FileBlock): void {
  for (const hunk of block.hunks) {
    let index = 0
    while (index < hunk.lines.length) {
      if (hunk.lines[index].type === 'del') {
        const dels: DiffLine[] = []
        const adds: DiffLine[] = []
        while (index < hunk.lines.length && hunk.lines[index].type === 'del') {
          dels.push(hunk.lines[index])
          index += 1
        }
        while (index < hunk.lines.length && hunk.lines[index].type === 'add') {
          adds.push(hunk.lines[index])
          index += 1
        }
        if (dels.length > 0 && adds.length > 0) {
          const pairs = Math.min(dels.length, adds.length)
          for (let pair = 0; pair < pairs; pair += 1) markPair(dels[pair], adds[pair])
        }
      } else {
        // ctx / add 开头的块直接跳过，保证 index 前进
        index += 1
      }
    }
  }
}

const _isLowSurrogate = (code: number): boolean => code >= 0xdc00 && code <= 0xdfff

/** 落点若在低位代理上，说明把一个 emoji 劈成两半了，退回高代理的位置 */
function alignBack(text: string, index: number): number {
  return index > 0 && index < text.length && _isLowSurrogate(text.charCodeAt(index))
    ? index - 1
    : index
}

/** 结尾若切在低位代理上，往后吞掉这一位，别把 emoji 拆开 */
function alignForward(text: string, index: number): number {
  return index < text.length && _isLowSurrogate(text.charCodeAt(index)) ? index + 1 : index
}

function markPair(del: DiffLine, add: DiffLine): void {
  const a = del.content
  const b = add.content
  if (!a || !b) return
  const minLen = Math.min(a.length, b.length)
  let start = 0
  while (start < minLen && a[start] === b[start]) start += 1
  let endA = a.length
  let endB = b.length
  while (endA > start && endB > start && a[endA - 1] === b[endB - 1]) {
    endA -= 1
    endB -= 1
  }
  // 😀 与 😁 的高位代理相同（0xD83D），逐位比较会从低位代理开始算差异，
  // 直接切会把代理对劈成两个非法字符，渲染成「�」。这里把边界拉回整字符。
  start = Math.min(alignBack(a, start), alignBack(b, start))
  endA = alignForward(a, endA)
  endB = alignForward(b, endB)
  if (start >= endA || start >= endB) return
  del.wordStart = start
  del.wordEnd = endA
  add.wordStart = start
  add.wordEnd = endB
}

/** 把 hunk 切成「行段 / 折叠段」：连续 ctx 超过阈值时保留首尾、折叠中段 */
export function splitSegments(hunk: DiffHunk, prefix: string): Segment[] {
  const segments: Segment[] = []
  let buffer: DiffLine[] = []

  const flush = (): void => {
    if (buffer.length === 0) return
    segments.push({ kind: 'lines', key: `${prefix}-${segments.length}`, lines: buffer })
    buffer = []
  }

  let index = 0
  while (index < hunk.lines.length) {
    if (hunk.lines[index].type !== 'ctx') {
      buffer.push(hunk.lines[index])
      index += 1
      continue
    }
    const start = index
    while (index < hunk.lines.length && hunk.lines[index].type === 'ctx') index += 1
    const run = hunk.lines.slice(start, index)
    if (run.length > FOLD_THRESHOLD) {
      const head = run.slice(0, FOLD_KEEP)
      const tailStart = Math.max(FOLD_KEEP, run.length - FOLD_KEEP)
      const tail = run.slice(tailStart)
      const folded = run.slice(FOLD_KEEP, tailStart)
      buffer.push(...head)
      flush()
      segments.push({
        kind: 'fold',
        key: `${prefix}-fold-${start}`,
        lines: folded,
        count: folded.length
      })
      buffer = [...tail]
    } else {
      buffer.push(...run)
    }
  }
  flush()
  return segments
}

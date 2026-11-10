import type { Message, RunSnapshot, TimelineItem, TurnMeta } from '../types'

type UserItem = Extract<TimelineItem, { type: 'user' }>
type AssistantItem = Extract<TimelineItem, { type: 'assistant' }>

export interface TurnView {
  id: string
  user?: UserItem
  process: TimelineItem[]
  conclusion?: AssistantItem
  meta?: TurnMeta
}

export function groupTurns(items: TimelineItem[]): TurnView[] {
  const turns: TurnView[] = []
  let current: TurnView | null = null
  const phases = new Set<string>()

  for (const item of items) {
    if (item.type === 'user' && !item.steering) {
      current = { id: item.id, user: item, process: [] }
      turns.push(current)
      continue
    }
    if (!current) {
      current = { id: `turn-${item.id}`, process: [] }
      turns.push(current)
    }
    if (item.type === 'turn_end') {
      const phase = item.meta.phase_id ?? item.id
      if (!phases.has(phase)) current.meta = mergeMeta(current.meta, item.meta)
      phases.add(phase)
      continue
    }
    current.process.push(item)
  }

  for (const turn of turns) {
    const last = turn.process[turn.process.length - 1]
    if (last?.type === 'assistant' && last.content.trim() && !last.awaiting && turn.meta?.status !== 'awaiting_approval') {
      turn.conclusion = last
      turn.process.pop()
    }
  }
  return turns
}

function mergeMeta(previous: TurnMeta | undefined, next: TurnMeta): TurnMeta {
  if (!previous) return next
  const usage = previous.usage && next.usage ? {
    ...next.usage,
    input: previous.usage.input + next.usage.input,
    output: previous.usage.output + next.usage.output,
    total: previous.usage.total + next.usage.total,
    cache_read: previous.usage.cache_read + next.usage.cache_read,
    calls: previous.usage.calls + next.usage.calls
  } : next.usage ?? previous.usage
  return {
    ...next,
    elapsed_ms: next.elapsed_scope === 'round'
      ? Math.max(previous.elapsed_ms, next.elapsed_ms)
      : previous.elapsed_ms + next.elapsed_ms,
    started_at: previous.started_at ?? next.started_at,
    retries: (previous.retries ?? 0) + (next.retries ?? 0),
    changes: { ...next.changes, files: [...new Set([...previous.changes.files, ...next.changes.files])],
      diff: [previous.changes.diff, next.changes.diff].filter(Boolean).join('\n') },
    usage
  }
}

export function timelineFromMessages(messages: Message[]): TimelineItem[] {
  const items: TimelineItem[] = []
  for (const message of messages) {
    const meta = message.meta
    if (message.role === 'assistant' && meta?.timeline) {
      meta.timeline.forEach((item, index) => {
        const id = `m${message.id}-trace${index}`
        items.push(item.type === 'tool'
          ? { ...item, id, status: item.status === 'done' ? 'done' : 'cancelled' }
          : item.type === 'notice' ? { id, type: 'notice', content: item.content }
          : { id, type: 'assistant', content: item.content, interrupted: Boolean(meta.interrupted), awaiting: Boolean(meta.awaiting_approval) })
      })
    } else {
      meta?.tool_calls?.forEach((call, index) => {
        items.push({ id: `m${message.id}-t${index}`, type: 'tool', name: call.name, input: call.input, status: 'done' })
      })
      if (message.content.trim()) {
        items.push(message.role === 'user'
          ? { id: `m${message.id}`, type: 'user', content: message.content, steering: Boolean(meta?.steering), references: meta?.references }
          : { id: `m${message.id}`, type: 'assistant', content: message.content, interrupted: Boolean(meta?.interrupted), awaiting: Boolean(meta?.awaiting_approval) })
      }
    }
    if (message.role === 'assistant' && meta?.turn) {
      items.push({ id: `t${message.id}`, type: 'turn_end', meta: { ...meta.turn,
        status: meta.turn.status ?? (meta.awaiting_approval ? 'awaiting_approval' : meta.interrupted ? 'interrupted' : 'completed') } })
    }
  }
  return items
}

/** 快照只含当前任务的输出，必须接在已有对话和用户请求后，不能替换整段历史。 */
export function timelineWithRun(messages: Message[], snapshot: RunSnapshot): TimelineItem[] {
  const boundary = snapshot.after_message_id
  const history = boundary === undefined
    ? messages.filter((message) => message.role === 'user' || Date.parse(message.created_at) < snapshot.started_at * 1000)
    : messages.filter((message) => message.id <= boundary || message.role === 'user')
  return [...timelineFromMessages(history), ...snapshot.items.map((item, index): TimelineItem => item.type === 'tool'
    ? { ...item, id: `run-t${index}`, status: item.status === 'done' ? 'done' : snapshot.running ? 'running' : 'cancelled' }
    : { id: `run-a${index}`, type: item.type === 'notice' ? 'notice' : 'assistant', content: item.content })]
}

/** 撤回失败模型的半截输出；Unicode 按码点计数，与后端 Python 保持一致。 */
export function timelineAfterRetry(items: TimelineItem[], removedChars: number, message: string): TimelineItem[] {
  let remaining = Math.max(0, removedChars)
  const next = [...items]
  for (let i = next.length - 1; i >= 0 && remaining; i -= 1) {
    const item = next[i]
    if (item.type !== 'assistant') continue
    const chars = Array.from(item.content)
    const removed = Math.min(remaining, chars.length)
    next[i] = { ...item, content: chars.slice(0, chars.length - removed).join('') }
    remaining -= removed
  }
  return [...next.filter((item) => item.type !== 'assistant' || item.content),
    { id: `retry-${Date.now()}-${next.length}`, type: 'notice', content: message }]
}

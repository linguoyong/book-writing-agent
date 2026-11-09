import type { Message, TimelineItem, TurnMeta } from '../types'

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
      current.meta = item.meta
      continue
    }
    current.process.push(item)
  }

  for (const turn of turns) {
    const last = turn.process[turn.process.length - 1]
    if (last?.type === 'assistant' && last.content.trim()) {
      turn.conclusion = last
      turn.process.pop()
    }
  }
  return turns
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
      items.push({ id: `t${message.id}`, type: 'turn_end', meta: meta.turn })
    }
  }
  return items
}

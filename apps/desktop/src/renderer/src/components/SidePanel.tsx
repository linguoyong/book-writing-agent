import { useEffect, useMemo, useRef, useState } from 'react'
import { ArrowUp, Eraser, Square } from 'lucide-react'
import { api, streamChat } from '../api'
import { useAppStore } from '../store'
import type { Message, TimelineItem } from '../types'
import { ConversationTurn, PendingBubble } from './ConversationTurn'
import { groupTurns, timelineFromMessages, timelineWithRun } from './conversation'

let counter = 0
const nextId = (): string => `s${Date.now()}-${counter++}`
const settleItems = (items: TimelineItem[]): TimelineItem[] => items.map((item) =>
  item.type === 'tool' && item.status === 'running' ? { ...item, status: 'cancelled' } : item)

export default function SidePanel(): React.JSX.Element {
  const project = useAppStore((state) => state.activeProject)
  const setPendingComposer = useAppStore((state) => state.setPendingComposer)
  const sessionId = useAppStore((state) => state.sideSessionId)
  const setSideSessionId = useAppStore((state) => state.setSideSessionId)
  const [items, setItems] = useState<TimelineItem[]>([])
  const [input, setInput] = useState('')
  const [streaming, setStreaming] = useState(false)
  const [startedAt, setStartedAt] = useState<number | null>(null)
  const [expanded, setExpanded] = useState(false)
  const scrollRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const abortRef = useRef<AbortController | null>(null)
  const generation = useRef(0)
  const activity = useRef(0)
  const busy = useRef(false)
  const stick = useRef(true)

  useEffect(() => {
    const seq = ++generation.current
    const initialActivity = activity.current
    busy.current = false
    setStreaming(false)
    setStartedAt(null)
    setInput('')
    setItems([])
    setExpanded(false)
    stick.current = true
    const sid = useAppStore.getState().sideSessionId
    let timer: ReturnType<typeof setTimeout> | undefined
    let history: Message[] | null = null
    const live = (): boolean => seq === generation.current && initialActivity === activity.current
    if (sid) {
      const restore = async (): Promise<void> => {
        try {
          const snapshot = await api.sessionRun(sid)
          if (!live()) return
          if (snapshot.running) {
            const messages = history ?? await api.messages(sid)
            if (!live()) return
            if (snapshot.items.length) history = messages
            busy.current = true
            setItems(timelineWithRun(messages, snapshot))
            setStreaming(true)
            setStartedAt(snapshot.started_at * 1000)
            timer = setTimeout(() => void restore(), 800)
          } else {
            const messages = await api.messages(sid)
            if (!live()) return
            busy.current = false
            setItems(timelineFromMessages(messages))
            setStreaming(false)
            setStartedAt(null)
          }
        } catch {
          if (live()) timer = setTimeout(() => void restore(), 800)
        }
      }
      void restore()
    }
    return () => {
      generation.current += 1
      clearTimeout(timer)
      abortRef.current?.abort()
      abortRef.current = null
    }
  }, [project?.id])

  useEffect(() => {
    const element = scrollRef.current
    if (element && stick.current) element.scrollTop = element.scrollHeight
  }, [items])

  const send = async (retry?: string): Promise<void> => {
    const text = retry ?? input
    if (!project || !text.trim() || busy.current) return
    busy.current = true
    activity.current += 1
    const seq = generation.current
    const live = (): boolean => seq === generation.current && useAppStore.getState().activeProject?.id === project.id
    setStreaming(true)
    setStartedAt(Date.now())
    stick.current = true
    if (retry === undefined) setInput('')
    const controller = new AbortController()
    abortRef.current = controller
    try {
      let sid = sessionId
      if (!sid) {
        const state = useAppStore.getState()
        const mainModel = state.sessions.find((item) => item.id === state.activeSessionId)?.model_id
        const session = await api.createSession(project.id, { title: '侧问', kind: 'side', modelId: mainModel ?? undefined })
        if (!live()) return
        sid = session.id
        setSideSessionId(sid)
      }
      setItems((prev) => [...prev, { id: nextId(), type: 'user', content: text }])
      let assistantId: string | null = null
      await streamChat(sid, text, 'side', [], {
        onToken: (token) => {
          if (!live()) return
          setItems((prev) => {
            const next = [...prev]
            const last = next[next.length - 1]
            if (assistantId && last?.type === 'assistant' && last.id === assistantId) {
              next[next.length - 1] = { ...last, content: last.content + token }
            } else {
              assistantId = nextId()
              next.push({ id: assistantId, type: 'assistant', content: token })
            }
            return next
          })
        },
        onToolStart: (name, toolInput) => {
          if (!live()) return
          assistantId = null
          setItems((prev) => [...prev, { id: nextId(), type: 'tool', name, input: toolInput, status: 'running' }])
        },
        onToolEnd: (name, output) => {
          if (!live()) return
          setItems((prev) => {
            const next = [...prev]
            for (let index = next.length - 1; index >= 0; index -= 1) {
              const item = next[index]
              if (item.type === 'tool' && item.name === name && item.status === 'running') {
                next[index] = { ...item, output, status: 'done' }
                break
              }
            }
            return next
          })
        },
        onError: (message) => {
          if (live()) setItems((prev) => [...prev, { id: nextId(), type: 'error', content: message }])
        },
        onDone: (payload) => {
          if (!live()) return
          setItems((prev) => [...settleItems(prev), {
            id: nextId(), type: 'turn_end', meta: {
              elapsed_ms: payload?.elapsed_ms ?? 0,
              changes: payload?.changes ?? { files: [], diff: '' },
              usage: payload?.usage
            }
          }])
        },
        onAborted: () => {
          if (live()) setItems(settleItems)
        }
      }, controller.signal, useAppStore.getState().activeSessionId ?? undefined)
    } catch (error) {
      if (live()) setItems((prev) => [...prev, { id: nextId(), type: 'error', content: (error as Error).message }])
    } finally {
      if (live()) {
        busy.current = false
        abortRef.current = null
        setStreaming(false)
        setStartedAt(null)
        setItems(settleItems)
      }
    }
  }

  const reset = (): void => {
    generation.current += 1
    abortRef.current?.abort()
    abortRef.current = null
    busy.current = false
    setStreaming(false)
    setStartedAt(null)
    setSideSessionId(null)
    setItems([])
    setInput('')
  }
  const stop = (): void => {
    const sid = useAppStore.getState().sideSessionId
    if (sid) void api.stopRun(sid).catch(() => undefined)
    abortRef.current?.abort()
  }
  const turns = useMemo(() => groupTurns(items), [items])
  const folded = expanded ? 0 : Math.max(0, turns.length - 60)
  const last = items[items.length - 1]

  return (
    <div className="right-body">
      <div className="kb-toolbar">
        <span style={{ flex: 1, fontSize: 11.5, color: 'var(--faint)', paddingLeft: 4 }}>独立上下文，不写入主对话</span>
        <button className="small-btn" onClick={reset} title="开启新的侧问"><Eraser size={12} /> 新侧问</button>
      </div>
      <div className="side-scroll" ref={scrollRef} onScroll={() => {
        const el = scrollRef.current
        if (el) stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80
      }}>
        {items.length === 0 && !streaming && <div className="panel-empty">快速提问，例如「林昭现在是什么境界」「上一章留下了哪些伏笔」</div>}
        {folded > 0 && <button className="small-btn" onClick={() => setExpanded(true)}>展开更早的 {folded} 轮</button>}
        {turns.slice(folded).map((turn, index, visible) => (
          <ConversationTurn key={turn.id} turn={turn} side live={streaming && index === visible.length - 1}
            isLast={index === visible.length - 1} startedAt={startedAt}
            onEdit={setInput} onRetry={turn.user ? () => void send(turn.user!.content) : undefined} onBring={setPendingComposer} />
        ))}
        {streaming && (!last || last.type === 'user') && <PendingBubble startedAt={startedAt} />}
      </div>
      <div className="side-composer">
        <div className="side-composer-box">
          <textarea ref={textareaRef} value={input} placeholder="侧问：查设定、查伏笔、查原文…"
            onChange={(event) => setInput(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
                event.preventDefault()
                void send()
              }
            }} />
          <div className="side-composer-actions">
            {streaming && <button className="stop-btn" onClick={stop} title="停止生成（已生成的内容会保留）"><Square size={11} fill="currentColor" /></button>}
            <button className="send-btn" onClick={() => void send()} disabled={!input.trim() || streaming} title="发送（Enter）"><ArrowUp size={15} /></button>
          </div>
        </div>
      </div>
    </div>
  )
}

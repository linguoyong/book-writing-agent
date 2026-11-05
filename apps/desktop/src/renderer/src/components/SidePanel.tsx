import { useEffect, useRef, useState } from 'react'
import { ArrowUp, CornerUpLeft, Eraser, Square } from 'lucide-react'
import { api, streamChat } from '../api'
import { useAppStore } from '../store'
import type { Message, TimelineItem } from '../types'
import Markdown from './Markdown'

let counter = 0
const nextId = (): string => `s${Date.now()}-${counter++}`

/** 流结束时把仍在执行中的工具收尾 */
const settleItems = (items: TimelineItem[]): TimelineItem[] =>
  items.map((item) =>
    item.type === 'tool' && item.status === 'running'
      ? { ...item, status: 'cancelled' as const }
      : item
  )

/** 把已落库的侧问消息还原成时间线（工具卡用 meta.tool_calls 重建） */
function toTimeline(messages: Message[]): TimelineItem[] {
  const items: TimelineItem[] = []
  for (const message of messages) {
    if (message.role === 'user') {
      items.push({ id: `h${message.id}`, type: 'user', content: message.content })
      continue
    }
    const calls = message.meta?.tool_calls ?? []
    calls.forEach((call, index) => {
      items.push({
        id: `h${message.id}-t${index}`,
        type: 'tool',
        name: call.name,
        input: call.input,
        status: 'done'
      })
    })
    if (message.content.trim()) {
      items.push({ id: `h${message.id}`, type: 'assistant', content: message.content })
    }
  }
  return items
}

export default function SidePanel(): React.JSX.Element {
  const project = useAppStore((state) => state.activeProject)
  const setPendingComposer = useAppStore((state) => state.setPendingComposer)
  const sessionId = useAppStore((state) => state.sideSessionId)
  const setSideSessionId = useAppStore((state) => state.setSideSessionId)

  const [items, setItems] = useState<TimelineItem[]>([])
  const [input, setInput] = useState('')
  const [streaming, setStreaming] = useState(false)
  const scrollRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const abortRef = useRef<AbortController | null>(null)

  useEffect(() => {
    let cancelled = false
    setInput('')
    const load = async (): Promise<void> => {
      const sid = useAppStore.getState().sideSessionId
      if (!sid) {
        setItems([])
        return
      }
      try {
        const messages = await api.messages(sid)
        if (!cancelled) setItems(toTimeline(messages))
      } catch {
        if (!cancelled) setItems([])
      }
    }
    void load()
    return () => {
      cancelled = true
    }
  }, [project?.id])

  useEffect(() => {
    const element = scrollRef.current
    if (element) element.scrollTop = element.scrollHeight
  }, [items])

  const send = async (): Promise<void> => {
    if (!project || !input.trim() || streaming) return
    let sid = sessionId
    if (!sid) {
      try {
        const state = useAppStore.getState()
        const mainModel = state.sessions.find(
          (item) => item.id === state.activeSessionId
        )?.model_id
        const session = await api.createSession(project.id, {
          title: '侧问',
          kind: 'side',
          modelId: mainModel ?? undefined
        })
        sid = session.id
        setSideSessionId(sid)
      } catch (error) {
        setItems((prev) => [
          ...prev,
          { id: nextId(), type: 'error', content: (error as Error).message }
        ])
        return
      }
    }

    const text = input
    setInput('')
    setStreaming(true)
    setItems((prev) => [...prev, { id: nextId(), type: 'user', content: text }])

    let assistantId: string | null = null

    const controller = new AbortController()
    abortRef.current = controller
    await streamChat(sid, text, 'side', [], {
      onToken: (token) => {
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
        assistantId = null
        setItems((prev) => [
          ...prev,
          { id: nextId(), type: 'tool', name, input: toolInput, status: 'running' }
        ])
      },
      onToolEnd: (name, output) => {
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
      onError: (message) =>
        setItems((prev) => [...prev, { id: nextId(), type: 'error', content: message }]),
      onDone: () => {
        abortRef.current = null
        setStreaming(false)
        setItems(settleItems)
      },
      onAborted: () => {
        abortRef.current = null
        setStreaming(false)
        setItems(settleItems)
      }
    }, controller.signal, useAppStore.getState().activeSessionId ?? undefined)
  }

  return (
    <div className="right-body">
      <div className="kb-toolbar">
        <span style={{ flex: 1, fontSize: 11.5, color: 'var(--faint)', paddingLeft: 4 }}>
          独立上下文，不写入主对话
        </span>
        <button
          className="small-btn"
          onClick={() => {
            abortRef.current?.abort()
            abortRef.current = null
            setStreaming(false)
            setSideSessionId(null)
            setItems([])
          }}
          title="开启新的侧问"
        >
          <Eraser size={12} />
          新侧问
        </button>
      </div>

      <div className="side-scroll" ref={scrollRef}>
        {items.length === 0 && (
          <div className="panel-empty">
            快速提问，例如「林昭现在是什么境界」「上一章留下了哪些伏笔」
          </div>
        )}
        {items.map((item, index) => {
          if (item.type === 'tool') {
            return (
              <details key={item.id} className="tool-card" style={{ margin: '0 0 10px 0' }}>
                <summary>
                  <span className="tool-name">{item.name}</span>
                  <span className={`status ${item.status === 'running' ? 'running' : ''}`}>
                    {item.status === 'running'
                      ? '检索中'
                      : item.status === 'cancelled'
                        ? '已停止'
                        : '完成'}
                  </span>
                </summary>
                <div className="tool-body">
                  {item.input}
                  {item.output ? `\n\n${item.output}` : ''}
                </div>
              </details>
            )
          }
          if (item.type === 'error') {
            return (
              <div key={item.id} className="side-msg error">
                {item.content}
              </div>
            )
          }
          if (item.type === 'user') {
            return (
              <div key={item.id} className="msg user side-msg-row">
                <div className="user-stack">
                  <div className="bubble">{item.content}</div>
                </div>
              </div>
            )
          }
          if (item.type !== 'assistant') return null
          return (
            <div key={item.id} className="msg assistant side-msg-row">
              <div className="avatar">墨</div>
              <div className="assistant-body">
                <div className="content md-content">
                  <Markdown content={item.content} />
                  {streaming && index === items.length - 1 ? <span className="cursor">▌</span> : null}
                </div>
                {index === items.length - 1 && item.content.trim() && !streaming && (
                  <button
                    className="small-btn"
                    style={{ marginTop: 6 }}
                    onClick={() => setPendingComposer(item.content)}
                  >
                    <CornerUpLeft size={12} />
                    带入主对话
                  </button>
                )}
              </div>
            </div>
          )
        })}
      </div>

      <div className="side-composer">
        <div className="side-composer-box">
          <textarea
            ref={textareaRef}
            value={input}
            placeholder="侧问：查设定、查伏笔、查原文…"
            onChange={(event) => setInput(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
                event.preventDefault()
                void send()
              }
            }}
          />
          <div className="side-composer-actions">
          {streaming && (
            <button
              className="stop-btn"
              onClick={() => abortRef.current?.abort()}
              title="停止生成（已生成的内容会保留）"
            >
              <Square size={11} fill="currentColor" />
            </button>
          )}
            <button
              className="send-btn"
              onClick={() => void send()}
              disabled={!input.trim() || streaming}
              title="发送（Enter）"
            >
              <ArrowUp size={15} />
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

import { useEffect, useRef, useState } from 'react'
import { ArrowUp, CornerUpLeft, Eraser } from 'lucide-react'
import { api, streamChat } from '../api'
import { useAppStore } from '../store'
import type { TimelineItem } from '../types'

let counter = 0
const nextId = (): string => `s${Date.now()}-${counter++}`

export default function SidePanel(): React.JSX.Element {
  const project = useAppStore((state) => state.activeProject)
  const setPendingComposer = useAppStore((state) => state.setPendingComposer)

  const [sessionId, setSessionId] = useState<string | null>(null)
  const [items, setItems] = useState<TimelineItem[]>([])
  const [input, setInput] = useState('')
  const [streaming, setStreaming] = useState(false)
  const scrollRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    setSessionId(null)
    setItems([])
    setInput('')
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
        const session = await api.createSession(project.id, '侧问', 'side')
        sid = session.id
        setSessionId(sid)
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

    await streamChat(sid, text, '', 'side', {
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
      onDone: () => setStreaming(false)
    })
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
            setSessionId(null)
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
                    {item.status === 'running' ? '检索中' : '完成'}
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
              <div key={item.id} className="side-msg user">
                <span className="side-bubble">{item.content}</span>
              </div>
            )
          }
          return (
            <div key={item.id} className="side-msg assistant">
              <div>
                {item.content}
                {streaming && index === items.length - 1 ? '▌' : ''}
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
          )
        })}
      </div>

      <div className="side-composer">
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
        <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 6 }}>
          <button className="send-btn" onClick={() => void send()} disabled={!input.trim() || streaming}>
            <ArrowUp size={15} />
          </button>
        </div>
      </div>
    </div>
  )
}

import { useEffect, useRef, useState } from 'react'
import { AlertTriangle, ArrowUp, Wrench } from 'lucide-react'
import { useAppStore } from '../store'
import type { TimelineItem } from '../types'

const SUGGESTIONS = [
  '根据大纲续写下一章',
  '检查本章与角色设定是否冲突',
  '梳理当前主要角色的状态',
  '检索与「宗门大比」相关的原文'
]

export default function ChatPane(): React.JSX.Element {
  const timeline = useAppStore((state) => state.timeline)
  const streaming = useAppStore((state) => state.streaming)
  const activeSessionId = useAppStore((state) => state.activeSessionId)
  const sendMessage = useAppStore((state) => state.sendMessage)

  const [input, setInput] = useState('')
  const scrollRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const pendingComposer = useAppStore((state) => state.pendingComposer)
  const setPendingComposer = useAppStore((state) => state.setPendingComposer)

  useEffect(() => {
    const element = scrollRef.current
    if (element) element.scrollTop = element.scrollHeight
  }, [timeline])

  useEffect(() => {
    if (!pendingComposer) return
    setInput(pendingComposer)
    setPendingComposer(null)
    textareaRef.current?.focus()
  }, [pendingComposer, setPendingComposer])

  useEffect(() => {
    setInput('')
    if (textareaRef.current) textareaRef.current.style.height = 'auto'
  }, [activeSessionId])

  const submit = (): void => {
    if (!input.trim() || streaming) return
    void sendMessage(input)
    setInput('')
    if (textareaRef.current) textareaRef.current.style.height = 'auto'
  }

  const handleInput = (event: React.ChangeEvent<HTMLTextAreaElement>): void => {
    setInput(event.target.value)
    const element = event.target
    element.style.height = 'auto'
    element.style.height = `${Math.min(element.scrollHeight, 180)}px`
  }

  return (
    <section className="chat-pane">
      <div className="chat-header">
        <span>{activeSessionId ? '对话' : '未选择会话'}</span>
        <span style={{ marginLeft: 'auto', fontSize: 11, color: streaming ? 'var(--accent)' : 'var(--faint)' }}>
          {streaming ? '生成中…' : '就绪'}
        </span>
      </div>

      <div className="chat-scroll" ref={scrollRef}>
        {timeline.length === 0 ? (
          <div className="chat-empty">
            <div className="big">开始你的第一章</div>
            <div style={{ fontSize: 12 }}>写正文、查设定、改知识库，都会落到书稿文件里</div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, justifyContent: 'center', marginTop: 6 }}>
              {SUGGESTIONS.map((text) => (
                <button key={text} className="expert-chip" onClick={() => setInput(text)}>
                  {text}
                </button>
              ))}
            </div>
          </div>
        ) : (
          timeline.map((item, index) => (
            <TimelineRow
              key={item.id}
              item={item}
              streaming={streaming && index === timeline.length - 1}
            />
          ))
        )}
      </div>

      <div className="composer">
        <div className="composer-box">
          <textarea
            ref={textareaRef}
            value={input}
            placeholder="描述你想写的内容，或向 Agent 提问…"
            onChange={handleInput}
            onKeyDown={(event) => {
              if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
                event.preventDefault()
                submit()
              }
            }}
          />
          <div className="composer-actions">
            <span className="composer-hint">Enter 发送 · Shift+Enter 换行</span>
            <button className="send-btn" onClick={submit} disabled={!input.trim() || streaming}>
              <ArrowUp size={15} />
            </button>
          </div>
        </div>
      </div>
    </section>
  )
}

function TimelineRow({
  item,
  streaming
}: {
  item: TimelineItem
  streaming: boolean
}): React.JSX.Element {
  if (item.type === 'tool') {
    return (
      <details className="tool-card">
        <summary>
          <Wrench size={12} />
          <span className="tool-name">{item.name}</span>
          <span className={`status ${item.status === 'running' ? 'running' : ''}`}>
            {item.status === 'running' ? '执行中' : '完成'}
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
      <div className="error-banner" style={{ margin: '0 0 14px 34px' }}>
        <AlertTriangle size={13} />
        <span style={{ flex: 1 }}>{item.content}</span>
      </div>
    )
  }

  if (item.type === 'user') {
    return (
      <div className="msg user">
        <div className="bubble">{item.content}</div>
      </div>
    )
  }

  return (
    <div className="msg assistant">
      <div className="avatar">墨</div>
      <div className={`content ${streaming ? 'streaming' : ''}`}>{item.content}</div>
    </div>
  )
}

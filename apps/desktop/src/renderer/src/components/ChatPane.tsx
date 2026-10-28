import { useEffect, useRef, useState } from 'react'
import { AlertTriangle, ArrowUp, ChevronDown, Sparkles, Wrench } from 'lucide-react'
import { api } from '../api'
import { useAppStore } from '../store'
import type { ReferenceItem, TimelineItem } from '../types'
import ApprovalCard from './ApprovalCard'

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
  const currentExpertId = useAppStore((state) => state.currentExpertId)
  const experts = useAppStore((state) => state.experts)
  const builder = useAppStore((state) => state.builder)
  const setBuilder = useAppStore((state) => state.setBuilder)
  const setView = useAppStore((state) => state.setView)

  const [input, setInput] = useState('')
  const scrollRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const pendingComposer = useAppStore((state) => state.pendingComposer)
  const setPendingComposer = useAppStore((state) => state.setPendingComposer)

  const expert = experts.find((item) => item.id === currentExpertId)
  const project = useAppStore((state) => state.activeProject)
  const approval = useAppStore((state) => state.approval)
  const resolveApproval = useAppStore((state) => state.resolveApproval)
  const references = useAppStore((state) => state.references)
  const addReference = useAppStore((state) => state.addReference)
  const removeReference = useAppStore((state) => state.removeReference)

  const [candidates, setCandidates] = useState<ReferenceItem[]>([])
  const [refOpen, setRefOpen] = useState(false)
  const refTimer = useRef<number | null>(null)

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
    if (refOpen && candidates.length) {
      selectReference(candidates[0])
      return
    }
    if (!input.trim() || streaming || approval) return
    void sendMessage(input)
    setInput('')
    if (textareaRef.current) textareaRef.current.style.height = 'auto'
  }

  const selectReference = (item: ReferenceItem): void => {
    const match = /@([^\s@]*)$/.exec(input)
    setInput(match ? input.slice(0, match.index) : input)
    addReference(item)
    setRefOpen(false)
    setCandidates([])
    textareaRef.current?.focus()
  }

  const handleInput = (event: React.ChangeEvent<HTMLTextAreaElement>): void => {
    const value = event.target.value
    setInput(value)
    const element = event.target
    element.style.height = 'auto'
    element.style.height = `${Math.min(element.scrollHeight, 180)}px`

    const match = /@([^\s@]*)$/.exec(value)
    if (!match || !project) {
      setRefOpen(false)
      return
    }
    setRefOpen(true)
    if (refTimer.current) window.clearTimeout(refTimer.current)
    refTimer.current = window.setTimeout(async () => {
      try {
        const result = await api.referenceCandidates(project.id, match[1])
        setCandidates(result.items)
      } catch {
        setCandidates([])
      }
    }, 160)
  }

  return (
    <section className="chat-pane">
      <div className="chat-header">
        <span>{activeSessionId ? '对话' : '未选择会话'}</span>
        {builder && (
          <span className="builder-chip">
            <Sparkles size={11} />
            创建{builder === 'expert' ? '专家' : '技能'}中
            <button
              onClick={() => {
                setBuilder(null)
                setView(builder === 'expert' ? 'experts' : 'skills')
              }}
            >
              结束
            </button>
          </span>
        )}
        <span
          style={{
            marginLeft: 'auto',
            fontSize: 11,
            color: streaming ? 'var(--accent)' : 'var(--faint)'
          }}
        >
          {streaming ? '生成中…' : '就绪'}
        </span>
      </div>

      <div className="chat-scroll" ref={scrollRef}>
        <div className="chat-inner">
          {timeline.length === 0 ? (
            <div className="chat-empty">
              <div className="big">
                {builder ? `创建${builder === 'expert' ? '专家' : '技能'}` : '开始你的第一章'}
              </div>
              <div style={{ fontSize: 12 }}>
                {builder
                  ? '描述你想要的定位、风格或流程，Agent 会逐步确认并写入文件'
                  : '写正文、查设定、改知识库，都会落到书稿文件里'}
              </div>
              {!builder && (
                <div
                  style={{
                    display: 'flex',
                    flexWrap: 'wrap',
                    gap: 6,
                    justifyContent: 'center',
                    marginTop: 6
                  }}
                >
                  {SUGGESTIONS.map((text) => (
                    <button key={text} className="expert-chip" onClick={() => setInput(text)}>
                      {text}
                    </button>
                  ))}
                </div>
              )}
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
      </div>

      {approval && (
        <div className="approval-wrap">
          <ApprovalCard
            approval={approval}
            streaming={streaming}
            onSubmit={(decisions) => void resolveApproval(decisions)}
          />
        </div>
      )}

      <div className="composer">
        <div className="composer-inner">
          {refOpen && (
            <div className="ref-pop">
              {candidates.length === 0 && <div className="ref-empty">没有匹配的文件、角色或章节</div>}
              {candidates.map((item) => (
                <button
                  key={`${item.type}-${item.path}-${item.id ?? ''}`}
                  className="ref-item"
                  onMouseDown={(event) => {
                    event.preventDefault()
                    selectReference(item)
                  }}
                >
                  <span className="ref-hint">{item.hint}</span>
                  <span className="ref-name">{item.name}</span>
                  <span className="ref-path">{item.path}</span>
                </button>
              ))}
            </div>
          )}
          <div className="composer-box">
            {references.length > 0 && (
              <div className="ref-bar">
                {references.map((ref, index) => (
                  <span className="ref-chip" key={`${ref.type}-${ref.path}-${index}`}>
                    <span className="ref-hint">{ref.hint}</span>
                    {ref.name}
                    <button onClick={() => removeReference(index)} title="移除引用">
                      ×
                    </button>
                  </span>
                ))}
              </div>
            )}
            <textarea
              ref={textareaRef}
              value={input}
              placeholder="描述你想写的内容，或向 Agent 提问；输入 @ 引用文件、角色、章节…"
              onChange={handleInput}
              onKeyDown={(event) => {
                if (event.key === 'Escape') {
                  setRefOpen(false)
                  return
                }
                if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
                  event.preventDefault()
                  submit()
                }
              }}
            />
            <div className="composer-actions">
              <button className="expert-selector" onClick={() => setView('experts')}>
                <Sparkles size={12} />
                专家 · {expert?.name ?? '通用'}
                <ChevronDown size={11} />
              </button>
              <span className="composer-hint">
                {approval ? '先处理待审批的写入' : 'Enter 发送 · Shift+Enter 换行 · @ 引用'}
              </span>
              <button
                className="send-btn"
                onClick={submit}
                disabled={!input.trim() || streaming || !!approval}
              >
                <ArrowUp size={15} />
              </button>
            </div>
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

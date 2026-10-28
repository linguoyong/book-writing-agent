import { useEffect, useRef, useState } from 'react'
import {
  AlertTriangle,
  ArrowUp,
  Check,
  ChevronDown,
  ChevronRight,
  FileDiff,
  Loader2,
  MessageSquareReply,
  ShieldCheck,
  Sparkles,
  Wrench
} from 'lucide-react'
import { api } from '../api'
import { useAppStore } from '../store'
import type { ReferenceItem, TimelineItem, TurnMeta } from '../types'
import ApprovalCard from './ApprovalCard'
import Markdown from './Markdown'

const SUGGESTIONS = [
  '根据大纲续写下一章',
  '检查本章与角色设定是否冲突',
  '梳理当前主要角色的状态',
  '检索与「宗门大比」相关的原文'
]

type UserItem = Extract<TimelineItem, { type: 'user' }>
type AssistantItem = Extract<TimelineItem, { type: 'assistant' }>

interface TurnView {
  id: string
  user?: UserItem
  process: TimelineItem[]
  conclusion?: AssistantItem
  meta?: TurnMeta
}

export default function ChatPane(): React.JSX.Element {
  const timeline = useAppStore((state) => state.timeline)
  const streaming = useAppStore((state) => state.streaming)
  const streamStartedAt = useAppStore((state) => state.streamStartedAt)
  const activeSessionId = useAppStore((state) => state.activeSessionId)
  const sendMessage = useAppStore((state) => state.sendMessage)
  const steerMessage = useAppStore((state) => state.steerMessage)
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
    if (!input.trim() || approval) return
    if (streaming) {
      void steerMessage(input)
      setInput('')
      if (textareaRef.current) textareaRef.current.style.height = 'auto'
      return
    }
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

  const turns = groupTurns(timeline)

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
          {streaming ? '处理中…' : '就绪'}
        </span>
      </div>

      <div className="chat-scroll" ref={scrollRef}>
        <div className="chat-inner">
          {turns.length === 0 ? (
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
            turns.map((turn, index) => (
              <TurnBlock
                key={turn.id}
                turn={turn}
                live={streaming && index === turns.length - 1}
                startedAt={streamStartedAt}
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
              <PermissionPicker />
              <span className="composer-hint">
                {approval
                  ? '先处理待审批的写入'
                  : streaming
                    ? '执行中 · 发送将作为引导，不打断当前任务'
                    : 'Enter 发送 · Shift+Enter 换行 · @ 引用'}
              </span>
              <button
                className="send-btn"
                onClick={submit}
                disabled={!input.trim() || !!approval}
                title={streaming ? '发送引导（不打断当前任务）' : '发送'}
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

function TurnBlock({
  turn,
  live,
  startedAt
}: {
  turn: TurnView
  live: boolean
  startedAt: number | null
}): React.JSX.Element {
  const showTurnDiff = useAppStore((state) => state.showTurnDiff)
  const [now, setNow] = useState(Date.now())

  useEffect(() => {
    if (!live) return
    const timer = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [live])

  const running = live && !turn.meta
  const elapsed = turn.meta?.elapsed_ms ?? (running && startedAt ? now - startedAt : 0)
  const steps = turn.process.filter((item) => item.type === 'tool')
  const files = turn.meta?.changes.files ?? []

  return (
    <div className="turn">
      {turn.user && (
        <div className="msg user">
          <div className="user-stack">
            {turn.user.references && turn.user.references.length > 0 && (
              <div className="msg-refs">
                {turn.user.references.map((ref, index) => (
                  <span
                    className="msg-ref-chip"
                    key={`${ref.type}-${ref.path}-${index}`}
                    title={ref.path}
                  >
                    <span className="ref-hint">{ref.hint}</span>
                    {ref.name}
                  </span>
                ))}
              </div>
            )}
            <div className="bubble">{turn.user.content}</div>
          </div>
        </div>
      )}

      {turn.process.length > 0 &&
        (running ? (
          <div className="turn-live">
            <div className="turn-live-head">
              <Loader2 size={12} className="spin" />
              处理中 · {formatDuration(elapsed)}
            </div>
            {turn.process.map((item) => (
              <StepRow key={item.id} item={item} />
            ))}
          </div>
        ) : (
          <details className="turn-fold">
            <summary>
              <Check size={12} />
              <span>已完成</span>
              {turn.meta && (
                <>
                  <span className="turn-dot">·</span>
                  <span>{formatDuration(elapsed)}</span>
                </>
              )}
              {steps.length > 0 && (
                <>
                  <span className="turn-dot">·</span>
                  <span>{steps.length} 步</span>
                </>
              )}
              <ChevronRight size={12} className="turn-chev" />
            </summary>
            <div className="turn-live">
              {turn.process.map((item) => (
                <StepRow key={item.id} item={item} />
              ))}
            </div>
          </details>
        ))}

      {turn.conclusion && (
        <div className="msg assistant">
          <div className="avatar">墨</div>
          <div className={`content md-content ${live ? 'streaming' : ''}`}>
            <Markdown content={turn.conclusion.content} />
          </div>
        </div>
      )}

      {files.length > 0 && turn.meta && (
        <div className="turn-changes">
          <button onClick={() => showTurnDiff(turn.meta!.changes)}>
            <FileDiff size={12} />
            查看变更 · {files.length} 个文件
          </button>
          <span className="turn-files">
            {files.slice(0, 3).join('、')}
            {files.length > 3 ? '…' : ''}
          </span>
        </div>
      )}
    </div>
  )
}

function StepRow({ item }: { item: TimelineItem }): React.JSX.Element | null {
  if (item.type === 'tool') {
    return (
      <details className="step-tool">
        <summary>
          <Wrench size={11} />
          <span className="step-name">{item.name}</span>
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
  if (item.type === 'user') {
    return (
      <div className="step-steer">
        <MessageSquareReply size={12} />
        <div>
          <span className="step-steer-label">引导</span>
          {item.content}
        </div>
      </div>
    )
  }
  if (item.type === 'assistant') {
    return <div className="step-text">{item.content}</div>
  }
  if (item.type === 'error') {
    return (
      <div className="step-error">
        <AlertTriangle size={12} />
        <span>{item.content}</span>
      </div>
    )
  }
  return null
}

function PermissionPicker(): React.JSX.Element {
  const mode = useAppStore((state) => state.permissionMode)
  const setPermissionMode = useAppStore((state) => state.setPermissionMode)
  const [open, setOpen] = useState(false)
  const auto = mode === 'auto'

  return (
    <div className="perm-wrap">
      {open && (
        <div className="perm-pop" role="menu">
          <div className="perm-pop-title">应如何批准操作？</div>
          <button
            className={`perm-option ${mode === 'ask' ? 'active' : ''}`}
            onClick={() => {
              setPermissionMode('ask')
              setOpen(false)
            }}
          >
            <ShieldCheck size={14} />
            <div className="perm-text">
              <strong>请求批准</strong>
              <span>编辑文件、写知识库前先询问</span>
            </div>
            {mode === 'ask' && <Check size={13} />}
          </button>
          <button
            className={`perm-option ${auto ? 'active warn' : ''}`}
            onClick={() => {
              setPermissionMode('auto')
              setOpen(false)
            }}
          >
            <AlertTriangle size={14} />
            <div className="perm-text">
              <strong>完全访问</strong>
              <span>不再询问，直接执行；敏感路径仍会被拒绝</span>
            </div>
            {auto && <Check size={13} />}
          </button>
        </div>
      )}
      <button
        className={`perm-trigger ${auto ? 'warn' : ''}`}
        onClick={() => setOpen((value) => !value)}
        title="选择权限模式"
      >
        {auto ? <AlertTriangle size={12} /> : <ShieldCheck size={12} />}
        {auto ? '完全访问' : '请求批准'}
        <ChevronDown size={10} />
      </button>
    </div>
  )
}

function groupTurns(items: TimelineItem[]): TurnView[] {
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
    for (let index = turn.process.length - 1; index >= 0; index -= 1) {
      const item = turn.process[index]
      if (item.type === 'assistant' && item.content.trim()) {
        turn.conclusion = item
        turn.process.splice(index, 1)
        break
      }
    }
  }
  return turns
}

function formatDuration(ms: number): string {
  if (!ms || ms < 1000) return '1 秒内'
  const seconds = Math.round(ms / 1000)
  if (seconds < 60) return `${seconds} 秒`
  const minutes = Math.floor(seconds / 60)
  const rest = seconds % 60
  return rest ? `${minutes} 分 ${rest} 秒` : `${minutes} 分`
}

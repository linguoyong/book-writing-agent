import { useEffect, useMemo, useRef, useState } from 'react'
import {
  AlertTriangle,
  ArrowUp,
  Check,
  ChevronDown,
  ChevronRight,
  Cpu,
  FileDiff,
  Folder,
  FolderOpen,
  Loader2,
  Plus,
  RotateCcw,
  Search,
  ShieldCheck,
  Sparkles,
  Square
} from 'lucide-react'
import { api } from '../api'
import { useAppStore } from '../store'
import type { ReferenceItem } from '../types'
import ApprovalCard from './ApprovalCard'
import { ConversationTurn, PendingBubble } from './ConversationTurn'
import { groupTurns } from './conversation'
import MessageNav from './MessageNav'

const SUGGESTIONS = [
  '根据大纲续写下一章',
  '检查本章与角色设定是否冲突',
  '梳理当前主要角色的状态',
  '检索与「宗门大比」相关的原文'
]

// 长会话只挂载最近这些轮，更早的折叠成一个「展开」按钮。
// 500 轮全挂上去时，每个 token 的 re-render 都要过一遍 500 个块的布局，
// 折叠后 DOM 与 diff 成本都是常数级。
const VISIBLE_TURNS = 60

export default function ChatPane(): React.JSX.Element {
  const timeline = useAppStore((state) => state.timeline)
  const streaming = useAppStore((state) => state.streaming)
  const streamStartedAt = useAppStore((state) => state.streamStartedAt)
  const activeSessionId = useAppStore((state) => state.activeSessionId)
  const sendMessage = useAppStore((state) => state.sendMessage)
  const steerMessage = useAppStore((state) => state.steerMessage)
  const stopStreaming = useAppStore((state) => state.stopStreaming)
  const builder = useAppStore((state) => state.builder)
  const setBuilder = useAppStore((state) => state.setBuilder)
  const setView = useAppStore((state) => state.setView)

  const [input, setInput] = useState('')
  const scrollRef = useRef<HTMLDivElement>(null)
  // 用户往上翻时不要再自动跟随；发消息 / 换会话时重新贴底
  const stickRef = useRef(true)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const pendingComposer = useAppStore((state) => state.pendingComposer)
  const setPendingComposer = useAppStore((state) => state.setPendingComposer)

  const project = useAppStore((state) => state.activeProject)
  const approval = useAppStore((state) => state.approval)
  const resolveApproval = useAppStore((state) => state.resolveApproval)
  const references = useAppStore((state) => state.references)
  const addReference = useAppStore((state) => state.addReference)
  const removeReference = useAppStore((state) => state.removeReference)
  const showTurnDiff = useAppStore((state) => state.showTurnDiff)

  const [candidates, setCandidates] = useState<ReferenceItem[]>([])
  const [refOpen, setRefOpen] = useState(false)
  const [showAllTurns, setShowAllTurns] = useState(false)
  const refTimer = useRef<number | null>(null)

  useEffect(() => {
    const element = scrollRef.current
    if (!element) return
    const nearBottom =
      element.scrollHeight - element.scrollTop - element.clientHeight < 80
    if (!stickRef.current && !nearBottom) return
    stickRef.current = true
    element.scrollTop = element.scrollHeight
  }, [timeline])

  useEffect(() => {
    if (!pendingComposer) return
    setInput(pendingComposer)
    setPendingComposer(null)
    textareaRef.current?.focus()
  }, [pendingComposer, setPendingComposer])

  useEffect(() => {
    setInput('')
    stickRef.current = true
    // 换会话时回到折叠状态：另一个会话的前 400 轮没必要一起挂上来
    setShowAllTurns(false)
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

  const turns = useMemo(() => groupTurns(timeline), [timeline])
  // 模型首字还没出来：先给一个「正在思考」，否则界面上什么都没有，像卡住了
  const lastItem = timeline[timeline.length - 1]
  const waitingFirstToken = !lastItem || lastItem.type === 'user'
  // 长会话只挂载最近 VISIBLE_TURNS 轮，更早的折叠起来
  const folded = showAllTurns ? 0 : Math.max(0, turns.length - VISIBLE_TURNS)
  const visibleTurns = folded > 0 ? turns.slice(folded) : turns

  const jumpToTurn = (id: string): void => {
    const node = document.getElementById(`turn-${id}`)
    if (node) {
      node.scrollIntoView({ block: 'start', behavior: 'smooth' })
      return
    }
    // 目标还在折叠区里：先展开，等这一帧挂上节点再滚
    setShowAllTurns(true)
    requestAnimationFrame(() => {
      document.getElementById(`turn-${id}`)?.scrollIntoView({ block: 'start' })
    })
  }
  const lastChange = useMemo(() => {
    for (let index = turns.length - 1; index >= 0; index -= 1) {
      if ((turns[index].meta?.changes.files.length ?? 0) > 0) return turns[index]
    }
    return undefined
  }, [turns])
  // 只依赖轮次数与最后一条用户消息：流式 token 不该重建导航刻度，
  // 否则 MessageNav 的 scroll effect 每个 token 都会全量 measure 一次。
  const navPoints = useMemo(
    () =>
      turns
        .filter((turn) => turn.user && !turn.user.steering && turn.user.content.trim())
        .map((turn) => ({
          id: turn.id,
          label: turn.user!.content.replace(/\s+/g, ' ').slice(0, 48)
        })),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [turns.length, turns[turns.length - 1]?.user?.content]
  )

  return (
    <section className="chat-pane">
      <div className="chat-header">
        <span>{activeSessionId ? '对话' : project ? '新对话' : '未选择会话'}</span>
        {streaming && (
          <span className="run-badge" title="这一轮在服务端继续跑，切走不会中断">
            <Loader2 size={11} className="spin" />
            运行中
          </span>
        )}
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

      <div className="chat-stage">
        <div
          className="chat-scroll"
          ref={scrollRef}
          onScroll={(event) => {
            const element = event.currentTarget
            stickRef.current =
              element.scrollHeight - element.scrollTop - element.clientHeight < 80
          }}
        >
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
            <>
              {folded > 0 && (
                <button className="turn-fold-more" onClick={() => setShowAllTurns(true)}>
                  上方还有 {folded} 轮更早的对话
                  <span>点此展开</span>
                </button>
              )}
              {visibleTurns.map((turn, index) => (
                <ConversationTurn
                  key={turn.id}
                  turn={turn}
                  live={streaming && folded + index === turns.length - 1}
                  isLast={folded + index === turns.length - 1}
                  startedAt={streamStartedAt}
                />
              ))}
              {streaming && waitingFirstToken && <PendingBubble startedAt={streamStartedAt} />}
            </>
          )}
          </div>
        </div>
        <MessageNav points={navPoints} scrollRef={scrollRef} onJump={jumpToTurn} />
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

      {lastChange && (
        <div className="composer-turn-changes">
          <div className="composer-inner">
            <button
              onClick={() => showTurnDiff(lastChange.meta!.changes)}
              title="在右侧「变更」页查看本轮改动的文件"
            >
              <FileDiff size={12} />
              <span>本轮变更 · {lastChange.meta!.changes.files.length} 个文件</span>
              <ChevronRight size={12} className="turn-chev" />
            </button>
          </div>
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
              <WorkspacePicker />
              <ExpertPicker />
              <PermissionPicker />
              <ModelPicker />
              <span className="composer-hint">
                {approval ? '先处理待审批的写入' : ''}
              </span>
              {streaming && (
                <button
                  className="stop-btn"
                  onClick={stopStreaming}
                  title="停止生成（已生成的内容会保留）"
                >
                  <Square size={11} fill="currentColor" />
                </button>
              )}
              <button
                className="send-btn"
                onClick={submit}
                disabled={!input.trim() || !!approval}
                title={
                  streaming
                    ? '发送引导（Enter）· 不打断当前任务'
                    : '发送（Enter）· Shift+Enter 换行 · @ 引用'
                }
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

/** 输入区左下角的空间选择：切空间、新建空间、把本地文件夹当空间打开。 */
function WorkspacePicker(): React.JSX.Element {
  const projects = useAppStore((state) => state.projects)
  const activeProject = useAppStore((state) => state.activeProject)
  const selectProject = useAppStore((state) => state.selectProject)
  const openProject = useAppStore((state) => state.openProject)
  const setProjectModalOpen = useAppStore((state) => state.setProjectModalOpen)
  const showToast = useAppStore((state) => state.showToast)

  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const wrapRef = useDismiss(open, setOpen)

  const keyword = query.trim().toLowerCase()
  const visible = keyword
    ? projects.filter(
        (project) =>
          project.name.toLowerCase().includes(keyword) ||
          project.path.toLowerCase().includes(keyword)
      )
    : projects

  const pick = (projectId: string): void => {
    setOpen(false)
    setQuery('')
    if (projectId === activeProject?.id) return
    // draft：切过去停在草稿态，别顺手打开上一个会话
    void selectProject(projectId, { draft: true })
  }

  const openFolder = async (): Promise<void> => {
    setOpen(false)
    setQuery('')
    const picked = await window.desktop?.pickDirectory?.(activeProject?.path)
    if (!picked) return
    try {
      await openProject(picked, { draft: true })
    } catch (error) {
      showToast((error as Error).message)
    }
  }

  return (
    <div className="workspace-wrap" ref={wrapRef}>
      {open && (
        <div className="workspace-pop">
          <div className="workspace-search">
            <Search size={12} />
            <input
              autoFocus
              value={query}
              placeholder="搜索工作空间"
              onChange={(event) => setQuery(event.target.value)}
            />
          </div>
          <div className="workspace-list">
            {visible.map((project) => (
              <button
                key={project.id}
                className={`workspace-option ${
                  project.id === activeProject?.id ? 'active' : ''
                }`}
                onClick={() => pick(project.id)}
                title={project.path}
              >
                <Folder size={13} />
                <span className="workspace-option-name">{project.name}</span>
                {project.id === activeProject?.id && <Check size={12} />}
              </button>
            ))}
            {visible.length === 0 && (
              <div className="panel-empty">
                {projects.length === 0 ? '还没有空间' : '没有匹配的空间'}
              </div>
            )}
          </div>
          <div className="workspace-actions">
            <button
              className="workspace-action"
              onClick={() => {
                setOpen(false)
                setProjectModalOpen(true)
              }}
            >
              <Plus size={13} />
              新建工作空间
            </button>
            <button className="workspace-action" onClick={() => void openFolder()}>
              <FolderOpen size={13} />
              打开本地文件夹
            </button>
          </div>
        </div>
      )}
      <button
        className="workspace-chip"
        onClick={() => setOpen((value) => !value)}
        title="选择工作空间：切空间、新建空间，或把本地文件夹当空间打开"
      >
        <Folder size={12} />
        <span className="workspace-chip-name">{activeProject?.name ?? '选择工作空间'}</span>
        <ChevronDown size={12} />
      </button>
    </div>
  )
}

/** 点击面板外部或按 Esc 关闭弹层。
 *
 * 原来用一层 `position: fixed` 的遮罩，但 `.composer-box` 设了 `container-type`，
 * 会建立包含块，遮罩只能盖住输入框本身，点别处关不掉。
 */
function useDismiss(
  open: boolean,
  setOpen: (open: boolean) => void
): React.RefObject<HTMLDivElement | null> {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    const onDown = (event: MouseEvent): void => {
      if (ref.current && !ref.current.contains(event.target as Node)) setOpen(false)
    }
    const onKey = (event: KeyboardEvent): void => {
      if (event.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [open, setOpen])
  return ref
}

function PermissionPicker(): React.JSX.Element {
  const mode = useAppStore((state) => state.permissionMode)
  const setPermissionMode = useAppStore((state) => state.setPermissionMode)
  const [open, setOpen] = useState(false)
  const wrapRef = useDismiss(open, setOpen)
  const auto = mode === 'auto'

  return (
    <div className="perm-wrap" ref={wrapRef}>
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
        <span className="perm-label">{auto ? '完全访问' : '请求批准'}</span>
        <ChevronDown size={10} className="chev" />
      </button>
    </div>
  )
}

function middleEllipsis(text: string, head = 13, tail = 5): string {
  if (text.length <= head + tail + 1) return text
  return `${text.slice(0, head)}…${text.slice(-tail)}`
}

function ExpertPicker(): React.JSX.Element {
  const experts = useAppStore((state) => state.experts)
  const currentExpertId = useAppStore((state) => state.currentExpertId)
  const setExpert = useAppStore((state) => state.setExpert)
  const setView = useAppStore((state) => state.setView)
  const [open, setOpen] = useState(false)
  const wrapRef = useDismiss(open, setOpen)

  const current = experts.find((item) => item.id === currentExpertId)

  return (
    <div className="expert-wrap" ref={wrapRef}>
      {open && (
        <>
          <div className="expert-pop">
            <div className="expert-pop-title">选择专家</div>
            <div className="expert-pop-list">
              {experts.map((item) => (
                <button
                  key={item.id}
                  className={`expert-option ${item.id === currentExpertId ? 'active' : ''}`}
                  onClick={() => {
                    setExpert(item.id)
                    setOpen(false)
                  }}
                >
                  <span className="expert-avatar">{item.avatar || item.name.slice(0, 1)}</span>
                  <span className="expert-option-text">
                    <span className="expert-option-name">{item.name}</span>
                    <span className="expert-option-desc">{item.description}</span>
                  </span>
                  {item.id === currentExpertId && <Check size={12} />}
                </button>
              ))}
              {experts.length === 0 && <div className="panel-empty">还没有专家</div>}
            </div>
            <button
              className="expert-manage"
              onClick={() => {
                setOpen(false)
                setView('experts')
              }}
            >
              管理专家 →
            </button>
          </div>
        </>
      )}
      <button className="expert-selector" onClick={() => setOpen((value) => !value)}>
        <Sparkles size={12} />
        <span className="expert-selector-label">
          专家 · {current?.name ?? '通用'}
        </span>
        <ChevronDown size={11} className="chev" />
      </button>
    </div>
  )
}

function formatWindow(value: number): string {
  if (value >= 1_000_000) {
    const millions = value / 1_000_000
    return `${Number.isInteger(millions) ? millions : millions.toFixed(1)}M`
  }
  if (value >= 1000) return `${Math.round(value / 1000)}K`
  return String(value)
}

function ModelPicker(): React.JSX.Element {
  const config = useAppStore((state) => state.config)
  const session = useAppStore((state) =>
    state.sessions.find((item) => item.id === state.activeSessionId)
  )
  const setModel = useAppStore((state) => state.setModel)
  const [open, setOpen] = useState(false)
  const wrapRef = useDismiss(open, setOpen)

  const models = config?.models ?? []
  if (!models.length) return <></>
  const activeId = session?.model_id || config?.active_model_id || models[0].id
  const current = models.find((item) => item.id === activeId) ?? models[0]

  return (
    <div className="model-wrap" ref={wrapRef}>
      {open && (
        <div className="model-pop" role="menu">
          <div className="model-pop-title">选择模型</div>
          {models.map((item) => (
            <button
              key={item.id}
              className={`model-option ${item.id === activeId ? 'active' : ''}`}
              onClick={() => {
                setOpen(false)
                if (item.id !== activeId) void setModel(item.id)
              }}
            >
              <span className="model-option-main">
                <span className="model-option-name">{item.name || item.model}</span>
                <span className="model-option-meta">
                  {item.model} · {formatWindow(item.context_window)}
                </span>
              </span>
              {item.id === activeId && <Check size={12} />}
            </button>
          ))}
        </div>
      )}
      <button
        className="model-trigger"
        onClick={() => setOpen((value) => !value)}
        title={`切换模型（当前会话）\n${current.name || current.model} · ${current.model} · ${formatWindow(
          current.context_window
        )}`}
      >
        <Cpu size={12} />
        <span className="model-label">{middleEllipsis(current.name || current.model, 13, 5)}</span>
        <ChevronDown size={10} className="chev" />
      </button>
    </div>
  )
}

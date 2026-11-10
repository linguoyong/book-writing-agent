import { timelineAfterRetry, timelineFromMessages, timelineWithRun } from './components/conversation'
import { create } from 'zustand'
import { ApiError, api, approveChat, regenerateChat, streamChat } from './api'
import type { StreamHandlerSet } from './api'
import type {
  AppConfig,
  AppView,
  ApprovalBundle,
  ApprovalDecision,
  ContextBundle,
  Entity,
  Expert,
  KbKind,
  MemoryState,
  Message,
  Overview,
  Project,
  ReferenceItem,
  SearchHit,
  Session,
  SessionPermission,
  TimelineItem,
  TreeNode,
  TurnChanges
} from './types'

export interface OpenFile {
  path: string
  content: string
  dirty: boolean
  kind: 'text' | 'image' | 'binary' | 'large'
  dataUrl?: string
  size?: number
  mtime?: number
  truncated?: boolean
}

type RightTab = 'kb' | 'files' | 'diff' | 'side' | 'context'

interface AppState {
  ready: boolean
  error: string | null
  config: AppConfig | null

  projects: Project[]
  activeProject: Project | null
  overview: Overview | null
  spaceSummaries: Record<string, { count: number; last: string }>

  sessions: Session[]
  allSessions: Session[]
  activeSessionId: string | null
  sideSessionId: string | null
  timeline: TimelineItem[]
  streaming: boolean

  tree: TreeNode[]
  openFile: OpenFile | null

  rightTab: RightTab
  kbKind: KbKind
  kbItems: Entity[]
  kbActive: Entity | null
  kbSearch: SearchHit[]
  diff: string
  context: ContextBundle | null
  memory: MemoryState | null
  approval: ApprovalBundle | null
  references: ReferenceItem[]
  permissionMode: SessionPermission
  streamStartedAt: number | null
  turnDiff: TurnChanges | null
  diffMode: 'all' | 'turn'
  toast: string | null

  leftCollapsed: boolean
  rightCollapsed: boolean
  leftWidth: number
  rightWidth: number
  view: AppView
  /** 提示词页要聚焦的那一层（从上下文面板点进来时用） */
  promptFocus: string | null
  experts: Expert[]
  builder: 'expert' | 'skill' | null
  settingsOpen: boolean
  projectModalOpen: boolean
  expertModalOpen: boolean
  skillsModalOpen: boolean
  writingStyle: string
  currentExpertId: string
  pendingComposer: string | null
  promptRequest: {
    title: string
    value: string
    placeholder?: string
    allowEmpty?: boolean
  } | null

  bootstrap: () => Promise<void>
  createProject: (
    name: string,
    title: string,
    author?: string,
    path?: string,
    wordsPerChapter?: number
  ) => Promise<void>
  deleteProject: (projectId: string, purge?: boolean) => Promise<void>
  openProject: (path: string, options?: { draft?: boolean }) => Promise<void>
  refreshSpaceSummaries: () => Promise<void>
  selectProject: (
    projectId: string,
    options?: { sessionId?: string; draft?: boolean }
  ) => Promise<void>
  openSession: (projectId: string, sessionId: string) => Promise<void>
  refreshAllSessions: () => Promise<void>
  refreshOverview: () => Promise<void>

  refreshSessions: () => Promise<void>
  /** 切回会话时接上仍在跑的那一轮（轮询快照直到结束） */
  resumeRun: (sessionId: string) => void
  /** 进入草稿态：不建会话，左侧列表不动，发出第一条消息时才落库 */
  startDraft: () => void
  newSession: () => Promise<Session | null>
  selectSession: (sessionId: string) => Promise<void>
  setSideSessionId: (sessionId: string | null) => void
  removeSession: (sessionId: string) => Promise<void>
  renameSession: (sessionId: string, title: string) => Promise<void>
  archiveSession: (sessionId: string, archived: boolean) => Promise<void>

  sendMessage: (text: string) => Promise<void>
  steerMessage: (text: string) => Promise<void>
  stopStreaming: () => void
  regenerate: () => Promise<void>
  /** 重试 = 把最后一条用户消息原样再发一次（保留原来的回答，不覆盖） */
  retryLastTurn: () => Promise<void>

  refreshTree: () => Promise<void>
  openFileByPath: (path: string, force?: boolean, head?: number) => Promise<void>
  updateOpenFile: (content: string) => void
  saveOpenFile: () => Promise<void>

  setRightTab: (tab: RightTab) => void
  loadKb: (kind: KbKind) => Promise<void>
  selectKbEntity: (entity: Entity | null) => void
  createKbEntity: (name: string) => Promise<void>
  patchKbActive: (patch: Partial<Entity>) => void
  saveKbActive: () => Promise<void>
  deleteKbActive: () => Promise<void>
  searchKb: (query: string) => Promise<void>
  reindexKb: () => Promise<void>

  refreshDiff: () => Promise<void>
  showTurnDiff: (changes: TurnChanges) => void
  setDiffMode: (mode: 'all' | 'turn') => void
  refreshContext: () => Promise<void>
  refreshMemory: () => Promise<void>
  distillMemory: () => Promise<{ ok: boolean; added: number; message?: string }>
  resolveApproval: (decisions: ApprovalDecision[]) => Promise<void>
  refreshPending: () => Promise<void>
  addReference: (item: ReferenceItem) => void
  removeReference: (index: number) => void
  clearReferences: () => void
  saveConfig: (config: AppConfig) => Promise<void>
  setModel: (modelId: string) => Promise<void>
  showToast: (text: string) => void
  askPrompt: (
    title: string,
    value?: string,
    options?: { placeholder?: string; allowEmpty?: boolean }
  ) => Promise<string | null>
  resolvePrompt: (value: string | null) => void

  clearError: () => void
  toggleLeft: () => void
  toggleRight: () => void
  setView: (view: AppView) => void
  setPromptFocus: (layer: string | null) => void
  loadExperts: () => Promise<void>
  startBuilder: (kind: 'expert' | 'skill') => Promise<void>
  setBuilder: (kind: 'expert' | 'skill' | null) => void
  setLeftWidth: (width: number) => void
  setRightWidth: (width: number) => void
  setSettingsOpen: (open: boolean) => void
  setProjectModalOpen: (open: boolean) => void
  setExpertModalOpen: (open: boolean) => void
  setSkillsModalOpen: (open: boolean) => void
  setExpert: (expertId: string) => void
  setPermissionMode: (mode: SessionPermission) => void
  setWritingStyle: (style: string) => void
  setPendingComposer: (text: string | null) => void
}

let seq = 0
const uid = (): string => `t${Date.now()}-${seq++}`

/** 一轮正在跑的生成：切走只停轮询，服务端任务继续；切回来接着看。 */
let runTimer: number | null = null
let runWatchSeq = 0

function stopRunWatch(): void {
  runWatchSeq += 1
  if (runTimer !== null) {
    window.clearInterval(runTimer)
    runTimer = null
  }
}

/** 当前主对话的流式请求；同一时间只允许一个（侧问有自己的 controller） */
let streamAbort: AbortController | null = null
let toastTimer: number | null = null
/** PromptDialog 的等待者：同一时间只允许一个输入框 */
let promptResolver: ((value: string | null) => void) | null = null
/** 会话消息加载序号：慢请求回来时不能覆盖后选的会话 */
let selectSeq = 0

export const KB_LABELS: Record<KbKind, string> = {
  characters: '角色',
  factions: '势力',
  items: '物品',
  locations: '地点',
  world: '世界观',
  outline: '大纲',
  materials: '素材',
  styles: '风格'
}

export const useAppStore = create<AppState>((set, get) => {
  /** 切换文件 / 切换空间 / 关窗前的统一守卫：脏内容必须先问一句 */
  const confirmDiscard = (): boolean => {
    const current = get().openFile
    if (!current?.dirty) return true
    return window.confirm(`「${current.path}」有未保存的修改，继续会丢失。继续？`)
  }

  /** 流结束时把仍标记为执行中的工具收尾，避免卡片永远停在「执行中」 */
  const settleRunning = (items: TimelineItem[]): TimelineItem[] =>
    items.map((item) =>
      item.type === 'tool' && item.status === 'running'
        ? { ...item, status: 'cancelled' as const }
        : item
    )

  /** 重新生成前清掉最后一轮回答（含它前面的工具卡与结尾统计） */
  const trimLastTurn = (items: TimelineItem[]): TimelineItem[] => {
    let index = -1
    for (let cursor = items.length - 1; cursor >= 0; cursor -= 1) {
      if (items[cursor].type === 'assistant') {
        index = cursor
        break
      }
    }
    if (index < 0) return items
    let start = index
    while (start > 0 && items[start - 1].type === 'tool') start -= 1
    return items.filter(
      (item, cursor) => cursor < start || (cursor > index && item.type !== 'turn_end')
    )
  }

  const makeHandlers = (sessionId: string, signal: AbortSignal): StreamHandlerSet => {
    const live = (): boolean => get().activeSessionId === sessionId && !signal.aborted
    let assistantId: string | null = null
    return {
      onContext: (bundle) => { if (live()) set({ context: bundle }) },
      onApproval: (approval) => {
        if (!live()) return
        set({ approval })
      },
      onToken: (token) => {
        if (!live()) return
        set((state) => {
          const items = [...state.timeline]
          const last = items[items.length - 1]
          if (assistantId && last?.type === 'assistant' && last.id === assistantId) {
            items[items.length - 1] = { ...last, content: last.content + token }
          } else {
            assistantId = uid()
            items.push({ id: assistantId, type: 'assistant', content: token })
          }
          return { timeline: items }
        })
      },
      onRetry: (removedChars, message) => {
        if (!live()) return
        assistantId = null
        set((state) => ({ timeline: timelineAfterRetry(state.timeline, removedChars, message) }))
      },
      onToolStart: (name, input) => {
        if (!live()) return
        assistantId = null
        set((state) => ({
          timeline: [
            ...state.timeline,
            { id: uid(), type: 'tool', name, input, status: 'running' }
          ]
        }))
      },
      onToolEnd: (name, output) => {
        if (!live()) return
        set((state) => {
          const items = [...state.timeline]
          for (let index = items.length - 1; index >= 0; index -= 1) {
            const item = items[index]
            if (item.type === 'tool' && item.name === name && item.status === 'running') {
              items[index] = { ...item, output, status: 'done' }
              break
            }
          }
          return { timeline: items }
        })
      },
      onError: (message) => {
        if (!live()) return
        set((state) => ({
          timeline: [...state.timeline, { id: uid(), type: 'error', content: message }]
        }))
      },
      onAborted: () => {
        if (!live()) return
        // 用户主动中止：保留已生成内容，只把运行态收回来，不当作错误
        set((state) => ({
          streaming: false,
          streamStartedAt: null,
          timeline: settleRunning(state.timeline)
        }))
      },
      onDone: (payload) => {
        if (!live()) return
        const turn =
          payload && (payload.elapsed_ms !== undefined || payload.changes)
            ? {
                ...payload,
                elapsed_ms: payload.elapsed_ms ?? 0,
                changes: payload.changes ?? { files: [], diff: '' },
                usage: payload.usage
              }
            : null
        set((state) => {
          const settled = settleRunning(state.timeline)
          return {
            streaming: false,
            streamStartedAt: null,
            timeline: turn
              ? [...settled, { id: uid(), type: 'turn_end', meta: turn } as TimelineItem]
              : settled
          }
        })
        void get().refreshSessions()
        void get().refreshOverview()
        void get().refreshDiff()
      }
    }
  }

  const autoApprovalAttempts = new Set<string>()

  return {
    ready: false,
  error: null,
  config: null,
  projects: [],
  activeProject: null,
  overview: null,
  spaceSummaries: {},
  sessions: [],
  allSessions: [],
  activeSessionId: null,
  sideSessionId: null,
  timeline: [],
  streaming: false,
  tree: [],
  openFile: null,
  rightTab: 'files',
  kbKind: 'characters',
  kbItems: [],
  kbActive: null,
  kbSearch: [],
  diff: '',
  context: null,
  memory: null,
  approval: null,
  references: [],
  permissionMode: 'ask',
  streamStartedAt: null,
  turnDiff: null,
  diffMode: 'all',
  toast: null,
  leftCollapsed: false,
  rightCollapsed: false,
  leftWidth: 268,
  rightWidth: 620,
  view: 'chat',
  experts: [],
  builder: null,
  settingsOpen: false,
  projectModalOpen: false,
  promptFocus: null,
  expertModalOpen: false,
  skillsModalOpen: false,
  writingStyle: '',
  currentExpertId: 'general',
  pendingComposer: null,
  promptRequest: null,

  bootstrap: async () => {
    for (let attempt = 0; attempt < 15; attempt += 1) {
      try {
        const [projects, config] = await Promise.all([api.listProjects(), api.getConfig()])
        set({
          projects,
          config,
          ready: true,
          error: null,
          permissionMode: config.sandbox.default_mode
        })
        if (projects.length > 0) await get().selectProject(projects[0].id)
        void get().refreshSpaceSummaries()
        return
      } catch (error) {
        if (attempt === 14) {
          const message = (error as Error).message
          set({
            ready: true,
            error: message || '无法连接本地后端，请确认服务已启动后刷新'
          })
          return
        }
        await new Promise((resolve) => setTimeout(resolve, 800))
      }
    }
  },

  createProject: async (name, title, author, path, wordsPerChapter) => {
    try {
      const project = await api.createProject({
        name,
        title,
        author,
        path,
        words_per_chapter: wordsPerChapter
      })
      const projects = await api.listProjects()
      set({ projects, projectModalOpen: false })
      // 新建空间后停在草稿态：左侧不该先冒出一个空会话
      await get().selectProject(project.id, { draft: true })
      await get().refreshSpaceSummaries()
    } catch (error) {
      set({ error: (error as Error).message })
    }
  },

  deleteProject: async (projectId, purge = false) => {
    const state = get()
    const dropLocally = async (): Promise<void> => {
      const projects = state.projects.filter((item) => item.id !== projectId)
      const summaries = { ...state.spaceSummaries }
      delete summaries[projectId]
      set({
        projects,
        spaceSummaries: summaries,
        allSessions: state.allSessions.filter((item) => item.project_id !== projectId)
      })
      if (state.activeProject?.id === projectId) {
        set({
          activeProject: null,
          overview: null,
          sessions: [],
          activeSessionId: null,
          sideSessionId: null,
          timeline: [],
          tree: [],
          openFile: null
        })
        if (projects.length > 0) await get().selectProject(projects[0].id)
        else get().setProjectModalOpen(true)
      }
    }
    try {
      await api.deleteProject(projectId, purge)
      await dropLocally()
    } catch (error) {
      // 后端已经被删掉了（列表还没刷新就重复点）：当成成功，别把 404 说成
      // 「接口不存在、后端是旧进程」——那会把用户引到错误的方向
      if (error instanceof ApiError && error.status === 404) {
        await dropLocally()
        get().showToast('该空间已经删掉了')
        return
      }
      set({ error: (error as Error).message })
    }
  },

  openProject: async (path) => {
    try {
      const project = await api.openProject(path)
      const projects = await api.listProjects()
      set({ projects, projectModalOpen: false })
      // 新建空间后停在草稿态：左侧不该先冒出一个空会话
      await get().selectProject(project.id, { draft: true })
      await get().refreshSpaceSummaries()
    } catch (error) {
      set({ error: (error as Error).message })
    }
  },

  refreshSpaceSummaries: async () => {
    const projects = get().projects
    const entries = await Promise.all(
      projects.map(async (project) => {
        try {
          const sessions = await api.listSessions(project.id)
          const visible = sessions.filter((session) => session.kind !== 'side')
          return [
            project.id,
            { count: visible.length, last: visible[0]?.title ?? '' }
          ] as const
        } catch {
          return [project.id, { count: 0, last: '' }] as const
        }
      })
    )
    set({ spaceSummaries: Object.fromEntries(entries) })
  },

  selectProject: async (projectId, options) => {
    const project = get().projects.find((item) => item.id === projectId)
    if (!project) return
    if (!confirmDiscard()) return
    // 旧流不停就会把 token 继续追加到新空间的对话里，引导也会发错会话
    streamAbort?.abort()
    streamAbort = null
    stopRunWatch()
    set({
      activeProject: project,
      streaming: false,
      streamStartedAt: null,
      approval: null,
      overview: null,
      sessions: [],
      activeSessionId: null,
      sideSessionId: window.localStorage.getItem(`book-agent:side:${project.id}`),
      timeline: [],
      tree: [],
      openFile: null,
      kbItems: [],
      kbActive: null,
      kbSearch: [],
      diff: '',
      error: null
    })
    try {
      const [overview, sessions, tree] = await Promise.all([
        api.overview(projectId),
        api.listSessions(projectId),
        api.tree(projectId)
      ])
      set({
        overview,
        sessions,
        tree,
        activeProject: { ...project, meta: overview.book }
      })
      if (!options?.sessionId) {
        const file = firstManuscript(tree)
        if (file) await get().openFileByPath(file)
      }
      await get().loadKb(get().kbKind)
      await get().loadExperts()
      void get().refreshMemory()
      if (options?.sessionId) {
        await get().selectSession(options.sessionId)
      } else if (!options?.draft) {
        const mainSessions = sessions.filter((session) => session.kind === 'main')
        if (mainSessions.length > 0) await get().selectSession(mainSessions[0].id)
      }
      void get().refreshAllSessions()
    } catch (error) {
      set({ error: (error as Error).message })
    }
  },

  openSession: async (projectId, sessionId) => {
    set({ view: 'chat' })
    if (get().activeProject?.id !== projectId) {
      await get().selectProject(projectId, { sessionId })
      return
    }
    await get().selectSession(sessionId)
  },

  refreshAllSessions: async () => {
    try {
      set({ allSessions: await api.allSessions() })
    } catch {
      /* 左栏摘要刷新失败不阻塞主流程 */
    }
  },

  refreshOverview: async () => {
    const project = get().activeProject
    if (!project) return
    try {
      const overview = await api.overview(project.id)
      if (get().activeProject?.id !== project.id) return
      set({ overview, activeProject: { ...project, meta: overview.book } })
      const kind = get().kbKind
      const kbItems = await api.entities(project.id, kind)
      if (get().activeProject?.id === project.id && get().kbKind === kind) set({ kbItems })
    } catch {
      /* 忽略概览刷新失败 */
    }
  },

  refreshSessions: async () => {
    const project = get().activeProject
    if (!project) return
    try {
      const sessions = await api.listSessions(project.id)
      const visible = sessions.filter((session) => session.kind !== 'side')
      set({
        sessions,
        spaceSummaries: {
          ...get().spaceSummaries,
          [project.id]: { count: visible.length, last: visible[0]?.title ?? '' }
        }
      })
      void get().refreshAllSessions()
    } catch (error) {
      set({ error: (error as Error).message })
    }
  },

  startDraft: () => {
    const project = get().activeProject
    if (!project) {
      get().setProjectModalOpen(true)
      return
    }
    if (!confirmDiscard()) return
    // 停掉旧流：否则旧会话的 token 会继续往这份新 timeline 里写
    streamAbort?.abort()
    streamAbort = null
    set({
      view: 'chat',
      activeSessionId: null,
      timeline: [],
      context: null,
      streaming: false,
      streamStartedAt: null,
      approval: null,
      references: [],
      builder: null,
      error: null
    })
  },

  newSession: async () => {
    const project = get().activeProject
    if (!project) return null

    // 当前就是一个没发过消息的空会话：复用它，别在列表里堆一串「新会话」
    const state = get()
    const current = state.sessions.find((item) => item.id === state.activeSessionId)
    if (
      current &&
      current.kind !== 'side' &&
      !current.archived &&
      state.timeline.length === 0 &&
      !state.streaming
    ) {
      set({ view: 'chat' })
      state.showToast('当前已经是新会话，直接开始输入即可')
      return current
    }

    try {
      const session = await api.createSession(project.id, {
        expertId: get().currentExpertId,
        domain: 'book',
        permissionMode: get().permissionMode,
        modelId: get().config?.active_model_id
      })
      set({
        sessions: [session, ...get().sessions],
        activeSessionId: session.id,
        timeline: [],
        context: null,
        builder: null
      })
      void get().refreshContext()
      void get().refreshAllSessions()
      return session
    } catch (error) {
      set({ error: (error as Error).message })
      return null
    }
  },

  setSideSessionId: (sessionId) => {
    const projectId = get().activeProject?.id
    if (projectId) {
      const key = `book-agent:side:${projectId}`
      if (sessionId) window.localStorage.setItem(key, sessionId)
      else window.localStorage.removeItem(key)
    }
    set({ sideSessionId: sessionId })
  },

  selectSession: async (sessionId) => {
    stopRunWatch()
    const session = get().sessions.find((item) => item.id === sessionId)
    // 旧流不停，token 会继续追加到新会话的 timeline，steer 也会发错会话
    streamAbort?.abort()
    streamAbort = null
    const seq = ++selectSeq
    set({
      activeSessionId: sessionId,
      timeline: [],
      error: null,
      streaming: false,
      streamStartedAt: null,
      approval: null,
      currentExpertId: session?.expert_id ?? get().currentExpertId,
      permissionMode:
        session?.permission_mode ?? get().config?.sandbox.default_mode ?? get().permissionMode
    })
    try {
      const messages = await api.messages(sessionId)
      // 快速连点时，先发的请求可能后回来
      if (seq !== selectSeq) return
      set({ timeline: timelineFromMessages(messages) })
    } catch (error) {
      if (seq === selectSeq) set({ error: (error as Error).message })
    }
    // 这一轮可能还在服务端跑（刚才是切走不是中断）：接上它继续看进展
    if (seq !== selectSeq || get().activeSessionId !== sessionId) return
    get().resumeRun(sessionId)
    void get().refreshContext()
    void get().refreshPending()
  },

  resumeRun: (sessionId) => {
    stopRunWatch()
    const seq = runWatchSeq
    const live = (): boolean => seq === runWatchSeq && get().activeSessionId === sessionId
    let history: Message[] | null = null
    let pending = false
    const tick = async (): Promise<void> => {
      if (!live() || pending) return
      pending = true
      try {
        const snapshot = await api.sessionRun(sessionId)
        if (!live()) return
        if (snapshot.running) {
          const messages = history ?? await api.messages(sessionId)
          if (!live()) return
          // Before the first output the user message may still be committing.
          // Reload once output appears, then keep the stable history as our base.
          if (snapshot.items.length) history = messages
          set({
            timeline: timelineWithRun(messages, snapshot),
            streaming: true,
            streamStartedAt: snapshot.started_at * 1000
          })
          if (runTimer === null) runTimer = window.setInterval(() => void tick(), 800)
          return
        }
        // Keep the running state until the authoritative final history arrives.
        const messages = await api.messages(sessionId)
        if (!live()) return
        set({ timeline: timelineFromMessages(messages), streaming: false, streamStartedAt: null })
        stopRunWatch()
        void get().refreshSessions()
        void get().refreshAllSessions()
        void get().refreshDiff()
        void get().refreshOverview()
        void get().refreshTree()
        void get().refreshPending()
      } catch {
        // A transient polling failure must not erase messages or strand a live run.
        if (live() && runTimer === null) runTimer = window.setInterval(() => void tick(), 800)
      } finally {
        pending = false
      }
    }
    void tick()
  },

  removeSession: async (sessionId) => {
    try {
      await api.deleteSession(sessionId)
      if (get().sideSessionId === sessionId) get().setSideSessionId(null)
      const sessions = get().sessions.filter((item) => item.id !== sessionId)
      set({ sessions })
      void get().refreshAllSessions()
      if (get().activeSessionId === sessionId) {
        set({ activeSessionId: null, timeline: [] })
        if (sessions.length > 0) await get().selectSession(sessions[0].id)
      }
    } catch (error) {
      set({ error: (error as Error).message })
    }
  },

  renameSession: async (sessionId, title) => {
    const clean = title.trim()
    if (!clean) return
    try {
      const updated = await api.updateSession(sessionId, { title: clean })
      set({
        sessions: get().sessions.map((item) => (item.id === sessionId ? updated : item))
      })
      void get().refreshAllSessions()
    } catch (error) {
      set({ error: (error as Error).message })
    }
  },

  archiveSession: async (sessionId, archived) => {
    try {
      const updated = await api.updateSession(sessionId, { archived })
      set({
        sessions: get().sessions.map((item) => (item.id === sessionId ? updated : item))
      })
      void get().refreshAllSessions()
      if (archived && get().activeSessionId === sessionId) {
        const next = get().sessions.find(
          (item) => item.id !== sessionId && item.kind !== 'side' && !item.archived
        )
        if (next) await get().selectSession(next.id)
        else await get().newSession()
      }
    } catch (error) {
      set({ error: (error as Error).message })
    }
  },

  sendMessage: async (text) => {
    const message = text.trim()
    if (!message || get().streaming) return
    stopRunWatch()
    let sessionId = get().activeSessionId
    if (!sessionId) {
      // 先占住 streaming：newSession 是 await，双击会建出两个会话、两路流写同一份 timeline
      set({ streaming: true, streamStartedAt: Date.now(), error: null })
      const session = await get().newSession()
      if (!session) {
        set({ streaming: false, streamStartedAt: null })
        return
      }
      sessionId = session.id
    }

    const references = get().references
    set((state) => ({
      timeline: [
        ...state.timeline,
        {
          id: uid(),
          type: 'user',
          content: message,
          references: references.length ? references : undefined
        }
      ],
      streaming: true,
      streamStartedAt: Date.now(),
      error: null,
      approval: null,
      references: []
    }))
    void get().refreshAllSessions()

    const builder = get().builder
    const mode =
      builder === 'expert' ? 'expert_builder' : builder === 'skill' ? 'skill_builder' : 'main'

    const controller = new AbortController()
    streamAbort = controller
    try {
      await streamChat(
        sessionId,
        message,
        mode,
        references,
        makeHandlers(sessionId, controller.signal),
        controller.signal
      )
      if (get().activeSessionId === sessionId && !controller.signal.aborted) get().resumeRun(sessionId)
    } finally {
      if (streamAbort === controller) streamAbort = null
    }
  },

  steerMessage: async (text) => {
    const message = text.trim()
    const sessionId = get().activeSessionId
    if (!message || !sessionId) return
    try {
      await api.steer(sessionId, message)
      if (get().activeSessionId !== sessionId) return
      set((state) => ({
        timeline: [
          ...state.timeline,
          { id: uid(), type: 'user', content: message, steering: true }
        ]
      }))
      // A restored run polls a cached history; refresh it after a new persisted
      // user message and invalidate any poll that started before the message.
      if (!streamAbort) get().resumeRun(sessionId)
    } catch (error) {
      set({ error: (error as Error).message })
    }
  },

  stopStreaming: () => {
    const sessionId = get().activeSessionId
    // 后端现在是后台任务：只 abort 本地读取并不能停下它，得显式叫停
    streamAbort?.abort()
    streamAbort = null
    stopRunWatch()
    set({ streaming: false, streamStartedAt: null })
    if (sessionId) void api.stopRun(sessionId).catch(() => undefined)
  },

  retryLastTurn: async () => {
    const state = get()
    if (state.streaming) {
      state.showToast('这一轮还在生成，等结束或先停止再重试')
      return
    }
    if (state.approval) {
      state.showToast('先处理待审批的写入，再重试')
      return
    }
    const lastUser = [...state.timeline].reverse().find((item) => item.type === 'user')
    if (!lastUser) {
      state.showToast('没有可以重试的消息')
      return
    }
    await get().sendMessage(lastUser.content)
  },

  regenerate: async () => {
    const sessionId = get().activeSessionId
    if (!sessionId || get().streaming) return
    if (get().approval) {
      get().showToast('先处理待审批的写入，再重新生成')
      return
    }
    set((state) => ({
      streaming: true,
      streamStartedAt: Date.now(),
      error: null,
      timeline: trimLastTurn(state.timeline)
    }))
    const controller = new AbortController()
    streamAbort = controller
    try {
      await regenerateChat(sessionId, makeHandlers(sessionId, controller.signal), controller.signal)
      if (get().activeSessionId === sessionId && !controller.signal.aborted) get().resumeRun(sessionId)
    } finally {
      if (streamAbort === controller) streamAbort = null
    }
  },

  refreshTree: async () => {
    const project = get().activeProject
    if (!project) return
    try {
      set({ tree: await api.tree(project.id) })
    } catch (error) {
      set({ error: (error as Error).message })
    }
  },

  openFileByPath: async (path, force = false, head) => {
    const project = get().activeProject
    if (!project) return
    const current = get().openFile
    if (!force && current?.dirty && current.path !== path && !confirmDiscard()) return
    try {
      const file = await api.readFile(project.id, path, head)
      set({
        openFile: {
          path: file.path,
          content: file.content ?? '',
          dirty: false,
          kind: file.kind,
          dataUrl: file.data_url,
          size: file.size,
          mtime: file.mtime,
          truncated: file.truncated
        },
        rightTab: 'files',
        rightCollapsed: false
      })
    } catch (error) {
      set({ error: (error as Error).message })
    }
  },

  updateOpenFile: (content) => {
    set((state) => (state.openFile ? { openFile: { ...state.openFile, content, dirty: true } } : {}))
  },

  saveOpenFile: async () => {
    const project = get().activeProject
    // 保存的是「点下保存那一刻」的内容；await 期间用户继续输入的字不能被回滚
    const snapshot = get().openFile
    if (!project || !snapshot || snapshot.kind !== 'text') return

    const write = async (expected?: number): Promise<number> => {
      const result = await api.writeFile(project.id, snapshot.path, snapshot.content, expected)
      return result.mtime
    }

    // 只更新脏标记与 mtime，绝不覆盖 content：
    // 保存期间又打了字，就仍然是 dirty，等下一次保存。
    const applySaved = (mtime: number): void => {
      set((state) => {
        const file = state.openFile
        if (!file || file.path !== snapshot.path) return {}
        return { openFile: { ...file, dirty: file.content !== snapshot.content, mtime } }
      })
    }

    try {
      const mtime = await write(snapshot.mtime)
      applySaved(mtime)
      await get().refreshDiff()
      await get().refreshOverview()
    } catch (error) {
      const message = (error as Error).message
      if (!message.includes('已被其他操作修改')) {
        set({ error: message })
        return
      }
      // 文件在打开后被 Agent 或其他窗口改过：让用户决定覆盖还是重载
      const overwrite = window.confirm(
        '这个文件刚被 Agent 或其他操作改过。\n\n确定：用编辑器当前内容覆盖\n取消：放弃本次保存并重新加载磁盘内容'
      )
      try {
        if (overwrite) {
          const mtime = await write()
          applySaved(mtime)
          await get().refreshDiff()
          await get().refreshOverview()
        } else {
          await get().openFileByPath(snapshot.path, true)
        }
      } catch (inner) {
        set({ error: (inner as Error).message })
      }
    }
  },

  setRightTab: (tab) => {
    set({ rightTab: tab })
    if (tab === 'files' && get().rightWidth < 560) set({ rightWidth: 620 })
    if (tab === 'diff') void get().refreshDiff()
    if (tab === 'files') void get().refreshTree()
    if (tab === 'context') {
      void get().refreshContext()
      void get().refreshMemory()
    }
  },

  loadKb: async (kind) => {
    const project = get().activeProject
    if (!project) return
    set({ kbKind: kind, kbActive: null, kbItems: [] })
    try {
      const kbItems = await api.entities(project.id, kind)
      if (get().activeProject?.id === project.id && get().kbKind === kind) set({ kbItems })
    } catch (error) {
      set({ error: (error as Error).message })
    }
  },

  selectKbEntity: (entity) => set({ kbActive: entity }),

  createKbEntity: async (name) => {
    const project = get().activeProject
    if (!project || !name.trim()) return
    const kind = get().kbKind
    try {
      const entity = await api.saveEntity(project.id, kind, {
        id: name.trim(),
        meta: { name: name.trim() },
        body: ''
      })
      await get().loadKb(kind)
      set({ kbActive: entity })
      await get().refreshTree()
      // 服务端已按单条卡片增量索引，不再触发整库重嵌
      await get().refreshOverview()
    } catch (error) {
      set({ error: (error as Error).message })
    }
  },

  patchKbActive: (patch) => {
    const active = get().kbActive
    if (!active) return
    set({ kbActive: { ...active, ...patch } })
  },

  saveKbActive: async () => {
    const project = get().activeProject
    const active = get().kbActive
    if (!project || !active) return
    try {
      const saved = await api.saveEntity(project.id, active.kind, {
        id: active.id,
        meta: active.meta,
        body: active.body
      })
      set({ kbActive: saved })
      await get().loadKb(active.kind)
      set({ kbActive: saved })
      await get().refreshTree()
      await get().refreshDiff()
      // 服务端已按单条卡片增量索引，不再触发整库重嵌
      await get().refreshOverview()
    } catch (error) {
      set({ error: (error as Error).message })
    }
  },

  deleteKbActive: async () => {
    const project = get().activeProject
    const active = get().kbActive
    if (!project || !active) return
    try {
      await api.deleteEntity(project.id, active.kind, active.id)
      set({ kbActive: null })
      await get().loadKb(active.kind)
      await get().refreshDiff()
      // 服务端已按单条卡片增量索引，不再触发整库重嵌
      await get().refreshOverview()
    } catch (error) {
      set({ error: (error as Error).message })
    }
  },

  reindexKb: async () => {
    const project = get().activeProject
    if (!project) return
    try {
      await api.reindex(project.id)
      // 后台任务：轮询状态，直到结束或超时（约 8 分钟）
      for (let attempt = 0; attempt < 600; attempt += 1) {
        await new Promise((resolve) => window.setTimeout(resolve, 800))
        const status = await api.indexStatus(project.id)
        if (!status.running) {
          if (status.error) set({ error: status.error })
          break
        }
      }
      await get().refreshOverview()
    } catch (error) {
      set({ error: (error as Error).message })
    }
  },

  searchKb: async (query) => {
    const project = get().activeProject
    if (!project || !query.trim()) {
      set({ kbSearch: [] })
      return
    }
    try {
      const result = await api.search(project.id, query)
      set({ kbSearch: result.results })
    } catch (error) {
      set({ error: (error as Error).message })
    }
  },

  refreshDiff: async () => {
    const project = get().activeProject
    if (!project) return
    try {
      const result = await api.gitDiff(project.id)
      set({ diff: result.diff })
    } catch {
      /* 忽略 diff 刷新失败 */
    }
  },

  refreshContext: async () => {
    const sessionId = get().activeSessionId
    if (!sessionId) {
      set({ context: null })
      return
    }
    try {
      set({ context: await api.context(sessionId) })
    } catch {
      /* 上下文面板失败不打扰对话 */
    }
  },

  showTurnDiff: (changes) => {
    set({
      turnDiff: changes,
      diffMode: 'turn',
      rightTab: 'diff',
      rightCollapsed: false
    })
  },

  setDiffMode: (mode) => set({ diffMode: mode }),

  refreshMemory: async () => {
    const project = get().activeProject
    try {
      set({ memory: await api.memory(project?.id) })
    } catch {
      /* 忽略记忆读取失败 */
    }
  },

  distillMemory: async () => {
    const sessionId = get().activeSessionId
    if (!sessionId) return { ok: false, added: 0, message: '当前没有会话' }
    try {
      const result = await api.distill(sessionId)
      if (result.ok) {
        await get().refreshMemory()
        await get().refreshContext()
      }
      return result
    } catch (error) {
      return { ok: false, added: 0, message: (error as Error).message }
    }
  },

  resolveApproval: async (decisions) => {
    const sessionId = get().activeSessionId
    if (!sessionId || get().streaming) return
    set({ streaming: true, streamStartedAt: Date.now(), approval: null, error: null })
    const controller = new AbortController()
    streamAbort = controller
    try {
      await approveChat(sessionId, decisions, makeHandlers(sessionId, controller.signal), controller.signal)
      if (get().activeSessionId === sessionId && !controller.signal.aborted) get().resumeRun(sessionId)
    } finally {
      if (streamAbort === controller) streamAbort = null
    }
  },

  refreshPending: async () => {
    const sessionId = get().activeSessionId
    if (!sessionId) {
      set({ approval: null })
      return
    }
    try {
      const result = await api.pending(sessionId)
      if (get().activeSessionId !== sessionId) return
      set({ approval: result.approval })
      if (result.approval && get().permissionMode === 'auto' && !get().streaming && !autoApprovalAttempts.has(result.approval.approval_id)) {
        // 模式可能在服务端暂停后才切换；等旧 SSE 结束后，再串行恢复。
        // 自动恢复失败时保留审批卡，避免后台反复提交同一批写入。
        autoApprovalAttempts.add(result.approval.approval_id)
        await get().resolveApproval(result.approval.requests.map(() => ({ type: 'approve' as const })))
      }
    } catch {
      /* 忽略待审批读取失败 */
    }
  },

  addReference: (item) => {
    const exists = get().references.some(
      (ref) => ref.type === item.type && ref.path === item.path && ref.id === item.id
    )
    if (exists) return
    set({ references: [...get().references, item] })
  },

  removeReference: (index) => {
    set({ references: get().references.filter((_, i) => i !== index) })
  },

  clearReferences: () => set({ references: [] }),

  saveConfig: async (config) => {
    try {
      const saved = await api.saveConfig(config)
      set({ config: saved, settingsOpen: false })
      // 改了模型窗口/输出上限后，右侧「上下文」面板要立刻反映新的预算
      if (get().activeSessionId) void get().refreshContext()
      if ((saved as AppConfig & { embedding_changed?: boolean }).embedding_changed) {
        get().showToast('向量配置已变更，请到知识库页点「重建索引」，否则语义检索为空')
      }
    } catch (error) {
      set({ error: (error as Error).message })
    }
  },

  setModel: async (modelId) => {
    const state = get()
    const config = state.config
    if (!config) return
    const model = config.models.find((item) => item.id === modelId)
    const label = model?.name || model?.model || modelId

    if (state.activeSessionId) {
      try {
        const updated = await api.updateSession(state.activeSessionId, {
          model_id: modelId
        })
        set({
          sessions: state.sessions.map((item) =>
            item.id === state.activeSessionId ? { ...item, model_id: updated.model_id } : item
          )
        })
        void get().refreshContext()
      } catch (error) {
        set({ error: (error as Error).message })
        return
      }
    } else {
      try {
        const saved = await api.saveConfig({ ...config, active_model_id: modelId })
        set({ config: saved })
      } catch (error) {
        set({ error: (error as Error).message })
        return
      }
    }

    get().showToast(
      state.streaming
        ? `已切换到 ${label}。当前任务仍在用旧模型执行；新模型会重新计算上下文，可能消耗更多 token。`
        : `已切换到 ${label}，下一轮对话生效。`
    )
  },

  showToast: (text) => {
    if (toastTimer) window.clearTimeout(toastTimer)
    set({ toast: text })
    toastTimer = window.setTimeout(() => set({ toast: null }), 5000)
  },

  askPrompt: (title, value = '', options) =>
    new Promise<string | null>((resolve) => {
      promptResolver?.(null)
      promptResolver = resolve
      set({
        promptRequest: {
          title,
          value,
          placeholder: options?.placeholder,
          allowEmpty: options?.allowEmpty
        }
      })
    }),

  resolvePrompt: (value) => {
    const resolver = promptResolver
    promptResolver = null
    set({ promptRequest: null })
    resolver?.(value)
  },

  clearError: () => set({ error: null }),
  toggleLeft: () => set({ leftCollapsed: !get().leftCollapsed }),
  toggleRight: () => set({ rightCollapsed: !get().rightCollapsed }),
  setView: (view) => set({ view }),
  loadExperts: async () => {
    const project = get().activeProject
    if (!project) return
    try {
      const experts = await api.experts(project.id)
      const current = experts.find((item) => item.id === get().currentExpertId) ?? experts[0]
      set({
        experts,
        currentExpertId: current?.id ?? 'general',
        writingStyle: current?.prompt ?? ''
      })
    } catch {
      /* 忽略专家加载失败 */
    }
  },
  startBuilder: async (kind) => {
    await get().newSession()
    set({
      builder: kind,
      view: 'chat',
      pendingComposer:
        kind === 'expert'
          ? '我想创建一个新的写作专家，请先问我几个问题来确定定位和风格。'
          : '我想创建一个新的技能，请先问我几个问题来确定用途和执行步骤。'
    })
  },
  setBuilder: (kind) => set({ builder: kind }),
  setLeftWidth: (width) => set({ leftWidth: Math.min(460, Math.max(200, width)) }),
  setRightWidth: (width) => set({ rightWidth: Math.min(960, Math.max(340, width)) }),
  setSettingsOpen: (open) => set({ settingsOpen: open }),
  setPromptFocus: (layer) => set({ promptFocus: layer }),
  setProjectModalOpen: (open) => set({ projectModalOpen: open }),
  setExpertModalOpen: (open) => set({ expertModalOpen: open }),
  setSkillsModalOpen: (open) => set({ skillsModalOpen: open }),
  setExpert: (expertId) => {
    const expert = get().experts.find((item) => item.id === expertId)
    set({ currentExpertId: expertId, writingStyle: expert?.prompt ?? '' })
    const sessionId = get().activeSessionId
    if (!sessionId) return
    void api
      .updateSession(sessionId, { expert_id: expertId })
      .then((updated) => {
        set({
          sessions: get().sessions.map((item) =>
            item.id === sessionId ? { ...item, expert_id: updated.expert_id } : item
          )
        })
        void get().refreshContext()
      })
      .catch((error: Error) => set({ error: error.message }))
  },
  setPermissionMode: (mode) => {
    const previous = get().permissionMode
    set({ permissionMode: mode })
    const sessionId = get().activeSessionId
    if (!sessionId) return
    void api
      .updateSession(sessionId, { permission_mode: mode })
      .then(async (updated) => {
        set({
          sessions: get().sessions.map((item) =>
            item.id === sessionId ? { ...item, permission_mode: updated.permission_mode } : item
          )
        })
        if (get().activeSessionId === sessionId && get().permissionMode === mode && !get().streaming) {
          await get().refreshPending()
        }
      })
      .catch((error: Error) => {
        if (get().activeSessionId === sessionId) set({ permissionMode: previous, error: error.message })
      })
  },

  setWritingStyle: (style) => set({ writingStyle: style }),
  setPendingComposer: (text) => set({ pendingComposer: text })
  }
})

function firstManuscript(nodes: TreeNode[]): string | null {
  for (const node of nodes) {
    if (node.type === 'file' && node.path.endsWith('.md') && node.path.startsWith('manuscript')) {
      return node.path
    }
    if (node.children) {
      const found = firstManuscript(node.children)
      if (found) return found
    }
  }
  return null
}

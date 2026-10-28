import { create } from 'zustand'
import { api, streamChat } from './api'
import type {
  AppConfig,
  AppView,
  Entity,
  Expert,
  KbKind,
  Overview,
  Project,
  SearchHit,
  Session,
  TimelineItem,
  TreeNode
} from './types'

export interface OpenFile {
  path: string
  content: string
  dirty: boolean
}

type RightTab = 'kb' | 'files' | 'diff' | 'side' | 'doc'

interface AppState {
  ready: boolean
  error: string | null
  config: AppConfig | null

  projects: Project[]
  activeProject: Project | null
  overview: Overview | null

  sessions: Session[]
  activeSessionId: string | null
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

  leftCollapsed: boolean
  rightCollapsed: boolean
  leftWidth: number
  rightWidth: number
  view: AppView
  experts: Expert[]
  builder: 'expert' | 'skill' | null
  settingsOpen: boolean
  projectModalOpen: boolean
  expertModalOpen: boolean
  skillsModalOpen: boolean
  writingStyle: string
  currentExpertId: string
  pendingComposer: string | null

  bootstrap: () => Promise<void>
  createProject: (name: string, title: string, author?: string) => Promise<void>
  selectProject: (projectId: string) => Promise<void>
  refreshOverview: () => Promise<void>

  refreshSessions: () => Promise<void>
  newSession: () => Promise<Session | null>
  selectSession: (sessionId: string) => Promise<void>
  removeSession: (sessionId: string) => Promise<void>

  sendMessage: (text: string) => Promise<void>
  stopStreaming: () => void

  refreshTree: () => Promise<void>
  openFileByPath: (path: string) => Promise<void>
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
  saveConfig: (config: AppConfig) => Promise<void>

  clearError: () => void
  toggleLeft: () => void
  toggleRight: () => void
  setView: (view: AppView) => void
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
  setWritingStyle: (style: string) => void
  setPendingComposer: (text: string | null) => void
}

let seq = 0
const uid = (): string => `t${Date.now()}-${seq++}`

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

export const useAppStore = create<AppState>((set, get) => ({
  ready: false,
  error: null,
  config: null,
  projects: [],
  activeProject: null,
  overview: null,
  sessions: [],
  activeSessionId: null,
  timeline: [],
  streaming: false,
  tree: [],
  openFile: null,
  rightTab: 'kb',
  kbKind: 'characters',
  kbItems: [],
  kbActive: null,
  kbSearch: [],
  diff: '',
  leftCollapsed: false,
  rightCollapsed: false,
  leftWidth: 268,
  rightWidth: 344,
  view: 'chat',
  experts: [],
  builder: null,
  settingsOpen: false,
  projectModalOpen: false,
  expertModalOpen: false,
  skillsModalOpen: false,
  writingStyle: '',
  currentExpertId: 'general',
  pendingComposer: null,

  bootstrap: async () => {
    for (let attempt = 0; attempt < 6; attempt += 1) {
      try {
        const [projects, config] = await Promise.all([api.listProjects(), api.getConfig()])
        set({ projects, config, ready: true, error: null })
        if (projects.length > 0) await get().selectProject(projects[0].id)
        return
      } catch {
        if (attempt === 5) {
          set({ ready: true, error: '无法连接本地后端，请确认服务已启动后刷新' })
          return
        }
        await new Promise((resolve) => setTimeout(resolve, 800))
      }
    }
  },

  createProject: async (name, title, author) => {
    try {
      const project = await api.createProject({ name, title, author })
      const projects = await api.listProjects()
      set({ projects, projectModalOpen: false })
      await get().selectProject(project.id)
    } catch (error) {
      set({ error: (error as Error).message })
    }
  },

  selectProject: async (projectId) => {
    const project = get().projects.find((item) => item.id === projectId)
    if (!project) return
    set({
      activeProject: project,
      overview: null,
      sessions: [],
      activeSessionId: null,
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
      const file = firstManuscript(tree)
      if (file) await get().openFileByPath(file)
      await get().loadKb(get().kbKind)
      await get().loadExperts()
      const mainSessions = sessions.filter((session) => session.kind === 'main')
      if (mainSessions.length > 0) await get().selectSession(mainSessions[0].id)
    } catch (error) {
      set({ error: (error as Error).message })
    }
  },

  refreshOverview: async () => {
    const project = get().activeProject
    if (!project) return
    try {
      const overview = await api.overview(project.id)
      set({ overview, activeProject: { ...project, meta: overview.book } })
    } catch {
      /* 忽略概览刷新失败 */
    }
  },

  refreshSessions: async () => {
    const project = get().activeProject
    if (!project) return
    try {
      const sessions = await api.listSessions(project.id)
      set({ sessions })
    } catch (error) {
      set({ error: (error as Error).message })
    }
  },

  newSession: async () => {
    const project = get().activeProject
    if (!project) return null
    try {
      const session = await api.createSession(project.id)
      set({
        sessions: [session, ...get().sessions],
        activeSessionId: session.id,
        timeline: [],
        builder: null
      })
      return session
    } catch (error) {
      set({ error: (error as Error).message })
      return null
    }
  },

  selectSession: async (sessionId) => {
    set({ activeSessionId: sessionId, timeline: [], error: null })
    try {
      const messages = await api.messages(sessionId)
      set({
        timeline: messages
          .filter((message) => message.content.trim().length > 0)
          .map((message) => ({
            id: `m${message.id}`,
            type: message.role,
            content: message.content
          }))
      })
    } catch (error) {
      set({ error: (error as Error).message })
    }
  },

  removeSession: async (sessionId) => {
    try {
      await api.deleteSession(sessionId)
      const sessions = get().sessions.filter((item) => item.id !== sessionId)
      set({ sessions })
      if (get().activeSessionId === sessionId) {
        set({ activeSessionId: null, timeline: [] })
        if (sessions.length > 0) await get().selectSession(sessions[0].id)
      }
    } catch (error) {
      set({ error: (error as Error).message })
    }
  },

  sendMessage: async (text) => {
    const message = text.trim()
    if (!message || get().streaming) return
    let sessionId = get().activeSessionId
    if (!sessionId) {
      const session = await get().newSession()
      if (!session) return
      sessionId = session.id
    }

    set((state) => ({
      timeline: [...state.timeline, { id: uid(), type: 'user', content: message }],
      streaming: true,
      error: null
    }))

    let assistantId: string | null = null

    const builder = get().builder
    const mode =
      builder === 'expert' ? 'expert_builder' : builder === 'skill' ? 'skill_builder' : 'main'

    await streamChat(sessionId, message, builder ? '' : get().writingStyle, mode, {
      onToken: (token) => {
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
      onToolStart: (name, input) => {
        assistantId = null
        set((state) => ({
          timeline: [
            ...state.timeline,
            { id: uid(), type: 'tool', name, input, status: 'running' }
          ]
        }))
      },
      onToolEnd: (name, output) => {
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
      onError: (errorMessage) => {
        set((state) => ({
          timeline: [...state.timeline, { id: uid(), type: 'error', content: errorMessage }]
        }))
      },
      onDone: () => {
        set({ streaming: false })
        void get().refreshSessions()
        void get().refreshOverview()
        void get().refreshDiff()
      }
    })
  },

  stopStreaming: () => set({ streaming: false }),

  refreshTree: async () => {
    const project = get().activeProject
    if (!project) return
    try {
      set({ tree: await api.tree(project.id) })
    } catch (error) {
      set({ error: (error as Error).message })
    }
  },

  openFileByPath: async (path) => {
    const project = get().activeProject
    if (!project) return
    try {
      const file = await api.readFile(project.id, path)
      set({
        openFile: { path: file.path, content: file.content, dirty: false },
        rightTab: 'doc',
        rightCollapsed: false
      })
    } catch (error) {
      set({ error: (error as Error).message })
    }
  },

  updateOpenFile: (content) => {
    const openFile = get().openFile
    if (!openFile) return
    set({ openFile: { ...openFile, content, dirty: true } })
  },

  saveOpenFile: async () => {
    const project = get().activeProject
    const openFile = get().openFile
    if (!project || !openFile) return
    try {
      await api.writeFile(project.id, openFile.path, openFile.content)
      set({ openFile: { ...openFile, dirty: false } })
      await get().refreshDiff()
      await get().refreshOverview()
    } catch (error) {
      set({ error: (error as Error).message })
    }
  },

  setRightTab: (tab) => {
    set({ rightTab: tab })
    if (tab === 'diff') void get().refreshDiff()
    if (tab === 'files') void get().refreshTree()
  },

  loadKb: async (kind) => {
    const project = get().activeProject
    if (!project) return
    try {
      set({ kbKind: kind, kbItems: await api.entities(project.id, kind), kbActive: null })
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
      await get().reindexKb()
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
      await get().reindexKb()
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
      await get().reindexKb()
    } catch (error) {
      set({ error: (error as Error).message })
    }
  },

  reindexKb: async () => {
    const project = get().activeProject
    if (!project) return
    try {
      await api.reindex(project.id)
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

  saveConfig: async (config) => {
    try {
      const saved = await api.saveConfig(config)
      set({ config: saved, settingsOpen: false })
    } catch (error) {
      set({ error: (error as Error).message })
    }
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
  setRightWidth: (width) => set({ rightWidth: Math.min(480, Math.max(280, width)) }),
  setSettingsOpen: (open) => set({ settingsOpen: open }),
  setProjectModalOpen: (open) => set({ projectModalOpen: open }),
  setExpertModalOpen: (open) => set({ expertModalOpen: open }),
  setSkillsModalOpen: (open) => set({ skillsModalOpen: open }),
  setExpert: (expertId) => {
    const expert = get().experts.find((item) => item.id === expertId)
    set({ currentExpertId: expertId, writingStyle: expert?.prompt ?? '' })
  },
  setWritingStyle: (style) => set({ writingStyle: style }),
  setPendingComposer: (text) => set({ pendingComposer: text })
}))

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

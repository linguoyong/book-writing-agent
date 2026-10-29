import {
  Brain,
  Folder,
  Library,
  MessageSquare,
  Plus,
  Settings,
  ShieldCheck,
  Sparkles,
  Stethoscope,
  Trash2,
  Wand2
} from 'lucide-react'
import { useAppStore } from '../store'

export default function LeftSidebar(): React.JSX.Element {
  const projects = useAppStore((state) => state.projects)
  const activeProject = useAppStore((state) => state.activeProject)
  const sessions = useAppStore((state) => state.sessions)
  const activeSessionId = useAppStore((state) => state.activeSessionId)
  const overview = useAppStore((state) => state.overview)
  const spaceSummaries = useAppStore((state) => state.spaceSummaries)
  const view = useAppStore((state) => state.view)
  const leftWidth = useAppStore((state) => state.leftWidth)
  const setLeftWidth = useAppStore((state) => state.setLeftWidth)
  const selectProject = useAppStore((state) => state.selectProject)
  const newSession = useAppStore((state) => state.newSession)
  const selectSession = useAppStore((state) => state.selectSession)
  const removeSession = useAppStore((state) => state.removeSession)
  const setProjectModalOpen = useAppStore((state) => state.setProjectModalOpen)
  const setSettingsOpen = useAppStore((state) => state.setSettingsOpen)
  const setView = useAppStore((state) => state.setView)

  const visibleSessions = sessions.filter((session) => session.kind !== 'side')
  const kbCount = overview
    ? Object.values(overview.kb_counts).reduce((total, count) => total + count, 0)
    : 0

  const startResize = (event: React.MouseEvent): void => {
    event.preventDefault()
    const startX = event.clientX
    const startWidth = leftWidth
    const onMove = (moveEvent: MouseEvent): void => {
      setLeftWidth(startWidth + moveEvent.clientX - startX)
    }
    const onUp = (): void => {
      document.removeEventListener('mousemove', onMove)
      document.removeEventListener('mouseup', onUp)
      document.body.style.cursor = ''
    }
    document.body.style.cursor = 'col-resize'
    document.addEventListener('mousemove', onMove)
    document.addEventListener('mouseup', onUp)
  }

  return (
    <aside className="left-sidebar" style={{ width: leftWidth }}>
      <div className="left-section">
        <button
          className="new-chat-btn"
          onClick={() => {
            if (!activeProject) {
              setProjectModalOpen(true)
              return
            }
            setView('chat')
            void newSession()
          }}
        >
          <Plus size={14} />
          新建会话
        </button>
      </div>

      <div className="left-manage">
        <button
          className={`nav-item ${view === 'experts' ? 'active' : ''}`}
          onClick={() => setView('experts')}
        >
          <Sparkles size={14} />
          <span className="label">专家</span>
        </button>
        <button
          className={`nav-item ${view === 'skills' ? 'active' : ''}`}
          onClick={() => setView('skills')}
        >
          <Wand2 size={14} />
          <span className="label">技能管理</span>
        </button>
        <button
          className={`nav-item ${view === 'knowledge' ? 'active' : ''}`}
          onClick={() => setView('knowledge')}
        >
          <Library size={14} />
          <span className="label">知识库</span>
          <span className="hint">{kbCount}</span>
        </button>
        <button
          className={`nav-item ${view === 'memory' ? 'active' : ''}`}
          onClick={() => setView('memory')}
        >
          <Brain size={14} />
          <span className="label">记忆</span>
        </button>
        <button
          className={`nav-item ${view === 'approvals' ? 'active' : ''}`}
          onClick={() => setView('approvals')}
        >
          <ShieldCheck size={14} />
          <span className="label">审批</span>
        </button>
        <button
          className={`nav-item ${view === 'diagnostics' ? 'active' : ''}`}
          onClick={() => setView('diagnostics')}
        >
          <Stethoscope size={14} />
          <span className="label">诊断</span>
        </button>
      </div>

      <div className="left-scroll">
        <section>
          <div className="left-section-title">
            <span>空间</span>
            <span className="hint">{projects.length}</span>
            <button
              className="icon-btn"
              style={{ width: 20, height: 20 }}
              onClick={() => setProjectModalOpen(true)}
              title="新建或打开空间"
            >
              <Plus size={12} />
            </button>
          </div>
          {projects.map((project) => {
            const summary = spaceSummaries[project.id]
            return (
              <div
                key={project.id}
                className={`space-item ${project.id === activeProject?.id ? 'active' : ''}`}
                onClick={() => void selectProject(project.id)}
                title={project.path}
              >
                <Folder size={14} />
                <div className="space-text">
                  <span className="label">{project.name}</span>
                  <span className="space-sub">{summary?.last || '暂无会话'}</span>
                </div>
                <span className="space-count">{summary?.count ?? 0}</span>
              </div>
            )
          })}
        </section>

        <section>
          <div className="left-section-title">
            <span>会话</span>
            <span className="hint">{visibleSessions.length}</span>
          </div>
          {visibleSessions.length === 0 && (
            <div style={{ padding: '4px 10px 10px', color: 'var(--faint)', fontSize: 12 }}>
              还没有会话
            </div>
          )}
          {visibleSessions.map((session) => (
            <div
              key={session.id}
              className={`list-item ${
                view === 'chat' && session.id === activeSessionId ? 'active' : ''
              }`}
              onClick={() => {
                setView('chat')
                void selectSession(session.id)
              }}
            >
              <MessageSquare size={13} />
              <span className="label">{session.title}</span>
              <button
                className="delete"
                onClick={(event) => {
                  event.stopPropagation()
                  if (window.confirm('删除这个会话？')) void removeSession(session.id)
                }}
                title="删除会话"
              >
                <Trash2 size={12} />
              </button>
            </div>
          ))}
        </section>
      </div>

      <div className="left-footer">
        <button className="small-btn" onClick={() => setSettingsOpen(true)}>
          <Settings size={12} />
          模型设置
        </button>
        <span style={{ fontSize: 11, color: 'var(--faint)', marginLeft: 'auto' }}>
          {overview?.index?.chunks ?? 0} 块索引
        </span>
      </div>

      <div className="resize-handle" onMouseDown={startResize} />
    </aside>
  )
}

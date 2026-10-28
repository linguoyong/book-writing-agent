import { BookOpen, Library, MessageSquare, Plus, Settings, Sparkles, Trash2, Wand2 } from 'lucide-react'
import { EXPERTS } from '../experts'
import { useAppStore } from '../store'
import EditorPane from './EditorPane'

export default function LeftSidebar(): React.JSX.Element {
  const leftTab = useAppStore((state) => state.leftTab)
  const setLeftTab = useAppStore((state) => state.setLeftTab)
  const leftWidth = useAppStore((state) => state.leftWidth)
  const setLeftWidth = useAppStore((state) => state.setLeftWidth)

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
      <div className="left-tabs">
        <button
          className={`left-tab ${leftTab === 'chats' ? 'active' : ''}`}
          onClick={() => setLeftTab('chats')}
        >
          会话
        </button>
        <button
          className={`left-tab ${leftTab === 'files' ? 'active' : ''}`}
          onClick={() => setLeftTab('files')}
        >
          文稿
        </button>
      </div>

      <div className="left-content">
        {leftTab === 'chats' ? <ChatsView /> : <EditorPane />}
      </div>

      <div className="resize-handle" onMouseDown={startResize} />
    </aside>
  )
}

function ChatsView(): React.JSX.Element {
  const projects = useAppStore((state) => state.projects)
  const activeProject = useAppStore((state) => state.activeProject)
  const sessions = useAppStore((state) => state.sessions)
  const activeSessionId = useAppStore((state) => state.activeSessionId)
  const overview = useAppStore((state) => state.overview)
  const rightCollapsed = useAppStore((state) => state.rightCollapsed)
  const selectProject = useAppStore((state) => state.selectProject)
  const newSession = useAppStore((state) => state.newSession)
  const selectSession = useAppStore((state) => state.selectSession)
  const removeSession = useAppStore((state) => state.removeSession)
  const setProjectModalOpen = useAppStore((state) => state.setProjectModalOpen)
  const setSettingsOpen = useAppStore((state) => state.setSettingsOpen)
  const setExpertModalOpen = useAppStore((state) => state.setExpertModalOpen)
  const setSkillsModalOpen = useAppStore((state) => state.setSkillsModalOpen)
  const setRightTab = useAppStore((state) => state.setRightTab)
  const toggleRight = useAppStore((state) => state.toggleRight)

  const visibleSessions = sessions.filter((session) => session.kind !== 'side')
  const kbCount = overview
    ? Object.values(overview.kb_counts).reduce((total, count) => total + count, 0)
    : 0

  return (
    <>
      <div className="left-section">
        <button className="new-chat-btn" onClick={() => void newSession()}>
          <Plus size={14} />
          新建会话
        </button>
      </div>

      <div className="left-manage">
        <div className="list-item" onClick={() => setExpertModalOpen(true)}>
          <Sparkles size={13} />
          <span className="label">专家</span>
          <span className="hint">{EXPERTS.length}</span>
        </div>
        <div className="list-item" onClick={() => setSkillsModalOpen(true)}>
          <Wand2 size={13} />
          <span className="label">技能管理</span>
        </div>
        <div
          className="list-item"
          onClick={() => {
            setRightTab('kb')
            if (rightCollapsed) toggleRight()
          }}
        >
          <Library size={13} />
          <span className="label">知识库</span>
          <span className="hint">{kbCount}</span>
        </div>
      </div>

      <div className="left-scroll">
        <section>
          <div className="left-section-title">
            <span>项目</span>
            <button
              className="icon-btn"
              style={{ width: 20, height: 20 }}
              onClick={() => setProjectModalOpen(true)}
              title="新建项目"
            >
              <Plus size={12} />
            </button>
          </div>
          {projects.map((project) => (
            <div
              key={project.id}
              className={`list-item ${project.id === activeProject?.id ? 'active' : ''}`}
              onClick={() => void selectProject(project.id)}
              title={project.path}
            >
              <BookOpen size={13} />
              <span className="label">{project.name}</span>
            </div>
          ))}
        </section>

        <section>
          <div className="left-section-title">
            <span>历史会话</span>
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
              className={`list-item ${session.id === activeSessionId ? 'active' : ''}`}
              onClick={() => void selectSession(session.id)}
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
    </>
  )
}

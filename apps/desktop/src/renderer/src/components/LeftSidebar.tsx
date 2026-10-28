import { BookOpen, MessageSquare, Plus, Settings, Trash2 } from 'lucide-react'
import { useAppStore } from '../store'

const STYLES = [
  { label: '冷峻克制', prompt: '冷峻克制的第三人称叙事，短句为主，少用形容词，情绪藏在动作里' },
  { label: '细腻抒情', prompt: '细腻抒情的叙事，注重感官与心理描写，节奏舒缓' },
  { label: '快节奏', prompt: '快节奏爽文风格，冲突密集，段落短，章末留钩子' },
  { label: '古典雅致', prompt: '古典雅致的白话文风，用词典雅，句式整饬' },
  { label: '悬疑冷调', prompt: '悬疑冷调叙事，信息克制，氛围压迫，善用留白' }
]

export default function LeftSidebar(): React.JSX.Element {
  const projects = useAppStore((state) => state.projects)
  const activeProject = useAppStore((state) => state.activeProject)
  const sessions = useAppStore((state) => state.sessions)
  const activeSessionId = useAppStore((state) => state.activeSessionId)
  const overview = useAppStore((state) => state.overview)
  const writingStyle = useAppStore((state) => state.writingStyle)
  const selectProject = useAppStore((state) => state.selectProject)
  const newSession = useAppStore((state) => state.newSession)
  const selectSession = useAppStore((state) => state.selectSession)
  const removeSession = useAppStore((state) => state.removeSession)
  const setProjectModalOpen = useAppStore((state) => state.setProjectModalOpen)
  const setSettingsOpen = useAppStore((state) => state.setSettingsOpen)
  const setWritingStyle = useAppStore((state) => state.setWritingStyle)

  const visibleSessions = sessions.filter((session) => session.kind !== 'side')

  return (
    <aside className="left-sidebar">
      <div className="left-section">
        <button className="new-chat-btn" onClick={() => void newSession()}>
          <Plus size={14} />
          新建会话
        </button>
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

        <section>
          <div className="left-section-title">
            <span>写作风格</span>
          </div>
          <div className="expert-grid">
            {STYLES.map((style) => (
              <button
                key={style.label}
                className={`expert-chip ${writingStyle === style.prompt ? 'active' : ''}`}
                onClick={() => setWritingStyle(writingStyle === style.prompt ? '' : style.prompt)}
                title={style.prompt}
              >
                {style.label}
              </button>
            ))}
          </div>
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
    </aside>
  )
}

import { useState } from 'react'
import {
  Archive,
  Brain,
  ChevronDown,
  ChevronRight,
  Folder,
  FolderPlus,
  Library,
  Maximize2,
  Minimize2,
  Pencil,
  Plus,
  RotateCcw,
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
  const allSessions = useAppStore((state) => state.allSessions)
  const activeSessionId = useAppStore((state) => state.activeSessionId)
  const view = useAppStore((state) => state.view)
  const leftWidth = useAppStore((state) => state.leftWidth)
  const setLeftWidth = useAppStore((state) => state.setLeftWidth)
  const selectProject = useAppStore((state) => state.selectProject)
  const newSession = useAppStore((state) => state.newSession)
  const openSession = useAppStore((state) => state.openSession)
  const removeSession = useAppStore((state) => state.removeSession)
  const renameSession = useAppStore((state) => state.renameSession)
  const archiveSession = useAppStore((state) => state.archiveSession)
  const setProjectModalOpen = useAppStore((state) => state.setProjectModalOpen)
  const setView = useAppStore((state) => state.setView)

  const [editingId, setEditingId] = useState<string | null>(null)
  const [draftTitle, setDraftTitle] = useState('')
  const [expandedSpaces, setExpandedSpaces] = useState<Set<string>>(new Set())
  const [spacesTouched, setSpacesTouched] = useState(false)
  const [archivedOpen, setArchivedOpen] = useState<Set<string>>(new Set())

  const isSpaceExpanded = (id: string): boolean =>
    spacesTouched ? expandedSpaces.has(id) : true

  const toggleSpace = (id: string): void => {
    const current = new Set(
      spacesTouched ? expandedSpaces : projects.map((project) => project.id)
    )
    if (current.has(id)) current.delete(id)
    else current.add(id)
    setExpandedSpaces(current)
    setSpacesTouched(true)
  }

  const expandSpace = (id: string): void => {
    if (isSpaceExpanded(id)) return
    const current = new Set(expandedSpaces)
    current.add(id)
    setExpandedSpaces(current)
    setSpacesTouched(true)
  }

  const allSpacesCollapsed = spacesTouched && expandedSpaces.size === 0

  const toggleAllSpaces = (): void => {
    if (allSpacesCollapsed) {
      setExpandedSpaces(new Set(projects.map((project) => project.id)))
    } else {
      setExpandedSpaces(new Set())
    }
    setSpacesTouched(true)
  }

  const toggleArchived = (id: string): void => {
    setArchivedOpen((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

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
        <section className="left-section spaces-section">
          <div className="left-section-title">
            <span className="section-label">
              空间 <span className="section-count">({projects.length})</span>
            </span>
            <span className="section-actions">
              <button
                className="icon-btn"
                onClick={toggleAllSpaces}
                title={allSpacesCollapsed ? '展开所有空间' : '折叠所有空间'}
              >
                {allSpacesCollapsed ? <Maximize2 size={12} /> : <Minimize2 size={12} />}
              </button>
              <button
                className="icon-btn"
                onClick={() => setProjectModalOpen(true)}
                title="新建工作空间"
              >
                <FolderPlus size={13} />
              </button>
            </span>
          </div>

          {projects.map((project) => {
            const expanded = isSpaceExpanded(project.id)
            const projectSessions = allSessions.filter(
              (session) => session.project_id === project.id && !session.archived
            )
            const projectArchived = allSessions.filter(
              (session) => session.project_id === project.id && session.archived
            )
            return (
              <div key={project.id} className="space-group">
                <div
                  className={`space-row ${project.id === activeProject?.id ? 'current' : ''}`}
                  onClick={() => {
                    expandSpace(project.id)
                    setView('chat')
                    void selectProject(project.id)
                  }}
                  title={project.path}
                >
                  <button
                    className="space-toggle"
                    onClick={(event) => {
                      event.stopPropagation()
                      toggleSpace(project.id)
                    }}
                    title={expanded ? '折叠空间' : '展开空间'}
                  >
                    {expanded ? <ChevronDown size={11} /> : <ChevronRight size={11} />}
                  </button>
                  <Folder size={13} className="space-folder" />
                  <span className="space-name">{project.name}</span>
                </div>

                {expanded && (
                  <div className="space-sessions">
                    {projectSessions.map((session) => (
                      <div
                        key={session.id}
                        className={`session-row ${
                          view === 'chat' && session.id === activeSessionId ? 'active' : ''
                        }`}
                        onClick={() => {
                          if (editingId === session.id) return
                          void openSession(project.id, session.id)
                        }}
                      >
                        {editingId === session.id ? (
                          <input
                            className="session-rename"
                            value={draftTitle}
                            autoFocus
                            onClick={(event) => event.stopPropagation()}
                            onChange={(event) => setDraftTitle(event.target.value)}
                            onKeyDown={(event) => {
                              if (event.key === 'Enter') {
                                void renameSession(session.id, draftTitle)
                                setEditingId(null)
                              }
                              if (event.key === 'Escape') setEditingId(null)
                            }}
                            onBlur={() => {
                              if (draftTitle.trim() && draftTitle.trim() !== session.title) {
                                void renameSession(session.id, draftTitle)
                              }
                              setEditingId(null)
                            }}
                          />
                        ) : (
                          <span className="session-title">{session.title}</span>
                        )}
                        <span className="session-time">{relativeTime(session.updated_at)}</span>
                        <div className="session-actions">
                          <button
                            onClick={(event) => {
                              event.stopPropagation()
                              setEditingId(session.id)
                              setDraftTitle(session.title)
                            }}
                            title="重命名"
                          >
                            <Pencil size={11} />
                          </button>
                          <button
                            onClick={(event) => {
                              event.stopPropagation()
                              void archiveSession(session.id, true)
                            }}
                            title="归档"
                          >
                            <Archive size={11} />
                          </button>
                          <button
                            onClick={(event) => {
                              event.stopPropagation()
                              if (window.confirm('删除这个会话？')) void removeSession(session.id)
                            }}
                            title="删除会话"
                          >
                            <Trash2 size={11} />
                          </button>
                        </div>
                      </div>
                    ))}

                    {projectSessions.length === 0 && (
                      <div className="space-empty">还没有会话</div>
                    )}

                    {projectArchived.length > 0 && (
                      <div className="archived-block">
                        <button
                          className="archived-toggle"
                          onClick={() => toggleArchived(project.id)}
                        >
                          {archivedOpen.has(project.id) ? (
                            <ChevronDown size={11} />
                          ) : (
                            <ChevronRight size={11} />
                          )}
                          已归档 · {projectArchived.length}
                        </button>
                        {archivedOpen.has(project.id) &&
                          projectArchived.map((session) => (
                            <div key={session.id} className="session-row archived">
                              <span className="session-title">{session.title}</span>
                              <button
                                className="session-restore"
                                onClick={() => void archiveSession(session.id, false)}
                                title="恢复会话"
                              >
                                <RotateCcw size={11} />
                              </button>
                            </div>
                          ))}
                      </div>
                    )}
                  </div>
                )}
              </div>
            )
          })}
        </section>

      </div>

      <div className="resize-handle" onMouseDown={startResize} />
    </aside>
  )
}

/** 会话时间：刚刚 / n分钟前 / n小时前 / 昨天 / 月日 */
function relativeTime(value: string): string {
  const time = new Date(value).getTime()
  if (Number.isNaN(time)) return ''
  const diff = Date.now() - time
  const minute = 60_000
  if (diff < minute) return '刚刚'
  if (diff < 60 * minute) return `${Math.floor(diff / minute)}分钟前`
  if (diff < 24 * 60 * minute) return `${Math.floor(diff / (60 * minute))}小时前`
  if (diff < 48 * 60 * minute) return '昨天'
  const date = new Date(time)
  return `${date.getMonth() + 1}月${date.getDate()}日`
}

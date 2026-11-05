import { useEffect, useState } from 'react'
import {
  Archive,
  BarChart3,
  Brain,
  ChevronDown,
  ChevronRight,
  FileText,
  Folder,
  FolderPlus,
  History,
  Library,
  Loader2,
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
import { formatRelativeTime } from '../format'
import { useAppStore } from '../store'
import ConfirmDialog, { type ConfirmRequest } from './ConfirmDialog'

export default function LeftSidebar(): React.JSX.Element {
  const projects = useAppStore((state) => state.projects)
  const activeProject = useAppStore((state) => state.activeProject)
  const allSessions = useAppStore((state) => state.allSessions)
  const activeSessionId = useAppStore((state) => state.activeSessionId)
  const refreshAllSessions = useAppStore((state) => state.refreshAllSessions)
  const view = useAppStore((state) => state.view)
  const leftWidth = useAppStore((state) => state.leftWidth)
  const setLeftWidth = useAppStore((state) => state.setLeftWidth)
  const selectProject = useAppStore((state) => state.selectProject)
  const startDraft = useAppStore((state) => state.startDraft)
  const openSession = useAppStore((state) => state.openSession)
  const removeSession = useAppStore((state) => state.removeSession)
  const renameSession = useAppStore((state) => state.renameSession)
  const archiveSession = useAppStore((state) => state.archiveSession)
  const deleteProject = useAppStore((state) => state.deleteProject)
  const setProjectModalOpen = useAppStore((state) => state.setProjectModalOpen)
  const setView = useAppStore((state) => state.setView)

  const [editingId, setEditingId] = useState<string | null>(null)
  const [draftTitle, setDraftTitle] = useState('')
  const [expandedSpaces, setExpandedSpaces] = useState<Set<string>>(new Set())
  const [spacesTouched, setSpacesTouched] = useState(false)
  const [archivedOpen, setArchivedOpen] = useState<Set<string>>(new Set())
  const [confirm, setConfirm] = useState<ConfirmRequest | null>(null)

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

  const removeProject = async (project: {
    id: string
    name: string
    path: string
  }): Promise<void> => {
    setConfirm({
      title: `删除空间「${project.name}」`,
      message: `空间下的全部会话与磁盘目录将一并删除：\n${project.path}\n\n此操作不可恢复。`,
      danger: true,
      confirmLabel: '删除空间',
      onConfirm: () => void deleteProject(project.id, true)
    })
  }

  // 有会话在跑就周期性刷新列表，跑完自动停：转圈要能自己消失
  const anyRunning = allSessions.some((session) => session.running)
  useEffect(() => {
    if (!anyRunning) return
    const timer = window.setInterval(() => void refreshAllSessions(), 4000)
    return () => window.clearInterval(timer)
  }, [anyRunning, refreshAllSessions])

  // 发出第一条消息后新会话会挂到当前空间下；空间若是折叠的就把它摊开
  useEffect(() => {
    if (!activeSessionId || !activeProject) return
    expandSpace(activeProject.id)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeSessionId, activeProject?.id])

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
            // 只是进入草稿态：左侧不落条目，发出第一条消息时才创建会话
            startDraft()
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
          className={`nav-item ${view === 'history' ? 'active' : ''}`}
          onClick={() => setView('history')}
        >
          <History size={14} />
          <span className="label">版本</span>
        </button>
        <button
          className={`nav-item ${view === 'usage' ? 'active' : ''}`}
          onClick={() => setView('usage')}
        >
          <BarChart3 size={14} />
          <span className="label">用量</span>
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
          className={`nav-item ${view === 'prompts' ? 'active' : ''}`}
          onClick={() => setView('prompts')}
          title="编辑系统提示词的各层内容"
        >
          <FileText size={14} />
          <span className="label">提示词</span>
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
                  <Folder size={13} className="space-folder" />
                  <span className="space-name">{project.name}</span>
                  <button
                    className="space-delete"
                    onClick={(event) => {
                      event.stopPropagation()
                      void removeProject(project)
                    }}
                    title="删除空间"
                  >
                    <Trash2 size={12} />
                  </button>
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
                          <span className="session-title">
                            {session.running && (
                              <Loader2 size={11} className="spin session-running" />
                            )}
                            {session.title}
                          </span>
                        )}
                        <span className="session-time">{formatRelativeTime(session.updated_at)}</span>
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
                              setConfirm({
                                title: '删除会话',
                                message: `「${session.title}」的对话记录将一并删除，不可恢复。`,
                                danger: true,
                                confirmLabel: '删除',
                                onConfirm: () => void removeSession(session.id)
                              })
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
      <ConfirmDialog request={confirm} onClose={() => setConfirm(null)} />
    </aside>
  )
}

/** 会话时间：刚刚 / n分钟前 / n小时前 / 昨天 / 月日 */

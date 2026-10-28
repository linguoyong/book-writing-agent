import { useEffect, useState } from 'react'
import { X } from 'lucide-react'
import { useAppStore } from './store'
import TitleBar from './components/TitleBar'
import LeftSidebar from './components/LeftSidebar'
import ChatPane from './components/ChatPane'
import RightSidebar from './components/RightSidebar'
import ProjectModal from './components/ProjectModal'
import SettingsModal from './components/SettingsModal'
import ExpertsPage from './views/ExpertsPage'
import SkillsPage from './views/SkillsPage'
import KnowledgePage from './views/KnowledgePage'

export default function App(): React.JSX.Element {
  const ready = useAppStore((state) => state.ready)
  const projects = useAppStore((state) => state.projects)
  const view = useAppStore((state) => state.view)
  const leftCollapsed = useAppStore((state) => state.leftCollapsed)
  const rightCollapsed = useAppStore((state) => state.rightCollapsed)
  const leftWidth = useAppStore((state) => state.leftWidth)
  const settingsOpen = useAppStore((state) => state.settingsOpen)
  const projectModalOpen = useAppStore((state) => state.projectModalOpen)
  const error = useAppStore((state) => state.error)
  const clearError = useAppStore((state) => state.clearError)
  const bootstrap = useAppStore((state) => state.bootstrap)

  const [leftHover, setLeftHover] = useState(false)

  useEffect(() => {
    void bootstrap()
  }, [bootstrap])

  useEffect(() => {
    if (!leftCollapsed) setLeftHover(false)
  }, [leftCollapsed])

  if (!ready) {
    return <div className="boot-screen">正在连接本地写作引擎…</div>
  }

  const showProjectModal = projectModalOpen || projects.length === 0

  return (
    <div className="app">
      <TitleBar />
      <div className="workspace">
        {!leftCollapsed && <LeftSidebar />}
        <div className="main-area">
          {view === 'chat' && <ChatPane />}
          {view === 'experts' && <ExpertsPage />}
          {view === 'skills' && <SkillsPage />}
          {view === 'knowledge' && <KnowledgePage />}
        </div>
        {view === 'chat' && !rightCollapsed && <RightSidebar />}

        {leftCollapsed && (
          <div className="left-hover-zone" onMouseEnter={() => setLeftHover(true)} />
        )}
        {leftCollapsed && leftHover && (
          <div
            className="left-overlay"
            style={{ width: leftWidth }}
            onMouseEnter={() => setLeftHover(true)}
            onMouseLeave={() => setLeftHover(false)}
          >
            <LeftSidebar />
          </div>
        )}
      </div>

      {error && (
        <div
          className="error-banner"
          style={{
            position: 'fixed',
            top: 50,
            left: '50%',
            transform: 'translateX(-50%)',
            zIndex: 80
          }}
        >
          <span style={{ flex: 1 }}>{error}</span>
          <button className="icon-btn" onClick={clearError} title="关闭">
            <X size={13} />
          </button>
        </div>
      )}

      {settingsOpen && <SettingsModal />}
      {showProjectModal && <ProjectModal canClose={projects.length > 0} />}
    </div>
  )
}

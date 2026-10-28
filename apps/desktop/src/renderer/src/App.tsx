import { useEffect } from 'react'
import { useAppStore } from './store'
import TitleBar from './components/TitleBar'
import LeftSidebar from './components/LeftSidebar'
import CenterPane from './components/CenterPane'
import RightSidebar from './components/RightSidebar'
import ProjectModal from './components/ProjectModal'
import SettingsModal from './components/SettingsModal'
import { X } from 'lucide-react'

export default function App(): React.JSX.Element {
  const ready = useAppStore((state) => state.ready)
  const projects = useAppStore((state) => state.projects)
  const leftCollapsed = useAppStore((state) => state.leftCollapsed)
  const rightCollapsed = useAppStore((state) => state.rightCollapsed)
  const settingsOpen = useAppStore((state) => state.settingsOpen)
  const projectModalOpen = useAppStore((state) => state.projectModalOpen)
  const error = useAppStore((state) => state.error)
  const clearError = useAppStore((state) => state.clearError)
  const bootstrap = useAppStore((state) => state.bootstrap)

  useEffect(() => {
    void bootstrap()
  }, [bootstrap])

  if (!ready) {
    return <div className="boot-screen">正在连接本地写作引擎…</div>
  }

  const showProjectModal = projectModalOpen || projects.length === 0

  return (
    <div className="app">
      <TitleBar />
      <div className="workspace">
        {!leftCollapsed && <LeftSidebar />}
        <CenterPane />
        {!rightCollapsed && <RightSidebar />}
      </div>
      {error && (
        <div className="error-banner" style={{ position: 'fixed', top: 50, left: '50%', transform: 'translateX(-50%)', zIndex: 80 }}>
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

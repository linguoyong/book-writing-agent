import { useEffect, useState } from 'react'
import { X } from 'lucide-react'
import { setApiBase } from './api'
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
import MemoryPage from './views/MemoryPage'
import ApprovalsPage from './views/ApprovalsPage'
import DiagnosticsPage from './views/DiagnosticsPage'
import HistoryPage from './views/HistoryPage'
import UsagePage from './views/UsagePage'

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
  const toast = useAppStore((state) => state.toast)
  const bootstrap = useAppStore((state) => state.bootstrap)

  const [leftHover, setLeftHover] = useState(false)
  const [bootError, setBootError] = useState<string | null>(null)

  useEffect(() => {
    const init = async (): Promise<void> => {
      try {
        const info = await window.desktop?.backendInfo?.()
        if (info?.port) setApiBase(info.port, info.token ?? '')
        if (info?.error) setBootError(info.error)
      } catch {
        /* 浏览器预览没有 preload，沿用默认端口 */
      }
      await bootstrap()
    }
    void init()
  }, [bootstrap])

  useEffect(() => {
    if (!leftCollapsed) setLeftHover(false)
  }, [leftCollapsed])

  if (!ready) {
    return (
      <div className="boot-screen">
        <div>{bootError ?? '正在启动本地写作引擎…'}</div>
        {bootError && (
          <button className="small-btn" style={{ marginTop: 10 }} onClick={() => void bootstrap()}>
            重试连接
          </button>
        )}
      </div>
    )
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
          {view === 'memory' && <MemoryPage />}
          {view === 'approvals' && <ApprovalsPage />}
          {view === 'diagnostics' && <DiagnosticsPage />}
          {view === 'history' && <HistoryPage />}
          {view === 'usage' && <UsagePage />}
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

      {toast && <div className="toast">{toast}</div>}

      {settingsOpen && <SettingsModal />}
      {showProjectModal && <ProjectModal canClose={projects.length > 0} />}
    </div>
  )
}

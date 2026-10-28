import { useAppStore } from '../store'
import KnowledgePanel from './KnowledgePanel'
import FileTree from './FileTree'
import DiffPanel from './DiffPanel'
import SidePanel from './SidePanel'

export default function RightSidebar(): React.JSX.Element {
  const rightTab = useAppStore((state) => state.rightTab)
  const setRightTab = useAppStore((state) => state.setRightTab)

  const tabs = [
    { key: 'kb', label: '知识库' },
    { key: 'files', label: '文件' },
    { key: 'diff', label: '变更' },
    { key: 'side', label: '侧问' }
  ] as const

  return (
    <aside className="right-sidebar">
      <div className="right-tabs">
        {tabs.map((tab) => (
          <button
            key={tab.key}
            className={`right-tab ${rightTab === tab.key ? 'active' : ''}`}
            onClick={() => setRightTab(tab.key)}
          >
            {tab.label}
          </button>
        ))}
      </div>

      <div className="right-body" style={{ display: rightTab === 'kb' ? 'flex' : 'none' }}>
        <KnowledgePanel />
      </div>
      <div className="right-body" style={{ display: rightTab === 'files' ? 'flex' : 'none' }}>
        <FileTree />
      </div>
      <div className="right-body" style={{ display: rightTab === 'diff' ? 'flex' : 'none' }}>
        <DiffPanel />
      </div>
      <div className="right-body" style={{ display: rightTab === 'side' ? 'flex' : 'none' }}>
        <SidePanel />
      </div>
    </aside>
  )
}

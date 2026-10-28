import { useAppStore } from '../store'
import KnowledgePanel from './KnowledgePanel'
import FileTree from './FileTree'
import DiffPanel from './DiffPanel'
import SidePanel from './SidePanel'
import EditorPane from './EditorPane'

export default function RightSidebar(): React.JSX.Element {
  const rightTab = useAppStore((state) => state.rightTab)
  const setRightTab = useAppStore((state) => state.setRightTab)
  const rightWidth = useAppStore((state) => state.rightWidth)
  const setRightWidth = useAppStore((state) => state.setRightWidth)

  const startResize = (event: React.MouseEvent): void => {
    event.preventDefault()
    const startX = event.clientX
    const startWidth = rightWidth
    const onMove = (moveEvent: MouseEvent): void => {
      setRightWidth(startWidth - (moveEvent.clientX - startX))
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

  const tabs = [
    { key: 'doc', label: '文稿' },
    { key: 'kb', label: '知识库' },
    { key: 'files', label: '文件' },
    { key: 'diff', label: '变更' },
    { key: 'side', label: '侧问' }
  ] as const

  return (
    <aside className="right-sidebar" style={{ width: rightWidth }}>
      <div className="resize-handle left" onMouseDown={startResize} />
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

      <div className="right-body" style={{ display: rightTab === 'doc' ? 'flex' : 'none' }}>
        <EditorPane />
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

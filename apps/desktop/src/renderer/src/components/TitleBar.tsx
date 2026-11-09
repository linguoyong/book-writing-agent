import { Minus, PanelLeft, PanelRight, Settings, Square, X } from 'lucide-react'
import { useAppStore } from '../store'

export default function TitleBar(): React.JSX.Element {
  const leftCollapsed = useAppStore((state) => state.leftCollapsed)
  const rightCollapsed = useAppStore((state) => state.rightCollapsed)
  const toggleLeft = useAppStore((state) => state.toggleLeft)
  const toggleRight = useAppStore((state) => state.toggleRight)
  const setSettingsOpen = useAppStore((state) => state.setSettingsOpen)

  return (
    <header className="titlebar">
      <button
        className={`icon-btn ${leftCollapsed ? '' : 'active'}`}
        onClick={toggleLeft}
        title="切换左栏"
      >
        <PanelLeft size={15} />
      </button>

      <div className="brand">
        <span className="brand-mark" />
        写作 Agent
      </div>

      <div className="spacer" />

      <button className="icon-btn" onClick={() => setSettingsOpen(true)} title="设置">
        <Settings size={15} />
      </button>
      <button
        className={`icon-btn ${rightCollapsed ? '' : 'active'}`}
        onClick={toggleRight}
        title="切换右栏"
      >
        <PanelRight size={15} />
      </button>

      <div className="win-divider" />

      <div className="win-controls">
        <button className="win-btn" onClick={() => window.desktop?.minimize()} title="最小化">
          <Minus size={14} />
        </button>
        <button
          className="win-btn"
          onClick={() => window.desktop?.toggleMaximize()}
          title="最大化"
        >
          <Square size={12} />
        </button>
        <button className="win-btn close" onClick={() => window.desktop?.close()} title="关闭">
          <X size={14} />
        </button>
      </div>
    </header>
  )
}

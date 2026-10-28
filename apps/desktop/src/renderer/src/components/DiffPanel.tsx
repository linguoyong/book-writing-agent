import { useEffect } from 'react'
import { RefreshCw } from 'lucide-react'
import { useAppStore } from '../store'

export default function DiffPanel(): React.JSX.Element {
  const diff = useAppStore((state) => state.diff)
  const refreshDiff = useAppStore((state) => state.refreshDiff)

  useEffect(() => {
    void refreshDiff()
  }, [refreshDiff])

  return (
    <div className="right-body">
      <div className="kb-toolbar">
        <span style={{ flex: 1, fontSize: 11.5, color: 'var(--faint)', paddingLeft: 4 }}>
          未提交的改动
        </span>
        <button className="small-btn" onClick={() => void refreshDiff()}>
          <RefreshCw size={12} />
          刷新
        </button>
      </div>
      {diff.trim() ? (
        <pre className="diff-view">{diff}</pre>
      ) : (
        <div className="panel-empty">当前没有未提交的改动</div>
      )}
    </div>
  )
}

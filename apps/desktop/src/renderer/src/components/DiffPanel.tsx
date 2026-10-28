import { useEffect } from 'react'
import { RefreshCw } from 'lucide-react'
import { useAppStore } from '../store'

export default function DiffPanel(): React.JSX.Element {
  const diff = useAppStore((state) => state.diff)
  const turnDiff = useAppStore((state) => state.turnDiff)
  const diffMode = useAppStore((state) => state.diffMode)
  const setDiffMode = useAppStore((state) => state.setDiffMode)
  const refreshDiff = useAppStore((state) => state.refreshDiff)

  useEffect(() => {
    void refreshDiff()
  }, [refreshDiff])

  const showingTurn = diffMode === 'turn' && !!turnDiff
  const text = showingTurn ? turnDiff!.diff : diff
  const files = showingTurn ? turnDiff!.files : []

  return (
    <div className="right-body">
      <div className="kb-toolbar">
        <span style={{ flex: 1, fontSize: 11.5, color: 'var(--faint)', paddingLeft: 4 }}>
          {showingTurn ? `本轮变更 · ${files.length} 个文件` : '未提交的全部改动'}
        </span>
        {turnDiff && (
          <button
            className="small-btn"
            onClick={() => setDiffMode(showingTurn ? 'all' : 'turn')}
            title={showingTurn ? '查看全部未提交改动' : '回到本轮变更'}
          >
            {showingTurn ? '全部改动' : '本轮变更'}
          </button>
        )}
        <button className="small-btn" onClick={() => void refreshDiff()}>
          <RefreshCw size={12} />
          刷新
        </button>
      </div>

      {files.length > 0 && (
        <div className="diff-files">
          {files.map((file) => (
            <span className="diff-file" key={file}>
              {file}
            </span>
          ))}
        </div>
      )}

      {text.trim() ? (
        <pre className="diff-view">{text}</pre>
      ) : (
        <div className="panel-empty">
          {showingTurn ? '本轮没有产生文件改动' : '当前没有未提交的改动'}
        </div>
      )}
    </div>
  )
}

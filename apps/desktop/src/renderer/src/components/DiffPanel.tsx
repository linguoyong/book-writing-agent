import { useEffect, useState } from 'react'
import { FileText, RefreshCw } from 'lucide-react'
import { api } from '../api'
import { useAppStore } from '../store'
import type { GitChange } from '../types'

const STATUS_LABEL: Record<string, string> = {
  untracked: 'U',
  added: 'A',
  modified: 'M',
  deleted: 'D'
}

export default function DiffPanel(): React.JSX.Element {
  const project = useAppStore((state) => state.activeProject)
  const diff = useAppStore((state) => state.diff)
  const turnDiff = useAppStore((state) => state.turnDiff)
  const diffMode = useAppStore((state) => state.diffMode)
  const setDiffMode = useAppStore((state) => state.setDiffMode)
  const refreshDiff = useAppStore((state) => state.refreshDiff)
  const showToast = useAppStore((state) => state.showToast)

  const [changes, setChanges] = useState<GitChange[]>([])
  const [selected, setSelected] = useState<string | null>(null)
  const [single, setSingle] = useState('')
  const [loading, setLoading] = useState(false)

  const showingTurn = diffMode === 'turn' && !!turnDiff

  const loadChanges = async (): Promise<void> => {
    if (!project) return
    try {
      setChanges((await api.gitChanges(project.id)).items)
    } catch {
      setChanges([])
    }
  }

  useEffect(() => {
    void loadChanges()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [project?.id, diffMode])

  const pick = async (path: string): Promise<void> => {
    if (selected === path) {
      setSelected(null)
      setSingle('')
      return
    }
    setSelected(path)
    if (showingTurn) {
      setSingle(extractFileDiff(turnDiff!.diff, path))
      return
    }
    if (!project) return
    setLoading(true)
    try {
      const result = await api.gitDiff(project.id, path)
      setSingle(result.diff || '（该文件没有可显示的 diff）')
    } catch (error) {
      setSingle((error as Error).message)
    } finally {
      setLoading(false)
    }
  }

  const refresh = (): void => {
    void refreshDiff()
    void loadChanges()
    setSelected(null)
    setSingle('')
  }

  const submit = async (): Promise<void> => {
    if (!project) return
    const message = window.prompt('提交信息（会提交全部未保存的改动）', '保存当前修改')
    if (!message?.trim()) return
    try {
      const result = await api.gitCommit(project.id, message.trim())
      await refreshDiff()
      await loadChanges()
      setSelected(null)
      setSingle('')
      showToast(result.message || '已提交')
    } catch (error) {
      showToast((error as Error).message)
    }
  }

  const files = showingTurn
    ? (turnDiff?.files ?? []).map((path) => ({ path, additions: 0, deletions: 0, status: '' }))
    : changes
  const text = selected ? single : showingTurn ? turnDiff?.diff ?? '' : diff

  return (
    <div className="changes-panel">
      <div className="changes-main">
        <div className="kb-toolbar">
          <span className="ft-hint">
            {showingTurn
              ? `本轮变更 · ${turnDiff?.files.length ?? 0} 个文件`
              : `未提交的全部改动 · ${changes.length} 个文件`}
          </span>
          <button
            className="small-btn"
            onClick={() => {
              setSelected(null)
              setSingle('')
              setDiffMode(showingTurn ? 'all' : 'turn')
            }}
            disabled={!turnDiff}
            title={showingTurn ? '查看全部未提交改动' : '回到本轮变更'}
          >
            {showingTurn ? '全部改动' : '本轮变更'}
          </button>
          <button className="small-btn" onClick={refresh}>
            <RefreshCw size={12} />
            刷新
          </button>
          <button
            className="small-btn primary"
            onClick={() => void submit()}
            disabled={changes.length === 0}
            title="提交全部未保存的改动（git commit）"
          >
            提交
          </button>
        </div>

        <div className="changes-scroll">
          {selected && (
            <div className="changes-single-bar">
              <span className="changes-single-path">{selected}</span>
              <button
                className="ft-icon"
                onClick={() => {
                  setSelected(null)
                  setSingle('')
                }}
                title="返回全部改动"
              >
                ×
              </button>
            </div>
          )}
          {loading ? (
            <div className="panel-empty">加载中…</div>
          ) : text.trim() ? (
            <pre className="diff-view">{text}</pre>
          ) : (
            <div className="panel-empty">
              {selected ? '该文件没有可显示的 diff' : '当前没有未提交的改动'}
            </div>
          )}
        </div>
      </div>

      <aside className="changes-tree">
        <div className="ct-title">
          {showingTurn ? '本轮更改' : '已更改文件'}
          <span className="ct-count">{files.length}</span>
        </div>
        <div className="ct-list">
          {files.map((file) => {
            const segments = file.path.split('/')
            const name = segments[segments.length - 1]
            const dir = segments.slice(0, -1).join('/')
            return (
              <button
                key={file.path}
                className={`ct-row ${selected === file.path ? 'active' : ''}`}
                onClick={() => void pick(file.path)}
                title={file.path}
              >
                <span className={`ct-status ${file.status}`}>
                  {STATUS_LABEL[file.status] ?? '·'}
                </span>
                <FileText size={12} className="ct-icon" />
                <span className="ct-name">
                  <span className="ct-file">{name}</span>
                  {dir && <span className="ct-dir">{dir}</span>}
                </span>
                {(file.additions > 0 || file.deletions > 0) && (
                  <span className="ct-stat">
                    <b>+{file.additions}</b>
                    <i>-{file.deletions}</i>
                  </span>
                )}
              </button>
            )
          })}
          {files.length === 0 && <div className="panel-empty">没有更改</div>}
        </div>
      </aside>
    </div>
  )
}

/** 从整份 diff 里截出某个文件的段落（本轮变更用） */
function extractFileDiff(text: string, path: string): string {
  const marker = `diff --git a/${path} b/${path}`
  const start = text.indexOf(marker)
  if (start < 0) return '（本轮没有该文件的 diff）'
  const next = text.indexOf('\ndiff --git ', start + 1)
  return next < 0 ? text.slice(start) : text.slice(start, next)
}

import { useEffect, useState } from 'react'
import { GitCommit, History, Loader2, RotateCcw } from 'lucide-react'
import { api } from '../api'
import { useAppStore } from '../store'
import type { GitCommit as Commit, GitFileChange } from '../types'
import DiffView from '../components/DiffView'

const STATUS_LABEL: Record<string, string> = {
  A: '新增',
  M: '修改',
  D: '删除',
  R: '重命名',
  C: '复制'
}

export default function HistoryPage(): React.JSX.Element {
  const project = useAppStore((state) => state.activeProject)
  const showToast = useAppStore((state) => state.showToast)
  const refreshTree = useAppStore((state) => state.refreshTree)

  const [commits, setCommits] = useState<Commit[]>([])
  const [active, setActive] = useState<Commit | null>(null)
  const [files, setFiles] = useState<GitFileChange[]>([])
  const [activeFile, setActiveFile] = useState('')
  const [diff, setDiff] = useState('')
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState('')
  const [confirming, setConfirming] = useState(false)

  const loadLog = async (): Promise<void> => {
    if (!project) return
    setLoading(true)
    try {
      const result = await api.gitLog(project.id, 60)
      setCommits(result.items)
      if (result.items.length) void selectCommit(result.items[0])
      else {
        setActive(null)
        setFiles([])
        setDiff('')
      }
    } catch (error) {
      showToast((error as Error).message)
    } finally {
      setLoading(false)
    }
  }

  const selectCommit = async (commit: Commit): Promise<void> => {
    if (!project) return
    setActive(commit)
    setActiveFile('')
    setDiff('')
    setConfirming(false)
    try {
      const result = await api.gitCommitFiles(project.id, commit.hash)
      setFiles(result.items)
    } catch (error) {
      setFiles([])
      showToast((error as Error).message)
    }
  }

  const selectFile = async (file: GitFileChange): Promise<void> => {
    if (!project || !active) return
    setActiveFile(file.path)
    setConfirming(false)
    setBusy('diff')
    try {
      const result = await api.gitFileDiff(project.id, active.hash, file.path)
      setDiff(result.diff)
    } catch (error) {
      setDiff('')
      showToast((error as Error).message)
    } finally {
      setBusy('')
    }
  }

  const restore = async (): Promise<void> => {
    if (!project || !active || !activeFile) return
    if (!confirming) {
      setConfirming(true)
      return
    }
    setBusy('restore')
    try {
      const restored = await api.gitRestore(project.id, active.hash, activeFile)
      await refreshTree()
      showToast(
        restored.unchanged
          ? `${activeFile} 的内容已经和 ${active.short} 一致`
          : `已把 ${activeFile} 恢复到 ${active.short}`
      )
      const result = await api.gitLog(project.id, 60)
      setCommits(result.items)
      setConfirming(false)
      if (result.items.length) void selectCommit(result.items[0])
    } catch (error) {
      showToast((error as Error).message)
    } finally {
      setBusy('')
    }
  }

  useEffect(() => {
    void loadLog()
  }, [project?.id])

  const projectName = project?.meta?.title || project?.name || ''

  return (
    <div className="page">
      <div className="page-header">
        <div className="page-title-block">
          <h1>版本历史</h1>
          <p>{projectName} · 在「变更」面板提交后，每个版本都会记录在这里</p>
        </div>
        <div className="page-actions">
          <button className="ghost-btn" onClick={() => void loadLog()} disabled={loading}>
            {loading ? <Loader2 size={13} className="spin" /> : <History size={13} />}
            刷新
          </button>
        </div>
      </div>

      <div className="history-layout">
        <aside className="history-commits">
          {loading && <div className="panel-empty">读取历史…</div>}
          {!loading && !commits.length && (
            <div className="panel-empty">
              还没有提交记录。
              <br />
              右侧「变更」面板里点「提交」，就能留下第一个版本。
            </div>
          )}
          {commits.map((commit) => (
            <button
              key={commit.hash}
              className={`history-commit ${active?.hash === commit.hash ? 'active' : ''}`}
              onClick={() => void selectCommit(commit)}
            >
              <div className="history-commit-title">{commit.message}</div>
              <div className="history-commit-meta">
                <span className="history-hash">{commit.short}</span>
                <span>{commit.date}</span>
              </div>
            </button>
          ))}
        </aside>

        <section className="history-detail">
          {!active && <div className="panel-empty">选择左侧的一个版本查看改动</div>}
          {active && (
            <>
              <div className="history-head">
                <div>
                  <div className="history-head-title">{active.message}</div>
                  <div className="history-head-meta">
                    <GitCommit size={12} />
                    {active.short} · {active.author} · {active.date}
                  </div>
                </div>
                {activeFile && (
                  <button
                    className={`ghost-btn ${confirming ? 'danger' : ''}`}
                    onClick={() => void restore()}
                    disabled={busy === 'restore'}
                  >
                    {busy === 'restore' ? (
                      <Loader2 size={13} className="spin" />
                    ) : (
                      <RotateCcw size={13} />
                    )}
                    {confirming ? `确认恢复 ${activeFile.split('/').pop()}` : '恢复此版本'}
                  </button>
                )}
              </div>

              <div className="history-files">
                {files.map((file) => (
                  <button
                    key={file.path}
                    className={`history-file ${activeFile === file.path ? 'active' : ''}`}
                    onClick={() => void selectFile(file)}
                  >
                    <span className={`history-status s-${file.status}`}>
                      {STATUS_LABEL[file.status] || file.status}
                    </span>
                    <span className="history-path">{file.path}</span>
                  </button>
                ))}
                {!files.length && <div className="panel-empty">这个提交没有文件改动</div>}
              </div>

              <div className="history-diff">
                {busy === 'diff' && <div className="panel-empty">加载 diff…</div>}
                {!busy && activeFile && !diff && <div className="panel-empty">没有可显示的 diff</div>}
                {!busy && diff && <DiffView text={diff} />}
                {!activeFile && <div className="panel-empty">选择文件查看该版本的内容差异</div>}
              </div>
            </>
          )}
        </section>
      </div>
    </div>
  )
}

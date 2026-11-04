import { useEffect, useState } from 'react'
import { Loader2, Search, X } from 'lucide-react'
import { api } from '../api'
import { useAppStore } from '../store'

interface Hit {
  path: string
  line: number
  snippet: string
}

export default function TextSearchModal({
  onClose
}: {
  onClose: () => void
}): React.JSX.Element {
  const project = useAppStore((state) => state.activeProject)
  const openFileByPath = useAppStore((state) => state.openFileByPath)
  const refreshTree = useAppStore((state) => state.refreshTree)
  const showToast = useAppStore((state) => state.showToast)

  const [query, setQuery] = useState('')
  const [scope, setScope] = useState<'manuscript' | 'chapters' | 'all'>('manuscript')
  const [regex, setRegex] = useState(false)
  const [ignoreCase, setIgnoreCase] = useState(false)
  const [hits, setHits] = useState<Hit[]>([])
  const [total, setTotal] = useState(0)
  const [truncated, setTruncated] = useState(false)
  const [replacement, setReplacement] = useState('')
  const [pending, setPending] = useState(0)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const body = {
    query,
    scope,
    regex,
    ignore_case: ignoreCase
  }

  // Esc 关窗（替换框里按 Esc 只清空输入，不关窗）
  useEffect(() => {
    const onKey = (event: KeyboardEvent): void => {
      if (event.key !== 'Escape') return
      const active = document.activeElement
      if (active instanceof HTMLInputElement && active.dataset.keepOpen === '1') {
        active.blur()
        return
      }
      onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const runSearch = async (): Promise<void> => {
    if (!project || !query.trim() || busy) return
    setBusy(true)
    setError('')
    setPending(0)
    try {
      const result = await api.searchText(project.id, body)
      setHits(result.items)
      setTotal(result.total)
      setTruncated(result.truncated)
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const previewReplace = async (): Promise<void> => {
    if (!project || !query.trim() || busy) return
    setBusy(true)
    setError('')
    try {
      const result = await api.replaceText(project.id, {
        ...body,
        replacement,
        dry_run: true
      })
      setPending(result.total)
      showToast(`将替换 ${result.total} 处（${result.files} 个文件）`)
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const doReplace = async (): Promise<void> => {
    if (!project || !pending || busy) return
    setBusy(true)
    setError('')
    try {
      const result = await api.replaceText(project.id, {
        ...body,
        replacement,
        dry_run: false
      })
      await refreshTree()
      showToast(`已替换 ${result.total} 处（${result.files} 个文件）`)
      setPending(0)
      setHits([])
      setTotal(0)
      onClose()
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="modal-mask" onClick={onClose}>
      <div className="modal search-modal" onClick={(event) => event.stopPropagation()}>
        <div className="modal-header">
          <span>查找与替换</span>
          <button className="icon-btn" onClick={onClose} title="关闭">
            <X size={14} />
          </button>
        </div>

        <div className="modal-body">
          <div className="search-row">
            <div className="search-box" style={{ flex: 1 }}>
              <Search size={13} />
              <input
                autoFocus
                value={query}
                placeholder="查找内容"
                onChange={(event) => setQuery(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter') void runSearch()
                }}
              />
            </div>
            <select
              value={scope}
              onChange={(event) => setScope(event.target.value as typeof scope)}
            >
              <option value="manuscript">正文</option>
              <option value="chapters">导入章节</option>
              <option value="all">全部</option>
            </select>
            <button className="primary-btn" onClick={() => void runSearch()} disabled={busy}>
              {busy ? <Loader2 size={13} className="spin" /> : '查找'}
            </button>
          </div>

          <div className="search-flags">
            <label>
              <input type="checkbox" checked={regex} onChange={(e) => setRegex(e.target.checked)} />
              正则
            </label>
            <label>
              <input
                type="checkbox"
                checked={ignoreCase}
                onChange={(e) => setIgnoreCase(e.target.checked)}
              />
              忽略大小写
            </label>
            {total > 0 && (
              <span className="search-count">
                {total} 处{truncated ? `（仅显示前 ${hits.length} 条）` : ''}
              </span>
            )}
          </div>

          {error && <div className="kb-notice warn">{error}</div>}

          <div className="search-list">
            {hits.map((hit) => (
              <button
                className="search-hit"
                key={`${hit.path}-${hit.line}-${hit.snippet.slice(0, 8)}`}
                onClick={() => {
                  void openFileByPath(hit.path, true)
                  onClose()
                }}
              >
                <span className="search-hit-path">
                  {hit.path}:{hit.line}
                </span>
                <span className="search-hit-text">{hit.snippet}</span>
              </button>
            ))}
            {!hits.length && <div className="panel-empty">输入关键词后回车查找</div>}
          </div>

          <div className="search-row">
            <input
              className="search-replace"
              value={replacement}
              placeholder="替换为（留空表示删除）"
              data-keep-open="1"
              onChange={(event) => {
                setReplacement(event.target.value)
                setPending(0)
              }}
            />
            <button className="ghost-btn" onClick={() => void previewReplace()} disabled={busy || !query.trim()}>
              预览替换
            </button>
            <button
              className="primary-btn danger"
              onClick={() => void doReplace()}
              disabled={busy || !pending}
            >
              {pending ? `确认替换 ${pending} 处` : '确认替换'}
            </button>
          </div>
          <div className="field-hint">
            替换会直接改写文件（正文范围还会触发索引重建）。建议先「预览替换」确认命中数。
          </div>
        </div>
      </div>
    </div>
  )
}

import { useMemo, useState } from 'react'
import { AlertTriangle, FileText, Loader2, Upload, X } from 'lucide-react'
import { api } from '../api'
import { useAppStore } from '../store'
import type { ImportPreview } from '../types'

const MAX_ROWS = 300

export default function ImportModal({
  onClose,
  onDone
}: {
  onClose: () => void
  onDone: () => void
}): React.JSX.Element {
  const project = useAppStore((state) => state.activeProject)
  const showToast = useAppStore((state) => state.showToast)

  const [path, setPath] = useState('')
  const [pattern, setPattern] = useState('')
  const [preview, setPreview] = useState<ImportPreview | null>(null)
  const [excluded, setExcluded] = useState<Set<number>>(new Set())
  const [titles, setTitles] = useState<Record<string, string>>({})
  const [loading, setLoading] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const runPreview = async (file: string, rule: string): Promise<void> => {
    if (!project || !file) return
    setLoading(true)
    setError('')
    setPreview(null)
    setExcluded(new Set())
    setTitles({})
    try {
      setPreview(await api.importPreview(project.id, file, rule))
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setLoading(false)
    }
  }

  const pick = async (): Promise<void> => {
    const picked = await window.desktop?.pickTextFile?.()
    if (!picked) return
    setPath(picked)
    await runPreview(picked, pattern)
  }

  const toggle = (index: number): void => {
    setExcluded((prev) => {
      const next = new Set(prev)
      if (next.has(index)) next.delete(index)
      else next.add(index)
      return next
    })
  }

  const selected = useMemo(
    () => (preview ? preview.chapters.filter((item) => !excluded.has(item.index)) : []),
    [preview, excluded]
  )
  const selectedChars = selected.reduce((sum, item) => sum + item.chars, 0)

  const submit = async (): Promise<void> => {
    if (!project || !preview || !selected.length || busy) return
    setBusy(true)
    try {
      const result = await api.importBook(project.id, path, [...excluded], titles, pattern)
      showToast(`已导入 ${result.imported} 章，正在后台建索引`)
      onDone()
      onClose()
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="modal-mask" onClick={onClose}>
      <div className="modal import-modal" onClick={(event) => event.stopPropagation()}>
        <div className="modal-header">
          <span>导入整本书</span>
          <button className="icon-btn" onClick={onClose} title="关闭">
            <X size={14} />
          </button>
        </div>

        <div className="modal-body">
          <div className="import-pick">
            <button className="ghost-btn" onClick={() => void pick()} disabled={loading || busy}>
              {loading ? <Loader2 size={13} className="spin" /> : <FileText size={13} />}
              {path ? '重新选择文件' : '选择 TXT / MD 文件'}
            </button>
            <span className="import-path">{path || '支持 UTF-8 / GBK / UTF-16，最大 50MB'}</span>
          </div>

          <details className="import-advanced">
            <summary>章节识别规则（可选）</summary>
            <div className="field-hint">
              默认识别「第X章 / 第X回 / 序章 / 楔子 / 番外 / Chapter N」，标题行不超过 40 字。
              识别不到时按约 3000 字自动分节。
            </div>
            <input
              value={pattern}
              onChange={(event) => setPattern(event.target.value)}
              placeholder="第\s*[0-9一二三…]+\s*[章回节]"
            />
            <button
              className="link-btn"
              disabled={!path || loading || busy}
              onClick={() => void runPreview(path, pattern)}
            >
              用这个规则重新解析
            </button>
          </details>

          {error && (
            <div className="kb-notice warn" style={{ marginTop: 10 }}>
              <AlertTriangle size={13} />
              <span>{error}</span>
            </div>
          )}

          {preview && (
            <>
              <div className="import-summary">
                <span>{preview.file}</span>
                <span>编码 {preview.encoding}</span>
                <span>{preview.total_chars.toLocaleString()} 字</span>
                <span>{preview.chapters.length} 章</span>
                {preview.preamble_chars > 0 && <span>卷首 {preview.preamble_chars} 字</span>}
              </div>

              <div className="import-list">
                <div className="import-row head">
                  <span />
                  <span>#</span>
                  <span>章节标题（可改）</span>
                  <span>字数</span>
                </div>
                {preview.chapters.slice(0, MAX_ROWS).map((chapter) => (
                  <label className="import-row" key={chapter.index}>
                    <input
                      type="checkbox"
                      checked={!excluded.has(chapter.index)}
                      onChange={() => toggle(chapter.index)}
                    />
                    <span className="import-index">{chapter.index + 1}</span>
                    <input
                      className="import-title"
                      value={titles[String(chapter.index)] ?? chapter.title}
                      onChange={(event) =>
                        setTitles({ ...titles, [String(chapter.index)]: event.target.value })
                      }
                    />
                    <span className="import-chars">{chapter.chars}</span>
                  </label>
                ))}
                {preview.chapters.length > MAX_ROWS && (
                  <div className="field-hint" style={{ padding: '6px 2px' }}>
                    仅列出前 {MAX_ROWS} 章，其余按原样导入
                  </div>
                )}
              </div>
            </>
          )}
        </div>

        <div className="modal-footer">
          <span className="import-count">
            {preview
              ? `已选 ${selected.length} 章 · ${selectedChars.toLocaleString()} 字`
              : '先选一个文件'}
          </span>
          <button className="ghost-btn" onClick={onClose} disabled={busy}>
            取消
          </button>
          <button
            className="primary-btn"
            onClick={() => void submit()}
            disabled={!preview || !selected.length || busy}
          >
            {busy ? <Loader2 size={13} className="spin" /> : <Upload size={13} />}
            {busy ? '导入中…' : '开始导入'}
          </button>
        </div>
      </div>
    </div>
  )
}

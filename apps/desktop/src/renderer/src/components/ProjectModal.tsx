import { useEffect, useState } from 'react'
import { BookPlus, FolderOpen } from 'lucide-react'
import { api } from '../api'
import { useAppStore } from '../store'

export default function ProjectModal({ canClose }: { canClose: boolean }): React.JSX.Element {
  const createProject = useAppStore((state) => state.createProject)
  const openProject = useAppStore((state) => state.openProject)
  const setProjectModalOpen = useAppStore((state) => state.setProjectModalOpen)

  const [mode, setMode] = useState<'create' | 'open'>('create')
  const [name, setName] = useState('')
  const [title, setTitle] = useState('')
  const [author, setAuthor] = useState('')
  const [wordsPerChapter, setWordsPerChapter] = useState(5000)
  const [path, setPath] = useState('')
  const [pathTouched, setPathTouched] = useState(false)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (mode !== 'create' || pathTouched || !name.trim()) return
    const timer = window.setTimeout(async () => {
      try {
        const result = await api.defaultPath(name.trim())
        setPath(result.path)
      } catch {
        /* 默认路径获取失败时留空，由后端兜底 */
      }
    }, 250)
    return () => window.clearTimeout(timer)
  }, [name, pathTouched, mode])

  const browse = async (): Promise<void> => {
    const picked = await window.desktop?.pickDirectory?.()
    if (picked) {
      setPath(picked)
      setPathTouched(true)
    }
  }

  const submit = async (): Promise<void> => {
    if (busy) return
    setBusy(true)
    if (mode === 'create') {
      if (name.trim()) {
        await createProject(
          name.trim(),
          title.trim() || name.trim(),
          author.trim(),
          path.trim() || undefined,
          wordsPerChapter
        )
      }
    } else if (path.trim()) {
      await openProject(path.trim())
    }
    setBusy(false)
  }

  const canSubmit = mode === 'create' ? !!name.trim() : !!path.trim()

  return (
    <div className="modal-mask">
      <div className="modal">
        <div className="modal-header">
          <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            {mode === 'create' ? <BookPlus size={15} /> : <FolderOpen size={15} />}
            {mode === 'create' ? '新建书稿空间' : '打开已有目录'}
          </span>
          {canClose && (
            <button className="icon-btn" onClick={() => setProjectModalOpen(false)}>
              取消
            </button>
          )}
        </div>

        <div className="modal-tabs">
          <button className={mode === 'create' ? 'active' : ''} onClick={() => setMode('create')}>
            新建空间
          </button>
          <button className={mode === 'open' ? 'active' : ''} onClick={() => setMode('open')}>
            打开目录
          </button>
        </div>

        <div className="modal-body">
          {mode === 'create' ? (
            <>
              <div className="field">
                <label>空间名称</label>
                <input
                  autoFocus
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                  placeholder="例如：长夜行"
                />
              </div>
              <div className="field">
                <label>书名（可选，默认同空间名）</label>
                <input value={title} onChange={(event) => setTitle(event.target.value)} />
              </div>
              <div className="field">
                <label>作者（可选）</label>
                <input value={author} onChange={(event) => setAuthor(event.target.value)} />
              </div>
              <div className="field">
                <label>每章目标字数</label>
                <input
                  type="number"
                  min={500}
                  step={500}
                  value={wordsPerChapter}
                  onChange={(event) =>
                    setWordsPerChapter(Number(event.target.value) || 5000)
                  }
                />
                <div className="field-hint">
                  写作篇幅与节奏检查会参考这个值，默认 5000 字，之后可在 book.json 调整。
                </div>
              </div>
              <div className="field">
                <label>存放目录</label>
                <div className="path-row">
                  <input
                    value={path}
                    placeholder="默认：~/.book-agent/books/<空间名>"
                    onChange={(event) => {
                      setPath(event.target.value)
                      setPathTouched(true)
                    }}
                  />
                  <button className="small-btn" onClick={() => void browse()}>
                    浏览…
                  </button>
                </div>
                <div className="field-hint">
                  目录即工作区。默认落在 ~/.book-agent/books/ 下，也可以指定任意空目录或已有书稿目录。
                </div>
              </div>
            </>
          ) : (
            <div className="field">
              <label>目录路径</label>
              <div className="path-row">
                <input
                  autoFocus
                  value={path}
                  placeholder="选择或输入已有目录"
                  onChange={(event) => setPath(event.target.value)}
                />
                <button className="small-btn" onClick={() => void browse()}>
                  浏览…
                </button>
              </div>
              <div className="field-hint">
                若目录里已有 book.json 会直接接入；否则会初始化为新的书稿空间（建目录结构 + git）。
              </div>
            </div>
          )}
        </div>

        <div className="modal-footer">
          <button
            className="primary-btn"
            disabled={!canSubmit || busy}
            onClick={() => void submit()}
          >
            {busy ? '处理中…' : mode === 'create' ? '创建空间' : '打开目录'}
          </button>
        </div>
      </div>
    </div>
  )
}

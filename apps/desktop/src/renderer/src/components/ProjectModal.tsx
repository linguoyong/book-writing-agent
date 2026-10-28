import { useState } from 'react'
import { BookPlus } from 'lucide-react'
import { useAppStore } from '../store'

export default function ProjectModal({ canClose }: { canClose: boolean }): React.JSX.Element {
  const createProject = useAppStore((state) => state.createProject)
  const setProjectModalOpen = useAppStore((state) => state.setProjectModalOpen)

  const [name, setName] = useState('')
  const [title, setTitle] = useState('')
  const [author, setAuthor] = useState('')
  const [busy, setBusy] = useState(false)

  const submit = async (): Promise<void> => {
    if (!name.trim() || busy) return
    setBusy(true)
    await createProject(name.trim(), title.trim() || name.trim(), author.trim())
    setBusy(false)
  }

  return (
    <div className="modal-mask">
      <div className="modal">
        <div className="modal-header">
          <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <BookPlus size={15} />
            新建书稿项目
          </span>
          {canClose && (
            <button className="icon-btn" onClick={() => setProjectModalOpen(false)}>
              取消
            </button>
          )}
        </div>

        <div className="modal-body">
          <div className="field">
            <label>项目名称</label>
            <input
              autoFocus
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="例如：长夜行"
            />
          </div>
          <div className="field">
            <label>书名（可选，默认同项目名）</label>
            <input value={title} onChange={(event) => setTitle(event.target.value)} />
          </div>
          <div className="field">
            <label>作者（可选）</label>
            <input value={author} onChange={(event) => setAuthor(event.target.value)} />
          </div>
          <div style={{ fontSize: 11.5, color: 'var(--faint)', lineHeight: 1.7 }}>
            项目会创建在默认书库目录，并自动初始化目录结构与 git 仓库。
          </div>
        </div>

        <div className="modal-footer">
          <button
            className="primary-btn"
            disabled={!name.trim() || busy}
            onClick={() => void submit()}
          >
            {busy ? '创建中…' : '创建项目'}
          </button>
        </div>
      </div>
    </div>
  )
}

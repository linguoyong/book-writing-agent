import { useEffect } from 'react'
import CodeMirror from '@uiw/react-codemirror'
import { markdown } from '@codemirror/lang-markdown'
import { FilePlus2, Save } from 'lucide-react'
import { api } from '../api'
import { useAppStore } from '../store'

export default function EditorPane(): React.JSX.Element {
  const project = useAppStore((state) => state.activeProject)
  const overview = useAppStore((state) => state.overview)
  const openFile = useAppStore((state) => state.openFile)
  const updateOpenFile = useAppStore((state) => state.updateOpenFile)
  const saveOpenFile = useAppStore((state) => state.saveOpenFile)
  const refreshTree = useAppStore((state) => state.refreshTree)
  const openFileByPath = useAppStore((state) => state.openFileByPath)

  useEffect(() => {
    const handler = (event: KeyboardEvent): void => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's') {
        event.preventDefault()
        void useAppStore.getState().saveOpenFile()
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [])

  const createChapter = async (): Promise<void> => {
    if (!project) return
    const next = (overview?.manuscript_count ?? 0) + 1
    const path = `manuscript/vol-01/ch-${String(next).padStart(3, '0')}.md`
    await api.writeFile(project.id, path, `# 第${next}章\n\n`)
    await refreshTree()
    await openFileByPath(path)
  }

  return (
    <div className="editor-pane" style={{ height: '100%' }}>
      <div className="editor-header">
        <span className="path">
          {openFile ? openFile.path : '当前作品'}
          {openFile?.dirty && <span className="dirty-dot" style={{ marginLeft: 8, display: 'inline-block' }} />}
        </span>
        <div style={{ marginLeft: 'auto', display: 'flex', gap: 4, alignItems: 'center' }}>
          <button
            className="icon-btn"
            onClick={() => void createChapter()}
            title="新建章节"
            disabled={!project}
          >
            <FilePlus2 size={14} />
          </button>
          <button
            className="icon-btn"
            onClick={() => void saveOpenFile()}
            title="保存（Ctrl+S）"
            disabled={!openFile?.dirty}
          >
            <Save size={14} />
          </button>
        </div>
      </div>

      <div className="editor-body">
        {openFile ? (
          <CodeMirror
            value={openFile.content}
            height="100%"
            extensions={[markdown()]}
            basicSetup={{
              lineNumbers: false,
              foldGutter: false,
              highlightActiveLine: true,
              autocompletion: false,
              indentOnInput: false
            }}
            onChange={(value) => updateOpenFile(value)}
          />
        ) : (
          <div className="editor-empty">
            <div>还没有打开文稿</div>
            <button className="small-btn primary" onClick={() => void createChapter()} disabled={!project}>
              <FilePlus2 size={13} />
              新建第一章
            </button>
            <div style={{ fontSize: 11.5 }}>或从右栏文件树中选择文件</div>
          </div>
        )}
      </div>
    </div>
  )
}

import { useEffect, useState } from 'react'
import CodeMirror from '@uiw/react-codemirror'
import { markdown } from '@codemirror/lang-markdown'
import {
  Check,
  Clipboard,
  Eye,
  FileCode2,
  FilePlus2,
  FolderOpen,
  PanelRight,
  Save
} from 'lucide-react'
import { api } from '../api'
import { useAppStore } from '../store'
import Markdown from './Markdown'

export default function FileViewer({
  treeOpen = true,
  onToggleTree
}: {
  treeOpen?: boolean
  onToggleTree?: () => void
}): React.JSX.Element {
  const project = useAppStore((state) => state.activeProject)
  const openFile = useAppStore((state) => state.openFile)
  const updateOpenFile = useAppStore((state) => state.updateOpenFile)
  const saveOpenFile = useAppStore((state) => state.saveOpenFile)
  const refreshTree = useAppStore((state) => state.refreshTree)
  const openFileByPath = useAppStore((state) => state.openFileByPath)
  const showToast = useAppStore((state) => state.showToast)
  const setRightTab = useAppStore((state) => state.setRightTab)

  const [mode, setMode] = useState<'preview' | 'source'>('preview')
  const isText = !openFile || openFile.kind === 'text'
  const isMarkdown =
    isText && Boolean(openFile?.path.toLowerCase().endsWith('.md'))

  useEffect(() => {
    const markdownFile =
      openFile?.kind === 'text' && openFile.path.toLowerCase().endsWith('.md')
    setMode(markdownFile ? 'preview' : 'source')
  }, [openFile?.path, openFile?.kind])

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

  const createFile = async (): Promise<void> => {
    if (!project) return
    const name = window.prompt('新建文件（相对工作区的路径）', 'manuscript/vol-01/ch-001.md')
    if (!name?.trim()) return
    try {
      await api.fsCreate(project.id, name.trim(), 'file')
      await refreshTree()
      await openFileByPath(name.trim(), true)
      setMode('source')
    } catch (error) {
      showToast((error as Error).message)
    }
  }

  const copyPath = async (): Promise<void> => {
    if (!openFile) return
    try {
      await navigator.clipboard.writeText(openFile.path)
      showToast('已复制相对路径')
    } catch {
      showToast('复制失败：当前环境不允许访问剪贴板')
    }
  }

  const reveal = (): void => {
    if (!project || !openFile) return
    void window.desktop?.showItemInFolder?.(project.path, openFile.path)
  }

  const segments = openFile?.path.split('/') ?? []

  return (
    <section className="file-viewer">
      <div className="fv-head">
        <div className="fv-crumbs" title={openFile?.path}>
          {openFile ? (
            segments.map((part, index) => (
              <span
                key={`${part}-${index}`}
                className={index === segments.length - 1 ? 'cur' : ''}
              >
                {index > 0 && <span className="fv-sep">/</span>}
                {part}
              </span>
            ))
          ) : (
            <span className="fv-idle">未打开文件</span>
          )}
        </div>
        <div className="fv-actions">
          <button
            className={`fv-icon ${treeOpen ? 'on' : ''}`}
            onClick={onToggleTree}
            title={treeOpen ? '收起文件树' : '展开文件树'}
          >
            <PanelRight size={12} />
          </button>
          {openFile?.dirty && <span className="fv-dirty">未保存</span>}
          {openFile?.truncated && <span className="fv-dirty">只读预览</span>}
          {isMarkdown && (
            <button
              className={`fv-btn ${mode === 'preview' ? 'on' : ''}`}
              onClick={() => setMode(mode === 'preview' ? 'source' : 'preview')}
              title={mode === 'preview' ? '查看源代码' : '预览 Markdown'}
            >
              {mode === 'preview' ? <FileCode2 size={12} /> : <Eye size={12} />}
              {mode === 'preview' ? '源码' : '预览'}
            </button>
          )}
          <button
            className="fv-icon"
            onClick={() => void copyPath()}
            disabled={!openFile}
            title="复制相对路径"
          >
            <Clipboard size={12} />
          </button>
          <button
            className="fv-icon"
            onClick={reveal}
            disabled={!openFile}
            title="在文件夹中打开"
          >
            <FolderOpen size={12} />
          </button>
          <button
            className="fv-icon"
            onClick={() => void saveOpenFile()}
            disabled={!openFile?.dirty || openFile?.truncated}
            title="保存（Ctrl+S）"
          >
            {openFile?.dirty ? <Save size={12} /> : <Check size={12} />}
          </button>
        </div>
      </div>

      <div className="fv-body">
        {openFile ? (
          openFile.kind === 'image' && openFile.dataUrl ? (
            <div className="fv-image">
              <img src={openFile.dataUrl} alt={openFile.path} />
            </div>
          ) : openFile.kind === 'large' ? (
            <div className="editor-empty">
              <div>文件较大（{formatSize(openFile.size)}），未直接加载</div>
              <div className="fv-size">整份打开可能让编辑器卡顿，可只读预览前 200 KB</div>
              <button
                className="small-btn primary"
                onClick={() => void openFileByPath(openFile.path, true, 200_000)}
              >
                只读预览
              </button>
              <button className="small-btn" onClick={reveal}>
                <FolderOpen size={13} />
                在文件夹中打开
              </button>
            </div>
          ) : openFile.kind === 'binary' ? (
            <div className="editor-empty">
              <div>该文件不支持预览</div>
              <div className="fv-size">{formatSize(openFile.size)}</div>
              <button className="small-btn" onClick={reveal}>
                <FolderOpen size={13} />
                在文件夹中打开
              </button>
            </div>
          ) : mode === 'preview' && isMarkdown ? (
            <div className="fv-preview">
              <Markdown content={openFile.content} />
            </div>
          ) : (
            <CodeMirror
              value={openFile.content}
              height="100%"
              extensions={[markdown()]}
              editable={!openFile.truncated}
              basicSetup={{
                lineNumbers: true,
                foldGutter: false,
                highlightActiveLine: true,
                autocompletion: false,
                indentOnInput: false
              }}
              onChange={(value) => updateOpenFile(value)}
            />
          )
        ) : (
          <div className="editor-empty">
            <div>从右侧文件树选择文件</div>
            <button className="small-btn primary" onClick={() => void createFile()} disabled={!project}>
              <FilePlus2 size={13} />
              新建文件
            </button>
            <button className="small-btn" onClick={() => setRightTab('diff')}>
              查看变更
            </button>
          </div>
        )}
      </div>
    </section>
  )
}

function formatSize(size?: number): string {
  if (!size) return ''
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / 1024 / 1024).toFixed(1)} MB`
}
